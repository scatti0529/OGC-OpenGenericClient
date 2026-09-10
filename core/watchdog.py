# -*- coding: utf-8 -*-
"""
主线程（GUI）看门狗
==================
问题：桌面程序最致命的故障不是崩溃，而是**卡死**——界面完全不响应、没有异常、
日志停在最后一行，用户只能强杀进程；事后完全不知道当时卡在哪一条语句上。

方案：心跳 + 超时转储。

* 主线程上挂一个 ``QTimer`` 周期性刷新心跳时间戳（心跳只可能由事件循环驱动）；
* 一个守护线程按间隔检查心跳。若心跳停止超过 ``threshold_sec``，说明主线程的
  事件循环被阻塞（在等锁 / 等 IO / join 子线程 / 跑长任务），立即把所有线程
  当时的 Python 栈转储到 ``logs/crash.log``，并记一条含"已阻塞多久"的警告；
* 同时做**线程数监控**：存活线程数超过阈值时告警，用于发现"每个条目起一个线程"
  这类无界并发导致的资源增长（正常空闲时应在个位数）。

为什么只转储、不自动"重启或隔离"：GUI 主线程无法安全强杀，Qt 对象也不允许
从外部线程重建；本看门狗定位为**取证工具**，把"无法复现的卡死"变成"有现场可查"。
真正的兜底仍是崩溃重启（见 core.crash_guard）。

用法（必须在主线程调用，且在事件循环启动前）::

    from core import watchdog
    watchdog.install()
"""
import threading
import time

# 心跳时间戳（单调时钟）。单变量赋值在 GIL 下是原子的，无需加锁。
_last_beat = 0.0
_last_report = 0.0
_installed = False
_watch_thread = None
_timer = None

# 存活线程数超过该值时告警（用于发现无界并发）
THREAD_WARN_THRESHOLD = 96
# 线程数告警的最小间隔，避免刷屏
THREAD_WARN_COOLDOWN = 120.0
_last_thread_warn = 0.0


def _log(message):
    """写日志，任何失败都不能影响看门狗自身。"""
    try:
        from core.logger import logger
        logger.warning(message)
    except Exception:
        pass


def _beat():
    """心跳：由主线程事件循环驱动（QTimer 回调）。"""
    global _last_beat
    _last_beat = time.monotonic()


def _watch_loop(threshold_sec, check_interval, dump_cooldown):
    """守护线程：检查心跳与线程数。"""
    global _last_report, _last_thread_warn
    while True:
        time.sleep(check_interval)
        now = time.monotonic()

        # ── 1) 主线程卡死检测 ──
        try:
            stalled = now - _last_beat if _last_beat else 0.0
            if stalled > threshold_sec and (now - _last_report) > dump_cooldown:
                _last_report = now
                detail = f"主线程已阻塞 {stalled:.1f} 秒（事件循环未心跳）"
                _log(f"[看门狗] {detail}，正在转储全部线程栈以定位卡点")
                try:
                    from core import crash_guard
                    crash_guard.dump_all_thread_stacks(
                        f"看门狗：{detail}")
                except Exception:
                    pass
        except Exception:
            pass

        # ── 2) 线程数监控（发现无界并发 / 线程泄漏）──
        try:
            if (now - _last_thread_warn) > THREAD_WARN_COOLDOWN:
                alive = threading.active_count()
                if alive >= THREAD_WARN_THRESHOLD:
                    _last_thread_warn = now
                    extra = ''
                    try:
                        import core.thread_guard as tg
                        extra = (f"，已登记 QThread={tg.tracked_count()}"
                                 f"（运行中 {tg.live_count()}）")
                    except Exception:
                        pass
                    _log(f"[看门狗] 存活线程数异常：{alive}{extra}，"
                         f"请检查是否存在「每个条目起一个线程」的无界并发")
        except Exception:
            pass


def install(threshold_sec=8.0, check_interval=1.0, dump_cooldown=30.0):
    """安装看门狗（幂等；必须在主线程调用）。

    Args:
        threshold_sec: 主线程心跳停止多久算卡死（默认 8 秒）。
        check_interval: 守护线程检查间隔（默认 1 秒）。
        dump_cooldown: 两次卡死转储之间的最小间隔，避免刷盘（默认 30 秒）。

    Returns:
        是否安装成功。
    """
    global _installed, _watch_thread, _timer
    if _installed:
        return True
    try:
        from PyQt5.QtCore import QTimer
        # 心跳定时器必须属于主线程，这样它"不触发"本身就代表主线程被阻塞
        _timer = QTimer()
        _timer.setInterval(500)
        _timer.timeout.connect(_beat)
        _timer.start()
        _beat()

        _watch_thread = threading.Thread(
            target=_watch_loop,
            args=(threshold_sec, check_interval, dump_cooldown),
            name='OGC-Watchdog',
            daemon=True,
        )
        _watch_thread.start()
        _installed = True
        _log(f"[看门狗] 已启动：主线程心跳超过 {threshold_sec:.0f} 秒未刷新即转储线程栈"
             f"到 logs/crash.log")
        return True
    except Exception:
        return False


def seconds_since_beat():
    """距上次心跳过去的秒数（诊断/测试用）。"""
    return (time.monotonic() - _last_beat) if _last_beat else -1.0


def is_installed():
    """看门狗是否已安装。"""
    return _installed
