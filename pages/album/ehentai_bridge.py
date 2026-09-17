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
    """把 ehviewer.db 指向统一数据库。

    ⚠️ 数据库已合并为一个（``core.database.DB_PATH``），所以传进来的路径只用于
    **兼容旧调用**：``ehviewer.db.set_db_path()`` 现在会忽略任何"换成别的库"的请求，
    本函数直接返回统一库路径。以前让界面从 A 库读、下载记录写进 B 库会让双方都
    看不到对方的数据，合并后刻意禁掉这种能力。
    """
    try:
        # 旧库若还存在，顺手把它的数据并进统一库（幂等，已并过就什么都不做）
        from core.database import get_db_path
        unified = get_db_path()
        if db_path and os.path.normcase(os.path.abspath(db_path)) != \
                os.path.normcase(os.path.abspath(unified)) and os.path.isfile(db_path):
            try:
                from core import db_unify
                r = db_unify.merge_database(db_path, target_path=unified,
                                            rename_source=False)
                if r['moved']:
                    print(f'[ehentai] 已从 {db_path} 合并 {r["moved"]} 行到统一库')
            except Exception as e:
                print(f'[ehentai] 合并 {db_path} 失败（忽略）: {e}')
        ehdb.set_db_path(None)
        return unified
    except Exception:
        return ehdb.get_db_path()


def shared_db_path(default_db_path: str) -> str:
    """返回最终数据库路径（永远是统一库）。"""
    try:
        from core.database import get_db_path
        return get_db_path()
    except Exception:
        return default_db_path or ehdb.get_db_path()
