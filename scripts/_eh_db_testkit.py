# -*- coding: utf-8 -*-
"""E-Hentai 冒烟测试的数据库隔离小工具
================================================

数据库统一之后（见 ``core/db_unify.py``），E-Hentai 的表就住在**账号库**
``data/ogc_users.db`` 里。冒烟脚本如果直接读写它，就会污染真实数据 ——
这些脚本要写下载记录、历史、收藏、标签屏蔽，必须跑在副本上。

用法::

    from _eh_db_testkit import use_temp_db, cleanup_temp_db
    tmp_dir, tmp_db = use_temp_db()      # 统一库的一份副本，已指给 ehviewer
    try:
        ...
    finally:
        cleanup_temp_db(tmp_dir)          # 会先 set_db_path(None) 还原

要点：
* ``core.database.DB_PATH`` 与 ``ehviewer.db`` 在测试进程里指向同一个文件
  （导入期就决定），所以这里拷贝统一库、再用 ``ehdb.set_db_path()`` 把
  ehviewer 切到副本；``ehentai_sync.db_path()`` / 收藏页的 ``db_path()`` 都走
  ``ehdb.get_db_path()``，因此会一起跟到副本上。
* 副本不存在时由 SQLite 建空库 + 由 ``ehdb._init_tables()`` 建全表结构，
  全新仓库（还没有 data/ogc_users.db）也能跑。
"""
import os
import shutil
import tempfile


def unified_db_path() -> str:
    """当前进程认定的统一库路径。"""
    from core.database import get_db_path
    return get_db_path()


def use_temp_db(prefix: str = 'ogc_eh_db_'):
    """把 ehviewer 指到统一库的一份临时副本，返回 ``(临时目录, 副本路径)``。"""
    from ehviewer import db as ehdb

    src = unified_db_path()
    tmp = tempfile.mkdtemp(prefix=prefix)
    dst = os.path.join(tmp, os.path.basename(src) or 'ogc_users.db')
    if os.path.isfile(src):
        shutil.copy2(src, dst)
        # WAL 模式下最近的改动可能还在 -wal 里；直接拷文件会丢掉它们。
        # 用 SQLite 的在线备份 API 拿到一致快照（与 core/db_unify 同一套做法）。
        try:
            import sqlite3
            s = sqlite3.connect(src, timeout=10.0)
            d = sqlite3.connect(dst)
            try:
                s.backup(d)
            finally:
                d.close()
                s.close()
        except Exception:
            pass
    ehdb.set_db_path(dst)
    # 立刻建全表结构（空副本时 SQLite 只有 0 字节）
    try:
        ehdb._get_conn()
    except Exception:
        pass
    return tmp, dst


def cleanup_temp_db(tmp_dir: str, restore: bool = True) -> None:
    """还原 ehviewer 的数据库指向并删除临时目录。"""
    if restore:
        try:
            from ehviewer import db as ehdb
            ehdb.set_db_path(None)
        except Exception:
            pass
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)
