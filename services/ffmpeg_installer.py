# -*- coding: utf-8 -*-
"""ffmpeg 按需安装（下载 → 解压 → 绑定路径）
================================================

**为什么是"按需"而不是随包内置**：全项目只有一处用 ffmpeg —— 给本地视频抽第一帧
当封面缩略图（``services/file_library.py::_extract_video_frame``）。没有它程序
照常运行，只是视频显示不出封面。而一套 Windows 完整构建 150~170 MB，会让安装包
从 87 MB 涨到 140 MB 以上 —— 为一个缩略图付这个代价不划算。

所以改成：**第一次真的需要时弹窗问用户**，用户可以选择
① 让程序自己下载解压（本模块），或 ② 自己下载后在设置里填路径。

目录约定（都在**下载根目录**下，绝不写进安装目录 —— 见 core/paths.py）：

    {下载根}/ffmpeg-download/                      下载与解压都放这里
    {下载根}/ffmpeg-download/ffmpeg-release-essentials.zip
    {下载根}/ffmpeg-download/ffmpeg/bin/ffmpeg.exe  解压后的可执行文件

绑定结果写进配置项 ``ffmpeg_path``，``find_ffmpeg()`` 会**最先**读它。

本模块**不含 Qt**（保持 services 层干净）：下载线程在
``ui/widgets/ffmpeg_prompt.py`` 里。这里只提供可被工作线程调用的纯函数。
"""
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from core.config import config as CFG
from core.logger import logger

# ── 下载源（都是公开的 Windows x64 essentials 构建，约 40 MB 的 zip）──
# 主源 gyan.dev：构建维护者的官方发布页，直链、无跳转链
# 备源 GitHub Releases：主源被墙/DNS 失败时用
DOWNLOAD_URLS = (
    'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
    'https://github.com/GyanD/codexffmpeg/releases/latest/download/ffmpeg-release-essentials.zip',
)
DOWNLOAD_PAGE = 'https://www.gyan.dev/ffmpeg/builds/'
ARCHIVE_NAME = 'ffmpeg-release-essentials.zip'
DOWNLOAD_DIR_NAME = 'ffmpeg-download'
EXE_NAME = 'ffmpeg.exe'
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


# ═══════════════════════ 路径 ═══════════════════════

def download_dir() -> Path:
    """下载/解压目录：``{下载根}/ffmpeg-download``（会自动创建）。"""
    d = Path(CFG.download_root) / DOWNLOAD_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def archive_path() -> Path:
    return download_dir() / ARCHIVE_NAME


# ═══════════════════════ 校验 / 探测 ═══════════════════════

def is_valid_exe(path) -> bool:
    """这个路径看起来是不是可用的 ffmpeg。"""
    try:
        return bool(path) and os.path.isfile(str(path)) and \
            os.path.getsize(str(path)) > 0 and \
            os.path.basename(str(path)).lower().startswith('ffmpeg')
    except OSError:
        return False


def probe_version(exe_path, timeout: int = 6) -> str:
    """跑 ``ffmpeg -version`` 取首行；不可用返回空串。

    设置页的「测试」按钮用它给出确定结论 —— 光看文件存在不够，
    有的"ffmpeg.exe"其实是损坏的下载残片。
    """
    if not is_valid_exe(exe_path):
        return ''
    try:
        r = subprocess.run([str(exe_path), '-version'],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, creationflags=CREATE_NO_WINDOW)
        out = (r.stdout or b'').decode('utf-8', 'replace').strip()
        return out.splitlines()[0] if out else ''
    except Exception as e:
        logger.warning(f'[ffmpeg] 版本探测失败: {e}')
        return ''


def locate_ffmpeg(root) -> str:
    """在 ``root`` 下递归找 ffmpeg.exe（解压后目录层级不固定）。"""
    root = Path(root)
    if not root.exists():
        return ''
    # 优先浅层：解压出来的通常是 <包名>/bin/ffmpeg.exe，先按常见位置找
    for rel in ('bin', ''):
        cand = root / rel / EXE_NAME if rel else root / EXE_NAME
        if is_valid_exe(cand):
            return str(cand)
    try:
        for p in sorted(root.rglob(EXE_NAME), key=lambda x: len(x.parts)):
            if is_valid_exe(p):
                return str(p)
    except OSError:
        pass
    return ''


# ═══════════════════════ 下载 ═══════════════════════

def download_archive(progress_cb=None, cancel_cb=None, urls=None) -> Path:
    """下载 ffmpeg 压缩包到下载根目录，返回本地路径。

    * ``progress_cb(done_bytes, total_bytes)`` —— total 为 0 表示服务端没给长度
    * ``cancel_cb() -> bool`` —— 返回 True 时中止，抛 ``InterruptedError``

    已存在且大小合理的压缩包直接复用（用户重试时不必再下一次）。

    ⚠️ **刻意只用默认的证书校验**：这是要拿去执行的二进制，不做"校验失败就
    忽略证书"的降级 —— 那等于给中间人开门。TLS 失败就如实报错，让用户走
    「手动下载 + 设置里填路径」那条路（调用方负责给出提示）。
    """
    import requests

    dest = archive_path()
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        logger.info(f'[ffmpeg] 复用已下载的压缩包 {dest}')
        return dest

    tmp = dest.with_suffix('.part')
    last_err = ''
    for url in (urls or DOWNLOAD_URLS):
        try:
            logger.info(f'[ffmpeg] 开始下载 {url}')
            with requests.get(url, stream=True, timeout=(15, 60)) as r:
                r.raise_for_status()
                total = int(r.headers.get('Content-Length') or 0)
                done = 0
                with open(tmp, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=256 * 1024):
                        if cancel_cb and cancel_cb():
                            raise InterruptedError('用户取消下载')
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total)
            if tmp.stat().st_size < 1_000_000:
                raise IOError(f'下载内容过小（{tmp.stat().st_size} 字节），可能不是有效压缩包')
            os.replace(str(tmp), str(dest))
            logger.info(f'[ffmpeg] 下载完成 {dest}（{dest.stat().st_size / 1048576:.1f} MB）')
            return dest
        except InterruptedError:
            raise
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
            logger.warning(f'[ffmpeg] 下载源失败 {url} -> {last_err}')
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
    raise RuntimeError(f'所有下载源都失败。最后一次错误：{last_err}')


