# -*- coding: utf-8 -*-
"""统一数据库回归测试：全程序只有一个 .db，且首次启动就建全结构

用户要求：把 E-Hentai 的 app_db.db 与账号库 ogc_users.db 合并成一个库，
旧数据要同步过去，第一次启动程序时创建**完整结构**的数据库。

守住四件事：

1. **首次启动即完整**：``init_db()`` 建出来的库必须包含 ``ALL_TABLES`` 里的每一张表
   （账号 / 权限 / 音乐 / JM / 抖音订阅 / E-Hentai 收藏下载历史…），
   否则新用户会看到"某个模块一进来就报 no such table"。
2. **只有一个库**：``ehviewer.db.get_db_path()`` 必须等于 ``core.database.DB_PATH``；
   通过 ehviewer 写入的数据要真的落进那个库，且**不会**再冒出 app_db.db。
3. **旧库能被合并进来**：给一个旧格式的 app_db.db（含 DOWNLOADS/LOCAL_FAVORITES 行，
   外加一张统一库里没有的自定义表），合并后行数与未知表都要在统一库里出现。
4. **幂等 + 留档**：重复合并不会重复插入；内置位置的旧库合并后会被改名留档
   （绝不删除），下次启动自然不再扫到。

全程在临时目录里跑：monkeypatch ``core.database.DB_PATH`` 做隔离（与
smoke_fresh_install.py 同一套做法），不碰真实 data/。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_unified_db.py

退出码 0 表示全部通过。
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
SCRIPTS = os.path.join(BASE, 'scripts')
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_PLUGIN_DIR = os.path.join(BASE, '.venv', 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(_PLUGIN_DIR, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', _PLUGIN_DIR)

FAILURES = []
TMP = tempfile.mkdtemp(prefix='ogc-unified-db-')


def step(name, fn):
    try:
        fn()
        print(f'[OK] {name}')
    except Exception:
        FAILURES.append(name)
        print(f'[FAIL] {name}')
        traceback.print_exc()


def _make_legacy_db(path: str):
    """造一个"旧版 E-Hentai 独立库"：有数据，还有一张统一库没有的自定义表。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE IF NOT EXISTS "LOCAL_FAVORITES" ('
              '"GID" INTEGER PRIMARY KEY NOT NULL, "TOKEN" TEXT, "TITLE" TEXT,'
              '"TITLE_JPN" TEXT, "THUMB" TEXT, "CATEGORY" INTEGER NOT NULL,'
              '"POSTED" TEXT, "UPLOADER" TEXT, "RATING" REAL NOT NULL,'
              '"SIMPLE_LANGUAGE" TEXT, "TIME" INTEGER NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS "DOWNLOADS" ('
              '"GID" INTEGER PRIMARY KEY NOT NULL, "TOKEN" TEXT, "TITLE" TEXT,'
              '"TITLE_JPN" TEXT, "THUMB" TEXT, "CATEGORY" INTEGER NOT NULL,'
              '"POSTED" TEXT, "UPLOADER" TEXT, "RATING" REAL NOT NULL,'
              '"SIMPLE_LANGUAGE" TEXT, "STATE" INTEGER NOT NULL, "LEGACY" INTEGER NOT NULL,'
              '"TIME" INTEGER NOT NULL, "LABEL" TEXT, "ARCHIVE_URI" TEXT)')
    # 统一库里没有的表 —— 用来验证"通用合并"不会把未知表丢掉
    c.execute('CREATE TABLE IF NOT EXISTS "EHV_EXTRA" ("K" TEXT PRIMARY KEY, "V" TEXT)')
    c.execute('INSERT INTO LOCAL_FAVORITES (GID,TOKEN,TITLE,CATEGORY,RATING,TIME) '
              'VALUES (424242,?,"旧库收藏",2,5.0,1)', ('tok424242',))
    c.execute('INSERT INTO DOWNLOADS (GID,TOKEN,TITLE,CATEGORY,RATING,STATE,LEGACY,TIME) '
              'VALUES (434343,?,"旧库下载",2,4.0,3,0,2)', ('tok434343',))
    c.execute('INSERT INTO EHV_EXTRA (K,V) VALUES ("hello","world")')
    c.commit()
    c.close()


