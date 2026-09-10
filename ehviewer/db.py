# -*- coding: utf-8 -*-
"""SQLite 持久层 —— 完全适配 Android 版 EhViewer (greenDAO) 数据库结构
数据库：EhViewer_PC/app_db.db
表：DOWNLOADS 下载记录 / DOWNLOAD_LABELS 下载分类 / DOWNLOAD_DIRNAME 下载目录名 /
    HISTORY 历史 / LOCAL_FAVORITES 本地收藏 / QUICK_SEARCH 快速搜索(标签收藏) / FILTER 标签屏蔽
    （另有 Gallery_Tags / Black_List / BOOKMARKS 原表，本程序暂不使用）
进度字段（finished/total/speed 等）Android 版仅存内存不入库，本程序同样只存内存。
"""
import os
import sqlite3
import threading
import time

from . import constants as C
from .models import GalleryInfo

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_db.db")
DB_DIR = os.path.dirname(DB_PATH)

# OGC 集成：允许在运行时把数据库指向与 E-Hentai 模块同一份 app_db.db（共享数据库）。
# set_db_path() 须在首次访问连接之前调用；调用后会重建内部连接缓存。
_CUSTOM_DB_PATH = None


def set_db_path(path):
    """设置共享数据库路径（传 None 还原为包内默认）。

    必须在**锁内**切换并显式关闭旧连接：原实现在锁外把 ``_conn = None``
    且不 close 旧连接 —— 运行中切库时，已持有旧 connection 的查询会继续
    读写旧库文件，而新查询走新库，造成"状态分叉"（下载记录写进 A 库、
    界面从 B 库读，双方都看不到对方），旧连接句柄也只能等 GC 才释放。
    """
    global _CUSTOM_DB_PATH, _conn, _COLS
    with _lock:
        old = _conn
        _conn = None
        _COLS = {}
        _CUSTOM_DB_PATH = path
    # 关闭放在锁外，避免持锁做可能阻塞的 IO
    if old is not None:
        try:
            old.close()
        except Exception:
            pass


def get_db_path():
    return _CUSTOM_DB_PATH or DB_PATH


_lock = threading.RLock()
_conn = None
_COLS = {}          # 表名 -> 列名集合（小写）
STATE_NONE, STATE_WAIT, STATE_DOWNLOAD = C.STATE_NONE, C.STATE_WAIT, C.STATE_DOWNLOAD
STATE_FINISH, STATE_FAILED = C.STATE_FINISH, C.STATE_FAILED

