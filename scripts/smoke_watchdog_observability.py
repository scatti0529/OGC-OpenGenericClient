# -*- coding: utf-8 -*-
"""看门狗与可观测性回归验证

验证本次按"统一管理 + 超时兜底 + 可观测"框架新增的两项能力：

1. ``core/watchdog.py``：主线程卡死（事件循环停止心跳）时，守护线程能检测到
   并把**所有线程当时的 Python 栈**转储到 logs/crash.log —— 断言转储内容里
   确实包含主线程卡住的位置（time.sleep），而不是仅仅"装了看门狗"。
2. ``core/logger.py``：日志行带**线程名 + 任务标签**，便于多线程下追踪；
   任务标签必须是线程本地的（A 线程设置不影响 B 线程）。
3. ``services/download_manager.py``：分块/HLS 等待改为"停滞检测"，
   卡死时有界退出而非永久 join。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_watchdog_observability.py
"""
import os
import sys
import tempfile
import threading
import time
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
    from PyQt5.QtCore import QThread
    from PyQt5.QtWidgets import QApplication

    from core import crash_guard
    crash_guard.install()
    app = QApplication.instance() or QApplication(sys.argv)

    # ══════════════ 1) 日志：线程名 + 任务标签 ══════════════
    from core.logger import logger, set_task_tag, get_task_tag

    tmp_logs = tempfile.mkdtemp(prefix='ogc_log_smoke_')
    op_log = os.path.join(tmp_logs, 'operation.log')
    err_log = os.path.join(tmp_logs, 'error.log')
    logger.initialize(op_log_path=op_log, err_log_path=err_log)
    check('logger.initialize 幂等且成功', logger.get_op_log_path() == op_log)

    def _emit_from_worker():
        set_task_tag('smoke:task-42')
        logger.info('线程上下文日志验证')

    tw = threading.Thread(target=_emit_from_worker, name='OGC-SmokeWorker')
    tw.start()
    tw.join(5)

    # 主线程不设标签，应当显示 '-'
    logger.info('主线程日志验证')
    time.sleep(0.2)

    text = open(op_log, encoding='utf-8').read()
    check('日志包含线程名', 'OGC-SmokeWorker' in text,
          '找到 OGC-SmokeWorker' if 'OGC-SmokeWorker' in text else text[-200:])
    check('日志包含任务标签', 'smoke:task-42' in text)
    check('主线程未设标签时显示占位符', '[MainThread][-]' in text)
    check('任务标签是线程本地的',
          get_task_tag() == '-',
          f'主线程读取到={get_task_tag()}（不应被工作线程污染）')

    # ══════════════ 2) 看门狗：真能抓到主线程卡死现场 ══════════════
    from core import watchdog
    from core import crash_guard as cg

    crash_log = cg.crash_log_path()
    check('crash.log 可用', bool(crash_log), crash_log)
    before = open(crash_log, encoding='utf-8', errors='ignore').read() if crash_log else ''
    before_hits = before.count('看门狗')

    ok_install = watchdog.install(threshold_sec=2.0, check_interval=0.3, dump_cooldown=0.0)
    check('watchdog.install 成功', ok_install and watchdog.is_installed())

    # 先让心跳正常跑一会儿（心跳由主线程事件循环驱动）
    for _ in range(20):
        app.processEvents()
        QThread.msleep(20)
    beat_ok = watchdog.seconds_since_beat() < 2.0
    check('事件循环正常时心跳新鲜', beat_ok,
          f'距上次心跳 {watchdog.seconds_since_beat():.2f}s')

    # 人为阻塞主线程 3 秒（模拟界面卡死：等锁 / 等 IO / join 子线程）
    # 记录下一行行号：下面的 time.sleep 就在这一行。
    # 注意 faulthandler 只打印 **Python 帧**，time.sleep 是 C 函数不会出现为帧，
    # 因此正确的断言是"主线程栈精确停在调用 sleep 的那一行"。
    freeze_line = sys._getframe().f_lineno + 1
    time.sleep(3.0)
    stalled = watchdog.seconds_since_beat()
    check('主线程阻塞期间心跳停止增长', stalled >= 1.5,
          f'阻塞后距上次心跳 {stalled:.2f}s')

    # 让守护线程完成检测与转储
    for _ in range(40):
        app.processEvents()
        QThread.msleep(50)

    after = open(crash_log, encoding='utf-8', errors='ignore').read() if crash_log else ''
    hits = after.count('看门狗')
    gained = after[len(before):]
    check('看门狗已检测到卡死并记入 crash.log', hits > before_hits,
          f'看门狗记录 {before_hits} -> {hits}')
    check('转储中主线程栈精确停在阻塞那一行',
          f'line {freeze_line} in main' in gained,
          f'期望 “line {freeze_line} in main”；实际片段：'
          + (gained[-200:] if gained else '(空)'))
    check('转储覆盖了看门狗守护线程本身',
          'OGC-Watchdog' in gained or '_watch_loop' in gained)

    # ══════════════ 3) 停滞检测：卡死线程不会让等待永久挂住 ══════════════
    from services.download_manager import join_threads_with_stall_detection

    stop_event = threading.Event()
    progress = {'n': 0}

    def _stuck():
        # 模拟一个永远不返回、也不推进进度的分块线程（连接假死）
        while not stop_event.is_set():
            time.sleep(0.05)

    stuck = threading.Thread(target=_stuck, daemon=True)
    stuck.start()
    t0 = time.monotonic()
    ok = join_threads_with_stall_detection(
        [stuck], lambda: progress['n'], stop_event,
        stall_timeout=1.0, grace_timeout=2.0)
    elapsed = time.monotonic() - t0
    check('停滞的分块线程不会让等待永久挂住（有界返回）',
          (ok is False) and elapsed < 10.0,
          f'返回={ok} 用时={elapsed:.1f}s stop_event={stop_event.is_set()}')

    # 正常推进的线程不应被误判
    stop_event2 = threading.Event()
    progress2 = {'n': 0}

    def _progressing():
        for _ in range(12):
            time.sleep(0.2)
            progress2['n'] += 1

    prog = threading.Thread(target=_progressing, daemon=True)
    prog.start()
    ok2 = join_threads_with_stall_detection(
        [prog], lambda: progress2['n'], stop_event2,
        stall_timeout=1.0, grace_timeout=2.0)
    check('持续有进度的线程不会被误判为卡死', ok2 is True,
          f'返回={ok2} 进度={progress2["n"]}')

    # ══════════════ 汇总 ══════════════
    import shutil
    shutil.rmtree(tmp_logs, ignore_errors=True)

    failed = [n for n, ok, _ in _results if not ok]
    print('-' * 60)
    if failed:
        print(f'WATCHDOG RESULT: FAILED ({len(failed)}): {failed}')
        return 1
    print(f'WATCHDOG RESULT: ALL PASSED ({len(_results)} checks)')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print('WATCHDOG RESULT: FAILED (未捕获异常)')
        sys.exit(1)
