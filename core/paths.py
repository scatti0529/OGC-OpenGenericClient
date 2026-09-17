# -*- coding: utf-8 -*-
"""应用路径：只读的程序目录 vs 可写的用户数据目录
==================================================
本程序有两种运行形态，路径策略必须不同 —— 这是能打包成 exe 的前提：

1. **源码运行**（``python main.py``）：一切都在项目目录内，与历史行为完全一致，
   开发与冒烟测试（把 data/ 落到 ``scripts/data`` 做隔离）不受影响。
2. **冻结运行**（PyInstaller 打的 exe）：程序本体在安装目录（用户可能装在
   Program Files 或 %LOCALAPPDATA%\\Programs，**通常只读**）。
   程序**绝不能**往安装目录写数据，否则普通用户一启动就因权限失败。
   用户数据一律落 ``%APPDATA%``。

三类路径：

=============  ================================  ============================================
RESOURCE       只读，随程序分发                  resources/ · ehviewer/data/ · data/7Z/ · ffmpeg
USER_DIR       可写，用户数据                    config · ogc_users.db · 索引 · avatars · logs
DOWNLOAD       用户自选（可换盘）                ``*-download/`` · ``.cache/`` · 工作区标记
=============  ================================  ============================================

⚠️ PyInstaller 6.x 的 onedir 布局把随包数据放在 ``_internal/`` 下，因此资源必须用
``sys._MEIPASS`` 定位，**不能**用 exe 所在目录 —— 否则 exe 一跑就找不到 resources/。
"""
import os
import sys
from pathlib import Path

# 应用标识：决定 %APPDATA% 下的目录名，安装器/卸载器也引用它
APP_NAME = 'OGC-OpenGenericClient'


def is_frozen() -> bool:
    """是否运行在打包后的 exe 中。"""
    return bool(getattr(sys, 'frozen', False))


def program_dir() -> Path:
    """程序根目录（兼容历史语义）。

    * 冻结：exe 所在目录（= 安装目录）
    * 源码：``sys.argv[0]`` 的父目录 —— **刻意保留这个历史行为**：
      ``python scripts/xxx.py`` 会解析成 ``scripts/``，测试数据因此落在
      ``scripts/data``，与真实 ``data/`` 隔离。**不要改成基于 __file__**，
      否则所有冒烟测试会开始读写真实用户数据。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(sys.argv[0]).resolve().parent


def resource_root() -> Path:
    """只读资源根目录（resources/、ehviewer/data/、data/7Z/、ffmpeg 都在其下）。

    * 冻结：``sys._MEIPASS``（onedir 下即 ``<安装目录>/_internal``）
    * 源码：项目根目录（由本文件位置推导，与 sys.argv[0] 无关 —— 历史上
      这正是 ``core.resource_paths.PROJECT_ROOT`` 的做法）
    """
    if is_frozen():
        return Path(getattr(sys, '_MEIPASS', sys.executable)).resolve()
    return Path(__file__).resolve().parent.parent


def install_dir() -> Path:
    """安装目录（仅冻结模式有意义）。用于定位 ``unins000.exe`` 等。"""
    return program_dir() if is_frozen() else Path()


def user_dir() -> Path:
    """可写的用户数据目录。

    * 冻结：``%APPDATA%\\OGC-OpenGenericClient``（每用户独立，装到 Program Files 也能写）
    * 源码：``<程序根>/data``（保持原样；脚本模式下即 ``scripts/data``）
    """
    if is_frozen():
        # 数据放 **APPDATA（Roaming）**，与安装范围的选择保持一致。
        # 之所以现在可以放 Roaming：大体积缓存（.cache/）已经移到下载根目录，
        # 这里只剩配置、索引、账号库、头像、日志 —— 合计几 MB，
        # 漫游同步不会成为负担。
        # ⚠️ 若将来又把大文件（缓存/媒体）塞回 USER_DIR，必须改回 LOCALAPPDATA，
        # 否则会跟着漫游配置一起被同步。
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return Path(base) / APP_NAME
    return program_dir() / 'data'


def user_log_dir() -> Path:
    if is_frozen():
        return user_dir() / 'logs'
    return program_dir() / 'logs'


def user_music_dir() -> Path:
    if is_frozen():
        return user_dir() / 'music'
    return program_dir() / 'music'


def bundled(*parts) -> str:
    """拼接随程序分发的只读资源路径。"""
    return str(resource_root().joinpath(*parts))


def bundled_7z() -> str:
    """内置 7z.exe 的路径。

    注意：``data/7Z`` 是**随程序分发的只读资产**，却历史地放在 data/ 这个
    「用户数据目录」里。装了 Program Files 后 data/ 变成 %APPDATA%，所以这里
    先找随包资源，再退回用户目录，两条路都保留以便源码模式继续可用。
    """
    for cand in (resource_root() / 'data' / '7Z' / '7z.exe',
                 user_dir() / '7Z' / '7z.exe'):
        try:
            if cand.is_file():
                return str(cand)
        except OSError:
            pass
    return ''


def bundled_ffmpeg() -> str:
    """内置 ffmpeg 的路径；未内置时返回空串（调用方自行退回外部查找）。"""
    exe = resource_root() / 'ffmpeg' / 'ffmpeg.exe'
    try:
        return str(exe) if exe.is_file() else ''
    except OSError:
        return ''


def gui_config_path() -> str:
    """qfluentwidgets 的 GUI 配置文件路径。

    * 源码模式：直接用项目内 ``resources/config/config.json``（零行为变化）
    * 冻结模式：安装目录只读，必须落到 USER_DIR；首次用随包默认值播种。
    """
    src = resource_root() / 'resources' / 'config' / 'config.json'
    if not is_frozen():
        return str(src)
    target = user_dir() / 'gui-config.json'
    if not target.exists():
        try:
            if src.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
        except OSError:
            pass
    return str(target) if target.exists() else str(src)


def ensure_user_dirs() -> Path:
    """创建用户数据子目录（幂等）。首次启动与设置变更后都可调用。"""
    d = user_dir()
    for sub in ('', 'logs', 'music', 'avatars', 'dir_cache', 'offline_index'):
        try:
            (d / sub).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return d


def describe() -> str:
    """给日志用的路径摘要（排查"数据写哪去了"必看）。"""
    return (f"frozen={is_frozen()} program={program_dir()} "
            f"resource={resource_root()} user={user_dir()}")
