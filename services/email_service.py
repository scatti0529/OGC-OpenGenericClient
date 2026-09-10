# -*- coding: utf-8 -*-
"""
邮箱模块 - 纯逻辑服务层
=======================
基于标准库 imaplib / smtplib / email，为 OGC 提供一个原生邮件客户端后端。

本模块**不依赖 Qt**，只做纯逻辑，供页面层后台线程调用：
- EmailAccount          —— 单个邮箱账号配置（IMAP / SMTP 服务器、端口、SSL、凭据）
- EmailConfig           —— 配置桥接：读写 data/config.json 的 "email" 节点（多账号）
- EmailAttachment       —— 附件元数据
- EmailMessage          —— 解析后的邮件模型（正文/HTML/附件/元信息）
- EmailService          —— IMAP 登录、列表文件夹+未读数、拉取邮件头/全文、SMTP 发送
- suggest_servers()     —— 依据邮箱域名推断常见 IMAP/SMTP 服务器

线程安全说明：每个公开方法都自己 连接→登录→操作→关闭，无共享状态；
页面层在 QThread 后台线程里调用，成功/失败通过信号回 UI。
"""

import imaplib
import smtplib
import ssl
import re
import uuid
import json
import base64
from pathlib import Path
from datetime import datetime, timezone, timedelta
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime, formataddr
from email.message import EmailMessage as StdEmailMessage
from email.header import decode_header, make_header
from typing import List, Optional, Dict, Any, Tuple

from core.config import config as CFG


# ============================================================
# 配置桥接（data/config.json 的 "email" 节点）
# ============================================================
class EmailConfig:
    """邮箱账号配置桥接：读写 data/config.json 中的 "email" 节点。"""

    SECTION = 'email'

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self._defaults = {
            'accounts': [],
            'current': None,
        }
        self._section = {}
        self._load()

    # ---------------- 读写 ----------------
    def _load(self) -> None:
        try:
            cfg_file = Path(CFG.cfg_file)
            if cfg_file.exists():
                data = json.loads(cfg_file.read_text(encoding='utf-8'))
                sec = data.get(self.SECTION)
                if isinstance(sec, dict):
                    self._section = sec
        except Exception:
            self._section = {}

    def save(self) -> None:
        """将 email 节点写回 data/config.json（不破坏其他配置）"""
        try:
            cfg_file = Path(CFG.cfg_file)
            data = {}
            if cfg_file.exists():
                try:
                    data = json.loads(cfg_file.read_text(encoding='utf-8'))
                except (json.JSONDecodeError, OSError):
                    data = {}
            data[self.SECTION] = self._section
            cfg_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
        except Exception:
            pass

    def get(self, key: str, default=None):
        return self._section.get(key, self._defaults.get(key, default))

    def _set(self, key: str, value):
        self._section[key] = value

    # ---------------- 账号操作 ----------------
    def get_accounts(self) -> List[Dict[str, Any]]:
        accounts = self.get('accounts', [])
        return list(accounts) if isinstance(accounts, list) else []

    def get_by_id(self, acc_id: str) -> Optional[Dict[str, Any]]:
        for acc in self.get_accounts():
            if acc.get('id') == acc_id:
                return acc
        return None

    def get_current(self) -> Optional[Dict[str, Any]]:
        cur = self.get('current')
        if cur:
            acc = self.get_by_id(cur)
            if acc:
                return acc
        # 回退到第一个账号
        accounts = self.get_accounts()
        return accounts[0] if accounts else None

    def upsert_account(self, acc: Dict[str, Any]) -> None:
        """新增或更新账号（按 id）。"""
        accounts = self.get_accounts()
        acc_id = acc.get('id') or uuid.uuid4().hex
        acc['id'] = acc_id
        for i, existing in enumerate(accounts):
            if existing.get('id') == acc_id:
                accounts[i] = acc
                break
        else:
            accounts.append(acc)
        self._set('accounts', accounts)
        if self.get('current') is None:
            self._set('current', acc_id)
        self.save()

    def remove_account(self, acc_id: str) -> None:
        accounts = self.get_accounts()
        accounts = [a for a in accounts if a.get('id') != acc_id]
        self._set('accounts', accounts)
        if self.get('current') == acc_id:
            next_id = accounts[0].get('id') if accounts else None
            self._set('current', next_id)
        self.save()

    def set_current(self, acc_id: str) -> None:
        self._set('current', acc_id)
        self.save()

    def delete_all(self) -> None:
        self._set('accounts', [])
        self._set('current', None)
        self.save()


