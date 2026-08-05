# -*- coding: utf-8 -*-
"""
SQLite 数据库管理模块
自动创建数据库和用户表，提供注册、登录验证、资料管理等功能
"""
import sqlite3
import os
import hashlib
import json
from datetime import datetime
import traceback

# 数据库文件路径（项目根目录下 data/ogc_users.db）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'ogc_users.db')
AVATAR_DIR = os.path.join(BASE_DIR, 'data', 'avatars')


def _persist_avatar(source_path: str, username: str) -> str:
    """将用户选择的头像复制到项目 data/avatars/ 目录，保证持久保存

    如果头像已在项目 avatars 目录内则直接返回原路径；
    外部图片会被复制进项目目录，避免源文件被删除后头像失效。
    """
    try:
        if not source_path or not os.path.exists(source_path):
            return source_path or ''
        # 已在项目 avatars 目录内，无需复制
        if os.path.abspath(os.path.dirname(source_path)) == os.path.abspath(AVATAR_DIR):
            return source_path
        os.makedirs(AVATAR_DIR, exist_ok=True)
        ext = os.path.splitext(source_path)[1] or '.png'
        safe_name = ''.join(c for c in username if c.isalnum() or c in '_-') or 'user'
        dest = os.path.join(AVATAR_DIR, f'{safe_name}{ext}')
        import shutil
        shutil.copy2(source_path, dest)
        return dest
    except Exception:
        return source_path or ''

# 延迟导入日志管理器（避免循环导入）
_log_manager = None

def _get_logger():
    """获取日志管理器实例"""
    global _log_manager
    if _log_manager is None:
        from ui.widgets.common import log_manager
        _log_manager = log_manager
    return _log_manager


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════ 权限常量 ═══════════════

# 所有可用模块
ALL_MODULES = [
    ('home', '首页'),
    ('music', '音乐'),
    ('video', '视频'),
    ('people', '人物'),
    ('about_me', '关于我'),
    ('settings', '设置'),
]

# 所有可用功能（模块下的具体功能）
ALL_FEATURES = [
    ('music_search', '音乐-在线搜索'),
    ('music_playlist', '音乐-播放列表'),
    ('music_download', '音乐-下载'),
    ('music_player', '音乐-播放器'),
    ('video_douyin', '视频-抖音'),
    ('video_bilibili', '视频-哔哩哔哩'),
    ('video_twitter', '视频-推特(X)'),
    ('video_pixiv', '视频-Pixiv'),
    ('video_xvideo', '视频-Xvideo'),
    ('video_youtube', '视频-YouTube'),
]


def get_default_permissions() -> dict:
    """获取默认权限（所有模块/功能全部开启）"""
    return {
        'modules': {key: True for key, _ in ALL_MODULES},
        'features': {key: True for key, _ in ALL_FEATURES},
    }


def init_jmcomic_tables():
    """初始化 JMComic 相关数据库表（配额 + 订阅）"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS download_quota (
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS jm_subscriptions (
            umo TEXT NOT NULL,
            album_id TEXT NOT NULL,
            user_id TEXT,
            title TEXT,
            last_count INTEGER DEFAULT 0,
            PRIMARY KEY (umo, album_id)
        )''')
        conn.commit()
        conn.close()
    except Exception:
        pass


def init_db():
    """初始化数据库"""
    logger = _get_logger()
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        # 初始化 JMComic 表
        try:
            init_jmcomic_tables()
        except Exception:
            pass
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                avatar_path TEXT DEFAULT '',
                role TEXT DEFAULT '',
                motto TEXT DEFAULT '',
                github TEXT DEFAULT '',
                email TEXT DEFAULT '',
                qq TEXT DEFAULT '',
                info_items TEXT DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                last_login TEXT,
                is_banned INTEGER DEFAULT 0,
                permissions TEXT DEFAULT ''
            )
        ''')
        conn.commit()
        # 兼容旧数据库：如果字段不存在则添加（ALTER TABLE）
        cursor.execute("PRAGMA table_info(users)")
        existing_cols = [r[1] for r in cursor.fetchall()]
        if 'is_banned' not in existing_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
        if 'permissions' not in existing_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN permissions TEXT DEFAULT ''")
        # 为 admin 用户设置默认权限（如果为空的）
        cursor.execute("SELECT id, permissions FROM users WHERE username='admin'")
        admin_row = cursor.fetchone()
        if admin_row and not admin_row['permissions']:
            cursor.execute(
                "UPDATE users SET permissions=?, is_banned=0 WHERE username='admin'",
                (json.dumps(get_default_permissions(), ensure_ascii=False),)
            )
        conn.commit()
        conn.close()
        # 初始化使用量统计表
        try:
            init_usage_table()
        except Exception:
            pass
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        raise


def _hash_password(password: str) -> str:
    """对密码进行哈希处理"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


