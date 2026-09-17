# -*- coding: utf-8 -*-
"""Windows 外壳集成：单实例互斥、注册表登记、卸载入口

三个职责都与「安装/卸载安全」直接相关：

1. **单实例互斥量**
   安装器/卸载器通过 Inno 的 ``AppMutex`` 判断"程序是不是正在运行"。
   没有它，卸载会在程序占用文件的情况下进行，留下半个程序；
   同时它也顺带避免两个实例同时写同一个 SQLite 库与 config.json。

2. **注册表登记**（``HKCU\\Software\\OGC-OpenGenericClient``）
   写入 ``InstallDir`` / ``Uninstaller`` / ``DownloadRoot``。
   卸载器**只装了一个 exe**，没法 import 本项目的 Python 代码，只能靠注册表
   知道"下载根目录在哪"，才能问用户是否清理 ``.cache``。

3. **定位卸载器**
   程序内的「卸载」按钮据此找到 ``unins000.exe``；找不到（例如直接跑 exe、
   没经过安装器）就隐藏该按钮 —— 而不是给用户一个点了没反应的按钮。

所有操作都容忍失败：注册表不可写、互斥量创建失败都不应影响程序启动。
"""
import os
import subprocess
import sys

REG_PATH = r'Software\OGC-OpenGenericClient'
MUTEX_NAME = 'OGC-OpenGenericClient-SingleInstance'

# 互斥量句柄必须由进程持有到退出，否则会被 GC 掉、互斥随之释放
_mutex_handle = None
_already_running = False


# ═══════════════════════════════════════════════════════════
#  单实例互斥
# ═══════════════════════════════════════════════════════════

def acquire_single_instance() -> bool:
    """获取单实例互斥量。

    Returns:
        True  —— 本进程是唯一实例（或系统不支持检查，按放行处理）
        False —— 已有实例在运行
    """
    global _mutex_handle, _already_running
    if _mutex_handle is not None:
        return not _already_running
    try:
        import ctypes
        from ctypes import wintypes

        ERROR_ALREADY_EXISTS = 183
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                          wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        err = ctypes.get_last_error()
        _mutex_handle = handle
        _already_running = (err == ERROR_ALREADY_EXISTS)
        return not _already_running
    except Exception:
        # 拿不到就用放行策略：宁可允许多开，也不要因为 API 异常就打不开程序
        return True


def already_running() -> bool:
    return _already_running


def warn_already_running() -> None:
    """用原生 MessageBox 提示（此时 Qt 可能还没初始化）。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            'OGC 已经在运行了。\n\n'
            '同时打开两个实例会争抢同一个数据库与配置文件，可能导致设置丢失，'
            '因此这里只允许运行一个。\n\n请切换到已打开的窗口。',
            'OGC-OpenGenericClient', 0x40)   # MB_ICONINFORMATION
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  注册表登记 / 卸载器定位
# ═══════════════════════════════════════════════════════════

def register_paths() -> bool:
    """把安装目录、卸载器路径、下载根目录写入 HKCU。

    卸载器是独立编译的 exe，读不到本项目的 Python 代码，只能靠这些值
    才能知道"下载根目录在哪"并询问是否清理 .cache。
    """
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        from core.config import config as CFG
        from core import paths as _paths

        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_PATH, 0,
                                 winreg.KEY_SET_VALUE)
        try:
            def _set(name, value):
                if value:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))

            _set('DownloadRoot', CFG.download_root)
            _set('UserDir', str(CFG.data))
            _set('AppVersion', str(CFG.get('version', '')))
            _set('Frozen', '1' if _paths.is_frozen() else '0')
            inst = _paths.install_dir()
            if inst:
                _set('InstallDir', str(inst))
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _reg_get(name: str) -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            v, _t = winreg.QueryValueEx(key, name)
            return str(v or '')
    except Exception:
        return ''


def uninstaller_path() -> str:
    """定位 ``unins000.exe``；找不到返回空串。

    查找顺序：
      1. 注册表里安装器写的 ``Uninstaller``（最准，包含用户自选安装目录）
      2. 安装目录下的 ``unins000.exe``（默认名）
      3. 安装目录下任意 ``unins*.exe``（用户可能改过名/多版本共存）
    """
    from core import paths as _paths

    p = _reg_get('Uninstaller')
    if p and os.path.isfile(p):
        return p
    inst = _paths.install_dir()
    if not inst:
        return ''
    default = os.path.join(str(inst), 'unins000.exe')
    if os.path.isfile(default):
        return default
    try:
        for name in os.listdir(str(inst)):
            low = name.lower()
            if low.startswith('unins') and low.endswith('.exe'):
                return os.path.join(str(inst), name)
    except OSError:
        pass
    return ''


def is_installed_copy() -> bool:
    """当前是否由安装器装出来的副本（决定是否显示「卸载」入口）。"""
    return bool(uninstaller_path())


def launch_uninstaller(silent: bool = False) -> tuple:
    """启动卸载器。

    默认**交互式**启动：让用户看到卸载器自己的询问（是否清理 .cache、
    是否删除用户数据），而不是由程序替他决定。

    Returns:
        (ok, message)
    """
    path = uninstaller_path()
    if not path:
        return False, '未找到卸载程序（可能是直接运行 exe，而非通过安装器安装）'
    args = [path]
    if silent:
        args.append('/SILENT')
    args.append('/NORESTART')
    try:
        # 卸载器需要以自身目录为工作目录，否则找不到 unins000.dat
        subprocess.Popen(args, cwd=os.path.dirname(path), close_fds=True)
        return True, '卸载程序已启动'
    except Exception as e:
        return False, f'启动卸载程序失败：{e}'


def install_summary() -> dict:
    """给设置页展示的安装信息。"""
    from core import paths as _paths
    return {
        'frozen': _paths.is_frozen(),
        'install_dir': str(_paths.install_dir() or ''),
        'uninstaller': uninstaller_path(),
        'installed': is_installed_copy(),
        'registry': REG_PATH,
    }
