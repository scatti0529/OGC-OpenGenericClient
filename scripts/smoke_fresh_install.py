# -*- coding: utf-8 -*-
"""全新安装冒烟测试：验证「从 GitHub 克隆 → 装依赖 → 首次启动」这条路径是通的。

覆盖三类真实发生过的事故，防止回归：

1. **.gitignore 误伤导致模块/资源没进仓库**
   - ``music/`` 规则吞掉 ``pages/music/`` → ``ModuleNotFoundError: No module named 'pages.music'``
     → 主窗口模块级导入失败 → 登录后主界面完全打不开
   - ``data/`` 规则吞掉 ``ehviewer/data/tag_translations.json.gz`` → E-Hentai 标签翻译失效
2. **首次建库没有管理员账号**：装了也进不去仪表盘（注册流程不会设置 role）
3. **内核层反向依赖 UI 层**：``core.database`` 曾 import ``ui.widgets.common``

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_fresh_install.py

退出码 0 表示全部通过。
"""
import os
import sys
import tempfile
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

FAILURES = []


def step(name, fn):
    try:
        fn()
        print(f'[OK] {name}')
    except Exception:
        FAILURES.append(name)
        print(f'[FAIL] {name}')
        traceback.print_exc()


# ═══════════════ 1. 随包分发的模块与资源 ═══════════════

def test_music_module_present():
    """音乐模块必须在仓库里（历史事故：被 .gitignore 的 music/ 吞掉）"""
    import importlib
    mod = importlib.import_module('pages.music.music_page')
    assert getattr(mod, 'MusicInterface', None) is not None, \
        'pages.music.music_page 未导出 MusicInterface'


def test_ehviewer_data_present():
    """E-Hentai 标签翻译库必须随包分发（历史事故：被 .gitignore 的 data/ 吞掉）"""
    path = os.path.join(BASE, 'ehviewer', 'data', 'tag_translations.json.gz')
    assert os.path.isfile(path), f'缺少资源文件: {path}'
    assert os.path.getsize(path) > 1024, '标签翻译库为空或明显不完整'


# ═══════════════ 2. 分层：core 不得依赖 ui ═══════════════

def test_core_does_not_depend_on_ui():
    """core 层反向依赖 ui 层会让 UI 依赖缺失时连数据库一起挂掉"""
    import importlib
    for mod in [m for m in list(sys.modules) if m == 'ui' or m.startswith('ui.')
                or m == 'pages' or m.startswith('pages.')]:
        sys.modules.pop(mod, None)
    sys.modules.pop('core.database', None)
    importlib.import_module('core.database')
    assert 'ui.widgets.common' not in sys.modules, \
        'core.database 反向导入了 ui.widgets.common，违反 core → 上层 的分层约定'


# ═══════════════ 3. 首次建库即自带管理员 ═══════════════

def _with_temp_db(prefix, fn):
    """在临时 DB 上执行 fn，事后恢复真实 DB_PATH。"""
    import core.database as db
    tmpdir = tempfile.mkdtemp(prefix=prefix)
    original = db.DB_PATH
    db.DB_PATH = os.path.join(tmpdir, 'ogc_users.db')
    try:
        return fn(db)
    finally:
        db.DB_PATH = original


def test_fresh_db_seeds_admin():
    """全新数据库初始化后应自带可登录的管理员账号"""
    def run(db):
        db.init_db()
        assert db.is_admin('admin'), 'admin 未被识别为管理员（role 不是「管理员」）'
        ok, msg = db.verify_login('admin', '11111111')
        assert ok, f'默认管理员 admin/11111111 无法登录: {msg}'
        perms = db.get_user_permissions('admin')
        assert all(perms.get('modules', {}).values()), '管理员模块权限不完整'
    _with_temp_db('ogc-fresh-', run)


def test_admin_seed_idempotent_and_non_destructive():
    """重复启动不得重复建号，更不得把用户改过的密码打回默认值"""
    def run(db):
        db.init_db()
        conn = db.get_db_connection()
        conn.execute("UPDATE users SET password=? WHERE username='admin'",
                     (db._hash_password('changed-by-user'),))
        conn.commit()
        conn.close()

        db.init_db()   # 模拟第二次、第三次启动
        db.init_db()

        conn = db.get_db_connection()
        n = conn.execute(
            "SELECT COUNT(*) FROM users WHERE username='admin'").fetchone()[0]
        conn.close()
        assert n == 1, f'admin 账号出现 {n} 条记录，应为 1 条'

        ok, _ = db.verify_login('admin', 'changed-by-user')
        assert ok, '再次启动把管理员密码重置了（严重安全回退）'
        ok_default, _ = db.verify_login('admin', '11111111')
        assert not ok_default, '用户改密后默认密码仍然可登录'
    _with_temp_db('ogc-repeat-', run)


if __name__ == '__main__':
    print('=== 全新安装冒烟测试 ===')
    step('pages/music 模块随包分发', test_music_module_present)
    step('ehviewer/data 资源随包分发', test_ehviewer_data_present)
    step('core 不反向依赖 ui', test_core_does_not_depend_on_ui)
    step('全新数据库自动创建管理员', test_fresh_db_seeds_admin)
    step('管理员种子幂等且不覆盖密码', test_admin_seed_idempotent_and_non_destructive)
    if FAILURES:
        print('FRESH INSTALL RESULT: FAILED ->', FAILURES)
        sys.exit(1)
    print('FRESH INSTALL RESULT: ALL PASSED')
