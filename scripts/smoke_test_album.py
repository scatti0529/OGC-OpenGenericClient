# -*- coding: utf-8 -*-
"""OGC 画册模块冒烟测试：编译检查 + 无头 Qt 构建页面"""
import os
import sys
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


def test_compile_all():
    import py_compile
    files = [
        'services/ehentai_downloader.py',
        'pages/album/__init__.py',
        'pages/album/ehentai_settings.py',
        'pages/album/ehentai_favorites_page.py',
        'pages/album/ehentai_page.py',
        'pages/album/album_interface.py',
        'ui/main_window.py',
    ]
    for f in files:
        py_compile.compile(os.path.join(BASE, f), doraise=True)
    print('  compiled:', len(files), 'files')


def test_imports():
    import services.ehentai_downloader as dl
    assert dl.EhentaiDownloader and dl.DownloadConfig and dl.DownloadProgress
    from pages.album.ehentai_settings import ehentai_cfg, SettingPage, EhentaiConfig
    from pages.album.ehentai_favorites_page import FavoritesPage
    from pages.album.ehentai_page import EhentaiPage
    from pages.album.album_interface import AlbumInterface
    print('  imports OK, db_path default =', ehentai_cfg.get(ehentai_cfg.KEY_DB_PATH))


def test_gui_build():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    # 与 main.py 相同：修复 Qt 平台插件路径（含中文/非 ASCII 路径）
    site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from pages.album.ehentai_page import EhentaiPage
    from pages.album.album_interface import AlbumInterface

    page = EhentaiPage()
    page.resize(1080, 780)
    page.show()
    app.processEvents()
    assert page.pivot.currentItem() is not None
    print('  EhentaiPage built, tabs:', list(page.pivot.items.keys()))
    assert page.favorites_page is not None
    assert page.download_page is not None
    assert page.settings_page is not None

    album = AlbumInterface()
    album.resize(1080, 780)
    album.show()
    app.processEvents()
    print('  AlbumInterface built, cards:', len(album._sub_cards))

    # 联动：收藏 -> 下载
    page.pivot.setCurrentItem(page.TAB_FAVORITES)
    app.processEvents()
    assert page.stackedWidget.currentWidget() is page.favorites_page
    page.pivot.setCurrentItem(page.TAB_SETTINGS)
    app.processEvents()
    assert page.stackedWidget.currentWidget() is page.settings_page
    print('  segmented switching OK')

    # 数据库路径切换（用合成小型库测试，不联网、不写原库）
    import sqlite3
    tmp = os.path.join(BASE, 'data', 'ehentai', '_smoke_test.db')
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp)
    conn.execute('CREATE TABLE LOCAL_FAVORITES (GID INTEGER, TOKEN TEXT, TITLE TEXT,'
                 ' TITLE_JPN TEXT, THUMB TEXT, CATEGORY INTEGER, POSTED TEXT,'
                 ' UPLOADER TEXT, RATING REAL, TIME REAL)')
    for i in range(12):
        conn.execute('INSERT INTO LOCAL_FAVORITES VALUES (?,?,?,?,?,?,?,?,?,?)',
                     (i, 'tok', f'title {i}', '', '', 2, '', 'u', 5.0, 0))
    conn.commit()
    conn.close()
    try:
        from pages.album.ehentai_settings import ehentai_cfg
        old = ehentai_cfg.get(ehentai_cfg.KEY_DB_PATH)
        page.favorites_page.set_db_path(tmp)
        app.processEvents()
        n = len(page.favorites_page._items)
        print(f'  favorites loaded {n} items from switched db')
        assert n == 12, f'expected 12 items, got {n}'
        ehentai_cfg.set(ehentai_cfg.KEY_DB_PATH, old or '')
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


step('compile_all', test_compile_all)
step('imports', test_imports)
step('gui_build', test_gui_build)

if FAILURES:
    print('SMOKE TEST RESULT: FAILED ->', FAILURES)
    sys.exit(1)
print('SMOKE TEST RESULT: ALL PASSED')
