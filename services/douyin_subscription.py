# -*- coding: utf-8 -*-
"""
抖音作者订阅服务
================
- 数据库表：douyin_subscriptions（合并到主数据库 ogc_users.db）
- 功能：订阅 / 取消订阅 / 查询订阅列表 / 刷新作者信息与更新状态
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import config as CFG


# ═══════════════════════════════════════════════════════════
#  数据库辅助
# ═══════════════════════════════════════════════════════════
def _db_path() -> Path:
    try:
        from core.database import DB_PATH
        return Path(DB_PATH)
    except Exception:
        return Path('data') / 'ogc_users.db'


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS douyin_subscriptions (
            sec_uid         TEXT PRIMARY KEY,
            nickname        TEXT,
            signature       TEXT,
            avatar_url      TEXT,
            user_home       TEXT,
            aweme_count     INTEGER DEFAULT 0,
            follower_count  INTEGER DEFAULT 0,
            last_aweme_id   TEXT,
            last_count      INTEGER DEFAULT 0,
            has_update      INTEGER DEFAULT 0,
            subscribed_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_checked_at TIMESTAMP
        )
    """)
    conn.commit()


# ═══════════════════════════════════════════════════════════
#  订阅数据操作
# ═══════════════════════════════════════════════════════════
def subscribe(author: dict, last_aweme_id: Optional[str] = None) -> bool:
    """订阅作者（author 为 get_user_profile 返回的结构）"""
    sec_uid = (author.get('sec_uid') or '').strip()
    if not sec_uid:
        return False

    conn = _connect()
    try:
        _migrate(conn)
        aweme_count = int(author.get('aweme_count') or 0)
        conn.execute("""
            INSERT INTO douyin_subscriptions
            (sec_uid, nickname, signature, avatar_url, user_home,
             aweme_count, follower_count, last_aweme_id, last_count,
             has_update, subscribed_at, last_checked_at)
            VALUES (?,?,?,?,?,?,?,?,?,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            ON CONFLICT(sec_uid) DO UPDATE SET
                nickname=excluded.nickname,
                signature=excluded.signature,
                avatar_url=excluded.avatar_url,
                user_home=excluded.user_home,
                aweme_count=excluded.aweme_count,
                follower_count=excluded.follower_count,
                last_aweme_id=COALESCE(excluded.last_aweme_id, last_aweme_id),
                last_count=excluded.last_count,
                last_checked_at=CURRENT_TIMESTAMP
        """, (
            sec_uid,
            author.get('nickname') or '',
            author.get('signature') or '',
            author.get('avatar_url') or '',
            author.get('user_home') or f'https://www.douyin.com/user/{sec_uid}',
            aweme_count,
            int(author.get('follower_count') or 0),
            last_aweme_id or '',
            aweme_count,
        ))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def unsubscribe(sec_uid: str) -> bool:
    sec_uid = (sec_uid or '').strip()
    if not sec_uid:
        return False
    conn = _connect()
    try:
        _migrate(conn)
        conn.execute("DELETE FROM douyin_subscriptions WHERE sec_uid=?", (sec_uid,))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def is_subscribed(sec_uid: str) -> bool:
    sec_uid = (sec_uid or '').strip()
    if not sec_uid:
        return False
    conn = _connect()
    try:
        _migrate(conn)
        cur = conn.execute(
            "SELECT 1 FROM douyin_subscriptions WHERE sec_uid=?", (sec_uid,))
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()


def list_subscriptions() -> list:
    conn = _connect()
    try:
        _migrate(conn)
        rows = conn.execute(
            "SELECT * FROM douyin_subscriptions ORDER BY subscribed_at DESC").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def update_author_status(sec_uid: str, author: dict,
                         last_aweme_id: Optional[str] = None) -> bool:
    """刷新作者信息与更新状态。

    更新判定：比较最新作品 aweme_id 是否与上次记录一致。
    若无法获取最新作品 id，则回退比较作品数量 aweme_count。
    """
    sec_uid = (sec_uid or '').strip()
    if not sec_uid:
        return False

    conn = _connect()
    try:
        _migrate(conn)
        row = conn.execute(
            "SELECT last_aweme_id, aweme_count FROM douyin_subscriptions WHERE sec_uid=?",
            (sec_uid,)).fetchone()
        old_last_id = row['last_aweme_id'] if row else ''
        old_count = row['aweme_count'] if row else 0

        new_count = int(author.get('aweme_count') or 0)
        has_update = 0
        if last_aweme_id and old_last_id:
            has_update = 1 if last_aweme_id != old_last_id else 0
        else:
            has_update = 1 if new_count > old_count else 0

        conn.execute("""
            UPDATE douyin_subscriptions SET
                nickname=?, signature=?, avatar_url=?, user_home=?,
                aweme_count=?, follower_count=?, last_aweme_id=?,
                last_count=?, has_update=?, last_checked_at=CURRENT_TIMESTAMP
            WHERE sec_uid=?
        """, (
            author.get('nickname') or '',
            author.get('signature') or '',
            author.get('avatar_url') or '',
            author.get('user_home') or f'https://www.douyin.com/user/{sec_uid}',
            new_count,
            int(author.get('follower_count') or 0),
            last_aweme_id or old_last_id,
            new_count,
            has_update,
            sec_uid,
        ))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def mark_checked(sec_uid: str):
    """清空更新标记（用户已查看）"""
    sec_uid = (sec_uid or '').strip()
    if not sec_uid:
        return
    conn = _connect()
    try:
        _migrate(conn)
        conn.execute(
            "UPDATE douyin_subscriptions SET has_update=0, last_checked_at=CURRENT_TIMESTAMP WHERE sec_uid=?",
            (sec_uid,))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()