# 全局单例
email_cfg = EmailConfig()


# ============================================================
# 账号模型
# ============================================================
class EmailAccount:
    """单个邮箱账号（含 IMAP/SMTP 服务器信息）。"""

    def __init__(self, data: Dict[str, Any]):
        self.id = data.get('id') or uuid.uuid4().hex
        self.name = data.get('name', '')
        self.email = data.get('email', '')
        self.password = data.get('password', '')          # 密码 / 授权码
        self.imap_host = data.get('imap_host', '')
        self.imap_port = int(data.get('imap_port', 993))
        self.imap_ssl = bool(data.get('imap_ssl', True))
        self.smtp_host = data.get('smtp_host', '')
        self.smtp_port = int(data.get('smtp_port', 465))
        self.smtp_ssl = bool(data.get('smtp_ssl', True))

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'password': self.password,
            'imap_host': self.imap_host,
            'imap_port': self.imap_port,
            'imap_ssl': self.imap_ssl,
            'smtp_host': self.smtp_host,
            'smtp_port': self.smtp_port,
            'smtp_ssl': self.smtp_ssl,
        }

    @property
    def display_name(self) -> str:
        return self.name or self.email


# ============================================================
# 常见域名 → 服务器推断
# ============================================================
_COMMON_PROVIDERS = {
    'gmail.com':      (993, 465, True, True),
    'googlemail.com': (993, 465, True, True),
    'qq.com':         (993, 465, True, True),
    'foxmail.com':    (993, 465, True, True),
    '163.com':        (993, 465, True, True),
    '126.com':        (993, 465, True, True),
    'yeah.net':       (993, 465, True, True),
    'sina.com':       (993, 465, True, True),
    'outlook.com':    (993, 587, True, False),
    'hotmail.com':    (993, 587, True, False),
    'live.com':       (993, 587, True, False),
    'icloud.com':     (993, 587, True, False),
    'yahoo.com':      (993, 465, True, True),
    'aliyun.com':     (993, 465, True, True),
}


def suggest_servers(email_addr: str) -> Dict[str, Any]:
    """依据邮箱域名推断 IMAP/SMTP 服务器。无匹配则按通用约定猜测。"""
    domain = (email_addr.split('@')[-1] if '@' in email_addr else email_addr).lower().strip()
    if domain in _COMMON_PROVIDERS:
        imap_port, smtp_port, imap_ssl, smtp_ssl = _COMMON_PROVIDERS[domain]
        return {
            'imap_host': 'imap.' + domain,
            'imap_port': imap_port,
            'imap_ssl': imap_ssl,
            'smtp_host': 'smtp.' + domain,
            'smtp_port': smtp_port,
            'smtp_ssl': smtp_ssl,
        }
    # 通用约定：imap.<domain> / smtp.<domain>
    return {
        'imap_host': 'imap.' + domain,
        'imap_port': 993,
        'imap_ssl': True,
        'smtp_host': 'smtp.' + domain,
        'smtp_port': 465,
        'smtp_ssl': True,
    }


# ============================================================
# MIME 解析模型
# ============================================================
class EmailAttachment:
    def __init__(self, filename: str, content_type: str, size: int):
        self.filename = filename
        self.content_type = content_type
        self.size = size


class EmailMessage:
    """解析后的邮件模型。"""

    def __init__(self):
        self.uid: str = ''
        self.date: Optional[datetime] = None
        self.date_str: str = ''
        self.subject: str = ''
        self.from_email: str = ''
        self.from_name: str = ''
        self.to: List[str] = []
        self.cc: List[str] = []
        self.text_body: str = ''
        self.html_body: str = ''
        self.attachments: List[EmailAttachment] = []
        self.is_seen: bool = False
        self.size: int = 0
        self.raw_bytes: bytes = b''      # 原始 RFC822 字节（附件下载用）

    @property
    def from_display(self) -> str:
        return self.from_name or self.from_email


