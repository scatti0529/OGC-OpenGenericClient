# -*- coding: utf-8 -*-
"""
下载文件库扫描服务
==================
扫描配置的下载根目录（video_download_root），提供：
- 平台目录列表（顶级文件夹）
- 指定目录下的子目录 / 文件列表（带分类）
- 文件类型分类（视频 / 音频 / 图片 / 压缩包 / 其他）

供 Folder library 页面检索与展示。
"""
import os
import re
import json
import time
import threading
from pathlib import Path

from core.config import config as CFG

# 封面加载全局并发限制（避免大量线程同时读盘/spawn ffmpeg 导致卡顿）
COVER_LOAD_SEM = threading.Semaphore(4)
VIDEO_COVER_SEM = threading.Semaphore(2)

# ── 缩略图索引（JSON：源文件绝对路径 -> 缩略图缓存路径） ──
_thumb_index = {}
_thumb_index_loaded = False
# 用 RLock：_register_thumb 需要在持锁状态下复用会再次取锁的 load_thumb_index()
_thumb_index_lock = threading.RLock()


def _thumb_index_file() -> str:
    return os.path.join(get_download_root(), '.thumb_index.json')


def load_thumb_index() -> dict:
    """加载缩略图索引（带内存缓存）"""
    global _thumb_index, _thumb_index_loaded
    with _thumb_index_lock:
        if _thumb_index_loaded:
            return _thumb_index
        _thumb_index_loaded = True
        try:
            if os.path.isfile(_thumb_index_file()):
                with open(_thumb_index_file(), 'r', encoding='utf-8') as fp:
                    _thumb_index = json.load(fp)
        except Exception:
            _thumb_index = {}
        return _thumb_index


def save_thumb_index():
    global _thumb_index
    with _thumb_index_lock:
        try:
            with open(_thumb_index_file(), 'w', encoding='utf-8') as fp:
                json.dump(_thumb_index, fp, ensure_ascii=False)
        except Exception:
            pass


def get_cached_thumb(source_path: str) -> str:
    """返回源文件对应的已缓存缩略图路径（无则空串）"""
    if not source_path:
        return ''
    key = os.path.abspath(source_path)
    p = load_thumb_index().get(key, '')
    if p and os.path.isfile(p):
        return p
    return ''


def _register_thumb(source_path: str, thumb_path: str):
    """将源文件与缩略图路径写入索引（异常安全，不干扰主流程）。

    关键：改共享 dict 与写盘必须**在同一把锁内**完成。
    ``load_thumb_index()`` 返回的是模块级共享 dict 本身，而
    ``save_thumb_index()`` 会在锁内 ``json.dump`` 迭代它；
    原实现在锁外 ``load_thumb_index()[key] = ...``，当多个扫描/下载线程
    （folder_library_page 的扫描线程、comic_offline、jmcomic_service、
    easycopy/downloader）并发写入时，迭代中字典被改会抛
    "dictionary changed size during iteration"，被 except 吞掉后
    整个索引写盘失败 —— 结果是缩略图反复重算、条目永久丢失。
    """
    try:
        if not source_path or not thumb_path or not os.path.isfile(thumb_path):
            return
        key = os.path.abspath(source_path)
        value = os.path.abspath(thumb_path)
        with _thumb_index_lock:      # RLock：save_thumb_index 会再次取同一把锁
            load_thumb_index()[key] = value
            save_thumb_index()
    except Exception:
        pass