# ═══════════════ 用户操作 ═══════════════

def register_user(username: str, password: str, profile: dict = None) -> tuple:
    if not username or not username.strip():
        return False, "用户名不能为空"
    if not password or len(password) < 6:
        return False, "密码长度至少为6位"
    if len(username.strip()) < 2:
        return False, "用户名长度至少为2个字符"

    username = username.strip()
    password_hash = _hash_password(password)
    p = profile or {}
    info_items = json.dumps(p.get('info_items', []), ensure_ascii=False)
    # 头像持久化：复制到项目 data/avatars/ 目录
    if p.get('avatar_path'):
        p['avatar_path'] = _persist_avatar(p['avatar_path'], username)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO users (username, password, avatar_path, role, motto, github, email, qq, info_items,
               permissions, is_banned)
               VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
            (username, password_hash, p.get('avatar_path',''), p.get('role',''),
             p.get('motto',''), p.get('github',''), p.get('email',''),
             p.get('qq',''), info_items,
             json.dumps(get_default_permissions(), ensure_ascii=False))
        )
        conn.commit()
        return True, "注册成功"
    except sqlite3.IntegrityError:
        return False, "用户名已存在"
    except Exception as e:
        return False, f"注册失败：{str(e)}"
    finally:
        conn.close()


def verify_login(username: str, password: str) -> tuple:
    if not username or not username.strip():
        return False, "请输入用户名"
    if not password:
        return False, "请输入密码"
    username = username.strip()
    password_hash = _hash_password(password)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        if user:
            # 检查是否被封禁
            if user['is_banned']:
                return False, "该账号已被封禁，请联系管理员"
            # 检查密码
            if user['password'] != password_hash:
                return False, "密码错误"
            cursor.execute("UPDATE users SET last_login=datetime('now','localtime') WHERE id=?", (user['id'],))
            conn.commit()
            return True, "登录成功"
        else:
            return False, "用户名不存在"
    except Exception as e:
        return False, f"登录验证失败：{str(e)}"
    finally:
        conn.close()


def get_user_profile(username: str) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE username=?", (username.strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            'id': row['id'], 'username': row['username'],
            'avatar_path': row['avatar_path'] or '', 'role': row['role'] or '',
            'motto': row['motto'] or '', 'github': row['github'] or '',
            'email': row['email'] or '', 'qq': row['qq'] or '',
            'info_items': json.loads(row['info_items']) if row['info_items'] else [],
            'created_at': row['created_at'], 'last_login': row['last_login'],
        }
    finally:
        conn.close()


def update_user_profile(username: str, profile: dict) -> tuple:
    allowed = {'avatar_path','role','motto','github','email','qq','info_items'}
    updates = {k:v for k,v in profile.items() if k in allowed}
    # 头像持久化：复制到项目 data/avatars/ 目录
    if 'avatar_path' in updates and updates['avatar_path']:
        updates['avatar_path'] = _persist_avatar(updates['avatar_path'], username)
    if not updates:
        return False, "没有需要更新的字段"
    if 'info_items' in updates and isinstance(updates['info_items'], list):
        updates['info_items'] = json.dumps(updates['info_items'], ensure_ascii=False)
    set_clause = ', '.join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [username.strip()]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE users SET {set_clause} WHERE username=?", values)
        conn.commit()
        return True, "资料更新成功"
    except Exception as e:
        return False, f"资料更新失败：{str(e)}"
    finally:
        conn.close()


