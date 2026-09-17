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

# 数据库与头像目录都是**可写用户数据**，必须走 core.config 的权威解析
# （冻结时 = %APPDATA%\OGC-OpenGenericClient，源码时 = <程序根>/data）。
#
# ⚠️ 绝不能再用 __file__ 推导：冻结后 __file__ 指向 _internal/，会把数据库写进
#    **安装目录**。装在 Program Files 时普通用户没有写权限，程序直接启动失败；
#    实测残留过 _internal\data\ogc_users.db（那次装在用户可写目录，所以没报错，
#    属于"侥幸能跑"）。
#
# 保持模块级变量形式：已有测试与脚本通过 monkeypatch db.DB_PATH 来隔离数据。
from core.config import config as CFG

BASE_DIR = str(CFG.data)
DB_PATH = os.path.join(BASE_DIR, 'ogc_users.db')
AVATAR_DIR = os.path.join(BASE_DIR, 'avatars')


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
    """获取日志管理器实例。

    直接复用 core.logger，**不要**再 import ui.widgets.common：
    * 分层约定：core 是最底层，反向依赖 ui 会让「UI 依赖缺失 / qfluentwidgets
      导入失败」连带把数据库日志一起拖挂，故障面被无谓放大；
    * ui.widgets.common 本身只是历史兼容层，内部同样只是转发 core.logger。
    """
    global _log_manager
    if _log_manager is None:
        from core.logger import logger as _core_logger
        _log_manager = _core_logger
    return _log_manager