# ── 文件类型分类 ──
VIDEO_EXTS = {'.mp4', '.mkv', '.webm', '.flv', '.avi', '.mov', '.m4v', '.ts', '.wmv'}
AUDIO_EXTS = {'.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg', '.wma', '.ape'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff'}
ARCHIVE_EXTS = {'.zip', '.rar', '.7z', '.cbz', '.cbr', '.tar', '.gz', '.bz2'}
TXT_EXTS = {'.txt', '.md', '.text', '.log'}

KIND_LABELS = {
    'video': '🎬 视频',
    'audio': '🎵 音乐',
    'image': '🖼 图片',
    'archive': '📦 压缩包',
    'txt': '📝 文本',
    'dir': '📁 文件夹',
    'other': '📄 文件',
}

# 封面查找优先的图片扩展名（排除动图 gif 避免卡顿）
COVER_EXTS = ('.jpg', '.jpeg', '.png', '.webp')
_COVER_NAMES = ('cover', 'poster', 'thumb', 'folder', 'preview', '封面')


def get_download_root() -> str:
    """获取下载根目录（设置里可改，不存在则回退默认）"""
    custom = CFG.get('video_download_root', '')
    if custom and os.path.isdir(custom):
        return custom
    default = os.path.join(str(CFG.root), 'data')
    return default if os.path.isdir(default) else str(CFG.root)


def classify_ext(ext: str) -> str:
    """按扩展名分类（ext 需带点的小写扩展名）"""
    ext = (ext or '').lower()
    if ext in VIDEO_EXTS:
        return 'video'
    if ext in AUDIO_EXTS:
        return 'audio'
    if ext in IMAGE_EXTS:
        return 'image'
    if ext in ARCHIVE_EXTS:
        return 'archive'
    if ext in TXT_EXTS:
        return 'txt'
    return 'other'


def is_media_ext(ext: str) -> bool:
    return classify_ext(ext) in ('video', 'audio', 'image')


def _entry(path: str):
    """构造单个文件/目录条目"""
    p = Path(path)
    name = p.name
    is_dir = p.is_dir()
    if is_dir:
        kind = 'dir'
        ext = ''
        size = 0
    else:
        ext = p.suffix.lower()
        kind = classify_ext(ext)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0
    return {
        'name': name,
        'path': str(p),
        'is_dir': is_dir,
        'ext': ext,
        'kind': kind,
        'size': size,
        'mtime': mtime,
        'label': KIND_LABELS.get(kind, '📄 文件'),
    }


def list_platforms(root: str = None) -> list:
    """列出下载根目录下的顶级目录（平台文件夹）"""
    root = root or get_download_root()
    if not root or not os.path.isdir(root):
        return []
    items = []
    try:
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if os.path.isdir(full):
                items.append(_entry(full))
    except OSError:
        pass
    return items


def list_directory(path: str) -> dict:
    """列出一个目录下的内容（子目录排前，文件按类型/名称排序）"""
    if not path or not os.path.isdir(path):
        return {'path': path, 'parent': None, 'dirs': [], 'files': []}

    parent = os.path.dirname(os.path.abspath(path))
    if parent == os.path.abspath(path):
        parent = None

    dirs = []
    files = []
    try:
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                dirs.append(_entry(full))
            else:
                files.append(_entry(full))
    except OSError:
        pass

    # 目录按名称（数字感知）排序
    dirs.sort(key=lambda e: _natural_key(e['name']))
    # 文件：按分类优先级 + 名称排序
    kind_order = {'video': 0, 'image': 1, 'audio': 2, 'archive': 3, 'other': 4}
    files.sort(key=lambda e: (kind_order.get(e['kind'], 5), _natural_key(e['name'])))

    return {'path': os.path.abspath(path), 'parent': parent, 'dirs': dirs, 'files': files}


# ── 目录扫描结果缓存（JSON，避免每次打开都全量扫描） ──
def get_dir_cache_dir() -> str:
    d = os.path.join(get_download_root(), '.dir_cache')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _dir_cache_file(path: str) -> str:
    import hashlib
    digest = hashlib.md5(os.path.abspath(path).encode('utf-8')).hexdigest()[:24]
    return os.path.join(get_dir_cache_dir(), f"{digest}.json")


def _dir_mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0


def load_dir_cache(path: str) -> dict:
    """读取目录列表缓存；目录 mtime 变化则返回 None"""
    if not path or not os.path.isdir(path):
        return None
    f = _dir_cache_file(path)
    try:
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        if data.get('mtime') != _dir_mtime(path):
            return None
        return data
    except Exception:
        return None


def save_dir_cache(path: str, data: dict):
    if not path or not os.path.isdir(path):
        return
    f = _dir_cache_file(path)
    try:
        data = dict(data)
        data['mtime'] = _dir_mtime(path)
        with open(f, 'w', encoding='utf-8') as fp:
            json.dump(data, fp, ensure_ascii=False)
    except Exception:
        pass


def list_directory_cached(path: str) -> dict:
    """带缓存列目录：mtime 未变则直接用缓存，否则重新扫描并保存"""
    cached = load_dir_cache(path)
    if cached is not None:
        return cached
    data = list_directory(path)
    save_dir_cache(path, data)
    return data


def list_images_in_dir(path: str, recursive: bool = False) -> list:
    """列出目录内所有图片（用于漫画/图集连续浏览）

    recursive=True 时递归扫描子目录，用于漫画作品根目录。
    """
    if not path or not os.path.isdir(path):
        return []
    images = []

    def _collect(d):
        try:
            entries = sorted(os.listdir(d), key=_natural_key)
            for name in entries:
                full = os.path.join(d, name)
                if os.path.isdir(full):
                    if recursive:
                        _collect(full)
                else:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in IMAGE_EXTS:
                        images.append(full)
        except OSError:
            pass

    _collect(path)
    images.sort(key=lambda p: _natural_key(os.path.relpath(p, path)))
    return images


def has_image_subdirs(path: str) -> bool:
    """判断目录内第一级子目录是否含有图片（识别漫画章节结构）"""
    if not path or not os.path.isdir(path):
        return False
    try:
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                subs = list_images_in_dir(full, recursive=False)
                if subs:
                    return True
    except OSError:
        pass
    return False


def _natural_key(s: str):
    """自然排序 key：数字按数值比较"""
    parts = re.split(r'(\d+)', s or '')
    return [int(x) if x.isdigit() else x.lower() for x in parts]


def format_size(size: int) -> str:
    """将字节数格式化为可读字符串"""
    if not size:
        return ''
    size = float(size)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            if unit == 'B':
                return f'{int(size)} {unit}'
            return f'{size:.1f} {unit}'
        size /= 1024
    return ''


def find_cover_in_dir(path: str) -> str:
    """在目录内查找封面图（优先 cover/poster/thumb 命名，其次第一张图片）

    用于目录卡片封面显示，快速返回，最多扫描前 200 项。
    """
    if not path or not os.path.isdir(path):
        return ''
    try:
        names = os.listdir(path)
        # 优先匹配封面命名
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext not in COVER_EXTS:
                continue
            stem = os.path.splitext(name)[0].lower()
            if any(k in stem for k in _COVER_NAMES):
                return os.path.join(path, name)
        # 其次取第一张静态图片
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext in COVER_EXTS:
                return os.path.join(path, name)
        # 最后尝试第一个子目录中的第一张图片（漫画章节封面）
        for name in sorted(names, key=_natural_key):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                try:
                    sub = sorted(os.listdir(full), key=_natural_key)
                    for sn in sub:
                        ext = os.path.splitext(sn)[1].lower()
                        if ext in COVER_EXTS:
                            return os.path.join(full, sn)
                except OSError:
                    pass
    except OSError:
        pass
    return ''


def find_audio_cover_in_dir(path: str) -> str:
    """音乐目录内查找封面图（folder.jpg / cover.jpg 等）"""
    if not path or not os.path.isdir(path):
        return ''
    try:
        for name in os.listdir(path):
            low = os.path.splitext(name)[0].lower()
            ext = os.path.splitext(name)[1].lower()
            if ext in COVER_EXTS and any(k in low for k in ('cover', 'folder', 'front')):
                return os.path.join(path, name)
    except OSError:
        pass
    return ''


def get_thumb_cache_dir() -> str:
    """获取缩略图缓存目录（绝对路径，避免相对路径加载失败）"""
    d = os.path.abspath(os.path.join(get_download_root(), '.thumbs'))
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _thumb_cache_path(source_path: str, size: tuple) -> str:
    """根据源文件路径与目标尺寸生成缩略图缓存路径"""
    import hashlib
    digest = hashlib.md5(os.path.abspath(source_path).encode('utf-8')).hexdigest()[:24]
    return os.path.join(get_thumb_cache_dir(), f"{digest}_{size[0]}x{size[1]}.jpg")


def _make_image_thumb(src: str, dst: str, size: tuple) -> bool:
    """用 Pillow 生成等比缩略图并保存为 JPEG"""
    try:
        from PIL import Image
        img = Image.open(src)
        img = img.convert('RGB')
        img.thumbnail(size)
        img.save(dst, 'JPEG', quality=85)
        return os.path.isfile(dst) and os.path.getsize(dst) > 0
    except Exception:
        return False


COVER_SIZE = (320, 180)


def get_image_thumbnail(path: str, size: tuple = COVER_SIZE) -> str:
    """图片缩略图缓存：返回缓存后的缩略图路径，失败返回原图"""
    if not path or not os.path.isfile(path):
        return ''
    dst = _thumb_cache_path(path, size)
    if os.path.isfile(dst) and os.path.getsize(dst) > 0:
        _register_thumb(path, dst)
        return dst
    if _make_image_thumb(path, dst, size):
        _register_thumb(path, dst)
        return dst
    return path


def _extract_video_frame(path: str) -> str:
    """用 ffmpeg 提取第一帧到临时图片（按源文件哈希独立命名，避免并发冲突）"""
    try:
        import shutil
        import subprocess
        import hashlib
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            return ''
        digest = hashlib.md5(os.path.abspath(path).encode('utf-8')).hexdigest()[:24]
        tmp = os.path.join(get_thumb_cache_dir(), f"_frame_{digest}.jpg")
        cmd = [ffmpeg, '-y', '-ss', '00:00:00', '-i', path,
               '-frames:v', '1', '-q:v', '3', tmp]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=8, check=False)
        if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
            return tmp
        return ''
    except Exception:
        return ''


