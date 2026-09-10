# -*- coding: utf-8 -*-
"""
全局线程看门狗
==============
问题：多数 QThread 子类的线程还没跑完，其 Python/C++ 包装对象就被垃圾回收/页面销毁，
Qt 报 ``QThread: Destroyed while thread is still running``。

方案：拦截所有 ``QThread.start()``，把每个已启动线程登记到全局集合（保持强引用，
避免被提前 GC）；在应用退出前（aboutToQuit）统一 ``requestInterruption()`` + ``wait()``，
从而保证线程要么自然结束、要么被协作式打断后再销毁。

用法：在 main.py 启动时 ``import core.thread_guard`` 即可自动生效，
并把 ``thread_guard.shutdown()`` 连到 ``app.aboutToQuit``。
"""
from PyQt5.QtCore import QThread, QThreadPool

# 全局存活的已启动线程（强引用，防止提前销毁）
_live_threads = set()
# 全局存活的线程池（QThreadPool 内部线程不经过 QThread.start，需单独登记并 waitForDone）
_live_pools = set()

# 缓存原始 start，避免重复包裹
_orig_start = getattr(QThread, 'start', None)
if _orig_start is not None and not getattr(QThread, '_ogc_thread_guarded', False):
    def _guarded_start(self, *args, **kwargs):
        # 登记（保持强引用）
        try:
            _live_threads.add(self)
        except Exception:
            pass
        # 记录是否有 stop / requestInterruption 钩子，供 shutdown 调用
        try:
            self._ogc_guarded = True
        except Exception:
            pass
        return _orig_start(self, *args, **kwargs)

    QThread.start = _guarded_start
    try:
        QThread._ogc_thread_guarded = True
    except Exception:
        pass


# ── 登记所有 QThreadPool 实例：内部 QThread 不经过 start 补丁，需在退出前 waitForDone ──
_orig_pool_start = getattr(QThreadPool, 'start', None)
if _orig_pool_start is not None and not getattr(QThreadPool, '_ogc_pool_guarded', False):
    def _guarded_pool_start(self, *args, **kwargs):
        try:
            _live_pools.add(self)
        except Exception:
            pass
        return _orig_pool_start(self, *args, **kwargs)

    QThreadPool.start = _guarded_pool_start
    try:
        QThreadPool._ogc_pool_guarded = True
    except Exception:
        pass


def shutdown(timeout_ms: int = 3000):
    """停止并等待所有仍存活的已启动线程与线程池（在应用退出前调用）。"""
    # 先排空线程池（内部 QThread 不经 start 补丁）
    pools = list(_live_pools)
    for pool in pools:
        try:
            pool.waitForDone(timeout_ms)
        except Exception:
            pass
    _live_pools.clear()

    threads = list(_live_threads)
    for t in threads:
        try:
            if not t.isRunning():
                continue
            # 若模块提供了协作式 stop()，优先调用；否则用 requestInterruption
            try:
                stop = getattr(t, 'stop', None)
                if callable(stop):
                    stop()
            except Exception:
                pass
            try:
                t.requestInterruption()
            except Exception:
                pass
            try:
                t.wait(timeout_ms)
            except Exception:
                pass
        except Exception:
            pass
    _live_threads.clear()


def live_count() -> int:
    """调试：当前已登记且仍在运行的线程数。"""
    return sum(1 for t in _live_threads if t.isRunning())