DDL = {
    "DOWNLOADS": """
        CREATE TABLE IF NOT EXISTS "DOWNLOADS" (
          "GID" INTEGER PRIMARY KEY NOT NULL, "TOKEN" TEXT, "TITLE" TEXT, "TITLE_JPN" TEXT,
          "THUMB" TEXT, "CATEGORY" INTEGER NOT NULL, "POSTED" TEXT, "UPLOADER" TEXT,
          "RATING" REAL NOT NULL, "SIMPLE_LANGUAGE" TEXT, "STATE" INTEGER NOT NULL,
          "LEGACY" INTEGER NOT NULL, "TIME" INTEGER NOT NULL, "LABEL" TEXT,
          "ARCHIVE_URI" TEXT)""",
    "DOWNLOAD_LABELS": """
        CREATE TABLE IF NOT EXISTS "DOWNLOAD_LABELS" (
          "_id" INTEGER PRIMARY KEY, "LABEL" TEXT, "TIME" INTEGER NOT NULL)""",
    "DOWNLOAD_DIRNAME": """
        CREATE TABLE IF NOT EXISTS "DOWNLOAD_DIRNAME" (
          "GID" INTEGER PRIMARY KEY, "DIRNAME" TEXT)""",
    "HISTORY": """
        CREATE TABLE IF NOT EXISTS "HISTORY" (
          "GID" INTEGER PRIMARY KEY NOT NULL, "TOKEN" TEXT, "TITLE" TEXT, "TITLE_JPN" TEXT,
          "THUMB" TEXT, "CATEGORY" INTEGER NOT NULL, "POSTED" TEXT, "UPLOADER" TEXT,
          "RATING" REAL NOT NULL, "SIMPLE_LANGUAGE" TEXT, "MODE" INTEGER NOT NULL,
          "TIME" INTEGER NOT NULL)""",
    "LOCAL_FAVORITES": """
        CREATE TABLE IF NOT EXISTS "LOCAL_FAVORITES" (
          "GID" INTEGER PRIMARY KEY NOT NULL, "TOKEN" TEXT, "TITLE" TEXT, "TITLE_JPN" TEXT,
          "THUMB" TEXT, "CATEGORY" INTEGER NOT NULL, "POSTED" TEXT, "UPLOADER" TEXT,
          "RATING" REAL NOT NULL, "SIMPLE_LANGUAGE" TEXT, "TIME" INTEGER NOT NULL)""",
    "QUICK_SEARCH": """
        CREATE TABLE IF NOT EXISTS "QUICK_SEARCH" (
          "_id" INTEGER PRIMARY KEY, "NAME" TEXT, "MODE" INTEGER NOT NULL,
          "CATEGORY" INTEGER NOT NULL, "KEYWORD" TEXT, "ADVANCE_SEARCH" INTEGER NOT NULL,
          "MIN_RATING" INTEGER NOT NULL, "PAGE_FROM" INTEGER NOT NULL,
          "PAGE_TO" INTEGER NOT NULL, "TIME" INTEGER NOT NULL)""",
    "FILTER": """
        CREATE TABLE IF NOT EXISTS "FILTER" (
          "_id" INTEGER PRIMARY KEY, "MODE" INTEGER NOT NULL, "TEXT" TEXT, "ENABLE" INTEGER)""",
    "GALLERY_TAGS": """
        CREATE TABLE IF NOT EXISTS "Gallery_Tags" (
          "GID" INTEGER PRIMARY KEY NOT NULL, "ROWS" TEXT, "ARTIST" TEXT, "COSPLAYER" TEXT,
          "CHARACTER" TEXT, "FEMALE" TEXT, "GROUP" TEXT, "LANGUAGE" TEXT, "MALE" TEXT,
          "MISC" TEXT, "MIXED" TEXT, "OTHER" TEXT, "PARODY" TEXT, "RECLASS" TEXT,
          "CREATE_TIME" INTEGER, "UPDATE_TIME" INTEGER)""",
    "BLACK_LIST": """
        CREATE TABLE IF NOT EXISTS "Black_List" (
          "_id" INTEGER PRIMARY KEY AUTOINCREMENT, "BADGAYNAME" TEXT, "REASON" TEXT,
          "ANGRYWITH" TEXT, "ADD_TIME" TEXT, "MODE" INTEGER)""",
    "BOOKMARKS": """
        CREATE TABLE IF NOT EXISTS "BOOKMARKS" (
          "GID" INTEGER PRIMARY KEY NOT NULL, "TOKEN" TEXT, "TITLE" TEXT, "TITLE_JPN" TEXT,
          "THUMB" TEXT, "CATEGORY" INTEGER NOT NULL, "POSTED" TEXT, "UPLOADER" TEXT,
          "RATING" REAL NOT NULL, "SIMPLE_LANGUAGE" TEXT, "PAGE" INTEGER NOT NULL,
          "TIME" INTEGER NOT NULL)""",
}

# FILTER.MODE 语义（与 Android EhFilter 一致）
FILTER_TITLE = 0
FILTER_UPLOADER = 1
FILTER_TAG = 2
FILTER_TAG_NAMESPACE = 3


def _get_conn():
    """获取共享连接（线程安全的惰性初始化 + 并发加固）。

    原实现没有加锁：两个线程同时首次访问会各自建立一个连接，多出来的那个
    成为**无人关闭的泄漏连接**，`_COLS` 也会被重复写入。

    另外该库（app_db.db）还会被 ehentai_sync 等模块用独立短连接并发读写，
    默认 journal 模式下读写互斥，很容易 "database is locked"，而调用方
    普遍 ``except Exception: return False`` 把它吞掉 —— 表现为下载记录/收藏
    静默丢失。这里统一开启 WAL + 忙等超时。
    """
    global _conn
    with _lock:
        if _conn is None:
            path = get_db_path()
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.Error:
                pass
            _init_tables(conn)
            _conn = conn
        return _conn


def _init_tables(conn):
    cur = conn.cursor()
    for ddl in DDL.values():
        try:
            cur.execute(ddl)
        except sqlite3.Error:
            pass
    # 记录每张表的实际列名（兼容列缺失）
    for t in DDL:
        try:
            cols = [r[1].lower() for r in cur.execute("PRAGMA table_info(%s)" % t).fetchall()]
            _COLS[t] = set(cols)
        except sqlite3.Error:
            _COLS[t] = set()
    conn.commit()