def get_video_thumbnail(path: str, size: tuple = COVER_SIZE) -> str:
    """视频缩略图缓存：提取第一帧并等比缩放为缩略图"""
    if not path or not os.path.isfile(path):
        return ''
    dst = _thumb_cache_path(path, size)
    if os.path.isfile(dst) and os.path.getsize(dst) > 0:
        _register_thumb(path, dst)
        return dst
    frame = _extract_video_frame(path)
    if frame and _make_image_thumb(frame, dst, size):
        _register_thumb(path, dst)
        return dst
    return ''


def ensure_thumbnail(path: str, kind: str, size: tuple = COVER_SIZE) -> str:
    """确保缩略图存在：先查索引，有则直接返回，无则生成并注册"""
    cached = get_cached_thumb(path)
    if cached:
        return cached
    thumb = get_cover_thumbnail(path, kind, size)
    if thumb and thumb != path:
        _register_thumb(path, thumb)
        return thumb
    return thumb


def get_cover_thumbnail(path: str, kind: str, size: tuple = COVER_SIZE) -> str:
    """统一获取封面缩略图缓存路径（目录/图片/音乐/视频）"""
    try:
        if kind == 'image':
            return get_image_thumbnail(path, size)
        if kind == 'video':
            return get_video_thumbnail(path, size)
        if kind == 'dir':
            cover = find_cover_in_dir(path)
            if cover:
                return get_image_thumbnail(cover, size)
            return ''
        if kind == 'audio':
            cover = find_audio_cover_in_dir(os.path.dirname(path))
            if cover:
                return get_image_thumbnail(cover, size)
            return ''
    except Exception:
        return ''
    return ''