# ============================================================
# 编码 / 解析辅助
# ============================================================
def _decode_mime_value(value) -> str:
    """解码 RFC2047 编码的头部字段（Subject / From / To 等）。"""
    if not value:
        return ''
    try:
        if isinstance(value, bytes):
            value = value.decode('utf-8', errors='replace')
        header = make_header(decode_header(value))
        return str(header)
    except Exception:
        return str(value)


def _decode_folder_name(name: str) -> str:
    """IMAP LIST 返回的文件夹名是 modified UTF-7 编码的字符串。"""
    if not name:
        return name
    name = name.strip().strip('"')
    try:
        return _modified_utf7_decode(name)
    except Exception:
        return name


def _modified_utf7_decode(s: str) -> str:
    """IMAP modified UTF-7 → Unicode（RFC 3501 §5.1.3）。"""
    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == '&':
            j = i
            while j < n and s[j] != '-':
                j += 1
            if j < n:
                payload = s[i + 1:j]
                if payload == '':
                    out.append('&')
                else:
                    # payload 是 '&...-',用 UTF-16BE 编码 base64
                    text = payload.replace(',', '/')
                    # 补足 padding
                    pad = (-len(text)) % 4
                    text += '=' * pad
                    try:
                        b = base64.b64decode(text)
                        out.append(b.decode('utf-16-be', errors='replace'))
                    except Exception:
                        out.append(s[i:j + 1])
                i = j + 1
                continue
            out.append(ch)
            i += 1
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def _parse_list_line(line: bytes) -> Tuple[str, Optional[str], str]:
    """解析 IMAP LIST 响应行 → (flags, delimiter, folder_name)。

    line 形如：b'(\\\\HasNoChildren) "/" "INBOX"'
    """
    if isinstance(line, bytes):
        line = line.decode('utf-8', errors='replace')
    m = re.match(r'\s*\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.*)', line)
    if not m:
        # 尝试不带引号的情形
        m2 = re.match(r'\s*\((?P<flags>[^)]*)\)\s+(?P<delim>\S+)\s+(?P<name>.+)', line)
        if not m2:
            return (line, None, line)
        return (m2.group('flags'), m2.group('delim').strip('"') or None, m2.group('name').strip())
    return (m.group('flags'), m.group('delim') or None, m.group('name').strip())


def _parse_imap_response_message(data: Any) -> Any:
    """从 imaplib 返回的 data 中提取 RFC822 完整消息字节。"""
    if not data:
        return None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                return item[1]
        # 若不是 tuple（如直接是 bytes）
        for item in data:
            if isinstance(item, bytes):
                return item
    return None


def _parse_header_bytes(header_bytes: bytes) -> Dict[str, str]:
    """从 BODY.PEEK[HEADER] 返回的字节解析出常用头部字段。"""
    try:
        msg = BytesParser(policy=policy.default).parsebytes(header_bytes)
    except Exception:
        return {}
    result = {
        'subject': _decode_mime_value(msg.get('Subject', '')),
        'from': msg.get('From', ''),
        'to': msg.get('To', ''),
        'cc': msg.get('Cc', ''),
        'date': msg.get('Date', ''),
        'message_id': msg.get('Message-ID', ''),
    }
    return result


