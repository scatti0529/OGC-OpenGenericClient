# -*- coding: utf-8 -*-
"""并发与崩溃兜底回归验证

验证本次修复的四个点，全部用"真实运行 + 断言"证明，而不是靠阅读代码判断：

1. ``core.crash_guard``：Qt 槽函数里未捕获的异常**不再**触发 PyQt5 的
   qFatal()->abort() 闪退，而是被记录后继续运行（脚本能跑到最后即为证明）。
2. ``core.thread_guard``：线程登记表不再"只增不减"，跑完 40 个线程后
   登记表规模保持有界（原实现会线性增长到 40+）。
3. ``core.config``：10 个线程并发保存配置后，config.json 仍是**完整合法 JSON**
   （原实现会被并发覆盖成半截文件）。
4. ``core.database``：启用 WAL + busy_timeout 后，8 线程并发写不再出现
   ``database is locked``。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_concurrency_guard.py
"""
import json
import os
import sys
import tempfile
import threading
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
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QThread, QTimer

    app = QApplication.instance() or QApplication(sys.argv)

    # ══════════════ 1) 槽函数异常不再 abort 闪退 ══════════════
    from core import crash_guard
    crash_guard.install()

    check('crash_guard 已接管 sys.excepthook',
          sys.excepthook is not sys.__excepthook__,
          'sys.excepthook 已被替换（PyQt5 因此不再调用 qFatal）')
    check('crash_guard 已接管 threading.excepthook',
          threading.excepthook is not threading.__excepthook__,
          '普通线程异常将写入错误日志')

    state = {'raised': False, 'reached': False}

    def _boom():
        state['raised'] = True
        raise RuntimeError('故意在 Qt 槽函数里抛异常（验证不再 abort 闪退）')

    def _after():
        state['reached'] = True
        app.quit()

    # 若 PyQt5 的 qFatal 行为仍生效，进程会直接 abort，_after 永远不会执行
    QTimer.singleShot(0, _boom)
    QTimer.singleShot(80, _after)
    app.exec_()
    check('槽函数抛异常后进程存活并继续执行',
          state['raised'] and state['reached'],
          f"raised={state['raised']} reached={state['reached']}")
    check('faulthandler 已开启（crash.log）',
          bool(crash_guard.crash_log_path()),
          crash_guard.crash_log_path())
    check('可主动转储全部线程栈（卡死诊断用）',
          crash_guard.dump_all_thread_stacks('smoke 自检'),
          '已写入 crash.log')

    # ══════════════ 2) 线程登记表保持有界 ══════════════
    import core.thread_guard as tg

    class _Worker(QThread):
        def run(self):
            self.msleep(4)

    before = tg.tracked_count()
    for _ in range(40):
        w = _Worker()
        w.start()
        w.wait(3000)          # 不保留引用：保活完全依赖 thread_guard 的登记表
    # finished 走队列连接回到主线程，再延后一拍回收，这里推进事件循环
    for _ in range(20):
        app.processEvents()
        QThread.msleep(5)
    after = tg.tracked_count()
    check('40 个线程跑完后登记表未线性增长',
          after - before < 10,
          f'登记表 {before} -> {after}（原实现会增长到 ~{before + 40}）')

    # ══════════════ 3) 配置并发保存不产生半截 JSON ══════════════
    from core.config import ConfigManager
    cfg = ConfigManager()
    cfg_file = cfg.cfg_file
    backup = cfg_file.read_bytes() if cfg_file.exists() else None
    try:
        errors = []

        def _writer(n):
            for i in range(40):
                try:
                    cfg[f'__smoke_key_{n}'] = i
                except Exception as e:      # noqa: BLE001
                    errors.append(f'{type(e).__name__}: {e}')

        ts = [threading.Thread(target=_writer, args=(n,)) for n in range(10)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(60)
        ok_parse = True
        detail = ''
        try:
            data = json.loads(cfg_file.read_text(encoding='utf-8'))
            missing = [n for n in range(10) if f'__smoke_key_{n}' not in data]
            ok_parse = not missing
            detail = f'键齐全={not missing}'
        except Exception as e:              # noqa: BLE001
            ok_parse = False
            detail = f'JSON 解析失败: {e}'
        check('10 线程并发保存后 config.json 仍为完整 JSON',
              ok_parse and not errors, detail or f'errors={errors[:3]}')

        # 清理测试键并还原用户原文件
        for n in range(10):
            cfg.cfg.pop(f'__smoke_key_{n}', None)
    finally:
        if backup is not None:
            cfg_file.write_bytes(backup)
        elif cfg_file.exists():
            cfg_file.unlink()

    # ══════════════ 4) SQLite 并发写不再 locked ══════════════
    import core.database as db
    tmpdir = tempfile.mkdtemp(prefix='ogc_smoke_db_')
    orig_path = db.DB_PATH
    try:
        db.DB_PATH = os.path.join(tmpdir, 'smoke.db')
        check('启用 WAL 模式成功', db._enable_wal_mode())
        c = db.get_db_connection()
        mode = c.execute('PRAGMA journal_mode').fetchone()[0]
        busy = c.execute('PRAGMA busy_timeout').fetchone()[0]
        c.execute('CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)')
        c.commit()
        c.close()
        check('journal_mode=wal', str(mode).lower() == 'wal', f'实际={mode}')
        check('busy_timeout 已生效', int(busy) >= 1000, f'实际={busy}ms')

        failures = []

        def _db_writer(n):
            for i in range(40):
                try:
                    conn = db.get_db_connection()
                    try:
                        conn.execute('INSERT INTO t (v) VALUES (?)', (f'{n}-{i}',))
                        conn.commit()
                    finally:
                        conn.close()
                except Exception as e:      # noqa: BLE001
                    failures.append(f'{type(e).__name__}: {e}')

        ts = [threading.Thread(target=_db_writer, args=(n,)) for n in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(120)
        c = db.get_db_connection()
        rows = c.execute('SELECT COUNT(*) FROM t').fetchone()[0]
        c.close()
        check('8 线程并发写 320 行全部成功',
              not failures and rows == 320,
              f'rows={rows} failures={failures[:3]}')
    finally:
        db.DB_PATH = orig_path
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    # ══════════════ 汇总 ══════════════
    failed = [n for n, ok, _ in _results if not ok]
    print('-' * 60)
    if failed:
        print(f'CONCURRENCY GUARD RESULT: FAILED ({len(failed)}): {failed}')
        return 1
    print(f'CONCURRENCY GUARD RESULT: ALL PASSED ({len(_results)} checks)')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print('CONCURRENCY GUARD RESULT: FAILED (未捕获异常)')
        sys.exit(1)