def get_video_cover(path: str) -> str:
    """兼容旧接口：返回视频缩略图缓存路径"""
    return get_video_thumbnail(path)


# ── 7z 解压 ──
def get_7z_path() -> str:
    """获取项目内置 7z.exe 路径"""
    return os.path.join(str(CFG.root), 'data', '7Z', '7z.exe')


def has_7z() -> bool:
    return os.path.isfile(get_7z_path())


def list_archive(path: str) -> list:
    """列出压缩包内文件（返回名称列表）"""
    if not path or not has_7z():
        return []
    try:
        import subprocess
        cmd = [get_7z_path(), 'l', '-slt', path]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=30)
        entries = []
        for line in proc.stdout.splitlines():
            if line.startswith('Path = '):
                name = line[7:].strip()
                if name:
                    entries.append(name)
        return entries
    except Exception:
        return []


def extract_archive(path: str, dest_dir: str, progress_cb=None) -> tuple:
    """解压压缩包到目标目录，返回 (success, message)"""
    if not path or not os.path.isfile(path):
        return False, '压缩包不存在'
    if not has_7z():
        return False, '未找到 7z.exe'
    dest_dir = os.path.abspath(dest_dir)
    try:
        import subprocess
        os.makedirs(dest_dir, exist_ok=True)
        cmd = [get_7z_path(), 'x', '-y', f'-o{dest_dir}', path]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding='utf-8', errors='replace')
        if proc.returncode == 0:
            return True, f'解压完成：{dest_dir}'
        return False, (proc.stderr.strip()[-500:] if proc.stderr else '解压失败')
    except Exception as e:
        return False, str(e)


def read_text_file(path: str, max_bytes: int = 512 * 1024) -> str:
    """读取文本文件内容（限制大小，尝试常见编码）"""
    if not path or not os.path.isfile(path):
        return ''
    try:
        size = os.path.getsize(path)
        if size > max_bytes:
            with open(path, 'rb') as f:
                data = f.read(max_bytes)
        else:
            with open(path, 'rb') as f:
                data = f.read()
    except OSError:
        return ''

    for enc in ('utf-8', 'gbk', 'gb18030', 'utf-16', 'big5'):
        try:
            return data.decode(enc, errors='strict')
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace')