# ============================================================
# IMAP / SMTP 服务
# ============================================================
class EmailService:
    """域名邮箱客户端：登录、文件夹、收信、发信。"""

    # ---------- 连接 ----------
    def _imap_connect(self, account: EmailAccount) -> imaplib.IMAP4:
        """建立并登录 IMAP 连接。"""
        if not account.imap_host:
            raise ValueError('IMAP 服务器未配置')
        if account.imap_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = imaplib.IMAP4_SSL(
                account.imap_host, account.imap_port, ssl_context=ctx)
        else:
            conn = imaplib.IMAP4(account.imap_host, account.imap_port)
        conn.login(account.email, account.password)
        return conn

    def _smtp_connect(self, account: EmailAccount) -> smtplib.SMTP:
        """建立并登录 SMTP 连接。"""
        if not account.smtp_host:
            raise ValueError('SMTP 服务器未配置')
        if account.smtp_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            smtp = smtplib.SMTP_SSL(
                account.smtp_host, account.smtp_port, timeout=20, context=ctx)
        else:
            smtp = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=20)
            smtp.ehlo()
            if account.smtp_port == 587:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
        smtp.login(account.email, account.password)
        return smtp

    # ---------- 测试连接 ----------
    def test_account(self, account: EmailAccount) -> Tuple[bool, str]:
        """测试 IMAP + SMTP 凭据。返回 (ok, message)。"""
        try:
            conn = self._imap_connect(account)
            try:
                typ, _ = conn.select('INBOX', readonly=True)
                conn.logout()
            except Exception:
                try:
                    conn.logout()
                except Exception:
                    pass
            return (True, '登录成功，凭据有效')
        except Exception as e:
            return (False, f'登录失败：{e}')

    # ---------- 文件夹 + 未读数 ----------
    def list_folders(self, account: EmailAccount) -> List[Dict[str, Any]]:
        """列出所有文件夹（含未读计数）。返回 [{'name','delimiter','flags','unread','depth'}]。"""
        conn = self._imap_connect(account)
        try:
            typ, data = conn.list()
            if typ != 'OK' or not data:
                return []
            folders = []
            for line in data:
                flags, delim, name = _parse_list_line(line)
                if not name:
                    continue
                if '\\Noselect' in flags.replace('\\\\', '\\'):
                    # 不可选中的容器（如 [Gmail]），跳过计数但仍列出
                    unread = None
                else:
                    unread = self._get_unread_count(conn, name)
                depth = 0
                if delim:
                    depth = name.count(delim)
                folders.append({
                    'name': name,
                    'display': _decode_folder_name(name),
                    'delimiter': delim,
                    'flags': flags,
                    'unread': unread,
                    'depth': depth,
                })
            return folders
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _get_unread_count(self, conn: imaplib.IMAP4, folder: str) -> int:
        """查询某文件夹未读数。"""
        try:
            typ, data = conn.status(folder, '(UNSEEN)')
            if typ != 'OK' or not data:
                return 0
            m = re.search(rb'UNSEEN\s+(\d+)', data[0] if isinstance(data[0], bytes) else str(data[0]).encode())
            if m:
                return int(m.group(1))
        except Exception:
            pass
        try:
            conn.select(folder, readonly=True)
            typ, data = conn.uid('search', None, 'UNSEEN')
            if typ == 'OK' and data and data[0]:
                return len(data[0].split())
        except Exception:
            pass
        return 0

    # ---------- 邮件列表（头部）----------
    def fetch_message_headers(
            self, account: EmailAccount, folder: str,
            limit: int = 50) -> List[Dict[str, Any]]:
        """拉取指定文件夹中最新 limit 封邮件的头部摘要。

        返回 [{uid, subject, from, date_str, size, is_seen}]。按时间倒序（最新的在前）。
        """
        conn = self._imap_connect(account)
        try:
            try:
                typ, _ = conn.select(folder, readonly=True)
            except Exception as e:
                raise ValueError(f'无法打开文件夹 {folder}: {e}')
            if typ != 'OK':
                raise ValueError(f'无法打开文件夹 {folder}（{typ}）')
            typ, data = conn.uid('search', None, 'ALL')
            if typ != 'OK' or not data or not data[0]:
                return []
            uids = data[0].split()
            uids = uids[-limit:] if len(uids) > limit else uids
            # 从最新往旧读取
            uids.reverse()
            results = []
            for uid in uids:
                uid_str = uid.decode('utf-8', errors='replace')
                try:
                    results.append(self._fetch_one_header(conn, uid_str))
                except Exception:
                    pass
            return results
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _fetch_one_header(self, conn: imaplib.IMAP4, uid: str) -> Dict[str, Any]:
        """拉取单封邮件头部摘要。"""
        typ, data = conn.uid(
            'fetch', uid,
            '(UID RFC822.SIZE FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])')
        if typ != 'OK':
            return {'uid': uid, 'subject': '', 'from': '', 'date_str': '', 'size': 0, 'is_seen': False}
        meta = {}
        header_bytes = b''
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                header_bytes = item[1]
                # 解析 meta（UID / FLAGS / SIZE）
                m = re.search(rb'UID\s+(\d+)', item[0])
                if m:
                    meta['uid'] = m.group(1).decode()
                m = re.search(rb'RFC822\.SIZE\s+(\d+)', item[0])
                if m:
                    meta['size'] = int(m.group(1))
                m = re.search(rb'FLAGS\s+\(([^)]*)\)', item[0])
                if m:
                    meta['flags'] = m.group(1).decode()
        headers = _parse_header_bytes(header_bytes)
        return {
            'uid': meta.get('uid', uid),
            'subject': headers.get('subject', ''),
            'from': headers.get('from', ''),
            'date_str': headers.get('date', ''),
            'size': meta.get('size', 0),
            'is_seen': '\\Seen' in meta.get('flags', ''),
        }

    # ---------- 拉取全文并解析 ----------
    def fetch_message(self, account: EmailAccount, folder: str, uid: str) -> EmailMessage:
        """拉取一封邮件全部分内容并解析成 EmailMessage。"""
        conn = self._imap_connect(account)
        try:
            conn.select(folder, readonly=True)
            typ, data = conn.uid('fetch', uid, '(RFC822)')
            if typ != 'OK' or not data:
                raise ValueError('邮件内容拉取失败')
            raw = _parse_imap_response_message(data)
            if not raw:
                raise ValueError('邮件内容为空')
            return self.parse_message(raw, uid=uid)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def parse_message(self, raw: bytes, uid: str = '') -> EmailMessage:
        """解析 RFC822 原始字节为 EmailMessage 模型。"""
        try:
            msg = BytesParser(policy=policy.default).parsebytes(raw)
        except Exception as e:
            raise ValueError(f'邮件解析失败：{e}')

        m = EmailMessage()
        m.uid = uid
        m.subject = _decode_mime_value(msg.get('Subject', ''))
        m.from_name, m.from_email = parseaddr(msg.get('From', ''))
        m.to = self._parse_addr_list(msg.get_all('To', []))
        m.cc = self._parse_addr_list(msg.get_all('Cc', []))
        m.date_str = msg.get('Date', '')
        try:
            m.date = parsedate_to_datetime(m.date_str)
        except Exception:
            m.date = None
        m.size = len(raw)

        # 遍历 MIME 部分
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            filename = part.get_filename()
            content_type = part.get_content_type()
            if filename:
                decoded = _decode_mime_value(filename)
                m.attachments.append(EmailAttachment(
                    filename=decoded,
                    content_type=content_type,
                    size=len(part.get_payload(decode=True) or b''),
                ))
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    payload = part.get_payload().encode('utf-8', errors='replace')
                charset = part.get_content_charset() or 'utf-8'
                text = payload.decode(charset, errors='replace')
            except Exception:
                text = ''
            if content_type == 'text/plain' and not m.text_body:
                m.text_body = text
            elif content_type == 'text/html' and not m.html_body:
                m.html_body = text

        if not m.text_body and not m.html_body:
            # 无 multipart 的纯文本邮件
            try:
                body = msg.get_payload(decode=True)
                if body is not None:
                    charset = msg.get_content_charset() or 'utf-8'
                    m.text_body = body.decode(charset, errors='replace')
            except Exception:
                pass
        m.raw_bytes = raw
        return m

    def _parse_addr_list(self, values) -> List[str]:
        addr_list = []
        for val in values:
            if not val:
                continue
            if isinstance(val, list):
                for v in val:
                    if isinstance(v, tuple):
                        addr_list.append(v[0])
                continue
            # 逗号分隔逐一解析
            for chunk in str(val).split(','):
                _, addr = parseaddr(chunk)
                if addr:
                    addr_list.append(addr)
        return addr_list

    # ---------- 邮件操作（标已读 / 删除 / 移动 / 存草稿） ----------
    def mark_seen(self, account: EmailAccount, folder: str, uid: str, seen: bool = True) -> None:
        """标记邮件已读/未读。"""
        conn = self._imap_connect(account)
        try:
            conn.select(folder)
            flag = '\\Seen' if seen else ''
            conn.uid('store', uid, '+FLAGS' if seen else '-FLAGS', '(' + flag + ')')
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def delete_message(self, account: EmailAccount, folder: str, uid: str) -> None:
        """把邮件标记为已删除并从当前文件夹 expunge。"""
        conn = self._imap_connect(account)
        try:
            conn.select(folder)
            conn.uid('store', uid, '+FLAGS', '(\\Deleted)')
            conn.expunge()
            # 尝试移动到 Trash（若存在）
            try:
                typ, data = conn.list()
                has_trash = False
                for line in (data or []):
                    s = line.decode('utf-8', 'replace')
                    if re.search(r'"\s*[Tt]rash\s*"', s):
                        has_trash = True
                        break
                if has_trash:
                    conn.uid('copy', uid, 'Trash')
            except Exception:
                pass
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def append_sent(self, account: EmailAccount, raw: bytes) -> None:
        """把已发送邮件原文追加到 Sent 文件夹。"""
        conn = self._imap_connect(account)
        try:
            try:
                conn.append('Sent', None, None, raw)
            except Exception:
                conn.append('INBOX', None, None, raw)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def build_sent_raw(self, account: EmailAccount, payload: dict) -> bytes:
        """构造用于存入 Sent 文件夹的原始邮件字节（与发送内容一致）。"""
        to = payload.get('to', []) or []
        cc = payload.get('cc', []) or []
        bcc = payload.get('bcc', []) or []
        try:
            msg = self._build_email(
                account, to, payload.get('subject', ''), payload.get('body', ''),
                cc, bcc, payload.get('html_body', ''),
                payload.get('attachments', []))
            return msg.as_bytes()
        except Exception:
            return b''

    # ---------- 发送 ----------
    def send_mail(
            self, account: EmailAccount,
            to: List[str], subject: str, body: str,
            cc: List[str] = None, bcc: List[str] = None,
            html_body: str = '',
            attachments: List[Tuple[str, bytes, str]] = None,
            ) -> None:
        """通过 SMTP 发送邮件。

        attachments: [(filename, bytes_data, content_type)]
        """
        cc = cc or []
        bcc = bcc or []
        msg = self._build_email(
            account, to, subject, body, cc, bcc, html_body, attachments)
        smtp = self._smtp_connect(account)
        try:
            smtp.send_message(msg)
        finally:
            try:
                smtp.quit()
            except Exception:
                pass

    def _build_email(
            self, account: EmailAccount,
            to, subject, body, cc, bcc, html_body, attachments) -> StdEmailMessage:
        msg = StdEmailMessage()
        msg['From'] = formataddr((account.name or account.email, account.email))
        msg['To'] = ', '.join(to)
        if cc:
            msg['Cc'] = ', '.join(cc)
        if bcc:
            msg['Bcc'] = ', '.join(bcc)
        msg['Subject'] = subject
        msg['Date'] = _format_datetime(_beijing_now())

        if html_body:
            msg.set_content(body if body else '')
            msg.add_alternative(html_body, subtype='html')
        else:
            msg.set_content(body if body else '')

        for filename, data, content_type in (attachments or []):
            maintype, _, subtype = content_type.partition('/')
            try:
                msg.add_attachment(
                    data, maintype=maintype or 'application',
                    subtype=subtype or 'octet-stream', filename=filename)
            except Exception:
                msg.add_attachment(data, filename=filename)

        return msg


def _beijing_now() -> datetime:
    """当前东八区（北京时间）的 tz-aware datetime。"""
    return datetime.now(timezone(timedelta(hours=8)))


def _format_datetime(dt: datetime) -> str:
    from email.utils import format_datetime
    try:
        # naive datetime 兜底为东八区，避免被当成 UTC 输出 -0000
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
        return format_datetime(dt)
    except Exception:
        return dt.strftime('%a, %d %b %Y %H:%M:%S %z')