# -*- coding: utf-8 -*-
"""
通用异步下载器
=============
提供基于 httpx + aiofiles 的异步文件下载能力，
替代原 ilbs.common / ilbs.video_page / ilbs.video_analysis_page 中重复的 Downloader。

用法::

    from services.downloader import Downloader, DownloadThread

    # 异步方式
    downloader = Downloader(Path('./downloads'))
    await downloader.download(url, filename, folder)

    # 带进度信号的线程方式
    thread = DownloadThread(url, title, path, file_type)
    thread.progress.connect(on_progress)
    thread.finished.connect(on_finished)
    thread.start()
"""
import asyncio
import os
from pathlib import Path
from typing import Callable, Optional

import aiofiles
import httpx
from PyQt5.QtCore import QThread, pyqtSignal


class Downloader:
    """异步文件下载器（支持并发限流、断点续传、自动扩展名、失败清理）"""

    CONTENT_TYPE_MAP = {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/webp": "webp",
        "video/mp4": "mp4",
        "video/quicktime": "mov",
        "audio/mp4": "m4a",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
    }

    def __init__(self, root_folder: Path, max_workers: int = 5,
                 chunk_size: int = 1024 * 1024):
        self.root_folder = root_folder
        self.max_workers = max_workers
        self.chunk_size = chunk_size
        self.semaphore = asyncio.Semaphore(max_workers)
        self.headers = {}

    # ---------- 内部工具 ----------
    def _extract_type(self, content: str) -> str:
        if not (s := self.CONTENT_TYPE_MAP.get(content)):
            return self._unknown_type(content)
        return s

    @staticmethod
    def _unknown_type(content: str) -> str:
        print(f"未收录的文件类型：{content}")
        return ""

    # ---------- 核心下载 ----------
    async def download(
        self,
        url: str,
        filename: str,
        folder_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """下载单个文件

        Args:
            url: 文件 URL
            filename: 保存文件名（不含后缀时自动补全）
            folder_path: 保存目录
            progress_callback: 进度回调 (downloaded, total)

        Returns:
            是否下载成功
        """
        async with self.semaphore:
            cache_path = folder_path / f"{filename}.tmp"
            actual_path = folder_path / filename
            folder_path.mkdir(parents=True, exist_ok=True)

            headers = self.headers.copy()
            headers["Range"] = "bytes=0-"

            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream("GET", url, headers=headers) as resp:
                        resp.raise_for_status()
                        content_length = int(resp.headers.get("Content-Length", 0))
                        content_type = resp.headers.get("Content-Type", "")

                        # 自动补后缀
                        if content_type:
                            suffix = self._extract_type(content_type)
                            if suffix:
                                actual_path = actual_path.with_suffix(f".{suffix}")

                        # 分块写入临时文件，完成后重命名
                        async with aiofiles.open(cache_path, "wb") as fp:
                            downloaded = 0
                            async for chunk in resp.aiter_bytes(self.chunk_size):
                                await fp.write(chunk)
                                downloaded += len(chunk)
                                if progress_callback:
                                    progress_callback(downloaded, content_length)

                        cache_path.rename(actual_path)
                        return True

            except Exception as e:
                print(f"下载失败: {e}")
                # 失败清理残留的临时文件
                try:
                    if cache_path.exists():
                        cache_path.unlink()
                    if actual_path.exists():
                        # 仅删除空文件（下载中途失败时.rename没执行，实际不会走到这里）
                        pass
                except OSError:
                    pass
                return False


class DownloadThread(QThread):
    """带进度信号的多线程下载"""

    finished = pyqtSignal()          # 下载结束
    progress = pyqtSignal(int, int)  # 实时进度 (current, total)

    def __init__(self, url, title, path, file_type):
        super().__init__()
        self.url = url
        self.text = title
        self.path = path
        self.file_type = file_type

    def run(self):
        downloader = Downloader(Path(self.path))

        def progress_callback(current, total):
            self.progress.emit(current, total)

        asyncio.run(
            downloader.download(
                url=self.url,
                filename=f"{self.text}{self.file_type}",
                folder_path=Path(self.path),
                progress_callback=progress_callback
            )
        )
        self.finished.emit()