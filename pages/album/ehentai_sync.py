# -*- coding: utf-8 -*-
"""E-Hentai 下载同步数据库 + 分类 辅助。

职责：
- 从画廊 URL 提取 gid/token。
- 读取 DOWNLOAD_LABELS（分类）。
- 下载完成后把 画廊信息 + 分类 写入 DOWNLOADS（与分享模块共享同一数据库）。
- 在每个下载目录写 .ehentai_info.json（gid/token），供本地画册与数据库对账。
"""
import json
import os
import re
import sqlite3

from pages.album.ehentai_settings import ehentai_cfg

_GID_TOKEN = re.compile(r"/g/(\d+)/([0-9a-f]{6,})", re.I)
INFO_FILENAME = ".ehentai_info.json"


def db_path() -> str:
    """E-Hentai 数据所在的数据库 —— 默认就是与账号库同一个统一库。

    走 ``ehviewer.db.get_db_path()``（而不是直接取 ``core.database.DB_PATH``），
    这样测试/维护脚本可以用 ``set_db_path()`` 把它临时指到统一库的副本上跑，
    而应用本身从不切换 —— 见 core/db_unify.py 与 ehviewer/db.py 的说明。
    """
    from ehviewer import db as ehdb
    return ehdb.get_db_path()


def download_root() -> str:
    return (ehentai_cfg.get(ehentai_cfg.KEY_OUTPUT_DIR) or "")


