# -*- coding: utf-8 -*-
"""
全局崩溃与未捕获异常兜底
========================
本模块解决三类"无日志闪退"，是运行时兜底的第一道防线：

1. **槽函数（Slot）内未捕获的 Python 异常**
   PyQt5 >= 5.5 在异常逃逸出槽函数时会调用 ``qFatal()``，默认行为即 ``abort()``：
   进程立刻闪退，且**不产生任何 Python 侧日志**。安装自定义 ``sys.excepthook``
   后 PyQt5 改为调用该钩子，异常被完整记录，进程不再中止。（已确认本项目
   PyQt5 5.15.11，该行为生效。）

2. **``threading.Thread`` 内未捕获的异常**（Python 3.8+ 走 ``threading.excepthook``）
   默认只写 stderr，GUI 程序通常看不到 stderr，表现为线程静默死亡、
   界面永久"加载中"、或信号永不发出导致卡死。

3. **C 层硬崩溃（段错误 / abort）**
   ``faulthandler`` 能把崩溃瞬间**所有线程**的 Python 调用栈写入
   ``logs/crash.log``，供事后定位。注意：C 层崩溃后进程状态不可信，
   兜底只能"记录现场"，不能保证安全恢复，仍以重启为准。

用法（必须在创建 QApplication 之后、进入事件循环之前尽早安装）::

    from core import crash_guard
    crash_guard.install()

设计约束：钩子内部**绝不允许再抛异常**（否则会形成异常递归），
因此所有写入路径都各自 try/except 兜住。
"""
import faulthandler
import sys
import threading
import traceback
from pathlib import Path

# 安装状态与保持引用的文件对象（faulthandler 需要文件对象长期存活）
_installed = False
_crash_file = None
_crash_log_path = None

# 原始钩子：KeyboardInterrupt 等需要保持默认行为时回退给它
_orig_excepthook = sys.excepthook
_orig_threading_excepthook = getattr(threading, 'excepthook', None)

# 兜底钩子自身重入保护：钩子内部再出异常时直接放弃，避免无限递归
_in_hook = threading.local()


def _default_log_dir() -> Path:
    """默认日志目录：项目根目录下的 logs/（与 core/logger 的默认值一致）。"""
    return Path(__file__).resolve().parent.parent / 'logs'


def _write(text: str):
    """把兜底信息写入错误日志与 crash.log，并回显 stderr。

    三条路径互相独立：任何一条失败都不影响其余，且**不依赖日志系统已初始化**——
    若 core.logger 尚未 initialize（例如启动早期就抛异常），记录仍会落到
    crash.log，不会出现"闪退了却什么都没有"。
    """
    # 1) 独立文件通道（安装时即已打开，最可靠）
    if _crash_file is not None:
        try:
            _crash_file.write(f"\n{text}\n")
            _crash_file.flush()
        except Exception:
            pass
    # 2) 统一错误日志
    try:
        from core.logger import logger
        logger.error(text)
    except Exception:
        pass
    # 3) stderr 回显
    try:
        sys.stderr.write(text + '\n')
        sys.stderr.flush()
    except Exception:
        pass


def _handle_uncaught(exc_type, exc_value, exc_tb):
    """``sys.excepthook``：拦截逃逸到 Qt 事件循环/主线程的异常。

    关键作用：不让 PyQt5 走 ``qFatal()``，把"闪退"降级为"记录 + 继续运行"。
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # Ctrl+C 保持默认行为，不被兜底吞掉
        try:
            _orig_excepthook(exc_type, exc_value, exc_tb)
        except Exception:
            pass
        return

    if getattr(_in_hook, 'busy', False):
        # 钩子内部又抛异常：只回显，绝不递归
        try:
            sys.stderr.write(''.join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        except Exception:
            pass
        return

    _in_hook.busy = True
    try:
        text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write(f"[未捕获异常] 线程={threading.current_thread().name} "
               f"（已拦截，进程继续运行，请据此定位）\n{text}")
    finally:
        _in_hook.busy = False


def _handle_thread_uncaught(args):
    """``threading.excepthook``：拦截普通 Python 线程里的未捕获异常。"""
    if issubclass(args.exc_type, SystemExit):
        return
    try:
        name = args.thread.name if args.thread is not None else '?'
        text = ''.join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))
        _write(f"[线程未捕获异常] 线程={name}（该线程已终止，"
               f"若界面在等它的结果则表现为卡死）\n{text}")
    except Exception:
        pass


def _enable_faulthandler(log_dir: Path) -> bool:
    """开启 faulthandler：硬崩溃（段错误/abort）时把所有线程栈写入 crash.log。"""
    global _crash_file, _crash_log_path
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / 'crash.log'
        _crash_file = open(path, 'a', encoding='utf-8', buffering=1)
        _crash_log_path = path
        # all_threads=True：崩溃时输出全部线程的栈，便于判断是否死锁/主线程阻塞
        faulthandler.enable(file=_crash_file, all_threads=True)
        return True
    except Exception:
        _crash_file = None
        _crash_log_path = None
        return False


def install(log_dir=None) -> bool:
    """安装全局兜底钩子。幂等，可重复调用。

    Args:
        log_dir: crash.log 所在目录；默认项目根目录下 ``logs/``。

    Returns:
        是否完成安装（True 表示钩子已就位）。
    """
    global _installed
    if _installed:
        return True

    try:
        sys.excepthook = _handle_uncaught
        if _orig_threading_excepthook is not None:
            threading.excepthook = _handle_thread_uncaught
        _installed = True
    except Exception:
        return False

    # faulthandler 失败不影响主要兜底能力（槽异常拦截），仅少一份硬崩溃现场
    ok_fh = _enable_faulthandler(Path(log_dir) if log_dir else _default_log_dir())
    try:
        from core.logger import logger
        logger.info(
            "已安装全局异常兜底（槽异常不再触发 qFatal 闪退；"
            f"faulthandler={'已开启: ' + str(_crash_log_path) if ok_fh else '未开启'}）"
        )
    except Exception:
        pass
    return True


def dump_all_thread_stacks(reason: str = '') -> bool:
    """把所有存活线程的 Python 栈写入 crash.log（看门狗/卡死诊断用）。

    用于"主线程疑似卡死"这类无法复现的问题：在超时点调用本函数即可留下
    "当时每个线程在干什么"的现场，而不必等进程崩溃。

    Returns:
        是否成功写出。
    """
    if _crash_file is None:
        return False
    try:
        _crash_file.write(
            f"\n===== 线程栈转储 {reason} =====\n")
        _crash_file.flush()
        faulthandler.dump_traceback(file=_crash_file, all_threads=True)
        _crash_file.write("===== 转储结束 =====\n")
        _crash_file.flush()
        return True
    except Exception:
        return False


def crash_log_path() -> str:
    """返回 crash.log 路径（未开启时返回空串）。"""
    return str(_crash_log_path) if _crash_log_path else ''


def is_installed() -> bool:
    """兜底钩子是否已安装。"""
    return _installed