def get_db_connection(busy_timeout_ms: int = 30000):
    """获取数据库连接（线程安全的用法：每次调用各自新建连接，用完即关）。

    并发加固说明：
    * 本项目有大量 QThread/threading.Thread 会在后台读写同一份 SQLite 文件
      （下载进度、使用量统计、订阅等）。默认 journal 模式下读写互斥，
      并发稍高就会抛 ``sqlite3.OperationalError: database is locked``。
    * ``timeout`` 是 sqlite3 的忙等超时（等价于 busy_timeout）：遇到锁时先等待
      而不是立刻报错，避免把瞬时锁竞争放大成业务失败。
    * 显式设置 ``busy_timeout`` PRAGMA，防止被其他连接/工具改回默认值。

    注意：杜绝跨线程共享同一个 connection —— sqlite3 默认 ``check_same_thread=True``，
    在别的线程使用会在运行时直接抛异常，正是"线程 A 建连接、线程 B 用"这类闪退来源。
    """
    conn = sqlite3.connect(DB_PATH, timeout=max(busy_timeout_ms, 0) / 1000.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    except Exception:
        pass
    return conn


def _enable_wal_mode():
    """把数据库切到 WAL 日志模式（幂等，设置后持久保存在库文件中）。

    WAL 下"读不阻塞写、写不阻塞读"，是把本应用从频繁 ``database is locked``
    里解放出来的关键一步。不支持的场景（如网络共享盘）静默跳过，不影响功能。
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL 在 WAL 下已能保证事务持久性，且显著减少 fsync 次数
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.close()
        return True
    except Exception:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        return False


# ═══════════════ 权限常量 ═══════════════

# 所有可用模块
ALL_MODULES = [
    ('home', '首页'),
    ('music', '音乐'),
    ('video', '视频'),
    ('people', '人物'),
    ('about_me', '关于我'),
    ('settings', '设置'),
    ('dashboard', '仪表盘'),
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
    ('jmcomic_search', 'JMComic-搜索浏览'),
    ('jmcomic_download', 'JMComic-下载打包'),
    ('jmcomic_account', 'JMComic-账号收藏'),
    ('jmcomic_subscribe', 'JMComic-订阅管理'),
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



# ═══════════════ 统一数据库 schema ═══════════════
# 全程序**只有一个** SQLite 文件：data/ogc_users.db（冻结时 %APPDATA%\OGC-OpenGenericClient\
# ogc_users.db）。历史上 E-Hentai 模块用的是另一个文件（data/ehentai/app_db.db），
# 于是"账号库"和"收藏/下载记录"分家：换机只备份一个库就会丢另一半，卸载向导也只能
# 备份其中之一。2026-09 合并成一个：E-Hentai 的表结构在这里定义（唯一真源），
# ehviewer/db.py 从这里导入，init_db() 会一次性建全 —— 所以**第一次启动就得到完整结构**。
#
# 表名沿用 Android EhViewer (greenDAO) 的原名，方便直接导入旧版 EhViewer 的数据库。
EHENTAI_DDL = {
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
    "Gallery_Tags": """
        CREATE TABLE IF NOT EXISTS "Gallery_Tags" (
          "GID" INTEGER PRIMARY KEY NOT NULL, "ROWS" TEXT, "ARTIST" TEXT, "COSPLAYER" TEXT,
          "CHARACTER" TEXT, "FEMALE" TEXT, "GROUP" TEXT, "LANGUAGE" TEXT, "MALE" TEXT,
          "MISC" TEXT, "MIXED" TEXT, "OTHER" TEXT, "PARODY" TEXT, "RECLASS" TEXT,
          "CREATE_TIME" INTEGER, "UPDATE_TIME" INTEGER)""",
    "Black_List": """
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

#: 其它模块负责建的表（各自 init_*_tables() 里 CREATE TABLE IF NOT EXISTS）。
#: 这里只登记名字，供启动自检与回归测试核对"结构是否齐全"。
OTHER_KNOWN_TABLES = (
    'users', 'usage_stats', 'pixiv_tokens', 'music_playlists', 'music_songs',
    'music_downloads', 'jm_subscriptions', 'download_quota',
)

#: 一个**完整**数据库应当包含的全部表（不含 sqlite_ 内部表）。
ALL_TABLES = tuple(EHENTAI_DDL.keys()) + OTHER_KNOWN_TABLES


def get_db_path() -> str:
    """统一数据库文件的绝对路径（其它模块要拿路径一律走这里）。"""
    return DB_PATH


def init_ehentai_tables():
    """确保 E-Hentai 的表存在（幂等；由 init_db() 调用，也可单独调用）。

    ``ehviewer/db.py::_get_conn()`` 也会做同样的事（它可能先于 init_db 被使用），
    两边用的是**同一份 DDL 常量**，不会出现结构漂移。
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for ddl in EHENTAI_DDL.values():
            try:
                cur.execute(ddl)
            except sqlite3.Error as e:
                _get_logger().warning(f"创建 E-Hentai 表失败（忽略）: {e}")
        conn.commit()
    finally:
        conn.close()


def list_tables() -> set:
    """当前数据库里的表名集合（不含 sqlite_ 内部表）。"""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def missing_tables() -> list:
    """ALL_TABLES 里有哪些还不存在（正常应为空 —— 用于启动自检与回归测试）。"""
    have = list_tables()
    return [t for t in ALL_TABLES if t not in have]


def _ensure_indexes():
    """为高频查询列创建索引（CREATE INDEX IF NOT EXISTS，幂等、纯增量）。"""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_usage_module ON usage_stats(module)",
        "CREATE INDEX IF NOT EXISTS idx_usage_username ON usage_stats(username)",
        "CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_stats(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_songs_playlist ON music_songs(playlist_id)",
        "CREATE INDEX IF NOT EXISTS idx_songs_identifier ON music_songs(identifier)",
        "CREATE INDEX IF NOT EXISTS idx_downloads_identifier ON music_downloads(identifier)",
        "CREATE INDEX IF NOT EXISTS idx_jm_sub_user ON jm_subscriptions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_pixiv_user ON pixiv_tokens(username)",
    ]
    conn = get_db_connection()
    cur = conn.cursor()
    for stmt in indexes:
        try:
            cur.execute(stmt)
        except Exception:
            # 某些表可能尚未创建/列缺失，忽略单个索引失败
            pass
    conn.commit()
    conn.close()


def init_db():
    """初始化数据库"""
    logger = _get_logger()
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        # 启用 WAL：多线程并发读写时不再频繁 database is locked（幂等）
        try:
            _enable_wal_mode()
        except Exception:
            pass
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
        # 内置管理员账号：首次创建数据库时自动写入，保证「克隆下来就能登录」
        try:
            ensure_admin_account()
        except Exception as e:
            logger.error(f"创建内置管理员账号失败: {str(e)}")
        # 初始化使用量统计表
        try:
            init_usage_table()
        except Exception:
            pass
        # E-Hentai 的表 —— 与账号库同库，首次启动即建全（见上方 EHENTAI_DDL 的说明）
        try:
            init_ehentai_tables()
        except Exception as e:
            logger.error(f"创建 E-Hentai 表失败: {str(e)}")
        # 音乐 / Pixiv 的表：以前只在**首次用到那个功能时**才懒创建，
        # 于是"全新安装 → 直接打开音乐页"这类路径会先撞上 no such table。
        # 用户要求"第一次启动就创建完整结构"，这里显式建全（幂等）。
        for _init in (init_pixiv_tokens_table, init_music_tables, init_jmcomic_tables):
            try:
                _init()
            except Exception as e:
                logger.error(f"创建表失败（{getattr(_init, '__name__', _init)}）: {e}")
        # 为高频查询列建索引（加速启动与模块查询）
        try:
            _ensure_indexes()
        except Exception:
            pass
        # 结构自检：全新数据库必须一次建全（少了表说明某个 init_*_tables 没跑到）
        try:
            missing = missing_tables()
            if missing:
                logger.warning(f"数据库缺少这些表（可能对应模块未初始化）: {missing}")
        except Exception:
            pass
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        raise


def _hash_password(password: str) -> str:
    """对密码进行哈希处理"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


# ═══════════════ 内置管理员账号 ═══════════════

# 首次创建数据库时自动写入的管理员凭据。
# 用途：让「克隆 → 装依赖 → 运行」的人无需先注册就能进主界面（注册流程会把
# 第一个用户的 role 留空，导致没有任何账号能进仪表盘）。
# 这是本地桌面程序、数据库只存在于用户自己的机器上；默认密码是弱口令，
# 请登录后立即在「关于我」里修改。
DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_PASSWORD = '11111111'
ADMIN_ROLE = '管理员'


def ensure_admin_account() -> bool:
    """确保内置管理员账号存在（每数据库只创建一次）。

    行为约定（重要）：
    * **幂等**：username 上有 UNIQUE 约束，重复调用不会产生第二条记录；
    * **绝不覆盖已有密码**：只在账号不存在时写入默认密码。若账号已存在，
      仅补齐空的 role / permissions —— 否则用户改过的密码会在每次启动时
      被默默打回默认值，这是个严重的安全回退；
    * 失败只记录日志、不抛异常：管理员账号创建失败不应阻塞整个程序启动。

    Returns:
        True 表示本次调用新建了账号；False 表示账号已存在或创建失败。
    """
    logger = _get_logger()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, role, permissions FROM users WHERE username=?",
            (DEFAULT_ADMIN_USERNAME,))
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                """INSERT INTO users (username, password, avatar_path, role,
                   info_items, permissions, is_banned)
                   VALUES (?,?,?,?,?,?,0)""",
                (DEFAULT_ADMIN_USERNAME,
                 _hash_password(DEFAULT_ADMIN_PASSWORD),
                 '', ADMIN_ROLE, '[]',
                 json.dumps(get_default_permissions(), ensure_ascii=False)))
            conn.commit()
            logger.info(
                f"已创建内置管理员账号「{DEFAULT_ADMIN_USERNAME}」"
                f"（默认密码 {DEFAULT_ADMIN_PASSWORD}，请登录后尽快修改）")
            return True

        # 账号已存在：只修补空字段，绝不触碰 password
        patch, params = [], []
        if not row['role']:
            patch.append("role=?")
            params.append(ADMIN_ROLE)
        if not row['permissions']:
            patch.append("permissions=?")
            params.append(json.dumps(get_default_permissions(), ensure_ascii=False))
        if patch:
            params.append(DEFAULT_ADMIN_USERNAME)
            cursor.execute(
                f"UPDATE users SET {', '.join(patch)} WHERE username=?", params)
            conn.commit()
        return False
    except Exception as e:
        logger.error(f"确保内置管理员账号失败: {str(e)}")
        return False
    finally:
        conn.close()


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