# ═══════════════ 1. 首次启动即完整结构 ═══════════════

def test_fresh_db_has_full_schema():
    import core.database as db

    target = os.path.join(TMP, 'fresh', 'ogc_users.db')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    saved = db.DB_PATH
    db.DB_PATH = target
    try:
        db.init_db()
        have = db.list_tables()
        missing = db.missing_tables()
        assert not missing, f'全新数据库缺少这些表: {missing}'
        # E-Hentai 的表必须也在（这是本次合并的核心）
        for t in ('DOWNLOADS', 'DOWNLOAD_LABELS', 'DOWNLOAD_DIRNAME', 'HISTORY',
                  'LOCAL_FAVORITES', 'QUICK_SEARCH', 'FILTER'):
            assert t in have, f'E-Hentai 表 {t} 未随首次建库创建'
        # 账号库该有的也不能少
        for t in ('users', 'usage_stats', 'music_downloads'):
            assert t in have, f'主库表 {t} 未随首次建库创建'
        assert os.path.isfile(target), 'init_db() 没有生成数据库文件'
    finally:
        db.DB_PATH = saved


# ═══════════════ 2. 只有一个库 ═══════════════

def test_single_database_path():
    import core.database as db
    from ehviewer import db as ehdb

    target = os.path.join(TMP, 'single', 'ogc_users.db')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    saved = db.DB_PATH
    db.DB_PATH = target
    try:
        assert os.path.normcase(ehdb.get_db_path()) == os.path.normcase(target), \
            f'ehviewer 用的不是统一库：{ehdb.get_db_path()} != {target}'

        # 通过 ehviewer 的 API 写一条收藏 → 必须出现在统一库里
        from ehviewer.models import GalleryInfo
        g = GalleryInfo()
        g.gid = 777001
        g.token = 'unified-token'
        g.title = '统一库写入验证'
        g.category = 2
        g.rating = 4.0
        assert ehdb.add_local_favorite(g) is True, '写入收藏失败'
        assert ehdb.is_local_favorited(777001) is True

        c = sqlite3.connect(target)
        n = c.execute('SELECT COUNT(*) FROM LOCAL_FAVORITES WHERE GID=777001').fetchone()[0]
        c.close()
        assert n == 1, '收藏没有写进统一库'

        # 绝不允许再冒出独立的 app_db.db
        strays = []
        for root, _d, files in os.walk(TMP):
            for f in files:
                if f == 'app_db.db':
                    strays.append(os.path.join(root, f))
        assert not strays, f'仍然生成了独立的 app_db.db: {strays}'
    finally:
        db.DB_PATH = saved


# ═══════════════ 3. 旧库合并（含未知表） ═══════════════

def test_merge_legacy_into_unified():
    import core.database as db
    from core import db_unify

    target = os.path.join(TMP, 'merge', 'ogc_users.db')
    legacy = os.path.join(TMP, 'merge', 'ehentai', 'app_db.db')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    saved = db.DB_PATH
    db.DB_PATH = target
    try:
        db.init_db()
        _make_legacy_db(legacy)

        r = db_unify.merge_database(legacy, target_path=target, rename_source=True)
        assert r['ok'], f'合并失败: {r["error"]}'
        assert r['moved'] >= 3, f'至少应搬 3 行，实际 {r["moved"]}：{r["tables"]}'

        c = sqlite3.connect(target)
        fav = c.execute('SELECT TITLE FROM LOCAL_FAVORITES WHERE GID=424242').fetchone()
        dl = c.execute('SELECT TITLE FROM DOWNLOADS WHERE GID=434343').fetchone()
        extra = c.execute('SELECT V FROM EHV_EXTRA WHERE K="hello"').fetchone()
        c.close()
        assert fav and fav[0] == '旧库收藏', '旧收藏没有合并进来'
        assert dl and dl[0] == '旧库下载', '旧下载记录没有合并进来'
        assert extra and extra[0] == 'world', '统一库里原本没有的表没有被带过来'

        # 旧文件必须留档而不是被删
        assert not os.path.exists(legacy), '旧库文件应被改名'
        kept = [f for f in os.listdir(os.path.dirname(legacy))
                if f.startswith('app_db.db' + db_unify.BACKUP_SUFFIX)]
        assert kept, '没有找到旧库的留档文件'

        # 幂等：再合一次不应重复插入
        r2 = db_unify.merge_database(kept and os.path.join(os.path.dirname(legacy), kept[0]),
                                     target_path=target, rename_source=False)
        c = sqlite3.connect(target)
        n = c.execute('SELECT COUNT(*) FROM LOCAL_FAVORITES WHERE GID=424242').fetchone()[0]
        c.close()
        assert n == 1, f'重复合并产生了重复行（{n} 条）'
        assert r2['moved'] == 0, f'重复合并不该再插入，实际 {r2["moved"]}'
    finally:
        db.DB_PATH = saved


