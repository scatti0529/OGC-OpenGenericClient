# -*- coding: utf-8 -*-
"""EhViewer 移植子系统的 OGC 桥接。

负责：
1. 让 ehviewer.db 指向与 E-Hentai 模块同一份共享数据库（app_db.db）。
2. 若共享库处于只读状态，则清除 Windows 只读属性，保证 下载/历史/收藏/评分 能写入。
3. 提供 show_notify 供 ehviewer 子系统（ctx.notify / bus.notify）提示。
"""
import ast
import os
import stat

from ehviewer import db as ehdb
from ehviewer.config import CFG as eh_cfg, set as eh_set

# 常见伴随文件（WAL/journal/shm），避免残留只读锁
_SIDE_FILES = ("-wal", "-shm", "-journal")


def _cookies_text_to_dict(text):
    """把 OGC ehentai_cfg 的 cookies 字符串（dict 文本 或 k=v; k2=v2）解析成 dict。"""
    text = (text or "").strip()
    if not text or text == "{}":
        return {}
    try:
        v = ast.literal_eval(text)
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
    except Exception:
        pass
    out = {}
    for part in text.split(";"):
        part = part.strip()
        if "=" in part:
            k, val = part.split("=", 1)
            out[k.strip()] = val.strip()
    return out


def sync_ogc_to_ehviewer(ogc_cfg):
    """把 OGC ehentai_cfg 的 登录Cookie / 代理 / 超时 同步到 ehviewer 子系统配置。

    这样无论用户在哪个登录入口登录，EhViewer 拓展都能共享同一登录态与代理。
    """
    try:
        cookies = _cookies_text_to_dict(ogc_cfg.get(ogc_cfg.KEY_COOKIES) or "")
        if cookies:
            eh_set("cookies", cookies)
        proxy = ogc_cfg.get(ogc_cfg.KEY_PROXY) or ""
        if proxy:
            eh_set("proxy", proxy)
        timeout = ogc_cfg.get(ogc_cfg.KEY_TIMEOUT)
        if timeout:
            eh_set("timeout", int(timeout))
    except Exception:
        pass


def _clear_readonly(path):
    try:
        if not os.path.exists(path):
            return True
        st = os.stat(path)
        # FILE_ATTRIBUTE_READONLY = 0x1
        if st.st_file_attributes & 0x1:
            os.chmod(path, stat.S_IWRITE)
            st = os.stat(path)
        return not (st.st_file_attributes & 0x1)
    except Exception:
        return False


def ensure_writable(path):
    """若 db 文件（及伴随文件）只读则改可写，返回是否已可写。"""
    ok = _clear_readonly(path)
    for sf in _SIDE_FILES:
        _clear_readonly(path + sf)
    return ok


def route_to_shared_db(db_path):
    """将 ehviewer.db 指向共享数据库。db_path 为空则用包内默认。"""
    if not db_path:
        ehdb.set_db_path(None)
        return ehdb.get_db_path()
    ensure_writable(db_path)
    ehdb.set_db_path(db_path)
    return ehdb.get_db_path()


def shared_db_path(default_db_path: str) -> str:
    """返回最终数据库路径（默认即共享库）。"""
    return default_db_path or ehdb.get_db_path()
