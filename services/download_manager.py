# -*- coding: utf-8 -*-
"""
统一下载管理模块
================
- 多模式智能下载引擎（并发分块 / 流式 / HLS）
- 自动判定最优下载模式，失败自动切换模式重试
- 下载到临时文件，成功后再重命名；失败自动清理残留数据
- 下载目录自检/创建
- 文件按类型自动分类存储（图片/视频/音频）
- 同名文件智能去重（自动添加后缀）
"""
import os
import re
import time
import shutil
import threading
import hashlib
import requests
from enum import Enum
from pathlib import Path

from core.config import config as CFG

# ═══════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# 小文件阈值：小于该值不分块并发（避免线程开销 > 收益）
MIN_PARALLEL_SIZE = 1 * 1024 * 1024  # 1 MB
# 单块最小大小
MIN_CHUNK_SIZE = 512 * 1024  # 512 KB
# 流式分块大小
STREAM_CHUNK_SIZE = 256 * 1024  # 256 KB
# 并发块读取大小
PARALLEL_CHUNK_READ = 128 * 1024  # 128 KB


# ═══════════════════════════════════════════════════════════
#  下载模式定义
# ═══════════════════════════════════════════════════════════
class DownloadMode(str, Enum):
    """下载模式"""
    AUTO = 'auto'        # 自动判定
    PARALLEL = 'parallel'  # 并发分块（大文件加速）
    STREAM = 'stream'    # 流式下载（兼容性好）
    HLS = 'hls'          # HLS 分片流媒体

    @property
    def display_name(self) -> str:
        return {
            DownloadMode.AUTO: '自动判定',
            DownloadMode.PARALLEL: '并发分块',
            DownloadMode.STREAM: '流式下载',
            DownloadMode.HLS: 'HLS分片',
        }.get(self, self.value)


# ═══════════════════════════════════════════════════════════
#  文件名清洗
# ═══════════════════════════════════════════════════════════
def sanitize_filename(filename: str) -> str:
    """去除 Windows 文件名中的无效字符"""
    if not filename:
        return 'untitled'
    filename = filename.replace('\n', '')
    filename = filename.replace(' ', '')
    filename = filename.replace('#', '_')
    # 使用正则表达式去除无效字符和控制字符
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    return filename.strip() or 'untitled'


# ═══════════════════════════════════════════════════════════
#  下载目录管理
# ═══════════════════════════════════════════════════════════
PLATFORM_FOLDERS = {
    'douyin': 'douyin-download',
    'bilibili': 'bilibili-download',
    'twitter': 'twitter-download',
    'pixiv': 'pixiv-download',
    'xvideo': 'xvideo-download',
    'youtube': 'youtube-download',
}

SUBDIRS = ('images', 'videos', 'audios')


def get_download_root() -> str:
    """获取下载根目录（默认 data 文件夹或设置中配置）"""
    custom = CFG.get('video_download_root', '')
    if custom and os.path.isdir(custom):
        return custom
    return os.path.join(CFG.root, 'data')


def ensure_download_dirs():
    """启动自检：确保所有平台下载目录及子目录存在"""
    root = get_download_root()
    created = []
    for platform, folder in PLATFORM_FOLDERS.items():
        base = os.path.join(root, folder)
        for sub in SUBDIRS:
            d = os.path.join(base, sub)
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
                created.append(d)
    return created


def get_platform_dir(platform: str, file_type: str) -> str:
    """获取平台指定类型文件的下载目录

    file_type: 'image' | 'video' | 'audio'
    """
    root = get_download_root()
    folder = PLATFORM_FOLDERS.get(platform, 'misc-download')
    type_map = {'image': 'images', 'video': 'videos', 'audio': 'audios'}
    sub = type_map.get(file_type, 'videos')
    d = os.path.join(root, folder, sub)
    os.makedirs(d, exist_ok=True)
    return d