# ═══════════════════════ 解压 / 安装 ═══════════════════════

def _extract_zip(archive, dest) -> None:
    with zipfile.ZipFile(str(archive)) as z:
        z.extractall(str(dest))


def _extract_7z(archive, dest) -> None:
    """用随包 7z.exe 解压（用户手动下的是 .7z 时走这条）。"""
    from core import paths as _paths
    seven = _paths.bundled_7z()
    if not seven:
        raise RuntimeError('未找到内置 7z.exe，无法解压 .7z；请改用 .zip 或手动指定 ffmpeg.exe')
    r = subprocess.run([seven, 'x', '-y', f'-o{dest}', str(archive)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=600, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f'7z 解压失败（退出码 {r.returncode}）')


def extract_archive(archive, dest=None) -> Path:
    """解压压缩包到 ``dest``（默认 ``{下载根}/ffmpeg-download``）。"""
    archive = Path(archive)
    if not archive.is_file():
        raise FileNotFoundError(f'压缩包不存在: {archive}')
    dest = Path(dest) if dest else download_dir()
    dest.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()
    logger.info(f'[ffmpeg] 解压 {archive} -> {dest}')
    if suffix == '.zip':
        _extract_zip(archive, dest)
    elif suffix in ('.7z', '.xz', '.tar'):
        _extract_7z(archive, dest)
    else:
        # 后缀不认识时按 zip 试一把（有些镜像把 zip 改名了）
        try:
            _extract_zip(archive, dest)
        except Exception:
            _extract_7z(archive, dest)
    return dest


def bind(path) -> str:
    """把 ffmpeg 路径写进配置并让查找缓存失效。返回规范化后的路径。"""
    from services import file_library as _FL
    p = str(Path(path))
    CFG['ffmpeg_path'] = p
    try:
        _FL.reset_ffmpeg_cache()
    except Exception:
        pass
    logger.info(f'[ffmpeg] 已绑定路径: {p}')
    return p


def unbind() -> None:
    """清掉配置里的路径（设置页的「清除」）。"""
    from services import file_library as _FL
    CFG['ffmpeg_path'] = ''
    try:
        _FL.reset_ffmpeg_cache()
    except Exception:
        pass


def find_existing_archive() -> Path:
    """在下载目录里找现成的压缩包（用户自己放进去的也能认）。"""
    d = download_dir()
    for pat in ('*.zip', '*.7z'):
        for p in sorted(d.glob(pat)):
            if p.is_file() and p.stat().st_size > 1_000_000:
                return p
    return Path()


def install_from_archive(archive) -> str:
    """解压 → 定位 → 绑定，一条龙。返回绑定的 ffmpeg 路径。"""
    dest = download_dir()
    extract_archive(archive, dest)
    exe = locate_ffmpeg(dest)
    if not exe:
        raise RuntimeError(
            f'解压后在 {dest} 里没找到 {EXE_NAME}，压缩包可能不完整。')
    return bind(exe)


def install_downloaded(progress_cb=None, cancel_cb=None) -> str:
    """下载 + 解压 + 绑定（工作线程里调用）。返回绑定的 ffmpeg 路径。"""
    archive = download_archive(progress_cb=progress_cb, cancel_cb=cancel_cb)
    return install_from_archive(archive)


def install_from_exe(exe_path) -> str:
    """用户直接指定一个现成的 ffmpeg.exe（或含它的目录）。"""
    p = Path(str(exe_path))
    if p.is_dir():
        found = locate_ffmpeg(p)
        if not found:
            raise RuntimeError(f'该目录下没有找到 {EXE_NAME}')
        p = Path(found)
    if not is_valid_exe(p):
        raise RuntimeError(f'这不是可用的 {EXE_NAME}：{p}')
    return bind(p)


def open_folder(path) -> bool:
    """在资源管理器里打开某个文件所在目录（下载成功后给用户看）。"""
    try:
        p = Path(str(path))
        target = p if p.is_dir() else p.parent
        if target.exists():
            os.startfile(str(target))       # noqa: S606 - Windows 专用，按需求打开
            return True
    except Exception as e:
        logger.warning(f'[ffmpeg] 打开目录失败: {e}')
    return False


def cleanup_archive() -> None:
    """解压成功后删掉压缩包（约 40 MB，留着没用）。"""
    try:
        a = archive_path()
        if a.is_file():
            a.unlink()
    except OSError:
        pass


def disk_usage_hint() -> str:
    """给弹窗用的一句话体积说明。"""
    return '约 40 MB（解压后约 130 MB，其中只需要 ffmpeg.exe）'


def free_space_mb(path=None) -> int:
    """目标盘剩余空间（MB），拿不到返回 -1。"""
    try:
        target = Path(path) if path else download_dir()
        # 目录可能还不存在（下载根在别的盘），往上找到存在的父目录
        while not target.exists() and target != target.parent:
            target = target.parent
        return int(shutil.disk_usage(str(target)).free / 1048576)
    except Exception:
        return -1