def _has_col(table, name):
    return name.lower() in _COLS.get(table, set())


def _g(row, name, default=None):
    """按列名安全取值（sqlite3.Row 大小写不敏感，这里统一小写判断）"""
    try:
        v = row[name]
        return default if v is None else v
    except (IndexError, KeyError, TypeError):
        return default


def _row_to_gallery(row, table="DOWNLOADS"):
    g = GalleryInfo()
    g.gid = _g(row, "GID", 0)
    g.token = _g(row, "TOKEN", "") or ""
    g.title = _g(row, "TITLE", "") or ""
    g.title_jpn = _g(row, "TITLE_JPN", "") or ""
    g.thumb = _g(row, "THUMB", "") or ""
    g.category = _g(row, "CATEGORY", C.UNKNOWN_CATEGORY) or C.UNKNOWN_CATEGORY
    g.posted = _g(row, "POSTED", "") or ""
    g.uploader = _g(row, "UPLOADER", "") or ""
    g.rating = _g(row, "RATING", 0.0) or 0.0
    g.simple_language = _g(row, "SIMPLE_LANGUAGE")
    g.simple_tags = None
    return g


def _gallery_params(g):
    return {
        "gid": g.gid, "token": g.token or "", "title": g.title or "",
        "title_jpn": g.title_jpn or "", "thumb": g.thumb or "",
        "category": g.category or C.UNKNOWN_CATEGORY, "posted": g.posted or "",
        "uploader": g.uploader or "", "rating": g.rating or 0.0,
        "simple_language": g.simple_language,
    }


# ================= 下载记录 =================

def insert_download(g, state=C.STATE_NONE, label="", total=0, finished=0):
    with _lock:
        conn = _get_conn()
        p = _gallery_params(g)
        p["state"] = state
        p["label"] = label or None
        p["time"] = int(time.time() * 1000)
        conn.execute("""
            INSERT OR REPLACE INTO DOWNLOADS
            (GID, TOKEN, TITLE, TITLE_JPN, THUMB, CATEGORY, POSTED, UPLOADER, RATING,
             SIMPLE_LANGUAGE, STATE, LEGACY, TIME, LABEL)
            VALUES (:gid,:token,:title,:title_jpn,:thumb,:category,:posted,:uploader,:rating,
             :simple_language,:state,0,:time,:label)""", p)
        conn.commit()


def update_download_state(gid, state, label=None, finished=None, total=None, downloaded=None):
    """更新状态；finished/total/downloaded 为内存字段，Android 表无对应列则忽略"""
    with _lock:
        conn = _get_conn()
        sets, params = ["STATE=?"], [state]
        if label is not None:
            sets.append("LABEL=?"); params.append(label)
        params.append(gid)
        conn.execute("UPDATE DOWNLOADS SET %s WHERE GID=?" % ", ".join(sets), params)
        conn.commit()


def update_download_gallery_info(g):
    with _lock:
        conn = _get_conn()
        p = _gallery_params(g)
        conn.execute("""
            UPDATE DOWNLOADS SET TOKEN=:token, TITLE=:title, TITLE_JPN=:title_jpn,
            THUMB=:thumb, CATEGORY=:category, POSTED=:posted, UPLOADER=:uploader,
            RATING=:rating, SIMPLE_LANGUAGE=:simple_language WHERE GID=:gid""", p)
        conn.commit()


def delete_download(gid):
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM DOWNLOADS WHERE GID=?", (gid,))
        conn.commit()


def get_download(gid):
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM DOWNLOADS WHERE GID=?", (gid,)).fetchone()
        if not row:
            return None
        g = _row_to_gallery(row)
        g.state = _g(row, "STATE", C.STATE_NONE)
        g.label = _g(row, "LABEL")
        g.time = _g(row, "TIME", 0)
        g.total = 0
        g.finished = 0
        return g


def list_downloads():
    with _lock:
        conn = _get_conn()
        rows = conn.execute("SELECT * FROM DOWNLOADS ORDER BY TIME DESC").fetchall()
        out = []
        for row in rows:
            g = _row_to_gallery(row)
            g.state = _g(row, "STATE", C.STATE_NONE)
            g.label = _g(row, "LABEL")
            g.time = _g(row, "TIME", 0)
            g.total = 0
            g.finished = 0
            out.append(g)
        return out


