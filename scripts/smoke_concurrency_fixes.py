# -*- coding: utf-8 -*-
"""模块级并发缺陷修复的回归验证

每个断言都对应一个**真实存在过**的缺陷，并且尽量构造出能触发原缺陷的场景
（例如 Pixiv 的"文件已存在 → 计数永不到顶 → join 永久卡死"）。

覆盖：
1. services/pixiv_service.py —— 已存在文件不再导致永久卡死；worker 不再阻塞在 get
2. services/downloader.py    —— 结束信号一定发出；不再覆盖 QThread.finished
3. ehviewer/image_cache.py   —— PixmapCache 并发安全 + remove 方法存在
4. services/file_library.py  —— 缩略图索引并发写不再产生坏 JSON
5. ehviewer/db.py            —— 惰性连接加锁 + WAL；切库关闭旧连接
6. core/thread_guard.py      —— 线程池登记表用弱引用，不再永久钉住池对象

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_concurrency_fixes.py
"""
import gc
import json
import os
import queue as _queue
import shutil
import sys
import tempfile
import threading
import time
import traceback
import weakref

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


def _run_in_threads(fn, n, timeout=60):
    errors = []

    def _wrap(i):
        try:
            fn(i)
        except Exception as e:      # noqa: BLE001
            errors.append(f'{type(e).__name__}: {e}')

    ts = [threading.Thread(target=_wrap, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout)
    return errors


def main():
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QThread, QThreadPool, QRunnable

    app = QApplication.instance() or QApplication(sys.argv)
    from core import crash_guard
    crash_guard.install()

    # ══════════════ 1) Pixiv：已存在文件不再永久卡死 ══════════════
    from services.pixiv_service import PixivDownloader

    dl = PixivDownloader()
    tmpd = tempfile.mkdtemp(prefix='ogc_pixiv_smoke_')
    try:
        existing = os.path.join(tmpd, 'exists.jpg')
        with open(existing, 'wb') as f:
            f.write(b'x' * 32)

        # 队列里 1 个任务，但其目标文件**已存在**。
        # 原实现该分支不自增 _finished_download → 计数永远追不上总数
        # → _track_progress 不退出 → _start_and_wait 永久阻塞。
        q = _queue.Queue()
        q.put({'url': 'http://127.0.0.1:1/never', 'file': 'exists.jpg', 'path': existing})
        dl._finished_download = 0
        dl._error_count = {}
        done = threading.Event()

        def _drive():
            dl._start_and_wait(q, 1)
            done.set()

        base_threads = len(threading.enumerate())
        threading.Thread(target=_drive, daemon=True).start()
        finished = done.wait(20)
        check('pixiv：目标文件已存在时不再永久卡死', finished,
              '20 秒内返回' if finished else '超时未返回（仍在卡死）')

        # 10 个 worker 从空队列退出：原实现会留下 9 个永久阻塞在 get() 上
        for _ in range(30):
            if len(threading.enumerate()) <= base_threads:
                break
            time.sleep(0.1)
        leaked = len(threading.enumerate()) - base_threads
        check('pixiv：worker 线程全部退出（无 get 永久阻塞）', leaked <= 0,
              f'残留线程={leaked}')

        # 混合场景：已存在 + 一个必然失败（不可达端口）的下载，仍须正常返回
        missing = os.path.join(tmpd, 'missing.jpg')
        q2 = _queue.Queue()
        q2.put({'url': 'http://127.0.0.1:1/never', 'file': 'exists.jpg', 'path': existing})
        q2.put({'url': 'http://127.0.0.1:1/never', 'file': 'missing.jpg', 'path': missing})
        dl._finished_download = 0
        dl._error_count = {}
        done2 = threading.Event()

        def _drive2():
            dl._start_and_wait(q2, 2)
            done2.set()

        threading.Thread(target=_drive2, daemon=True).start()
        ok2 = done2.wait(60)
        check('pixiv：失败重试耗尽后计数仍能追平（不卡死）', ok2,
              f'_finished_download={dl._finished_download}' if ok2 else '超时未返回')
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

    # ══════════════ 2) DownloadThread 的结束信号 ══════════════
    from services.downloader import DownloadThread
    check('DownloadThread 不再覆盖 QThread.finished',
          DownloadThread.finished is QThread.finished,
          '自定义信号已改名为 downloadFinished')
    check('DownloadThread 提供 downloadFinished 结束信号',
          hasattr(DownloadThread, 'downloadFinished'))
    import inspect as _inspect
    _src = _inspect.getsource(DownloadThread.run)
    check('DownloadThread.run 有 try/finally 保证信号必发',
          'finally' in _src and 'downloadFinished.emit()' in _src)

    # ══════════════ 3) PixmapCache 并发安全 + remove ══════════════
    from ehviewer.image_cache import PixmapCache
    pc = PixmapCache(max_count=50)
    check('PixmapCache.remove 已实现（invalidate 不再 AttributeError）',
          hasattr(pc, 'remove'))

    def _hammer(n):
        for i in range(300):
            k = f'k{(i + n) % 80}'
            pc.put(k, object())
            pc.get(k)
            pc.remove(f'k{(i * 7 + n) % 80}')

    errs = _run_in_threads(_hammer, 6)
    check('PixmapCache 6 线程并发 put/get/remove 无异常', not errs,
          f'{errs[:3]}' if errs else '')

    # ══════════════ 4) 缩略图索引并发写不产生坏 JSON ══════════════
    import services.file_library as fl
    tmp_idx = tempfile.mkdtemp(prefix='ogc_thumb_smoke_')
    idx_path = os.path.join(tmp_idx, '.thumb_index.json')
    orig_file_fn = fl._thumb_index_file
    orig_index, orig_loaded = fl._thumb_index, fl._thumb_index_loaded
    try:
        fl._thumb_index_file = lambda: idx_path
        fl._thumb_index = {}
        fl._thumb_index_loaded = True
        # 造真实存在的缩略图文件（_register_thumb 会检查 os.path.isfile）
        thumbs = []
        for i in range(20):
            p = os.path.join(tmp_idx, f't{i}.jpg')
            with open(p, 'wb') as f:
                f.write(b'x')
            thumbs.append(p)

        def _reg(n):
            for i in range(60):
                fl._register_thumb(os.path.join(tmp_idx, f'src{n}_{i}.mp4'),
                                   thumbs[(i + n) % len(thumbs)])

        errs = _run_in_threads(_reg, 6)
        valid = True
        detail = ''
        try:
            data = json.loads(open(idx_path, encoding='utf-8').read())
            valid = isinstance(data, dict) and len(data) > 0
            detail = f'索引条目={len(data)}'
        except Exception as e:      # noqa: BLE001
            valid = False
            detail = f'JSON 损坏: {e}'
        check('缩略图索引 6 线程并发写后仍为完整 JSON', valid and not errs,
              detail or f'{errs[:3]}')
    finally:
        fl._thumb_index_file = orig_file_fn
        fl._thumb_index = orig_index
        fl._thumb_index_loaded = orig_loaded
        shutil.rmtree(tmp_idx, ignore_errors=True)

    # ══════════════ 5) ehviewer/db.py 惰性连接与切库 ══════════════
    from ehviewer import db as ehdb
    tmp_db = tempfile.mkdtemp(prefix='ogc_ehdb_smoke_')
    try:
        p1 = os.path.join(tmp_db, 'a.db')
        ehdb.set_db_path(p1)
        c1 = ehdb._get_conn()
        mode = c1.execute('PRAGMA journal_mode').fetchone()[0]
        busy = c1.execute('PRAGMA busy_timeout').fetchone()[0]
        check('ehviewer 库已启用 WAL', str(mode).lower() == 'wal', f'实际={mode}')
        check('ehviewer 库已设置 busy_timeout', int(busy) >= 1000, f'实际={busy}ms')

        # 并发首次访问只应产生一个连接（原实现会重复建连并泄漏）
        ehdb._conn = None
        conns = []
        lk = threading.Lock()

        def _grab(_):
            c = ehdb._get_conn()
            with lk:
                conns.append(id(c))

        _run_in_threads(_grab, 8)
        check('并发首次访问复用同一连接（无重复建连）',
              len(set(conns)) == 1, f'不同连接数={len(set(conns))}')

        # 切库：旧连接必须被关闭，避免"写旧库/读新库"的状态分叉
        old = ehdb._get_conn()
        ehdb.set_db_path(os.path.join(tmp_db, 'b.db'))
        closed = False
        try:
            old.execute('SELECT 1')
        except Exception:
            closed = True
        check('切换数据库后旧连接已关闭', closed)
    finally:
        ehdb.set_db_path(None)
        try:
            if ehdb._conn is not None:
                ehdb._conn.close()
        except Exception:
            pass
        ehdb._conn = None
        shutil.rmtree(tmp_db, ignore_errors=True)

    # ══════════════ 6) 线程池登记表用弱引用 ══════════════
    import core.thread_guard as tg
    check('线程池登记表为 WeakSet（不再永久钉住池对象）',
          isinstance(tg._live_pools, weakref.WeakSet))

    class _Task(QRunnable):
        def run(self):
            pass

    before = len(tg._live_pools)
    pool = QThreadPool()
    pool.start(_Task())
    pool.waitForDone(3000)
    app.processEvents()
    after_add = len(tg._live_pools)
    check('QThreadPool.start 会被登记', after_add >= before + 1,
          f'{before} -> {after_add}')

    del pool
    for _ in range(20):
        gc.collect()
        app.processEvents()
        if len(tg._live_pools) <= before:
            break
        time.sleep(0.05)
    check('池对象失去引用后自动从登记表移除（原实现永久驻留）',
          len(tg._live_pools) <= before,
          f'登记表={len(tg._live_pools)}')

    # ══════════════ 汇总 ══════════════
    failed = [n for n, ok, _ in _results if not ok]
    print('-' * 60)
    if failed:
        print(f'MODULE FIXES RESULT: FAILED ({len(failed)}): {failed}')
        return 1
    print(f'MODULE FIXES RESULT: ALL PASSED ({len(_results)} checks)')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print('MODULE FIXES RESULT: FAILED (未捕获异常)')
        sys.exit(1)