def update_user_password(username: str, old_password: str, new_password: str) -> tuple:
    if not new_password or len(new_password) < 6:
        return False, "新密码长度至少为6位"
    success, msg = verify_login(username, old_password)
    if not success:
        return False, "旧密码错误"
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET password=? WHERE username=?", (_hash_password(new_password), username.strip()))
        conn.commit()
        return True, "密码修改成功"
    except Exception as e:
        return False, f"密码修改失败：{str(e)}"
    finally:
        conn.close()


def update_username(old_username: str, new_username: str) -> tuple:
    if not new_username or len(new_username.strip()) < 2:
        return False, "新用户名长度至少为2个字符"
    if old_username == 'admin':
        return False, "管理员账号不可修改用户名"
    new_username = new_username.strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE username=?", (new_username,))
        if cursor.fetchone():
            return False, "该用户名已被使用"
        cursor.execute("SELECT id FROM users WHERE username=?", (old_username.strip(),))
        if not cursor.fetchone():
            return False, "用户不存在"
        # 同步更新使用量统计表中的用户名
        try:
            cursor.execute("UPDATE usage_stats SET username=? WHERE username=?", (new_username, old_username.strip()))
        except Exception:
            pass
        cursor.execute("UPDATE users SET username=? WHERE username=?", (new_username, old_username.strip()))
        conn.commit()
        return True, "用户名修改成功"
    except Exception as e:
        return False, f"用户名修改失败：{str(e)}"
    finally:
        conn.close()


def user_exists(username: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE username=?", (username.strip(),))
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_user_avatar(username: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT avatar_path FROM users WHERE username=?", (username.strip(),))
        row = cursor.fetchone()
        return row['avatar_path'] if row and row['avatar_path'] else ''
    finally:
        conn.close()


# ═══════════════ 权限 / 封禁管理 ═══════════════

def is_admin(username: str) -> bool:
    """判断用户是否为管理员（admin）"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT role FROM users WHERE username=?", (username.strip(),))
        row = cursor.fetchone()
        return bool(row and row['role'] == '管理员')
    finally:
        conn.close()


def get_all_users() -> list:
    """获取所有注册用户（脱敏，不含密码）"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""SELECT id, username, avatar_path, role, motto, email, qq,
                          created_at, last_login, is_banned, permissions
                          FROM users ORDER BY id""")
        rows = cursor.fetchall()
        users = []
        for r in rows:
            users.append({
                'id': r['id'],
                'username': r['username'],
                'avatar_path': r['avatar_path'] or '',
                'role': r['role'] or '',
                'motto': r['motto'] or '',
                'email': r['email'] or '',
                'qq': r['qq'] or '',
                'created_at': r['created_at'],
                'last_login': r['last_login'],
                'is_banned': bool(r['is_banned']),
                'permissions': r['permissions'] or '',
            })
        return users
    finally:
        conn.close()


def get_user_permissions(username: str) -> dict:
    """获取用户权限字典，缺失的权限默认全部开启"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT permissions FROM users WHERE username=?", (username.strip(),))
        row = cursor.fetchone()
        if not row or not row['permissions']:
            return get_default_permissions()
        try:
            perms = json.loads(row['permissions'])
            default = get_default_permissions()
            # 补齐缺失的键
            for k in default['modules']:
                perms.setdefault('modules', {}).setdefault(k, True)
            for k in default['features']:
                perms.setdefault('features', {}).setdefault(k, True)
            return perms
        except (json.JSONDecodeError, AttributeError):
            return get_default_permissions()
    finally:
        conn.close()


def save_user_permissions(username: str, permissions: dict) -> tuple:
    """保存用户权限"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET permissions=? WHERE username=?",
            (json.dumps(permissions, ensure_ascii=False), username.strip())
        )
        conn.commit()
        return True, "权限保存成功"
    except Exception as e:
        return False, f"权限保存失败：{str(e)}"
    finally:
        conn.close()


def set_user_banned(username: str, banned: bool) -> tuple:
    """设置用户封禁状态"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET is_banned=? WHERE username=?",
            (1 if banned else 0, username.strip())
        )
        conn.commit()
        return True, "封禁成功" if banned else "解封成功"
    except Exception as e:
        return False, f"操作失败：{str(e)}"
    finally:
        conn.close()


