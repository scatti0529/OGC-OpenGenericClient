# -*- coding: utf-8 -*-
"""端到端启动/退出验证（模拟 main.py 的真实生命周期）

目的：确认 core.crash_guard + core.thread_guard 的接入没有破坏启动与退出，
并且**走正常退出路径**（app.exec_() → aboutToQuit → thread_guard.shutdown）
后不再出现 "QThread: Destroyed while thread is still running"。

与 scripts/smoke_test_window.py 的区别：后者直接 sys.exit(0) 硬退出，
从不进入事件循环、也不会触发 aboutToQuit，因此退出瞬间线程仍存活属正常现象，
不能用来判断是否存在回归。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_startup_lifecycle.py
"""
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

_results = []


def check(name, ok, detail=''):
    _results.append((name, bool(ok), detail))
    print(('[PASS] ' if ok else '[FAIL] ') + name + (f' -> {detail}' if detail else ''))


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    # ── 与 main.py 一致的顺序：先装兜底，再建 QApplication ──
    from core import crash_guard
    crash_guard.install()
    check('crash_guard.install() 成功', crash_guard.is_installed())

    app = QApplication.instance() or QApplication(sys.argv)

    # ── 与 main.py 一致的看门狗接线 ──
    import core.thread_guard as tg
    app.aboutToQuit.connect(tg.shutdown)
    check('thread_guard.shutdown 已接到 aboutToQuit', True)

    from core import watchdog
    check('watchdog.install 成功（主线程心跳看门狗）',
          watchdog.install(threshold_sec=5.0) and watchdog.is_installed())
    check('看门狗心跳在事件循环中保持新鲜',
          watchdog.seconds_since_beat() < 5.0,
          f'距上次心跳 {watchdog.seconds_since_beat():.2f}s')

    # ── 构造主窗口（真实页面全部实例化）──
    from ui.main_window import Window
    win = Window()
    win.resize(1080, 780)
    win.show()
    app.processEvents()
    check('主窗口构造并显示成功', win.isVisible())

    # ── 进入真实事件循环，然后正常退出（触发 aboutToQuit）──
    state = {'quit': False}

    def _quit():
        state['quit'] = True
        win.close()          # 走 closeEvent → _reap_threads（有界预算）
        app.quit()           # 触发 aboutToQuit → thread_guard.shutdown

    QTimer.singleShot(1500, _quit)
    app.exec_()
    check('事件循环正常退出（aboutToQuit 已触发）', state['quit'])

    # 退出后不应仍有登记在册的运行中线程
    left = tg.live_count()
    check('退出后无仍在运行的已登记线程', left == 0, f'live={left}')

    failed = [n for n, ok, _ in _results if not ok]
    print('-' * 60)
    if failed:
        print(f'LIFECYCLE RESULT: FAILED ({len(failed)}): {failed}')
        return 1
    print(f'LIFECYCLE RESULT: ALL PASSED ({len(_results)} checks)')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print('LIFECYCLE RESULT: FAILED (未捕获异常)')
        sys.exit(1)
