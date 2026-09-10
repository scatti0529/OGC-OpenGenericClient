# -*- coding: utf-8 -*-
"""验证 ui.main_window 导入并构建 Window（含画册模块注册）"""
import os
import sys
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

try:
    import ui.main_window as mw
    print('[OK] ui.main_window imported')

    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    win = mw.Window()
    win.resize(1080, 780)
    app.processEvents()
    print('[OK] Window constructed')

    # 画册模块导航项
    nav_names = [k for k in win._nav_items.keys()]
    print('nav items:', nav_names)
    assert '画册' in nav_names, 'album parent nav missing'
    assert 'E-Hentai' in nav_names, 'ehentai sub nav missing'
    assert hasattr(win, 'albumInterface') and hasattr(win, 'ehentaiPage')
    print('[OK] album nav registered: 画册 -> E-Hentai')

    # 点击联动（直接调用，不依赖真实点击）
    win.ehentaiPage.pivot.setCurrentItem(win.ehentaiPage.TAB_FAVORITES)
    app.processEvents()
    print('[OK] ehentai favorites tab switch works inside Window')

    print('WINDOW TEST RESULT: ALL PASSED')
    sys.exit(0)
except Exception:
    traceback.print_exc()
    print('WINDOW TEST RESULT: FAILED')
    sys.exit(1)
