# -*- coding: utf-8 -*-
"""
拷贝漫画章节下载核心（无 GUI 依赖，可独立测试）
============================================
下载单个章节的所有漫画图片，保存到：
    {下载根目录}/easycopy-download/{漫画名}/{章节名}/{图片文件}

下载根目录 = OGC 程序下载目录（data 或设置中的 video_download_root），
与 douyin-download 同级，均为程序下载文件夹下的子文件夹。

特性：
1. 章节页 HTML 解析（AES 解密）后得到真实图片直链；
2. 流式分块写入 + 停止检查（停止立即生效，剩余任务记入失败列表）；
3. **自动重试**：单张图片失败自动重试（per_file_retries 次）；
4. **跳过已存在**：目录下已有且非空的文件直接跳过（断点续传幂等）；
5. **完成标记**：章节全部下载成功后写入 .easycopy_done 标记，
   重复下载时整章跳过（离线库也据此判定已下载完成）。
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import requests

from services.easycopy.config import DESKTOP_USER_AGENT
from services.easycopy.models import ReaderPageData
from services.easycopy.parser import SiteHtmlParser, make_soup


# 章节完成标记文件名
DONE_MARKER = ".easycopy_done"


def _record_usage(action: str, detail: str = ''):
    """记录 EasyCopy 使用行为（供仪表盘统计，函数内导入避免循环依赖）"""
    try:
        from core.database import record_usage
        record_usage('easycopy', action, detail)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  下载配置与进度
# ═══════════════════════════════════════════════════════════
@dataclass
class EasyCopyDownloadConfig:
    """单次章节下载配置。"""

    comic_title: str = ""          # 漫画名（用于目录命名）
    chapter_label: str = ""        # 章节名（用于目录命名）
    chapter_href: str = ""         # 章节页 URL（相对或绝对）
    output_root: str = ""          # 下载根目录（默认取 get_download_root()）
    concurrency: int = 4           # 图片并发数
    timeout: int = 30              # 单张图片超时
    per_file_retries: int = 3      # 单张图片重试次数
    chapter_retries: int = 2       # 章节页解析失败重试次数


@dataclass
class EasyCopyProgress:
    """下载进度。"""

    done: int = 0
    total: int = 0
    failed: int = 0
    current: str = ""
    finished: bool = False
    title: str = ""
    skipped: bool = False           # 整章跳过（已下载完成）


# ═══════════════════════════════════════════════════════════
#  下载器
# ═══════════════════════════════════════════════════════════
class EasyCopyDownloader:
    """下载指定章节的全部图片到 easycopy-download/漫画名/章节名/。"""

    def __init__(self, config: EasyCopyDownloadConfig, ctx=None):
        self.config = config
        # ctx: services.easycopy.app.AppContext（可选，提供解析器；缺失时自行解析）
        self._ctx = ctx
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._failed_tasks: List[str] = []
        self._listener: Optional[Callable] = None

    # ---------- 控制 ----------
    def set_listener(self, listener) -> None:
        """设置回调：listener(msg: str, level: str), listener.progress(EasyCopyProgress)"""
        self._listener = listener

    def stop(self) -> None:
        self._stop.set()

    def is_stopping(self) -> bool:
        return self._stop.is_set()

    # ---------- 日志 ----------
    def _log(self, msg: str, level: str = 'info') -> None:
        if self._listener is not None and hasattr(self._listener, 'on_log'):
            try:
                self._listener.on_log(msg, level)
            except Exception:
                pass

    def _report(self, progress: EasyCopyProgress) -> None:
        if self._listener is not None and hasattr(self._listener, 'on_progress'):
            try:
                self._listener.on_progress(progress)
            except Exception:
                pass

    # ---------- 目录 ----------
    def download_root(self) -> str:
        """EasyCopy 下载根目录：{程序下载目录}/easycopy-download"""
        root = self.config.output_root
        if not root:
            try:
                from services.download_manager import get_download_root
                root = get_download_root()
            except Exception:
                root = 'data'
        return os.path.join(root, 'easycopy-download')

    def chapter_dir(self) -> str:
        """当前章节的目标目录：easycopy-download/漫画名/章节名"""
        title = self._safe_name(self.config.comic_title or '未知漫画')
        chapter = self._safe_name(self.config.chapter_label or '未知章节')
        return os.path.join(self.download_root(), title, chapter)

    def _safe_name(self, name: str) -> str:
        """清洗目录名中的非法字符。"""
        if not name:
            return '未命名'
        name = name.strip()
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
        name = name.rstrip('. ')
        return name[:120] or '未命名'

    # ---------- 完成标记 ----------
    @staticmethod
    def is_chapter_done(chapter_path: str) -> bool:
        """判断章节是否已下载完成（存在完成标记）。"""
        return os.path.isfile(os.path.join(chapter_path, DONE_MARKER))

    def _mark_done(self, chapter_path: str) -> None:
        try:
            with open(os.path.join(chapter_path, DONE_MARKER), 'w', encoding='utf-8') as f:
                f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
        except Exception:
            pass

    # ---------- 主流程 ----------
    def run(self) -> EasyCopyProgress:
        """下载章节。"""
        self._stop.clear()
        self._failed_tasks = []

        cfg = self.config
        title = self._safe_name(cfg.comic_title or '未知漫画')
        chapter = self._safe_name(cfg.chapter_label or '未知章节')

        root = os.path.join(self.download_root(), title, chapter)
        os.makedirs(root, exist_ok=True)
        self._log(f'保存目录：{root}', 'info')

        progress = EasyCopyProgress(title=f'{title} · {chapter}')

        # 已下载完成 -> 整章跳过
        if self.is_chapter_done(root):
            existing = self._count_images(root)
            progress.total = existing
            progress.done = existing
            progress.skipped = True
            progress.finished = True
            self._log(f'[跳过] {cfg.chapter_label} 已下载完成（{existing} 张）。', 'success')
            self._report(progress)
            self._finish(progress)
            return progress

        # 1. 解析章节页，获取图片列表（解析失败自动重试）
        images: List[str] = []
        last_error: Optional[Exception] = None
        for attempt in range(1, max(1, cfg.chapter_retries) + 1):
            if self._stop.is_set():
                break
            self._log(f'正在解析章节：{cfg.chapter_label}（第 {attempt} 次）…', 'info')
            try:
                images = self._load_chapter_images(cfg.chapter_href)
                if images:
                    break
            except Exception as e:
                last_error = e
                time.sleep(0.8 * attempt)

        if not images:
            progress.failed = 1
            progress.finished = True
            self._log(f'章节解析失败：{last_error or "未能解析到任何图片"}', 'error')
            self._report(progress)
            self._finish(progress)
            return progress

        progress.total = len(images)
        self._log(f'共 {len(images)} 张图片，开始下载 …', 'info')
        self._report(progress)
        _record_usage('parse', cfg.comic_title or cfg.chapter_label)

        # 2. 逐张下载（自动重试 + 跳过已存在）
        for idx, url in enumerate(images):
            if self._stop.is_set():
                self._log('收到停止请求，正在停止…', 'warning')
                break

            done = idx
            target = self._target_path(root, url, idx)
            if target is not None and os.path.exists(target) and os.path.getsize(target) > 0:
                self._log(f'[已存在] {os.path.basename(target)}', 'info')
                progress.done = done + 1
                self._report(progress)
                continue

            ok = self._download_one(url, target, idx, progress)
            if ok:
                progress.done = done + 1
            else:
                progress.failed += 1
                self._failed_tasks.append(url)
            self._report(progress)

        # 3. 全部成功 -> 写完成标记
        if progress.failed == 0 and not self._stop.is_set() and progress.done >= progress.total:
            self._mark_done(root)
            self._log('章节全部下载完成，已标记。', 'success')

        # 下载完成 -> 离线索引失效（下次扫描重建）
        try:
            from services.comic_library import invalidate_index, default_index_path
            invalidate_index(default_index_path(self.download_root(), 'easycopy'))
        except Exception:
            pass

        finished = progress.done + progress.failed
        if self._stop.is_set():
            self._log(f'已停止：成功 {progress.done} 张，失败 {progress.failed} 张。', 'warning')
        else:
            self._log(
                f'下载完成：成功 {progress.done} 张，失败 {progress.failed} 张。',
                'success' if progress.failed == 0 else 'error',
            )
        # 记录使用量（下载成功张数 > 0）
        if progress.done > 0:
            _record_usage('download', cfg.comic_title or cfg.chapter_label)
        progress.finished = True
        self._report(progress)
        self._finish(progress)
        return progress

    # ---------- 内部 ----------
    def _finish(self, progress: EasyCopyProgress) -> None:
        if self._listener is not None and hasattr(self._listener, 'on_finished'):
            try:
                self._listener.on_finished(progress)
            except Exception:
                pass

    def _load_chapter_images(self, href: str) -> List[str]:
        """加载章节页并解析图片列表。"""
        if self._ctx is not None:
            page = self._ctx.load_page_sync(href)
            if isinstance(page, ReaderPageData):
                return list(page.images)
            return []

        # 无 ctx 时自行请求并解析
        from urllib.parse import urljoin

        base = 'https://www.2026copy.com/'
        url = urljoin(base, href)
        resp = requests.get(url, headers={'User-Agent': DESKTOP_USER_AGENT}, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f'HTTP {resp.status_code}')
        html = resp.content.decode('utf-8', errors='replace')
        soup = make_soup(html)
        page = SiteHtmlParser().parse_reader(url, html, soup)
        return list(page.images)

    def _target_path(self, root: str, url: str, idx: int) -> Optional[str]:
        """根据 URL 推断扩展名，生成目标文件路径。"""
        ext = self._guess_ext(url)
        if not ext:
            ext = '.jpg'
        return os.path.join(root, f'{idx + 1:04d}{ext}')

    @staticmethod
    def _guess_ext(url: str) -> str:
        m = re.search(r'\.(jpg|jpeg|png|webp|gif)(?:[?#].*)?$', url, re.I)
        if m:
            return '.' + m.group(1).lower()
        return ''

    @staticmethod
    def _count_images(chapter_path: str) -> int:
        """统计章节目录中的图片数量（不含标记文件）。"""
        count = 0
        try:
            for name in os.listdir(chapter_path):
                if name.startswith('.') or name.endswith('.part'):
                    continue
                if os.path.isfile(os.path.join(chapter_path, name)):
                    count += 1
        except Exception:
            pass
        return count

    def _download_one(self, url: str, target: Optional[str], idx: int, progress: EasyCopyProgress) -> bool:
        """下载单张图片（带重试）。"""
        last_error: Optional[Exception] = None
        for attempt in range(max(1, self.config.per_file_retries)):
            if self._stop.is_set():
                return False
            try:
                progress.current = f'({idx + 1}/{progress.total}) 第 {idx + 1} 张（重试 {attempt}）'
                self._report(progress)
                resp = requests.get(
                    url,
                    headers={'User-Agent': DESKTOP_USER_AGENT, 'Referer': self.config.chapter_href},
                    timeout=self.config.timeout,
                    stream=True,
                )
                if resp.status_code != 200:
                    raise RuntimeError(f'HTTP {resp.status_code}')
                if target is None:
                    resp.close()
                    return True
                self._write_stream(resp, target)
                # 内容校验：太小可能是错误页
                if os.path.getsize(target) < 512:
                    os.remove(target)
                    raise RuntimeError('内容过小，疑似错误响应')
                return True
            except Exception as e:
                last_error = e
                time.sleep(0.5 * (attempt + 1))
        self._log(f'图片下载失败：{os.path.basename(target or url)}（{last_error}）', 'error')
        return False

    def _write_stream(self, resp, target: str) -> None:
        """流式分块写入，期间检查停止。"""
        tmp = target + '.part'
        with open(tmp, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if self._stop.is_set():
                    resp.close()
                    f.close()
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
                    raise RuntimeError('已停止')
                if chunk:
                    f.write(chunk)
        os.replace(tmp, target)
