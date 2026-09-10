# -*- coding: utf-8 -*-
"""
E-Hentai 画廊下载核心模块（无 GUI 依赖，可独立测试）
====================================================
移植自 OGC-E-hentai 独立程序的 downloader.py，并与此程序（OGC）的
下载代码（services/download_manager.py）优化合并。

针对「经常失败、重试不成功」的优化：
1. **解析更健壮**：分页总数支持新版 table.ptt 与旧版 onclick 两种结构；
   图片列表按 div#gdt 的 id 匹配（不再依赖 class），失败时回退到任意
   /s/ 详情链接；图片地址支持 img#img / og:image / #i7 多种来源。
2. **限流识别**：HTTP 429/509 与页面内「bandwidth limit / banned /
   sad panda」标记 → 抛出 RateLimitError，按 10s/20s/… 长退避重试，
   不再快速重复请求加重限流。
3. **重试不重蹈覆辙**：任务失败时记录已解析出的图片直链，重试时直接
   下载图片、跳过详情页二次解析（请求减半，命中率更高）。
4. **内容校验**：下载内容做图片魔数校验，反爬返回的错误页 HTML 不会
   被当成成功图片保存；已存在且非空的文件直接跳过（断点续传幂等）。
5. 停止仍即时生效（流式分块读取 + 停止检查），剩余任务记入失败列表
   供「重试失败」续传。
"""
import ast
import io
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from services.download_manager import DEFAULT_HEADERS

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False


def _make_soup(text: str):
    """构造 BeautifulSoup，优先 lxml，缺失时回退 html.parser"""
    try:
        return BeautifulSoup(text, 'lxml')
    except Exception:
        return BeautifulSoup(text, 'html.parser')


def _invalidate_ehentai_index() -> None:
    """E-Hentai 下载完成后使离线索引失效（下次扫描重建）。"""
    try:
        from services.comic_library import invalidate_index, default_index_path
        from pages.album.ehentai_settings import ehentai_cfg as _cfg
        root = _cfg.get(_cfg.KEY_OUTPUT_DIR, '') or 'data/ehentai/galleries'
        invalidate_index(default_index_path(root, 'ehentai'))
    except Exception:
        pass


class DownloadError(Exception):
    """下载异常基类"""


class RateLimitError(DownloadError):
    """访问受限（429/509/封禁）：需要长退避后重试"""


# 页面中被反爬/限流拦截的标记
LIMIT_MARKERS = (
    '509 bandwidth limit exceeded',
    'your ip address has been temporarily banned',
    'you have been temporarily banned',
    'sad panda',
)


@dataclass
class DownloadProgress:
    """下载进度快照"""
    total: int = 0          # 图片总数
    done: int = 0           # 已完成
    failed: int = 0         # 失败
    current: str = ''       # 当前任务描述
    page: int = 0           # 当前分页
    page_total: int = 0     # 分页总数
    finished: bool = False  # 是否结束
    failed_tasks: list = field(default_factory=list)  # 失败任务 [(页码, 序号, 详情URL), ...]
    task_status: dict = field(default_factory=dict)   # 溯源: (页码, 序号) -> 'downloaded'|'skipped'|'failed'


@dataclass
class DownloadConfig:
    """下载配置"""
    url: str = ''
    cookies: str = ''             # 支持 dict 文本 或 k=v; k2=v2 格式
    headers: str = ''             # 支持 dict 文本
    proxy: str = ''               # 例如 http://127.0.0.1:7890
    ignore_env_proxy: bool = True  # 忽略系统环境变量代理
    output_dir: str = './'        # 下载根目录
    concurrency: int = 4          # 并发数
    timeout: int = 30             # 超时秒数
    image_format: str = ''        # ''=原始格式, 'jpg', 'png', 'webp'
    per_file_retries: int = 3     # 单张图片失败重试次数
    retry_delay: float = 1.5      # 重试基础延迟（指数退避）秒


def _html_is_limited(html: str) -> bool:
    """检测页面是否被反爬/限流拦截"""
    low = (html or '').lower()
    return any(marker in low for marker in LIMIT_MARKERS)