def test_merge_is_non_destructive_on_conflict():
    """同名主键已存在时保留统一库里那一行（不用旧数据覆盖用户当前数据）。"""
    import core.database as db
    from core import db_unify

    target = os.path.join(TMP, 'conflict', 'ogc_users.db')
    legacy = os.path.join(TMP, 'conflict', 'old', 'app_db.db')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.makedirs(os.path.dirname(legacy), exist_ok=True)
    saved = db.DB_PATH
    db.DB_PATH = target
    try:
        db.init_db()
        _make_legacy_db(legacy)
        # 统一库里先放一条同 GID、内容更新的收藏
        c = sqlite3.connect(target)
        c.execute('INSERT INTO LOCAL_FAVORITES (GID,TOKEN,TITLE,CATEGORY,RATING,TIME) '
                  'VALUES (424242,"new","统一库里的新标题",2,5.0,99)')
        c.commit()
        c.close()

        db_unify.merge_database(legacy, target_path=target, rename_source=False)
        c = sqlite3.connect(target)
        row = c.execute('SELECT TITLE FROM LOCAL_FAVORITES WHERE GID=424242').fetchone()
        c.close()
        assert row and row[0] == '统一库里的新标题', \
            f'旧数据覆盖了统一库里已有的记录：{row}'
    finally:
        db.DB_PATH = saved


def test_legacy_scan_finds_known_locations():
    """内置的旧库位置要被扫到（ehentai/app_db.db 与更早的包内位置）。"""
    from core import db_unify

    assert os.path.join('ehentai', 'app_db.db') in db_unify.LEGACY_DB_RELPATHS
    assert 'app_db.db' in db_unify.LEGACY_DB_RELPATHS
    # 不存在的路径不该被返回；调用本身也不能抛异常
    assert isinstance(db_unify._iter_legacy_paths(), list)
    assert isinstance(db_unify.describe(), str)


def test_ehentai_sync_uses_unified_path():
    """ehentai_sync / 收藏页读到的数据库路径必须是统一库（不是另一个文件）。"""
    import core.database as db
    from pages.album import ehentai_sync as S

    target = os.path.join(TMP, 'syncdb', 'ogc_users.db')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    saved = db.DB_PATH
    db.DB_PATH = target
    try:
        assert os.path.normcase(os.path.abspath(S.db_path())) == \
            os.path.normcase(os.path.abspath(target)), \
            f'ehentai_sync.db_path() 返回了别的库：{S.db_path()}'
    finally:
        db.DB_PATH = saved


if __name__ == '__main__':
    print('=== 统一数据库回归测试 ===')
    step('首次启动即建全结构', test_fresh_db_has_full_schema)
    step('只有一个库（ehviewer 写入落进统一库）', test_single_database_path)
    step('旧库合并（含未知表 / 留档 / 幂等）', test_merge_legacy_into_unified)
    step('主键冲突时保留统一库现有数据', test_merge_is_non_destructive_on_conflict)
    step('旧库位置扫描', test_legacy_scan_finds_known_locations)
    step('ehentai_sync 使用统一库路径', test_ehentai_sync_uses_unified_path)

    shutil.rmtree(TMP, ignore_errors=True)
    if FAILURES:
        print('UNIFIED DB RESULT: FAILED ->', FAILURES)
        sys.exit(1)
    print('UNIFIED DB RESULT: ALL PASSED')