def is_user_banned(username: str) -> bool:
    """查询用户是否被封禁"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT is_banned FROM users WHERE username=?", (username.strip(),))
        row = cursor.fetchone()
        return bool(row and row['is_banned'])
    finally:
        conn.close()


def delete_user(username: str) -> tuple:
    """删除用户（永久移除账号及其数据）"""
    if username == 'admin':
        return False, "不能删除管理员账户"
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE username=?", (username.strip(),))
        if not cursor.fetchone():
            return False, "用户不存在"
        # 删除用户及关联的使用量记录
        cursor.execute("DELETE FROM users WHERE username=?", (username.strip(),))
        cursor.execute("DELETE FROM usage_stats WHERE username=?", (username.strip(),))
        conn.commit()
        return True, f"用户「{username}」已删除"
    except Exception as e:
        return False, f"删除用户失败：{str(e)}"
    finally:
        conn.close()


# ═══════════════ 统计信息 ═══════════════

def get_system_stats() -> dict:
    """获取系统统计数据（用于仪表盘）"""
    import json as _json
    conn = get_db_connection()
    cursor = conn.cursor()
    stats = {}
    try:
        # 用户总数
        cursor.execute("SELECT COUNT(*) FROM users")
        stats['user_count'] = cursor.fetchone()[0]
        # 封禁用户数
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned=1")
        stats['banned_count'] = cursor.fetchone()[0]
        # 音乐相关统计
        try:
            cursor.execute("SELECT COUNT(*) FROM music_songs")
            stats['music_song_count'] = cursor.fetchone()[0]
        except Exception:
            stats['music_song_count'] = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM music_downloads")
            stats['music_download_count'] = cursor.fetchone()[0]
        except Exception:
            stats['music_download_count'] = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM music_playlists")
            stats['music_playlist_count'] = cursor.fetchone()[0]
        except Exception:
            stats['music_playlist_count'] = 0
        # 媒体文件统计
        try:
            base = BASE_DIR
            vids = os.path.join(base, 'videos')
            videos_count = sum(len(f) for _, _, f in os.walk(vids)) if os.path.exists(vids) else 0
            stats['video_file_count'] = videos_count
        except Exception:
            stats['video_file_count'] = 0
        try:
            musics_dir = os.path.join(base, 'music')
            musics_count = sum(len(f) for _, _, f in os.walk(musics_dir))
            stats['music_file_count'] = musics_count
        except Exception:
            stats['music_file_count'] = 0
        # 使用量统计
        try:
            stats['usage'] = get_usage_stats()
        except Exception:
            stats['usage'] = {}
        return stats
    finally:
        conn.close()


# ═══════════════ 使用量统计 ═══════════════

def init_usage_table():
    """初始化使用量统计表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS usage_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module TEXT NOT NULL,          -- 模块: home/music/video/people
        action TEXT NOT NULL,          -- 动作: search/play/download/parse/upload/visit
        detail TEXT DEFAULT '',        -- 详情（如平台名、歌曲名）
        username TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )''')
    conn.commit()
    conn.close()


# ═══════════════ Pixiv Token 存储 ═══════════════

def init_pixiv_tokens_table():
    """初始化 Pixiv refresh token 存储表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS pixiv_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT DEFAULT '',
        refresh_token TEXT DEFAULT '',
        access_token TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )''')
    conn.commit()
    conn.close()


