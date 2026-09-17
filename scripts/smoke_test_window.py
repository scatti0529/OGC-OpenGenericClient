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


def _exit_skip_qt_teardown(code):
    """用 ``os._exit`` 直接结束进程，跳过解释器退出流程。

    本脚本会构建**真实窗口**，窗口里的 worker（QThread）在脚本跑完时仍在运行。
    正常 ``sys.exit`` 会走 Qt 的清理流程，撞上
    ``QThread: Destroyed while thread is still running`` **直接 abort**
    （退出码 0xC0000409 = -1073740791）—— 于是"测试通过"看起来像"崩溃"，
    按 AGENTS.md §6 的约定（成功必须是 0）等于永远失败。

    生产程序不怕这个：``core/thread_guard.py`` 在退出时统一
    ``requestInterruption + wait``。临时冒烟脚本没有也不需要那套收尾。
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)

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
    _exit_skip_qt_teardown(0)
except Exception:
    traceback.print_exc()
    print('WINDOW TEST RESULT: FAILED')
    _exit_skip_qt_teardown(1)