def downloaded_set():
    """扫描下载目录，返回 (gid集合, 标题小写集合)，用于判断某漫画是否已下载。"""
    gids = set()
    titles = set()
    od = download_root()
    if not od or not os.path.isdir(od):
        return gids, titles
    try:
        for name in os.listdir(od):
            full = os.path.join(od, name)
            if os.path.isdir(full):
                titles.add(name.strip().lower())
                info_path = os.path.join(full, INFO_FILENAME)
                if os.path.isfile(info_path):
                    try:
                        with open(info_path, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        g = int(d.get("gid", 0) or 0)
                        if g:
                            gids.add(g)
                    except Exception:
                        pass
    except Exception:
        pass
    return gids, titles


def extract_gid_token(url: str):
    """从画廊 URL 提取 (gid, token)；无法识别返回 (0, '')。"""
    if not url:
        return (0, "")
    m = _GID_TOKEN.search(url or "")
    if m:
        return (int(m.group(1)), m.group(2))
    return (0, "")


def read_download_labels():
    """返回分类列表 [{'label':.., 'id':..}]（含 未分类 并不返回，由调用方加）。"""
    p = db_path()
    out = []
    if p and os.path.isfile(p):
        try:
            c = sqlite3.connect(p)
            rows = c.execute("SELECT _id, LABEL FROM DOWNLOAD_LABELS ORDER BY TIME").fetchall()
            for r in rows:
                out.append({"id": r[0], "label": r[1]})
            c.close()
        except Exception:
            out = []
    return out


def add_label(label: str):
    """新增分类，返回其 id（已存在则返回现有 id）。写到共享库 DOWNLOAD_LABELS。"""
    label = (label or "").strip()
    if not label:
        return None
    p = db_path()
    try:
        c = sqlite3.connect(p)
        row = c.execute("SELECT _id FROM DOWNLOAD_LABELS WHERE LABEL=?", (label,)).fetchone()
        if row:
            c.close()
            return row[0]
        import time
        cur = c.execute("INSERT INTO DOWNLOAD_LABELS (LABEL, TIME) VALUES (?,?)",
                        (label, int(time.time() * 1000)))
        c.commit()
        lid = cur.lastrowid
        c.close()
        return lid
    except Exception:
        return None


def write_comic_metadata(output_dir: str, gid, token, title="") -> str:
    """在每个下载目录写 .ehentai_info.json，供本地画册/详情对账。返回文件路径或 ''."""
    if not output_dir or not gid:
        return ""
    try:
        path = os.path.join(output_dir, INFO_FILENAME)
        data = {"gid": gid, "token": token or "", "title": title or ""}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path
    except Exception:
        return ""


def sync_download_to_db(url: str, title: str, label="", category=0x400, state=3):
    """把一次下载的画廊写入 DOWNLOADS（gid/token/title/category/label/state）。

    category: 画廊的 E-Hentai 分类位掩码（未知用 UNKNOWN_CATEGORY=0x400）。
    state: C.STATE_FINISH=3。
    """
    gid, token = extract_gid_token(url)
    if not gid or not token:
        return False
    p = db_path()
    if not p:
        return False
    try:
        import time
        params = {
            "gid": gid, "token": token, "title": title or "", "title_jpn": "",
            "thumb": "", "category": category, "posted": "", "uploader": "",
            "rating": 0.0, "simple_language": None, "state": state, "legacy": 0,
            "time": int(time.time() * 1000), "label": (label or None),
        }
        c = sqlite3.connect(p)
        c.execute("""
            INSERT OR REPLACE INTO DOWNLOADS
            (GID, TOKEN, TITLE, TITLE_JPN, THUMB, CATEGORY, POSTED, UPLOADER, RATING,
             SIMPLE_LANGUAGE, STATE, LEGACY, TIME, LABEL)
            VALUES (:gid,:token,:title,:title_jpn,:thumb,:category,:posted,:uploader,:rating,
             :simple_language,:state,:legacy,:time,:label)""", params)
        c.commit()
        c.close()
        return True
    except Exception:
        return False


def remove_download_row(gid):
    """从 DOWNLOADS 删除某画廊记录（用于本地画册清理）。"""
    p = db_path()
    if not p:
        return
    try:
        c = sqlite3.connect(p)
        c.execute("DELETE FROM DOWNLOADS WHERE GID=?", (gid,))
        c.commit()
        c.close()
    except Exception:
        pass


def comic_gid(path, title=""):
    """由漫画目录读取 gid（.ehentai_info.json）；拿不到返回 0。"""
    try:
        info_path = os.path.join(path or '', INFO_FILENAME)
        if os.path.isfile(info_path):
            with open(info_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return int(d.get("gid", 0) or 0)
    except Exception:
        pass
    return 0


def comic_category(path, title=""):
    """漫画的分类：优先按 gid 查 DOWNLOADS.LABEL，否则按标题匹配，最终''=未分类。"""
    gid = comic_gid(path, title)
    p = db_path()
    if not gid or not p or not os.path.isfile(p):
        return ""
    try:
        c = sqlite3.connect(p)
        row = c.execute("SELECT LABEL FROM DOWNLOADS WHERE GID=?", (gid,)).fetchone()
        if row and row[0]:
            c.close()
            return row[0]
        row = c.execute("SELECT LABEL FROM DOWNLOADS WHERE TITLE=? AND LABEL IS NOT NULL LIMIT 1",
                        ((title or "").strip(),)).fetchone()
        c.close()
        return (row[0] if row and row[0] else "")
    except Exception:
        return ""


def set_comic_category(path, title, label):
    """设置漫画分类：写入 DOWNLOADS.LABEL（无对应行且能拿到 gid 则补写）。label=''=未分类。"""
    gid = comic_gid(path, title)
    p = db_path()
    if not gid or not p:
        return False
    try:
        c = sqlite3.connect(p)
        exists = c.execute("SELECT 1 FROM DOWNLOADS WHERE GID=?", (gid,)).fetchone()
        if exists:
            c.execute("UPDATE DOWNLOADS SET LABEL=? WHERE GID=?", (label or None, gid))
        else:
            import time
            c.execute("""
                INSERT OR REPLACE INTO DOWNLOADS
                (GID,TOKEN,TITLE,TITLE_JPN,THUMB,CATEGORY,POSTED,UPLOADER,RATING,
                 SIMPLE_LANGUAGE,STATE,LEGACY,TIME,LABEL)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (gid, '', title or '', '', '', 0x400, '', '', 0.0, None, 3, 0,
                 int(time.time() * 1000), (label or None)))
        c.commit()
        c.close()
        return True
    except Exception:
        return False


def list_tag_favorites():
    """读取标签收藏（QUICK_SEARCH 中 MODE=2 的记录）。"""
    p = db_path()
    out = []
    if not p or not os.path.isfile(p):
        return out
    try:
        c = sqlite3.connect(p)
        rows = c.execute("SELECT _id, NAME, KEYWORD, MODE, TIME FROM QUICK_SEARCH "
                         "WHERE MODE=2 ORDER BY TIME DESC").fetchall()
        for r in rows:
            out.append({"id": r[0], "name": r[1] or r[2] or "", "tag": r[2] or "",
                        "mode": r[3] or 2, "time": r[4] or 0})
        c.close()
    except Exception:
        out = []
    return out


def delete_tag_favorite(tid):
    """删除一条标签收藏。"""
    p = db_path()
    if not p:
        return
    try:
        c = sqlite3.connect(p)
        c.execute("DELETE FROM QUICK_SEARCH WHERE _id=?", (tid,))
        c.commit()
        c.close()
    except Exception:
        pass


def add_tag_favorite(tag, name=""):
    """新增标签收藏（QUICK_SEARCH MODE=2），用于收藏页「+ 标签」。返回 id 或 None。"""
    tag = (tag or "").strip()
    if not tag:
        return None
    p = db_path()
    if not p:
        return None
    try:
        c = sqlite3.connect(p)
        row = c.execute("SELECT _id FROM QUICK_SEARCH WHERE KEYWORD=? AND MODE=2",
                        (tag,)).fetchone()
        if row:
            c.close()
            return row[0]
        import time
        cur = c.execute("INSERT INTO QUICK_SEARCH (NAME, MODE, CATEGORY, KEYWORD, "
                        "ADVANCE_SEARCH, MIN_RATING, PAGE_FROM, PAGE_TO, TIME) "
                        "VALUES (?,2,-1,?,-1,-1,-1,-1,?)",
                        (name or tag, tag, int(time.time() * 1000)))
        c.commit()
        lid = cur.lastrowid
        c.close()
        return lid
    except Exception:
        return None


def reconcile_downloads(output_dir, delete_orphans=False):
    """把【下载目录】作为本地画册唯一真相，与 DOWNLOADS 表对账。

    - delete_orphans=False（默认，安全）：只把下载目录里【已知 gid】且【无 DOWNLOADS
      记录】的漫画补写为 DOWNLOADS（分类=未分类），不删除任何记录。
    - delete_orphans=True：额外删除 DOWNLOADS 中【标题/元数据 gid 均不匹配任何目录】
      的孤立记录 —— 仅当你确认 DOWNLOADS 与下载目录是同一数据集时才应开启。
    返回 {"deleted":.., "added":.., "unmatched":.., "catalogs":..}.
    """
    result = {"deleted": 0, "added": 0, "unmatched": 0, "catalogs": 0}
    if not output_dir or not os.path.isdir(output_dir):
        result["catalogs"] = 0
        return result
    try:
        from services.comic_library import scan_comics
        comics = scan_comics(output_dir, index_path="", force=True)
    except Exception:
        comics = []
    if not comics:
        result["catalogs"] = 0
        return result

    dir_titles = set()          # 目录名（小写）
    gid_set = set()             # 已知 gid
    dir_listing = []            # {title, gid}
    for cm in comics:
        title = (getattr(cm, 'title', '') or '').strip()
        t = title.lower()
        dir_titles.add(t)
        gid = 0
        try:
            base = getattr(cm, 'path', '') or ''
            info_path = os.path.join(base, INFO_FILENAME)
            if os.path.isfile(info_path):
                with open(info_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                gid = int(d.get("gid", 0) or 0)
        except Exception:
            gid = 0
        if gid:
            gid_set.add(gid)
        dir_listing.append({"title": title, "gid": gid})

    p = db_path()
    if not p or not os.path.isfile(p):
        result["catalogs"] = len(dir_listing)
        result["unmatched"] = len([e for e in dir_listing if not e["gid"]])
        return result

    import time
    try:
        c = sqlite3.connect(p)
        # 1) 清理孤立 DOWNLOADS 记录 —— 默认不删（delete_orphans=False），
        #    因为 DOWNLOADS 表可能包含与下载目录并非同一数据集的历史记录，
        #    盲目按标题匹配会误删大量记录。仅显式要求删除时才清理。
        if delete_orphans:
            rows = c.execute("SELECT GID, TOKEN, TITLE FROM DOWNLOADS").fetchall()
            for gid, token, title in rows:
                t = (title or "").strip().lower()
                if not t:
                    c.execute("DELETE FROM DOWNLOADS WHERE GID=?", (gid,))
                    result["deleted"] += 1
                    continue
                if t in dir_titles or gid in gid_set:
                    continue  # 有对应目录
                c.execute("DELETE FROM DOWNLOADS WHERE GID=?", (gid,))
                result["deleted"] += 1

        # 2) 目录漫画补写 DOWNLOADS（分类=未分类），仅已知 gid
        for e in dir_listing:
            if not e["gid"]:
                result["unmatched"] += 1
                continue
            if c.execute("SELECT 1 FROM DOWNLOADS WHERE GID=?", (e["gid"],)).fetchone():
                continue
            c.execute("""
                INSERT OR REPLACE INTO DOWNLOADS
                (GID,TOKEN,TITLE,TITLE_JPN,THUMB,CATEGORY,POSTED,UPLOADER,RATING,
                 SIMPLE_LANGUAGE,STATE,LEGACY,TIME,LABEL)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (e["gid"], '', e["title"] or '', '', '', 0x400,
                 '', '', 0.0, None, 3, 0, int(time.time() * 1000), None))
            result["added"] += 1
        c.commit()
        c.close()
    except Exception:
        pass
    result["catalogs"] = len(dir_listing)
    return result
