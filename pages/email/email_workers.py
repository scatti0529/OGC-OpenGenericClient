# -*- coding: utf-8 -*-
"""
邮箱模块 - 后台线程 Workers
===========================
所有 imaplib / smtplib 网络操作都在 QThread 子线程中执行，避免阻塞主 UI。

每个 Worker 负责一个独立操作，成功/失败通过信号回传到 UI：
    EmailWorker 基类     —— 通用 try/except 包装
    FetchFoldersWorker   —— 列出文件夹（含未读数）
    FetchHeadersWorker   —— 拉取邮件列表摘要
    FetchMessageWorker   —— 拉取单封邮件全文并解析
    SendMailWorker       —— SMTP 发送
    TestAccountWorker    —— 测试账号凭据
    OperationWorker      —— 标记已读/未读、删除
"""

from PyQt5.QtCore import QThread, pyqtSignal

from services.email_service import EmailService, EmailAccount


class EmailWorker(QThread):
    """所有邮箱后台任务的基类（成功/失败信号 + 通用异常包装）。"""

    succeeded = pyqtSignal(object)   # 成功结果
    failed = pyqtSignal(str)         # 错误消息

    def __init__(self, account: EmailAccount, parent=None):
        super().__init__(parent)
        self.account = account
        self._stop = False
        self.service = EmailService()

    def stop(self):
        self._stop = True

    def _work(self):
        """子类实现，返回结果对象。"""
        raise NotImplementedError

    def run(self):
        try:
            result = self._work()
            if not self._stop:
                self.succeeded.emit(result)
        except Exception as e:
            if not self._stop:
                self.failed.emit(str(e))


class FetchFoldersWorker(EmailWorker):
    """列出全部文件夹（含未读数）。"""

    def _work(self):
        return self.service.list_folders(self.account)


class FetchHeadersWorker(EmailWorker):
    """拉取指定文件夹的最新邮件列表摘要。"""

    def __init__(self, account: EmailAccount, folder: str, limit: int = 50, parent=None):
        super().__init__(account, parent)
        self.folder = folder
        self.limit = limit

    def _work(self):
        return self.service.fetch_message_headers(self.account, self.folder, self.limit)


class FetchMessageWorker(EmailWorker):
    """拉取并解析单封邮件全文。"""

    def __init__(self, account: EmailAccount, folder: str, uid: str, parent=None):
        super().__init__(account, parent)
        self.folder = folder
        self.uid = uid

    def _work(self):
        return self.service.fetch_message(self.account, self.folder, self.uid)


class SendMailWorker(EmailWorker):
    """SMTP 发送邮件。"""

    def __init__(self, account: EmailAccount, payload: dict, parent=None):
        super().__init__(account, parent)
        self.payload = payload

    def _work(self):
        self.service.send_mail(
            self.account,
            to=self.payload.get('to', []),
            subject=self.payload.get('subject', ''),
            body=self.payload.get('body', ''),
            cc=self.payload.get('cc', []),
            bcc=self.payload.get('bcc', []),
            html_body=self.payload.get('html_body', ''),
            attachments=self.payload.get('attachments', []),
        )
        res = '已发送'
        # 发送成功后把原文存入 Sent 文件夹（供「已发送」分区可见）
        try:
            raw = self.service.build_sent_raw(self.account, self.payload)
            if raw:
                self.service.append_sent(self.account, raw)
        except Exception:
            pass
        return res


class TestAccountWorker(EmailWorker):
    """测试 IMAP+SMTP 凭据是否有效。"""

    def __init__(self, account: EmailAccount, parent=None):
        super().__init__(account, parent)

    def _work(self):
        ok, message = self.service.test_account(self.account)
        if not ok:
            raise ValueError(message)
        return message


class OperationWorker(EmailWorker):
    """标记已读/未读、删除。"""

    def __init__(self, account: EmailAccount, op: str,
                 folder: str = 'INBOX', uid: str = '', seen: bool = True, parent=None):
        super().__init__(account, parent)
        self.op = op
        self.folder = folder
        self.uid = uid
        self.seen = seen

    def _work(self):
        if self.op == 'mark_seen':
            self.service.mark_seen(self.account, self.folder, self.uid, self.seen)
            return 'ok'
        if self.op == 'delete':
            self.service.delete_message(self.account, self.folder, self.uid)
            return 'deleted'
        raise ValueError(f'未知操作：{self.op}')