def save_pixiv_refresh_token(refresh_token: str, access_token: str = '', username: str = '') -> bool:
    """保存 Pixiv refresh token 到数据库（存在则更新）"""
    try:
        init_pixiv_tokens_table()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM pixiv_tokens WHERE id=1")
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE pixiv_tokens SET refresh_token=?, access_token=?, username=?, updated_at=datetime('now','localtime') WHERE id=?",
                (refresh_token, access_token, username, row['id'])
            )
        else:
            cursor.execute(
                "INSERT INTO pixiv_tokens (username, refresh_token, access_token) VALUES (?,?,?)",
                (username, refresh_token, access_token)
            )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_pixiv_refresh_token() -> str:
    """从数据库读取 Pixiv refresh token"""
    try:
        init_pixiv_tokens_table()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT refresh_token FROM pixiv_tokens WHERE id=1")
        row = cursor.fetchone()
        conn.close()
        return row['refresh_token'] if row and row['refresh_token'] else ''
    except Exception:
        return ''


def record_usage(module: str, action: str, detail: str = '', username: str = ''):
    """记录一次使用行为"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO usage_stats (module, action, detail, username) VALUES (?,?,?,?)",
            (module, action, detail, username)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_usage_stats(start_date: str = '', end_date: str = '') -> dict:
    """获取使用量统计（可按日期范围筛选）

    返回结构:
    {
        'music': {'search': 10, 'play': 15, 'download': 5},
        'video': {'parse': 8, 'download': 12},
        'video_sub': {'douyin': 5, 'bilibili': 3},  # 子模块使用量
        ...
    }
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    where = []
    params = []
    if start_date:
        where.append("date(created_at) >= ?")
        params.append(start_date)
    if end_date:
        where.append("date(created_at) <= ?")
        params.append(end_date)
    where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''

    result = {'music': {}, 'video': {}, 'video_sub': {}, 'people': {}, 'home': {}, 'downloads': {}}
    try:
        # 按 module + action 分组统计
        cursor.execute(f"SELECT module, action, COUNT(*) as cnt FROM usage_stats{where_sql} GROUP BY module, action", params)
        for row in cursor.fetchall():
            mod, act, cnt = row['module'], row['action'], row['cnt']
            if mod not in result:
                result[mod] = {}
            result[mod][act] = cnt

        # 视频子模块（从 video 模块按 detail=平台名 分组统计）
        sub_where = (where + ["module='video'"]) if where else ["module='video'"]
        sub_sql = ' WHERE ' + ' AND '.join(sub_where)
        cursor.execute(f"SELECT detail, COUNT(*) as cnt FROM usage_stats{sub_sql} GROUP BY detail", params)
        for row in cursor.fetchall():
            if row['detail']:
                result['video_sub'][row['detail']] = row['cnt']

        # 总下载量
        cursor.execute(f"SELECT COUNT(*) FROM usage_stats WHERE action='download'{' AND ' + where_sql if where_sql else ''}", params)
        result['downloads']['total'] = cursor.fetchone()[0]
    except Exception:
        pass
    finally:
        conn.close()
    return result


# ═══════════════ 音乐数据库表 ═══════════════