def list_downloads_finished():
    """已完成的下载记录（本地画册用）"""
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM DOWNLOADS WHERE STATE=? ORDER BY TIME DESC",
            (C.STATE_FINISH,)).fetchall()
        out = []
        for row in rows:
            g = _row_to_gallery(row)
            g.state = _g(row, "STATE", C.STATE_NONE)
            g.label = _g(row, "LABEL")
            g.time = _g(row, "TIME", 0)
            g.total = 0
            g.finished = 0
            out.append(g)
        return out


def get_download_state(gid):
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT STATE FROM DOWNLOADS WHERE GID=?", (gid,)).fetchone()
        return row["STATE"] if row else C.STATE_NONE


# ================= 下载分类（DOWNLOAD_LABELS） =================

def add_label(label):
    label = (label or "").strip()
    if not label:
        return None
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT _id FROM DOWNLOAD_LABELS WHERE LABEL=?", (label,)).fetchone()
        if row:
            return row["_id"]
        cur = conn.execute("INSERT INTO DOWNLOAD_LABELS (LABEL, TIME) VALUES (?,?)",
                           (label, int(time.time() * 1000)))
        conn.commit()
        return cur.lastrowid


def list_labels():
    with _lock:
        conn = _get_conn()
        rows = conn.execute("SELECT * FROM DOWNLOAD_LABELS ORDER BY TIME").fetchall()
        return [{"id": r["_id"], "label": r["LABEL"], "time": r["TIME"]} for r in rows]


def rename_label(lid, new_label):
    new_label = (new_label or "").strip()
    if not new_label:
        return
    with _lock:
        conn = _get_conn()
        old = conn.execute("SELECT LABEL FROM DOWNLOAD_LABELS WHERE _id=?", (lid,)).fetchone()
        if old is None:
            return
        conn.execute("UPDATE DOWNLOAD_LABELS SET LABEL=? WHERE _id=?", (new_label, lid))
        conn.execute("UPDATE DOWNLOADS SET LABEL=? WHERE LABEL=?", (new_label, old["LABEL"]))
        conn.commit()


def delete_label(lid):
    """删除分类：该分类下的下载记录回到未分类（LABEL 置 NULL）"""
    with _lock:
        conn = _get_conn()
        old = conn.execute("SELECT LABEL FROM DOWNLOAD_LABELS WHERE _id=?", (lid,)).fetchone()
        if old is None:
            return
        conn.execute("DELETE FROM DOWNLOAD_LABELS WHERE _id=?", (lid,))
        conn.execute("UPDATE DOWNLOADS SET LABEL=NULL WHERE LABEL=?", (old["LABEL"],))
        conn.commit()


# ================= 下载目录名（DOWNLOAD_DIRNAME） =================

def put_download_dirname(gid, dirname):
    with _lock:
        conn = _get_conn()
        conn.execute("INSERT OR REPLACE INTO DOWNLOAD_DIRNAME (GID, DIRNAME) VALUES (?,?)",
                     (gid, dirname))
        conn.commit()


def get_download_dirname(gid):
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT DIRNAME FROM DOWNLOAD_DIRNAME WHERE GID=?", (gid,)).fetchone()
        return row["DIRNAME"] if row else None


def remove_download_dirname(gid):
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM DOWNLOAD_DIRNAME WHERE GID=?", (gid,))
        conn.commit()


# ================= 历史（HISTORY） =================

def add_history(g, mode=0):
    with _lock:
        conn = _get_conn()
        p = _gallery_params(g)
        p["mode"] = mode
        p["time"] = int(time.time() * 1000)
        conn.execute("""
            INSERT OR REPLACE INTO HISTORY
            (GID, TOKEN, TITLE, TITLE_JPN, THUMB, CATEGORY, POSTED, UPLOADER, RATING,
             SIMPLE_LANGUAGE, MODE, TIME)
            VALUES (:gid,:token,:title,:title_jpn,:thumb,:category,:posted,:uploader,:rating,
             :simple_language,:mode,:time)""", p)
        conn.commit()


def list_history(limit=500):
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM HISTORY ORDER BY TIME DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_gallery(r, "HISTORY") for r in rows]


def clear_history():
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM HISTORY")
        conn.commit()


def delete_history(gid):
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM HISTORY WHERE GID=?", (gid,))
        conn.commit()


# ================= 本地收藏（LOCAL_FAVORITES） =================