def _count_files(dirs) -> int:
    """统计目录中的文件数量（跳过隐藏文件、.part/.tmp 残留与缓存目录）"""
    if isinstance(dirs, str):
        dirs = [dirs]
    # 缓存目录一律排除：旧命名（thumb_cache / dir_cache / thumbs）
    # 与新命名（.cache 及其下的 thumbs、ehentai、easycopy 等）都算
    excluded_dirs = {'thumb_cache', 'thumbs', '.thumbs', 'dir_cache', '.dir_cache',
                     '.cache', '__pycache__', 'cache', '.git'}
    total = 0
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        try:
            for root, dirnames, filenames in os.walk(d):
                dirnames[:] = [x for x in dirnames if x not in excluded_dirs]
                for f in filenames:
                    if f.startswith('.'):
                        continue
                    low = f.lower()
                    if low.endswith(('.part', '.tmp')):
                        continue
                    total += 1
        except Exception:
            continue
    return total


def get_module_file_counts() -> dict:
    """统计各模块下载目录中的文件数量

    下载根目录 = services.download_manager.get_download_root()，
    各平台目录形如 douyin-download / bilibili-download / jmcomic-download /
    easycopy-download；E-Hentai 读配置 ehentai.output_dir；
    音乐取 ``CFG.music_download_dir``（= {下载根}/music-download，派生而非配置）。

    Returns:
        {'douyin': N, ..., 'jmcomic': N, 'easycopy': N, 'ehentai': N,
         'music': N, 'total': N}
    """
    counts = {}
    try:
        from services.download_manager import get_download_root, PLATFORM_FOLDERS
        from core.config import config as CFG
        root = get_download_root()
        for key, folder in PLATFORM_FOLDERS.items():
            counts[key] = _count_files(os.path.join(root, folder))
        # E-Hentai（读配置 ehentai.output_dir）
        try:
            eh = (CFG.get('ehentai') or {}).get('output_dir', '')
            counts['ehentai'] = _count_files(eh) if eh else 0
        except Exception:
            counts['ehentai'] = 0
        # 音乐下载目录（不再读配置键，直接问 CFG 的派生属性）
        try:
            counts['music'] = _count_files(CFG.music_download_dir)
        except Exception:
            counts['music'] = 0
        counts['total'] = sum(counts.values())
    except Exception:
        pass
    return counts