def init_music_tables():
    """初始化音乐相关数据库表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS music_playlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS music_songs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, playlist_id INTEGER NOT NULL,
        song_name TEXT DEFAULT '', singers TEXT DEFAULT '', album TEXT DEFAULT '',
        duration TEXT DEFAULT '', duration_s REAL DEFAULT 0,
        download_url TEXT DEFAULT '', quality TEXT DEFAULT '', identifier TEXT DEFAULT '',
        cover_url TEXT DEFAULT '', ext TEXT DEFAULT '', file_size TEXT DEFAULT '',
        file_size_bytes INTEGER DEFAULT 0, lyric TEXT DEFAULT '',
        local_path TEXT DEFAULT '', sort_order INTEGER DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (playlist_id) REFERENCES music_playlists(id) ON DELETE CASCADE)''')
    # 下载相关表
    cursor.execute('''CREATE TABLE IF NOT EXISTS music_downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        song_name TEXT DEFAULT '', singers TEXT DEFAULT '', album TEXT DEFAULT '',
        duration TEXT DEFAULT '', duration_s REAL DEFAULT 0,
        download_url TEXT DEFAULT '', quality TEXT DEFAULT '', identifier TEXT DEFAULT '',
        cover_url TEXT DEFAULT '', ext TEXT DEFAULT '', file_size TEXT DEFAULT '',
        file_size_bytes INTEGER DEFAULT 0, lyric TEXT DEFAULT '',
        local_path TEXT DEFAULT '', blob_data BLOB DEFAULT NULL,
        sort_order INTEGER DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))''')
    conn.commit()
    # 确保默认播放列表存在
    for name in ['音乐缓存', '我的下载']:
        cursor.execute("SELECT id FROM music_playlists WHERE name=?", (name,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO music_playlists (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()


# ── 播放列表操作 ──────────────────────────

def create_playlist(name: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO music_playlists (name) VALUES (?)", (name,))
    conn.commit()
    pid = cursor.lastrowid
    conn.close()
    return pid


def delete_playlist(pid: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM music_playlists WHERE id=?", (pid,))
    conn.commit()
    conn.close()


def get_all_playlists() -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = cursor.execute("SELECT * FROM music_playlists ORDER BY id").fetchall()
    conn.close()
    return [{'id':r['id'], 'name':r['name'], 'created_at':r['created_at']} for r in rows]


def add_song_to_db(playlist_id: int, item: dict) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO music_songs (playlist_id,song_name,singers,album,duration,duration_s,
        download_url,quality,identifier,cover_url,ext,file_size,file_size_bytes,lyric,local_path)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
        playlist_id, item.get('song_name',''), item.get('singers',''), item.get('album',''),
        item.get('duration',''), item.get('duration_s',0), item.get('download_url',''),
        item.get('quality',''), item.get('identifier',''), item.get('cover_url',''),
        item.get('ext',''), item.get('file_size',''), item.get('file_size_bytes',0),
        item.get('lyric',''), item.get('local_path','')))
    conn.commit()
    sid = cursor.lastrowid
    conn.close()
    return sid


def delete_song_from_db(song_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM music_songs WHERE id=?", (song_id,))
    conn.commit()
    conn.close()


def get_songs_by_playlist(playlist_id: int) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = cursor.execute("SELECT * FROM music_songs WHERE playlist_id=? ORDER BY sort_order,id", (playlist_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_playlist_songs(playlist_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM music_songs WHERE playlist_id=?", (playlist_id,))
    conn.commit()
    conn.close()


def get_all_playlists_with_song_count() -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = cursor.execute('''SELECT p.*,COUNT(s.id) as song_count FROM music_playlists p
        LEFT JOIN music_songs s ON s.playlist_id=p.id GROUP BY p.id ORDER BY p.id''').fetchall()
    conn.close()
    return [{'id':r['id'],'name':r['name'],'song_count':r['song_count'],'created_at':r['created_at']} for r in rows]


# ── 下载操作 ──────────────────────────────

def add_download_song(item: dict, blob_data: bytes = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO music_downloads (song_name,singers,album,duration,duration_s,
        download_url,quality,identifier,cover_url,ext,file_size,file_size_bytes,lyric,local_path,blob_data)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
        item.get('song_name',''), item.get('singers',''), item.get('album',''),
        item.get('duration',''), item.get('duration_s',0), item.get('download_url',''),
        item.get('quality',''), item.get('identifier',''), item.get('cover_url',''),
        item.get('ext',''), item.get('file_size',''), item.get('file_size_bytes',0),
        item.get('lyric',''), item.get('local_path',''),
        sqlite3.Binary(blob_data) if blob_data else None))
    conn.commit()
    sid = cursor.lastrowid
    conn.close()
    return sid


def get_download_songs() -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    rows = cursor.execute("SELECT * FROM music_downloads ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_download_song(did: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM music_downloads WHERE id=?", (did,))
    conn.commit()
    conn.close()


def clear_all_downloads():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM music_downloads")
    conn.commit()
    conn.close()