def _record_usage(action: str, detail: str = ''):
    """记录 E-Hentai 使用行为（供仪表盘统计，函数内导入避免循环依赖）"""
    try:
        from core.database import record_usage
        record_usage('ehentai', action, detail)
    except Exception:
        pass


class EhentaiDownloader:
    """E-Hentai 画廊下载器"""

    CHUNK_SIZE = 256 * 1024   # 图片流式分块读取大小
    RATE_LIMIT_STATUS = (429, 509)

    def __init__(self, config: DownloadConfig):
        self.config = config
        self.session: Optional[requests.Session] = None
        self._stop_event = threading.Event()
        self._progress = DownloadProgress()
        self._title = ''
        self._output_path = ''
        self._listener: Optional[object] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._emit_locked = False  # run() 结束后锁定信号发射
        self._failed_tasks: list = []  # 最近一次运行失败的 (page, num, url)
        self._task_image_urls: dict = {}  # (page, num) -> 已解析出的图片直链（重试复用）

    # ------------------------------------------------------------------
    # 监听器接口（GUI 通过 set_listener 注入）
    # ------------------------------------------------------------------
    def set_listener(self, listener: object) -> None:
        self._listener = listener

    def _emit_progress(self) -> None:
        if self._emit_locked:
            return
        if self._listener and hasattr(self._listener, 'on_progress'):
            self._listener.on_progress(self._progress)

    def _emit_log(self, msg: str, level: str = 'info') -> None:
        if self._emit_locked:
            return
        if self._listener and hasattr(self._listener, 'on_log'):
            self._listener.on_log(msg, level)

    def _emit_finished(self) -> None:
        if self._emit_locked:
            return
        if self._listener and hasattr(self._listener, 'on_finished'):
            self._listener.on_finished(self._progress)

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    def stop(self) -> None:
        """请求停止：设置标志并立即取消线程池中未开始的任务"""
        self._stop_event.set()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def is_stopping(self) -> bool:
        return self._stop_event.is_set()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.trust_env = not self.config.ignore_env_proxy

        # 传输层仅做轻量重试（total=2），真正的失败重试由应用层
        # 可中断循环（_download_one / _worker）负责 → 「停止」响应更快
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.2,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset(['GET', 'HEAD']),
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=max(self.config.concurrency, 4),
            pool_maxsize=max(self.config.concurrency * 2, 8),
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        if self.config.proxy.strip():
            session.proxies = {
                'http': self.config.proxy.strip(),
                'https': self.config.proxy.strip(),
            }

        # 合并 OGC 默认请求头 + E-Hentai 防盗链 Referer
        headers = dict(DEFAULT_HEADERS)
        headers['Referer'] = 'https://e-hentai.org/'
        session.headers.update(headers)

        # 解析 Cookies；未配置时默认加 nw=1（跳过年龄确认页）
        cookies_text = self.config.cookies.strip()
        cookie_jar = requests.cookies.RequestsCookieJar()
        if cookies_text and cookies_text != '{}':
            try:
                cookies_dict = ast.literal_eval(cookies_text)
                if isinstance(cookies_dict, dict):
                    for k, v in cookies_dict.items():
                        cookie_jar.set(str(k), str(v))
            except (ValueError, SyntaxError):
                # 尝试 'k=v; k2=v2' 格式
                for part in cookies_text.split(';'):
                    if '=' in part:
                        k, v = part.strip().split('=', 1)
                        cookie_jar.set(k.strip(), v.strip())
        else:
            cookie_jar.set('nw', '1')
        session.cookies = cookie_jar

        # 解析 Headers
        headers_text = self.config.headers.strip()
        if headers_text and headers_text != '{}':
            try:
                extra = ast.literal_eval(headers_text)
                if isinstance(extra, dict):
                    session.headers.update(extra)
            except (ValueError, SyntaxError):
                self._emit_log('Headers 格式无法解析，已忽略', 'warning')

        return session

    def _safe_get(self, url: str, stream: bool = False) -> requests.Response:
        """带超时与停止检查的 GET 请求

        stream=True 时调用方必须自行 close() 响应，并以分块方式读取内容，
        以便在读取过程中随时响应「停止」。
        """
        if self._stop_event.is_set():
            raise DownloadError('任务已停止')
        # (连接超时, 读取超时)：连接超时收紧，避免停止后长时间无响应
        resp = self.session.get(url, timeout=(8, 25), stream=stream)
        if resp.status_code in self.RATE_LIMIT_STATUS:
            resp.close()
            raise RateLimitError(f'HTTP {resp.status_code}（访问过于频繁或带宽受限）')
        resp.raise_for_status()
        return resp

    def _check_html_limited(self, html: str) -> None:
        """检测页面是否被反爬/限流拦截"""
        if _html_is_limited(html):
            raise RateLimitError('页面被拦截（带宽限制 / IP 封禁 / sad panda）')

    def _read_stream(self, resp: requests.Response) -> bytes:
        """分块读取响应体，每块都检查停止标志（借鉴 OGC StreamDownloader）"""
        chunks = []
        total = 0
        try:
            for chunk in resp.iter_content(chunk_size=self.CHUNK_SIZE):
                if self._stop_event.is_set() or not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        finally:
            resp.close()
        if self._stop_event.is_set():
            raise DownloadError('任务已停止')
        if total == 0:
            raise DownloadError('响应内容为空')
        return b''.join(chunks)

    # ------------------------------------------------------------------
    # 页面解析（多版本兼容）
    # ------------------------------------------------------------------
    def _parse_page_total(self, html: str) -> int:
        """解析画廊分页总数（新版 table.ptt / 旧版 onclick 两种结构）"""
        # 1) 新版：<table class="ptt"> 内的数字页码链接
        soup = _make_soup(html)
        ptt = soup.find('table', class_='ptt')
        if ptt is not None:
            nums = []
            for a in ptt.find_all('a'):
                t = (a.get_text(strip=True) or '')
                if t.isdigit():
                    nums.append(int(t))
            if nums:
                return max(nums)

        # 2) 旧版：<td onclick="..."><a>N</a></td>
        page_find_all = re.findall(
            r'<td onclick="document.location=this.firstChild.href">.*?<a.*?>(.*?)</a>.*?</td>',
            html,
            re.S,
        )
        if len(page_find_all) > 1:
            try:
                return int(page_find_all[-2])
            except (TypeError, ValueError):
                pass

        return 1

    def _parse_gallery(self) -> tuple:
        """解析画廊首页，返回 (标题, 分页总数)"""
        self._emit_log(f'正在连接画廊：{self.config.url}')
        resp = self._safe_get(self.config.url)
        html_text = resp.text
        self._check_html_limited(html_text)

        title_match = re.search(r'<title>(.*?)</title>', html_text, re.S)
        if not title_match:
            raise DownloadError('无法从页面解析出标题，请检查 URL 是否正确')
        title = title_match.group(1).strip()

        page_total = self._parse_page_total(html_text)
        return title, page_total

    def _get_page_image_urls(self, page_index: int) -> list:
        """解析某一分页下所有图片详情页的 URL"""
        base = self.config.url.rstrip('/') + '/'
        suffix = '' if page_index == 0 else f'?p={page_index}'
        page_url = base + suffix

        self._emit_log(f'正在解析第 {page_index + 1}/{self._progress.page_total} 页...')
        resp = self._safe_get(page_url)
        html_text = resp.text
        self._check_html_limited(html_text)

        soup = _make_soup(html_text)
        urls: list = []
        # 1) 按 id="gdt" 匹配（不再依赖 class）
        gdt = soup.find('div', id='gdt')
        if gdt is not None:
            urls = re.findall(r'<a href="(.*?)"', str(gdt), re.S)
        else:
            # 2) 回退：任意包含 /s/ 的详情链接
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                if '/s/' in href and href.startswith('http'):
                    urls.append(href)

        # 去重保序
        seen = set()
        result = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                result.append(u)

        if not result:
            self._emit_log(f'第 {page_index + 1} 页未找到图片列表，已跳过', 'warning')
        return result

    def _resolve_image_url(self, detail_url: str) -> str:
        """从图片详情页解析出原始图片 URL（多来源兼容）"""
        if self._stop_event.is_set():
            raise DownloadError('任务已停止')
        resp = self._safe_get(detail_url)
        html_text = resp.text
        self._check_html_limited(html_text)

        # 1) 标准：<img id="img" src="...">
        m = re.search(r'<img[^>]+id="img"[^>]+src="([^"]+)"', html_text, re.S)
        if m:
            return unescape(m.group(1))
        # 2) og:image
        m = re.search(
            r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html_text, re.S)
        if m:
            return unescape(m.group(1))
        # 3) #i7 容器内的第一张图
        soup = _make_soup(html_text)
        i7 = soup.find(id='i7')
        if i7 is not None:
            img = i7.find('img')
            if img is not None and img.get('src'):
                return unescape(img['src'])

        raise DownloadError(f'无法解析图片地址：{detail_url}')

    # ------------------------------------------------------------------
    # 图片保存（含格式转换与内容校验）
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_ext(image_url: str) -> str:
        """从 URL 提取扩展名，默认 jpg"""
        match = re.search(r'\.([^.]+)$', image_url)
        return match.group(1) if match else 'jpg'

    def _target_name(self, image_url: str, page_num: int, number: int) -> str:
        """计算目标文件名（与 _save_image 保持一致）"""
        fmt = (self.config.image_format or '').strip().lower()
        fmt = 'jpeg' if fmt == 'jpg' else fmt
        if fmt:
            ext = {'jpeg': 'jpg', 'png': 'png', 'webp': 'webp'}.get(fmt, 'jpg')
        else:
            ext = self._parse_ext(image_url)
        return f'{page_num}-{number}.{ext}'

    @staticmethod
    def _looks_like_image(data: bytes) -> bool:
        """图片魔数校验：防止反爬返回的错误页 HTML 被当成成功图片保存"""
        if not data:
            return False
        if data[:3] == b'\xff\xd8\xff':      # jpg
            return True
        if data[:8] == b'\x89PNG\r\n\x1a\n':  # png
            return True
        if data[:4] == b'GIF8':               # gif
            return True
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':  # webp
            return True
        if data[:2] == b'BM':                 # bmp
            return True
        return False

    def _save_image(self, data: bytes, image_url: str, page_num: int, number: int, save_dir: Path) -> None:
        """保存图片。当 image_format 指定时使用 Pillow 转换格式"""
        fmt = (self.config.image_format or '').strip().lower()
        fmt = 'jpeg' if fmt == 'jpg' else fmt

        full_name = self._target_name(image_url, page_num, number)

        # 保持原始格式
        if not fmt:
            (save_dir / full_name).write_bytes(data)
            return

        # 需要格式转换
        if not PILLOW_AVAILABLE:
            raise DownloadError('需要格式转换但 Pillow 未安装，请在设置中选择"原始格式"')

        fmt_map = {
            'jpeg': ('JPEG', 'jpg'),
            'png': ('PNG', 'png'),
            'webp': ('WEBP', 'webp'),
        }
        if fmt not in fmt_map:
            raise DownloadError(f'不支持的图片格式：{self.config.image_format}')

        pil_fmt, ext_name = fmt_map[fmt]
        image = Image.open(io.BytesIO(data))

        # JPEG 不支持透明通道，需转 RGB
        if pil_fmt == 'JPEG' and image.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        elif pil_fmt == 'JPEG' and image.mode == 'P':
            image = image.convert('RGB')
        elif pil_fmt == 'WEBP' and image.mode == 'P':
            image = image.convert('RGBA')
        elif image.mode == 'P':
            image = image.convert('RGB')

        out_buf = io.BytesIO()
        if pil_fmt == 'JPEG':
            image.save(out_buf, format='JPEG', quality=95)
        elif pil_fmt == 'PNG':
            image.save(out_buf, format='PNG', optimize=True)
        else:
            image.save(out_buf, format='WEBP', quality=90)

        (save_dir / full_name).write_bytes(out_buf.getvalue())

    def _download_one(self, image_url: str, page_num: int, number: int) -> None:
        """下载单张图片，失败自动重试（指数退避，可中断，限流长退避）"""
        save_dir = self._output_path
        max_retries = max(0, self.config.per_file_retries)
        last_error: Optional[Exception] = None

        # 已存在且非空 → 跳过（断点续传 / 重复运行幂等）
        target = save_dir / self._target_name(image_url, page_num, number)
        if target.exists() and target.stat().st_size > 0:
            self._emit_log(f'第 {page_num} 页第 {number} 张已存在，跳过', 'info')
            self._progress.task_status[(page_num, number)] = 'skipped'
            return

        rl_attempts = 0
        for attempt in range(1, max_retries + 2):
            if self._stop_event.is_set():
                return
            try:
                resp = self._safe_get(image_url, stream=True)
                data = self._read_stream(resp)
                if not self._looks_like_image(data):
                    raise DownloadError('下载内容不是有效图片（可能被反爬拦截）')
                self._save_image(data, image_url, page_num, number, save_dir)
                self._progress.task_status[(page_num, number)] = 'downloaded'
                if attempt > 1:
                    self._emit_log(
                        f'第 {page_num} 页第 {number} 张重试成功（第 {attempt} 次尝试）', 'success'
                    )
                return
            except RateLimitError as e:
                if self._stop_event.is_set():
                    return
                rl_attempts += 1
                delay = min(60.0, 10.0 * rl_attempts) + random.uniform(0, 1)
                self._emit_log(
                    f'第 {page_num} 页第 {number} 张访问受限：{e}\n'
                    f'将在 {delay:.0f} 秒后重试...',
                    'warning',
                )
                if self._stop_event.wait(delay):
                    return
                if rl_attempts >= 5:
                    raise DownloadError(f'持续访问受限：{e}')
                continue  # 限流不算普通失败次数
            except Exception as e:  # noqa: BLE001
                if self._stop_event.is_set():
                    return
                last_error = e
                if attempt <= max_retries:
                    delay = (self.config.retry_delay * (2 ** (attempt - 1))
                             + random.uniform(0, 1))
                    self._emit_log(
                        f'第 {page_num} 页第 {number} 张下载失败：{e}\n'
                        f'将在 {delay:.1f} 秒后重试（{attempt}/{max_retries + 1}）...',
                        'warning',
                    )
                    if self._stop_event.wait(delay):
                        return
                else:
                    raise DownloadError(
                        f'重试 {max_retries} 次后仍失败：{last_error}') from last_error

    def _worker(self, task: tuple) -> None:
        """单个图片任务：task = (page_num, number, detail_url, known_image_url)

        全程可中断；解析成功后的图片直链会记录，供「重试失败」直接复用。
        """
        page_num, number, detail_url, known_image_url = task
        if self._stop_event.is_set():
            return
        self._progress.current = f'第 {page_num} 页 第 {number} 张'
        self._emit_progress()

        max_retries = max(0, self.config.per_file_retries)
        image_url = known_image_url
        last_error: Optional[Exception] = None
        rl_attempts = 0

        for attempt in range(1, max_retries + 2):
            if self._stop_event.is_set():
                return
            try:
                if not image_url:
                    image_url = self._resolve_image_url(detail_url)
                    self._task_image_urls[(page_num, number)] = image_url
                self._download_one(image_url, page_num, number)
                return
            except RateLimitError as e:
                if self._stop_event.is_set():
                    return
                rl_attempts += 1
                delay = min(60.0, 10.0 * rl_attempts) + random.uniform(0, 1)
                self._emit_log(
                    f'第 {page_num} 页第 {number} 张访问受限：{e}\n'
                    f'将在 {delay:.0f} 秒后重试...',
                    'warning',
                )
                if self._stop_event.wait(delay):
                    return
                if rl_attempts >= 5:
                    raise DownloadError(f'持续访问受限：{e}')
                continue  # 限流不算普通失败次数
            except DownloadError:
                # 图片下载内部已重试过，直接抛出（与源码一致）；
                # 若因停止抛出则静默返回
                if self._stop_event.is_set():
                    return
                raise
            except Exception as e:  # noqa: BLE001
                if self._stop_event.is_set():
                    return
                last_error = e
                if attempt <= max_retries:
                    delay = (self.config.retry_delay * (2 ** (attempt - 1))
                             + random.uniform(0, 1))
                    self._emit_log(
                        f'第 {page_num} 页第 {number} 张详情解析失败：{e}\n'
                        f'将在 {delay:.1f} 秒后重试（{attempt}/{max_retries + 1}）...',
                        'warning',
                    )
                    if self._stop_event.wait(delay):
                        return
        raise DownloadError(f'任务重试 {max_retries} 次后仍失败：{last_error}')

    # ------------------------------------------------------------------
    # 任务列表并发下载
    # ------------------------------------------------------------------
    def _download_task_list(self, tasks: list) -> tuple:
        """并发下载任务列表，返回 (done, failed)

        tasks: [(page, num, detail_url, known_image_url), ...]
        """
        done = 0
        failed = 0
        self._progress.failed_tasks.clear()

        executor = ThreadPoolExecutor(max_workers=max(self.config.concurrency, 1))
        self._executor = executor
        future_map = {}
        try:
            # 提交所有任务
            for task in tasks:
                if self._stop_event.is_set():
                    break
                future = executor.submit(self._worker, task)
                future_map[future] = (task[0], task[1], task[2])  # (page, num, detail_url)

            # 轮询等待完成（每 0.2 秒检查一次停止标志）
            while future_map and not self._stop_event.is_set():
                finished_futures = set()
                for future in list(future_map):
                    if future.done():
                        page_idx, num, detail_url = future_map[future]
                        try:
                            future.result()
                            done += 1
                            self._progress.task_status.setdefault((page_idx, num), 'downloaded')
                        except Exception as e:  # noqa: BLE001
                            failed += 1
                            self._progress.failed_tasks.append((page_idx, num, detail_url))
                            self._progress.task_status[(page_idx, num)] = 'failed'
                            self._emit_log(
                                f'下载失败：第 {page_idx} 页第 {num} 张 - {e}', 'error'
                            )
                        self._progress.done = done
                        self._progress.failed = failed
                        self._emit_progress()
                        finished_futures.add(future)
                for f in finished_futures:
                    del future_map[f]
                if future_map and not self._stop_event.is_set():
                    time.sleep(0.2)

            # 停止时取消未完成的任务，并把尚未完成的记入失败列表
            # （便于「重试失败」按钮续传剩余图片）
            if self._stop_event.is_set():
                for f in future_map:
                    f.cancel()
                for page_idx, num, detail_url in future_map.values():
                    task = (page_idx, num, detail_url)
                    if task not in self._progress.failed_tasks:
                        self._progress.failed_tasks.append(task)
                if future_map:
                    self._progress.failed = failed + len(future_map)
                    self._emit_progress()
        finally:
            # 不等待线程结束，立即释放线程池
            executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

        return done, failed

    def run_failed(self) -> None:
        """重新下载上次失败的图片（直接复用已解析的图片直链，可中断）"""
        failed_tasks = list(self._failed_tasks)
        self._stop_event.clear()
        self._progress = DownloadProgress()
        self._emit_locked = False

        if not failed_tasks:
            self._emit_log('没有可重试的失败任务。', 'warning')
            self._progress.finished = True
            self._emit_progress()
            self._emit_finished()
            return

        try:
            self.session = self._build_session()

            # 输出目录（沿用上次解析的标题）
            root = Path(self.config.output_dir or './')
            self._output_path = root / re.sub(r'[\\/:*?"<>|]', ' ', self._title)
            self._output_path.mkdir(parents=True, exist_ok=True)

            self._progress.total = len(failed_tasks)
            self._emit_log(f'开始重试 {len(failed_tasks)} 张失败图片...')

            tasks = []
            for page, num, detail_url in failed_tasks:
                known = self._task_image_urls.get((page, num), '')
                tasks.append((page, num, detail_url, known))

            done, failed = self._download_task_list(tasks)
            self._failed_tasks = list(self._progress.failed_tasks)

            # 收尾
            self._progress.finished = True
            if self._stop_event.is_set():
                self._emit_log('重试任务已手动停止。', 'warning')
            else:
                self._emit_log(f'重试完成！成功 {done} 张，失败 {failed} 张。')
                # 记录使用量（重试补齐成功张数 > 0）
                if done > 0:
                    _record_usage('download', self._title)
                # 全部补齐 -> 写完成标记
                if failed == 0 and done > 0:
                    try:
                        (self._output_path / '.ehentai_done').write_text(
                            time.strftime('%Y-%m-%d %H:%M:%S'), encoding='utf-8')
                    except Exception:
                        pass
                # 下载完成 -> 离线索引失效（下次扫描重建）
                _invalidate_ehentai_index()
            self._emit_progress()
            self._emit_finished()

        except Exception as e:  # noqa: BLE001
            self._emit_log(f'重试发生错误：{e}', 'error')
            self._progress.finished = True
            self._emit_progress()
            self._emit_finished()
        finally:
            self._emit_locked = True

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._stop_event.clear()
        self._progress = DownloadProgress()
        self._emit_locked = False
        try:
            self.session = self._build_session()

            # 1. 解析画廊
            title, page_total = self._parse_gallery()
            self._title = title
            self._progress.page_total = page_total
            _record_usage('parse', title)

            # 2. 创建输出目录（标题去除非法字符）
            root = Path(self.config.output_dir or './')
            self._output_path = root / re.sub(r'[\\/:*?"<>|]', ' ', title)
            self._output_path.mkdir(parents=True, exist_ok=True)

            self._emit_log(f'画廊标题：{title}')
            self._emit_log(f'共 {page_total} 页，保存到：{self._output_path}')

            # 3. 收集所有分页的图片详情页
            all_pages: list = []
            for p in range(page_total):
                if self._stop_event.is_set():
                    break
                urls = self._get_page_image_urls(p)
                if urls:
                    all_pages.append(urls)
                self._progress.page = p + 1
                self._emit_progress()

            total_images = sum(len(page_urls) for page_urls in all_pages)
            self._progress.total = total_images
            self._emit_progress()
            if total_images == 0:
                self._emit_log('未解析到任何图片，请检查画廊是否可访问（可能需要登录 Cookies）。',
                               'error')
            else:
                self._emit_log(f'共解析到 {total_images} 张图片，开始下载...')

            # 4. 构建任务列表
            tasks: list = []
            for page_idx, page_urls in enumerate(all_pages, start=1):
                for num, detail_url in enumerate(page_urls, start=1):
                    tasks.append((page_idx, num, detail_url, ''))

            # 5. 并发下载（手动管理 executor，支持立即停止）
            done, failed = self._download_task_list(tasks)
            self._failed_tasks = list(self._progress.failed_tasks)

            # 6. 收尾
            self._progress.finished = True
            if self._stop_event.is_set():
                self._emit_log(
                    f'任务已手动停止。已下载 {done} 张，剩余 {len(self._failed_tasks)} 张'
                    f'可用「重试失败」继续下载。',
                    'warning',
                )
            else:
                self._emit_log(f'下载完成！成功 {done} 张，失败 {failed} 张。')
                # 全部成功 -> 写完成标记（溯源：离线阅读识别已下载完成）
                if failed == 0 and done > 0:
                    try:
                        (self._output_path / '.ehentai_done').write_text(
                            time.strftime('%Y-%m-%d %H:%M:%S'), encoding='utf-8')
                    except Exception:
                        pass
                # 记录使用量（下载成功张数 > 0）
                if done > 0:
                    _record_usage('download', title)
                # 下载完成 -> 离线索引失效（下次扫描重建）
                _invalidate_ehentai_index()
            self._emit_progress()
            self._emit_finished()

        except RateLimitError as e:
            self._emit_log(f'访问受限：{e}。请稍等片刻后重试，或检查代理 / Cookies 配置。', 'error')
            self._progress.finished = True
            self._emit_progress()
            self._emit_finished()
        except Exception as e:  # noqa: BLE001
            self._emit_log(f'发生错误：{e}', 'error')
            self._progress.finished = True
            self._emit_progress()
            self._emit_finished()
        finally:
            # 锁住信号发射，防止后台线程后续仍发送信号
            self._emit_locked = True