def get_system_stats() -> dict:
    """获取系统统计数据（用于仪表盘）"""
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
        # 音乐相关统计（数据库记录数）
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
        try:
            cursor.execute("SELECT COUNT(*) FROM jm_subscriptions")
            stats['jmcomic_subscription_count'] = cursor.fetchone()[0]
        except Exception:
            stats['jmcomic_subscription_count'] = 0
        # 各模块下载文件数（扫描下载目录）
        module_files = get_module_file_counts()
        stats['module_files'] = module_files
        stats['total_download_files'] = module_files.get('total', 0)
        video_keys = ('douyin', 'bilibili', 'twitter', 'pixiv', 'xvideo', 'youtube')
        stats['video_file_count'] = sum(module_files.get(k, 0) for k in video_keys)
        stats['jmcomic_download_count'] = module_files.get('jmcomic', 0)
        stats['music_file_count'] = module_files.get('music', 0)
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

    result = {'music': {}, 'video': {}, 'video_sub': {}, 'people': {}, 'home': {},
              'jmcomic': {}, 'ehentai': {}, 'easycopy': {}, 'downloads': {}}
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

        # 总下载量（所有模块 action='download' 的记录数）
        count_sql = "SELECT COUNT(*) FROM usage_stats WHERE action='download'"
        if where:
            count_sql += ' AND ' + ' AND '.join(where)
        cursor.execute(count_sql, params)
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
