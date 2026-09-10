# -*- coding: utf-8 -*-
"""
全局线程看门狗
==============
问题：多数 QThread 子类的线程还没跑完，其 Python/C++ 包装对象就被垃圾回收/页面销毁，
Qt 报 ``QThread: Destroyed while thread is still running``。

方案：拦截所有 ``QThread.start()``，把每个已启动线程登记到全局表（保持强引用，
避免被提前 GC）；在应用退出前（aboutToQuit）统一 ``requestInterruption()`` + ``wait()``，
从而保证线程要么自然结束、要么被协作式打断后再销毁。

**回收（本版本修复的核心缺陷）**：原实现只往 ``_live_threads`` 里 add、从不移除，
登记表随运行时间**单调增长**：每个启动过的 QThread 及其闭包捕获的控件、图片、
会话对象都被永久强引用，长时间使用（逐个封面/逐张图片各起一个线程的场景）会持续
吃内存，并使已销毁控件的引用无法释放。现改为：

* 线程 ``finished`` 后先打"完成"标记，再延后一拍（``QTimer.singleShot(0)``）回收——
  因为 ``finished`` 是在 ``run()`` 返回**之前**发出的，立刻丢弃引用会重现
  "Destroyed while thread is still running"，必须等线程真正结束才放手；
* 每次 ``start()`` 与 ``shutdown()`` 前顺带回收已结束的登记项，保证表有界；
* 线程运行期间仍然保持强引用，原有的防崩溃保证不变。

用法：在 main.py 启动时 ``import core.thread_guard`` 即可自动生效，
并把 ``thread_guard.shutdown()`` 连到 ``app.aboutToQuit``。
"""
import threading
import time
import weakref

from PyQt5.QtCore import QThread, QThreadPool, QTimer

# 已启动的 QThread -> 是否已发出 finished
# 保持强引用，防止运行中的线程被提前 GC（这是本模块存在的根本目的）
_live_threads = {}
# 全局存活的线程池（QThreadPool 内部线程不经过 QThread.start，需单独登记并 waitForDone）
# 用 WeakSet：池对象的生命周期本来就由它的 parent 控件决定（image_cache /
# album_page / reader_window 都是 QThreadPool(self)），这里只需要在退出时能等到它。
# 若用强引用，则每个用过的 QThreadPool 都被永久钉住，反复开关页面即线性泄漏。
_live_pools = weakref.WeakSet()
# start() 可能从任意线程调用，登记表读写加锁（避免并发变更导致迭代 RuntimeError）
_registry_lock = threading.Lock()

# 缓存原始 start，避免重复包裹
_orig_start = getattr(QThread, 'start', None)
if _orig_start is not None and not getattr(QThread, '_ogc_thread_guarded', False):

    def _reap_finished_threads():
        """回收"已 finished 且确实不再运行"的线程登记项，使登记表有界。"""
        with _registry_lock:
            candidates = [t for t, done in _live_threads.items() if done]
        for t in candidates:
            try:
                if t.isRunning():
                    # finished 已发出但线程尚在收尾：继续持有强引用，等下次回收
                    continue
            except RuntimeError:
                # 底层 C++ 对象已销毁，直接摘除登记项
                pass
            except Exception:
                pass
            with _registry_lock:
                _live_threads.pop(t, None)

    def _mark_finished(ref):
        """线程 run() 已返回：打标记并延后一拍再回收（避开 finished 与真正结束之间的窗口）。

        参数是**弱引用**：finished 的连接由本线程对象持有，若直接闭包捕获线程本身会形成
        "线程→连接→闭包→线程"的强引用环，登记表就永远回收不掉。线程在运行期间由
        ``_live_threads`` 保活，因此这里解引用一定能拿到活对象。
        """
        thread = ref()
        if thread is None:
            return
        with _registry_lock:
            if thread in _live_threads:
                _live_threads[thread] = True
        try:
            QTimer.singleShot(0, _reap_finished_threads)
        except Exception:
            # 无事件循环（例如非 GUI 线程）时退化为立即尝试一次
            _reap_finished_threads()

    def _guarded_start(self, *args, **kwargs):
        # 登记（保持强引用）；顺带回收上一批已结束的线程，避免表无限增长
        with _registry_lock:
            _live_threads[self] = False
        try:
            _reap_finished_threads()
        except Exception:
            pass
        try:
            ref = weakref.ref(self)
            self.finished.connect(lambda r=ref: _mark_finished(r))
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
        # 登记失败绝不能影响线程池本身的启动（WeakSet.add 对不支持弱引用的
        # 包装对象会抛 TypeError，必须兜住）
        try:
            with _registry_lock:
                _live_pools.add(self)
        except Exception:
            pass
        return _orig_pool_start(self, *args, **kwargs)

    QThreadPool.start = _guarded_pool_start
    try:
        QThreadPool._ogc_pool_guarded = True
    except Exception:
        pass


def shutdown(timeout_ms: int = 3000, total_budget_ms: int = 8000):
    """停止并等待所有仍存活的已启动线程与线程池（在应用退出前调用）。

    引入**总预算**：原实现对每个线程/线程池串行 ``wait(timeout_ms)``，
    20 个存活线程最长会阻塞 60 秒 —— 用户看到的现象是"程序关不掉、
    点了退出像死机"。现在所有等待共享一个总预算，超时即放弃等待；
    这些线程都是 daemon/随进程回收，放弃等待不会造成新的崩溃。
    """
    deadline = time.monotonic() + max(total_budget_ms, 0) / 1000.0

    def _remaining_ms() -> int:
        """剩余预算（毫秒）；<=0 表示预算耗尽。"""
        left = deadline - time.monotonic()
        if left <= 0:
            return 0
        return max(50, min(int(left * 1000), timeout_ms))

    # 先排空线程池（内部 QThread 不经 start 补丁）
    with _registry_lock:
        pools = list(_live_pools)
        _live_pools.clear()
    for pool in pools:
        budget = _remaining_ms()
        if budget <= 0:
            break
        try:
            pool.waitForDone(budget)
        except Exception:
            pass

    with _registry_lock:
        threads = list(_live_threads)
    for t in threads:
        try:
            if not t.isRunning():
                continue
            budget = _remaining_ms()
            if budget <= 0:
                break
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
                t.wait(budget)
            except Exception:
                pass
        except Exception:
            pass
    with _registry_lock:
        _live_threads.clear()


def live_count() -> int:
    """调试：当前已登记且仍在运行的线程数。"""
    with _registry_lock:
        threads = list(_live_threads)
    n = 0
    for t in threads:
        try:
            if t.isRunning():
                n += 1
        except Exception:
            pass
    return n


def tracked_count() -> int:
    """调试：当前登记表规模（含已结束但待回收的条目）。

    用于验证"登记表不再单调增长"：长时间使用后该值应稳定在个位/十位量级，
    而不是随启动过的线程总数线性上涨。
    """
    with _registry_lock:
        return len(_live_threads)