# ═══════════════════════════════════════════════════════════
#  文件去重检测
# ═══════════════════════════════════════════════════════════
def file_similarity(file_a: str, file_b: str) -> float:
    """计算两个文件的相似度（基于文件大小 + 采样哈希）"""
    try:
        if not os.path.exists(file_a) or not os.path.exists(file_b):
            return 0.0
        size_a = os.path.getsize(file_a)
        size_b = os.path.getsize(file_b)
        if size_a == 0 or size_b == 0:
            return 0.0
        # 大小差异超过 20% 视为不同
        ratio = min(size_a, size_b) / max(size_a, size_b)
        if ratio < 0.8:
            return 0.0
        # 采样文件开头/中间/结尾的哈希
        def sample_hash(path):
            h = hashlib.md5()
            with open(path, 'rb') as f:
                size = os.path.getsize(path)
                for pos in (0, size // 3, size // 2, size * 2 // 3, max(0, size - 4096)):
                    if pos < size:
                        f.seek(pos)
                        h.update(f.read(1024))
            return h.hexdigest()
        if sample_hash(file_a) == sample_hash(file_b):
            return 1.0
        return ratio
    except Exception:
        return 0.0


def resolve_conflict_filename(directory: str, filename: str) -> str:
    """检查目录中是否有同名文件，若有则自动添加后缀避免覆盖"""
    target = os.path.join(directory, filename)
    if not os.path.exists(target):
        return filename

    # 自动添加后缀避免覆盖
    name, ext = os.path.splitext(filename)
    for i in range(1, 1000):
        new_name = f"{name}_{i}{ext}"
        new_path = os.path.join(directory, new_name)
        if not os.path.exists(new_path):
            return new_name
    return f"{name}_{int(time.time())}{ext}"


def get_unique_path(directory: str, filename: str) -> tuple:
    """获取唯一文件路径：如果存在同名则添加后缀

    Returns:
        (final_path, is_new)
    """
    target = os.path.join(directory, filename)
    if not os.path.exists(target):
        return target, True

    # 同名文件存在 - 自动添加后缀
    name, ext = os.path.splitext(filename)
    for i in range(1, 1000):
        new_name = f"{name}_{i}{ext}"
        new_path = os.path.join(directory, new_name)
        if not os.path.exists(new_path):
            return new_path, True
    new_path = os.path.join(directory, f"{name}_{int(time.time())}{ext}")
    return new_path, True


# ═══════════════════════════════════════════════════════════
#  URL 探测（获取文件信息）
# ═══════════════════════════════════════════════════════════
class URLProbe:
    """探测 URL 信息：大小 / 是否支持 Range / 内容类型"""

    def __init__(self, url: str, headers: dict = None, timeout: int = 10):
        self.url = url
        self.headers = dict(DEFAULT_HEADERS)
        if headers:
            self.headers.update(headers)
        self.timeout = timeout

        self.ok = False
        self.total_size = 0
        self.supports_partial = False
        self.content_type = ''
        self.final_url = ''

    def probe(self) -> 'URLProbe':
        """执行探测"""
        # 1. HEAD 请求
        try:
            resp = requests.head(self.url, headers=self.headers,
                                 allow_redirects=True, timeout=self.timeout)
            if 200 <= resp.status_code < 300:
                self._parse_headers(resp)
                self.final_url = resp.url or self.url
                self.ok = True
                return self
        except Exception:
            pass

        # 2. Range GET 请求（部分服务器不支持 HEAD）
        try:
            headers = dict(self.headers)
            headers['Range'] = 'bytes=0-0'
            resp = requests.get(self.url, headers=headers, stream=True,
                                allow_redirects=True, timeout=self.timeout)
            if resp.status_code == 206:
                content_range = resp.headers.get('Content-Range', '')
                match = re.search(r'bytes\s+0-0/(\d+)', content_range)
                if match:
                    self.total_size = int(match.group(1))
                    self.supports_partial = True
                    self.content_type = resp.headers.get('Content-Type', '')
                    self.final_url = resp.url or self.url
                    self.ok = True
                    return self
            elif 200 <= resp.status_code < 300:
                self._parse_headers(resp)
                self.final_url = resp.url or self.url
                self.ok = True
                return self
            resp.close()
        except Exception:
            pass

        return self

    def _parse_headers(self, resp):
        """从响应头解析信息"""
        self.supports_partial = resp.headers.get('Accept-Ranges', '').lower() == 'bytes'
        content_length = resp.headers.get('Content-Length')
        if content_length and content_length.isdigit():
            self.total_size = int(content_length)
        self.content_type = resp.headers.get('Content-Type', '')
        # 部分服务器不在 HEAD 暴露 Accept-Ranges，用 Range 再确认
        if not self.supports_partial and self.total_size > 0:
            try:
                headers = dict(self.headers)
                headers['Range'] = 'bytes=0-0'
                r = requests.get(self.url, headers=headers, stream=True,
                                 allow_redirects=True, timeout=self.timeout)
                if r.status_code == 206:
                    self.supports_partial = True
                r.close()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════
#  并发分块下载器
# ═══════════════════════════════════════════════════════════
class ParallelDownloader:
    """多线程分块下载器（支持断点续传、单块失败重试）"""

    def __init__(self, url: str, file_path: str, total_size: int,
                 num_threads: int = 8, headers: dict = None,
                 referer: str = '', progress_callback=None,
                 retry_times: int = 3):
        self.url = url
        self.file_path = file_path
        self.total_size = total_size
        self.num_threads = max(1, min(num_threads, 16))
        self.headers = dict(DEFAULT_HEADERS)
        if headers:
            self.headers.update(headers)
        if referer:
            self.headers['Referer'] = referer
        self.progress_callback = progress_callback
        self.retry_times = max(0, retry_times)

        self.downloaded = 0
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.failed_chunks = []
        self._chunk_results = {}

    def _calc_chunks(self) -> list:
        """计算分块范围"""
        chunk_size = max(MIN_CHUNK_SIZE, self.total_size // self.num_threads)
        chunk_size = min(chunk_size, self.total_size)
        chunks = []
        start = 0
        while start < self.total_size:
            end = min(start + chunk_size - 1, self.total_size - 1)
            chunks.append((start, end))
            start = end + 1
        return chunks

    def _download_range(self, start: int, end: int, attempts: int = 0) -> bool:
        """下载单个分块（带重试）"""
        if self.stop_event.is_set():
            return False
        try:
            headers = dict(self.headers)
            headers['Range'] = f'bytes={start}-{end}'
            response = requests.get(self.url, headers=headers, stream=True, timeout=30)
            if response.status_code not in (206, 200):
                response.close()
                raise RuntimeError(f"HTTP {response.status_code}")

            offset = start
            with self.lock:
                with open(self.file_path, 'r+b') as f:
                    f.seek(start)
                    for chunk in response.iter_content(chunk_size=PARALLEL_CHUNK_READ):
                        if self.stop_event.is_set() or not chunk:
                            break
                        f.write(chunk)
                        offset += len(chunk)
                        self.downloaded += len(chunk)
                        if self.progress_callback:
                            try:
                                self.progress_callback(self.downloaded, self.total_size)
                            except Exception:
                                pass
            response.close()
            return True
        except Exception:
            if attempts < self.retry_times and not self.stop_event.is_set():
                time.sleep(0.5 * (attempts + 1))
                return self._download_range(start, end, attempts + 1)
            self.failed_chunks.append((start, end))
            return False

    def _resume_download_range(self, start: int, end: int, current_offset: int,
                               attempts: int = 0) -> bool:
        """断点续传下载分块（从 current_offset 继续）"""
        if self.stop_event.is_set():
            return False
        if current_offset > end:
            return True
        try:
            headers = dict(self.headers)
            headers['Range'] = f'bytes={current_offset}-{end}'
            response = requests.get(self.url, headers=headers, stream=True, timeout=30)
            if response.status_code not in (206, 200):
                response.close()
                raise RuntimeError(f"HTTP {response.status_code}")

            with self.lock:
                with open(self.file_path, 'r+b') as f:
                    f.seek(current_offset)
                    for chunk in response.iter_content(chunk_size=PARALLEL_CHUNK_READ):
                        if self.stop_event.is_set() or not chunk:
                            break
                        f.write(chunk)
                        current_offset += len(chunk)
                        self.downloaded += len(chunk)
                        if self.progress_callback:
                            try:
                                self.progress_callback(self.downloaded, self.total_size)
                            except Exception:
                                pass
            response.close()
            return True
        except Exception:
            if attempts < self.retry_times and not self.stop_event.is_set():
                time.sleep(0.5 * (attempts + 1))
                return self._resume_download_range(start, end, current_offset, attempts + 1)
            self.failed_chunks.append((start, end))
            return False

    def download(self) -> bool:
        """执行并发分块下载，返回是否成功"""
        if self.total_size <= 0:
            return False

        # 预分配文件空间
        with open(self.file_path, 'wb') as f:
            f.truncate(self.total_size)

        chunks = self._calc_chunks()
        if len(chunks) < 2:
            # 分块过少时使用单个完整下载
            return self._download_single()

        self.downloaded = 0
        threads = []
        for start, end in chunks:
            t = threading.Thread(target=self._download_range, args=(start, end))
            t.daemon = True
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        # 检查失败分块，尝试断点续传
        retry_rounds = 0
        while self.failed_chunks and retry_rounds < 2:
            retry_rounds += 1
            pending = list(self.failed_chunks)
            self.failed_chunks = []
            for start, end in pending:
                # 检查已下载进度，从断点继续
                current_offset = self._get_chunk_progress(start, end)
                self._resume_download_range(start, end, current_offset)

        if self.failed_chunks:
            return False

        # 验证文件完整性
        try:
            with open(self.file_path, 'rb') as f:
                f.seek(self.total_size - 1)
                if len(f.read(1)) != 1:
                    return False
            return os.path.getsize(self.file_path) == self.total_size
        except Exception:
            return False

    def _get_chunk_progress(self, start: int, end: int) -> int:
        """获取分块当前已下载的字节偏移"""
        try:
            with open(self.file_path, 'rb') as f:
                size = os.path.getsize(self.file_path)
                limit = min(end + 1, size)
                # 从末尾向前扫描直到发现非零字节
                f.seek(limit)
                pos = limit
                read_size = max(1, limit - start)
                f.seek(start)
                data = f.read(read_size)
                for i in range(len(data) - 1, -1, -1):
                    if data[i] != 0:
                        return start + i + 1
            return start
        except Exception:
            return start

    def _download_single(self) -> bool:
        """单块完整下载（文件较小时避免并发开销）"""
        attempts = 0
        while attempts <= self.retry_times and not self.stop_event.is_set():
            try:
                headers = dict(self.headers)
                headers['Range'] = f'bytes=0-{self.total_size - 1}'
                response = requests.get(self.url, headers=headers, stream=True, timeout=30)
                if response.status_code not in (206, 200):
                    response.close()
                    raise RuntimeError(f"HTTP {response.status_code}")

                with open(self.file_path, 'wb') as f:
                    self.downloaded = 0
                    for chunk in response.iter_content(chunk_size=STREAM_CHUNK_SIZE):
                        if self.stop_event.is_set() or not chunk:
                            break
                        f.write(chunk)
                        self.downloaded += len(chunk)
                        if self.progress_callback:
                            try:
                                self.progress_callback(self.downloaded, self.total_size)
                            except Exception:
                                pass
                response.close()
                return os.path.getsize(self.file_path) == self.total_size
            except Exception:
                attempts += 1
                if attempts <= self.retry_times:
                    time.sleep(0.5 * attempts)
        return False


# ═══════════════════════════════════════════════════════════
#  流式下载器（兼容性最好）
# ═══════════════════════════════════════════════════════════
class StreamDownloader:
    """单线程流式下载器（带自动重试 + 断点续传）"""

    def __init__(self, url: str, file_path: str, headers: dict = None,
                 referer: str = '', total_size: int = 0,
                 progress_callback=None, retry_times: int = 3):
        self.url = url
        self.file_path = file_path
        self.headers = dict(DEFAULT_HEADERS)
        if headers:
            self.headers.update(headers)
        if referer:
            self.headers['Referer'] = referer
        self.total_size = total_size
        self.progress_callback = progress_callback
        self.retry_times = max(0, retry_times)

        self.downloaded = 0
        self.stop_event = threading.Event()

    def download(self) -> bool:
        """执行流式下载，返回是否成功"""
        attempts = 0
        resume_offset = 0

        # 支持断点续传时，检查临时文件已有大小
        existing = os.path.getsize(self.file_path) if os.path.exists(self.file_path) else 0
        if existing > 0:
            resume_offset = existing

        while attempts <= self.retry_times and not self.stop_event.is_set():
            try:
                headers = dict(self.headers)
                if resume_offset > 0:
                    headers['Range'] = f'bytes={resume_offset}-'
                response = requests.get(self.url, headers=headers, stream=True,
                                        allow_redirects=True, timeout=30)

                # 服务器不支持 Range 且已有部分数据时，从头重下
                if response.status_code == 200 and resume_offset > 0:
                    resume_offset = 0
                    response.close()
                    continue

                if response.status_code >= 400:
                    response.close()
                    raise RuntimeError(f"HTTP {response.status_code}")

                # 获取总大小（若之前未知）
                if not self.total_size:
                    content_length = response.headers.get('Content-Length')
                    if content_length and content_length.isdigit():
                        self.total_size = int(content_length)

                mode = 'ab' if resume_offset > 0 else 'wb'
                with open(self.file_path, mode) as f:
                    for chunk in response.iter_content(chunk_size=STREAM_CHUNK_SIZE):
                        if self.stop_event.is_set() or not chunk:
                            break
                        f.write(chunk)
                        resume_offset += len(chunk)
                        self.downloaded += len(chunk)
                        if self.progress_callback:
                            try:
                                self.progress_callback(self.downloaded, self.total_size)
                            except Exception:
                                pass
                response.close()
                return True
            except Exception:
                attempts += 1
                if attempts <= self.retry_times:
                    time.sleep(0.5 * attempts)
        return False


# ═══════════════════════════════════════════════════════════
#  HLS 分片下载器
# ═══════════════════════════════════════════════════════════
class HlsDownloader:
    """HLS（m3u8）流媒体下载器"""

    def __init__(self, m3u8_url: str, headers: dict = None, referer: str = '',
                 progress_callback=None, retry_times: int = 3,
                 max_segment_threads: int = 4):
        self.m3u8_url = m3u8_url
        self.headers = dict(DEFAULT_HEADERS)
        if headers:
            self.headers.update(headers)
        if referer:
            self.headers['Referer'] = referer
        self.progress_callback = progress_callback
        self.retry_times = max(0, retry_times)
        self.max_segment_threads = max(1, min(max_segment_threads, 8))

        self.stop_event = threading.Event()
        self._seg_lock = threading.Lock()
        self._seg_results = {}

    def _resolve_segment_url(self, base_url: str, segment: str) -> str:
        """解析分片绝对 URL"""
        from urllib.parse import urljoin
        if segment.startswith(('http://', 'https://')):
            return segment
        return urljoin(base_url, segment)

    def _parse_playlist(self, content: str) -> list:
        """解析 m3u8 清单，返回分片 URL 列表（跳过加密分片回调）"""
        segments = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 跳过加密 KEY 等非分片行
            if 'encrypted' in line.lower() and '.key' in line.lower():
                continue
            segments.append(line)
        return segments

    def download(self, output_path: str) -> bool:
        """下载并合并 HLS 流媒体

        Returns:
            bool: 是否成功
        """
        import tempfile

        try:
            # 1. 获取 m3u8 清单
            resp = requests.get(self.m3u8_url, headers=self.headers, timeout=15)
            if resp.status_code != 200:
                return False
            content = resp.text

            segments = self._parse_playlist(content)
            if not segments:
                return False

            # 处理相对路径
            base_url = self.m3u8_url[:self.m3u8_url.rfind('/') + 1]

            # 2. 临时目录存分片
            tmp_dir = tempfile.mkdtemp(prefix='hls_dl_')
            ts_paths = []
            try:
                total = len(segments)
                self._seg_results = {}
                self._seg_lock = threading.Lock()

                def _download_segment(idx: int, seg_rel: str):
                    if self.stop_event.is_set():
                        return
                    seg_url = self._resolve_segment_url(base_url, seg_rel)
                    attempts = 0
                    while attempts <= self.retry_times:
                        try:
                            sresp = requests.get(seg_url, headers=self.headers, timeout=30)
                            if sresp.status_code == 200:
                                ts_path = os.path.join(tmp_dir, f'seg_{idx:05d}.ts')
                                with open(ts_path, 'wb') as f:
                                    f.write(sresp.content)
                                with self._seg_lock:
                                    self._seg_results[idx] = ts_path
                                return
                            sresp.close()
                        except Exception:
                            pass
                        attempts += 1
                        time.sleep(0.3 * attempts)

                # 并发下载分片
                threads = []
                for idx, seg in enumerate(segments):
                    if self.stop_event.is_set():
                        break
                    t = threading.Thread(target=_download_segment, args=(idx, seg))
                    t.daemon = True
                    t.start()
                    threads.append(t)
                    # 控制并发数量
                    if len(threads) >= self.max_segment_threads:
                        for done in threads:
                            done.join(timeout=0.1)
                        threads = [t for t in threads if t.is_alive()]
                for t in threads:
                    t.join()

                # 3. 检查完整性并合并
                if len(self._seg_results) < total:
                    return False

                with open(output_path, 'wb') as out:
                    for idx in sorted(self._seg_results):
                        ts = self._seg_results[idx]
                        with open(ts, 'rb') as f:
                            out.write(f.read())
                        if self.progress_callback:
                            try:
                                self.progress_callback(idx + 1, total)
                            except Exception:
                                pass

                return True
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
#  自适应下载器（多模式调度）
# ═══════════════════════════════════════════════════════════
class AdaptiveDownloader:
    """自适应多模式下载器

    自动判定最优模式 → 失败自动切换其他模式重试
    下载到 .part 临时文件，成功才重命名；失败清除残留数据
    """

    def __init__(self, url: str, file_path: str, headers: dict = None,
                 referer: str = '', progress_callback=None,
                 mode: str = None, retry_times: int = None,
                 max_threads: int = None, parallel_threshold_mb: int = None):
        self.url = url
        self.file_path = file_path
        self.headers = dict(DEFAULT_HEADERS)
        if headers:
            self.headers.update(headers)
        self.referer = referer or self.headers.get('Referer', '')
        self.progress_callback = progress_callback

        # 优先使用调用方指定的模式，否则从配置读取
        if mode is None:
            mode = str(CFG.get('download_mode', 'auto'))
        if mode not in DownloadMode._value2member_map_:
            mode = 'auto'
        self.mode = DownloadMode(mode)

        # 从配置读取参数（支持外部覆盖）
        self.max_threads = max_threads if max_threads is not None \
            else int(CFG.get('download_max_threads', 8))
        self.parallel_threshold_mb = parallel_threshold_mb \
            if parallel_threshold_mb is not None \
            else int(CFG.get('download_parallel_threshold', 20))
        self.retry_times = retry_times if retry_times is not None \
            else int(CFG.get('download_retry_times', 3))

        self.probe = None
        self.used_mode = None
        self.tmp_path = ''
        self._downloaded = 0
        self._lock = threading.Lock()

    # ---------- 临时文件管理 ----------
    def _setup_tmp_path(self):
        """创建临时下载路径（.part）"""
        self.tmp_path = f"{self.file_path}.part"
        # 清理历史残留
        if os.path.exists(self.tmp_path):
            try:
                os.remove(self.tmp_path)
            except OSError:
                pass

    def _finalize(self) -> bool:
        """将临时文件重命名为最终文件"""
        tmp_path = self.tmp_path
        if not tmp_path or not os.path.exists(tmp_path):
            return False
        try:
            # 确保目标目录存在
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            # 若最终文件已存在（并发下载同名），删除后替换
            if os.path.exists(self.file_path):
                try:
                    os.remove(self.file_path)
                except OSError:
                    pass
            os.rename(tmp_path, self.file_path)
            return True
        except OSError:
            # 重命名失败时尝试复制
            try:
                shutil.copy2(tmp_path, self.file_path)
                self.cleanup()
                return True
            except OSError:
                return False

    def cleanup(self):
        """清理残留的临时文件（最终失败时调用）"""
        if self.tmp_path and os.path.exists(self.tmp_path):
            try:
                os.remove(self.tmp_path)
            except OSError:
                pass
        self.tmp_path = ''

    # ---------- 模式判定 ----------
    def _decide_mode(self) -> DownloadMode:
        """根据探测结果自动判定最优下载模式"""
        # 强制模式
        if self.mode != DownloadMode.AUTO:
            return self.mode

        if not self.probe or not self.probe.ok:
            return DownloadMode.STREAM

        # 大文件且支持 Range → 并发分块
        size_mb = self.probe.total_size / (1024 * 1024)
        if self.probe.supports_partial and self.probe.total_size >= MIN_PARALLEL_SIZE:
            # 超过阈值使用并发分块
            if size_mb >= self.parallel_threshold_mb:
                return DownloadMode.PARALLEL
            # 小文件直接流式（避免线程开销）
            return DownloadMode.STREAM

        # 不支持 Range → 流式
        return DownloadMode.STREAM

    def _mode_order(self, first: DownloadMode) -> list:
        """生成模式尝试顺序"""
        order = [first]
        for m in (DownloadMode.PARALLEL, DownloadMode.STREAM, DownloadMode.HLS):
            if m not in order:
                order.append(m)
        return order

    # ---------- 各模式执行 ----------
    def _run_parallel(self) -> bool:
        if not self.probe or not self.probe.total_size:
            return False
        downloader = ParallelDownloader(
            url=self.url,
            file_path=self.tmp_path,
            total_size=self.probe.total_size,
            num_threads=self.max_threads,
            headers=self.headers,
            referer=self.referer,
            progress_callback=self.progress_callback,
            retry_times=self.retry_times,
        )
        return downloader.download()

    def _run_stream(self) -> bool:
        downloader = StreamDownloader(
            url=self.url,
            file_path=self.tmp_path,
            headers=self.headers,
            referer=self.referer,
            total_size=self.probe.total_size if self.probe else 0,
            progress_callback=self.progress_callback,
            retry_times=self.retry_times,
        )
        return downloader.download()

    # ---------- 主下载流程 ----------
    def download(self) -> bool:
        """执行自适应下载

        Returns:
            bool: 是否成功
        """
        # 探测 URL
        self.probe = URLProbe(self.url, headers=self.headers).probe()

        # 决定优先模式
        if self.mode == DownloadMode.HLS:
            first_mode = DownloadMode.HLS
        else:
            first_mode = self._decide_mode()

        # 模式尝试顺序
        mode_order = self._mode_order(first_mode)

        # 临时文件
        self._setup_tmp_path()

        last_error = None
        for mode in mode_order:
            if self.mode != DownloadMode.AUTO and mode != self.mode:
                continue

            # 跳过 HLS（仅当 URL 是 m3u8 时）
            if mode == DownloadMode.HLS and '.m3u8' not in self.url.lower():
                continue

            # 并发模式需要探测信息
            if mode == DownloadMode.PARALLEL and (not self.probe or not self.probe.total_size):
                continue

            # 清理上次遗留的临时文件
            self._setup_tmp_path()

            self.used_mode = mode
            try:
                if mode == DownloadMode.PARALLEL:
                    ok = self._run_parallel()
                elif mode == DownloadMode.STREAM:
                    ok = self._run_stream()
                elif mode == DownloadMode.HLS:
                    hls = HlsDownloader(
                        self.url, headers=self.headers, referer=self.referer,
                        progress_callback=self.progress_callback,
                        retry_times=self.retry_times,
                    )
                    ok = hls.download(self.tmp_path)
                else:
                    ok = False

                if ok:
                    # 验证文件非空
                    if os.path.exists(self.tmp_path) and os.path.getsize(self.tmp_path) > 0:
                        if self._finalize():
                            return True
                    continue
            except Exception as e:
                last_error = e

        # 全部模式失败 → 清理残留数据
        self.cleanup()
        if last_error:
            print(f"下载失败: {self.url} - {last_error}")
        return False

    def get_used_mode(self) -> str:
        """获取实际使用的下载模式"""
        return self.used_mode.value if self.used_mode else ''


# ═══════════════════════════════════════════════════════════
#  兼容性：SmartDownloader
# ═══════════════════════════════════════════════════════════
class SmartDownloader:
    """多线程分块下载器（兼容旧接口，内部使用自适应多模式引擎）"""

    def __init__(self, url, filename, download_dir, file_type='video',
                 platform='douyin', num_threads=4, progress_callback=None,
                 referer='', is_hls=False):
        self.url = url
        self.filename = filename
        self.download_dir = download_dir
        self.file_type = file_type
        self.platform = platform
        self.num_threads = num_threads
        self.referer = referer
        self.is_hls = is_hls
        # 智能分类目录
        self.target_dir = get_platform_dir(platform, file_type)
        self.file_path, _ = get_unique_path(self.target_dir, filename)
        self.total_size = 0
        self.downloaded = 0
        self.progress_callback = progress_callback
        self._success = False

    def _safe_progress(self, current, total):
        self.downloaded = current
        self.total_size = total
        if self.progress_callback:
            try:
                self.progress_callback(current, total)
            except Exception:
                pass

    def download(self):
        """执行下载"""
        os.makedirs(self.target_dir, exist_ok=True)

        # HLS 强制 hls 模式；否则 None（从全局配置读取下载模式）
        mode = 'hls' if self.is_hls else None
        downloader = AdaptiveDownloader(
            url=self.url,
            file_path=self.file_path,
            referer=self.referer,
            progress_callback=self._safe_progress,
            mode=mode,
            max_threads=self.num_threads,
        )
        self._success = downloader.download()
        if not self._success:
            # 失败时清理可能残留的 .part 临时文件
            tmp_path = f"{self.file_path}.part"
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return self._success

    def get_file_path(self):
        return self.file_path

    def get_downloaded_path(self):
        return self.file_path


# ═══════════════════════════════════════════════════════════
#  文件类型智能推断
# ═══════════════════════════════════════════════════════════
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic')
VIDEO_EXTS = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.m4v', '.ts', '.m3u8')
AUDIO_EXTS = ('.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.opus')
CONTENT_TYPE_MAP = {
    'image/': 'image',
    'video/': 'video',
    'audio/': 'audio',
    'application/octet-stream': None,  # 无法判断，用 URL 推断
}


def infer_file_type(url: str, file_type: str = 'video', filename: str = '') -> str:
    """推断实际文件类型

    优先级: 文件名扩展名 > URL 扩展名 > Content-Type > 传入默认值

    Returns:
        'image' | 'video' | 'audio'
    """
    import posixpath
    from urllib.parse import urlparse

    # 1. 从文件名扩展名判断
    if filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext in IMAGE_EXTS:
            return 'image'
        if ext in VIDEO_EXTS:
            return 'video'
        if ext in AUDIO_EXTS:
            return 'audio'

    # 2. 从 URL 路径扩展名判断（去掉查询参数）
    try:
        path = urlparse(url).path
        ext = posixpath.splitext(path)[1].lower()
        if ext in IMAGE_EXTS:
            return 'image'
        if ext in VIDEO_EXTS:
            return 'video'
        if ext in AUDIO_EXTS:
            return 'audio'
    except Exception:
        pass

    # 3. 尝试 HEAD 请求获取 Content-Type
    try:
        resp = requests.head(url, allow_redirects=True, timeout=5)
        content_type = resp.headers.get('Content-Type', '').lower()
        for prefix, ftype in CONTENT_TYPE_MAP.items():
            if prefix in content_type and ftype:
                return ftype
    except Exception:
        pass

    return file_type


# ═══════════════════════════════════════════════════════════
#  便捷下载函数
# ═══════════════════════════════════════════════════════════
def download_hls_stream(m3u8_url: str, output_path: str,
                        referer: str = '', progress_callback=None) -> bool:
    """下载并合并 HLS 流媒体（m3u8 + TS 分片 → mp4）

    兼容旧接口，内部使用 HlsDownloader

    Returns:
        bool: 是否成功
    """
    hls = HlsDownloader(
        m3u8_url=m3u8_url,
        referer=referer,
        progress_callback=progress_callback,
    )
    return hls.download(output_path)


def download_media(url: str, filename: str, platform: str, file_type: str = 'video',
                   progress_callback=None, num_threads=4, is_hls=False,
                   referer='') -> tuple:
    """下载媒体文件并自动分类存储

    Args:
        url: 下载链接
        filename: 文件名
        platform: 平台标识 (douyin/bilibili/twitter/pixiv/xvideo/youtube)
        file_type: 文件类型 (image/video/audio)
        progress_callback: 进度回调 (current, total)
        is_hls: 是否为 HLS 流媒体（Xvideo 等）
        referer: 下载时的 Referer（防盗链）

    Returns:
        (success, message, file_path)
    """
    filename = sanitize_filename(filename)
    if not filename:
        filename = f"{platform}_{int(time.time())}"

    # 智能推断实际文件类型（解决解析器类型误报问题）
    actual_type = infer_file_type(url, file_type, filename)

    # 根据推断类型补充扩展名
    if actual_type == 'image' and not re.search(r'\.(png|jpe?g|gif|webp|bmp|heic)$', filename, re.I):
        filename += '.jpg'
    elif actual_type == 'video' and not re.search(r'\.(mp4|mkv|webm|avi|mov|flv|m4v|ts)$', filename, re.I):
        filename += '.mp4'
    elif actual_type == 'audio' and not re.search(r'\.(mp3|m4a|aac|flac|wav|ogg|opus)$', filename, re.I):
        filename += '.mp3'

    target_dir = get_platform_dir(platform, actual_type)
    output_path, _ = get_unique_path(target_dir, filename)

    # HLS 流媒体：走 HLS 分片下载
    if is_hls and actual_type == 'video':
        if download_hls_stream(url, output_path, referer, progress_callback):
            return True, f"{filename} 下载完成", output_path
        # 失败清理残留
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        tmp_path = f"{output_path}.part"
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False, f"{filename} 下载失败", output_path

    downloader = SmartDownloader(
        url=url,
        filename=filename,
        download_dir='',
        file_type=actual_type,
        platform=platform,
        num_threads=num_threads,
        progress_callback=progress_callback,
        referer=referer,
        is_hls=is_hls,
    )
    success = downloader.download()
    path = downloader.get_downloaded_path()
    if success:
        return True, f"{filename} 下载完成", path
    return False, f"{filename} 下载失败", path