def add_local_favorite(g, slot=-1):
    with _lock:
        conn = _get_conn()
        # Android 语义：仅当不存在时插入
        row = conn.execute("SELECT GID FROM LOCAL_FAVORITES WHERE GID=?", (g.gid,)).fetchone()
        if row:
            return False
        p = _gallery_params(g)
        p["time"] = int(time.time() * 1000)
        conn.execute("""
            INSERT OR REPLACE INTO LOCAL_FAVORITES
            (GID, TOKEN, TITLE, TITLE_JPN, THUMB, CATEGORY, POSTED, UPLOADER, RATING,
             SIMPLE_LANGUAGE, TIME)
            VALUES (:gid,:token,:title,:title_jpn,:thumb,:category,:posted,:uploader,:rating,
             :simple_language,:time)""", p)
        conn.commit()
        return True


def delete_local_favorite(gid):
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM LOCAL_FAVORITES WHERE GID=?", (gid,))
        conn.commit()


def list_local_favorites():
    with _lock:
        conn = _get_conn()
        rows = conn.execute("SELECT * FROM LOCAL_FAVORITES ORDER BY TIME DESC").fetchall()
        return [_row_to_gallery(r, "LOCAL_FAVORITES") for r in rows]


def is_local_favorited(gid):
    with _lock:
        conn = _get_conn()
        return conn.execute("SELECT 1 FROM LOCAL_FAVORITES WHERE GID=?", (gid,)).fetchone() is not None


# ================= 标签收藏 / 快速搜索（QUICK_SEARCH） =================

def add_tag_favorite(tag, name=None):
    """标签收藏 = 一条快速搜索记录（MODE=2 标签搜索，KEYWORD=标签）"""
    tag = (tag or "").strip()
    if not tag:
        return None
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT _id FROM QUICK_SEARCH WHERE KEYWORD=? AND MODE=2",
                           (tag,)).fetchone()
        if row:
            return row["_id"]
        cur = conn.execute("""
            INSERT INTO QUICK_SEARCH (NAME, MODE, CATEGORY, KEYWORD, ADVANCE_SEARCH,
                                      MIN_RATING, PAGE_FROM, PAGE_TO, TIME)
            VALUES (?,2,-1,?,-1,-1,-1,-1,?)""",
            (name or tag, tag, int(time.time() * 1000)))
        conn.commit()
        return cur.lastrowid


def list_tag_favorites():
    """列出全部已收藏的搜索/标签（兼容 Android 已有记录）"""
    with _lock:
        conn = _get_conn()
        rows = conn.execute("SELECT * FROM QUICK_SEARCH ORDER BY TIME DESC").fetchall()
        return [{"id": r["_id"], "name": r["NAME"], "tag": r["KEYWORD"],
                 "mode": r["MODE"], "time": r["TIME"]} for r in rows]


def delete_tag_favorite(tid):
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM QUICK_SEARCH WHERE _id=?", (tid,))
        conn.commit()


def is_tag_favorite(tag):
    with _lock:
        conn = _get_conn()
        return conn.execute("SELECT 1 FROM QUICK_SEARCH WHERE KEYWORD=? AND MODE=2",
                            (tag,)).fetchone() is not None


# ================= 标签屏蔽（FILTER，MODE=2 标签） =================

def add_blocked_tag(tag):
    tag = (tag or "").strip()
    if not tag:
        return None
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT _id FROM FILTER WHERE TEXT=? AND MODE=2", (tag,)).fetchone()
        if row:
            return row["_id"]
        cur = conn.execute("INSERT INTO FILTER (MODE, TEXT, ENABLE) VALUES (2,?,1)", (tag,))
        conn.commit()
        return cur.lastrowid


def list_blocked_tags():
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM FILTER WHERE MODE=2 AND ENABLE=1 ORDER BY _id DESC").fetchall()
        return [{"id": r["_id"], "text": r["TEXT"], "enable": r["ENABLE"]} for r in rows]


def set_blocked_tag_enable(fid, enable):
    with _lock:
        conn = _get_conn()
        conn.execute("UPDATE FILTER SET ENABLE=? WHERE _id=?", (1 if enable else 0, fid))
        conn.commit()


def delete_blocked_tag(fid):
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM FILTER WHERE _id=?", (fid,))
        conn.commit()


def blocked_tag_set():
    with _lock:
        conn = _get_conn()
        rows = conn.execute("SELECT TEXT FROM FILTER WHERE MODE=2 AND ENABLE=1").fetchall()
        return {(r["TEXT"] or "").strip().lower() for r in rows}
