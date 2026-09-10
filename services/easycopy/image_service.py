# -*- coding: utf-8 -*-
"""拷贝漫画图片下载与内存/LRU 磁盘缓存（移植自 OGC-EasyCopy）。"""
from __future__ import annotations

import hashlib
import os
import threading
from typing import Dict, Optional

import requests


class ImageCache:
    """线程安全的 LRU 内存缓存 + 磁盘缓存。"""

    def __init__(self, cache_dir: str, memory_limit: int = 256):
        self.cache_dir = cache_dir
        self.memory_limit = memory_limit
        self._memory: Dict[str, bytes] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        os.makedirs(cache_dir, exist_ok=True)

    def _key(self, url: str) -> str:
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    def _disk_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, key)

    def get(self, url: str) -> Optional[bytes]:
        key = self._key(url)
        with self._lock:
            if key in self._memory:
                # 更新 LRU
                self._order.remove(key)
                self._order.append(key)
                return self._memory[key]
        # 磁盘
        path = self._disk_path(key)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    data = f.read()
                if data:
                    with self._lock:
                        self._memory[key] = data
                        self._order.append(key)
                        self._evict_locked()
                    return data
            except Exception:
                pass
        return None

    def put(self, url: str, data: bytes) -> None:
        if not data:
            return
        key = self._key(url)
        with self._lock:
            self._memory[key] = data
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
            self._evict_locked()
        path = self._disk_path(key)
        try:
            with open(path, "wb") as f:
                f.write(data)
        except Exception:
            pass

    def _evict_locked(self) -> None:
        while len(self._memory) > self.memory_limit and self._order:
            oldest = self._order.pop(0)
            self._memory.pop(oldest, None)

    def clear(self) -> None:
        with self._lock:
            self._memory.clear()
            self._order.clear()


class ImageFetcher:
    """图片下载器，带并发限制与去重。"""

    def __init__(self, cache: ImageCache, max_workers: int = 8):
        self.cache = cache
        self._semaphore = threading.BoundedSemaphore(max_workers)
        self._inflight: Dict[str, threading.Event] = {}
        self._inflight_data: Dict[str, Optional[bytes]] = {}
        self._lock = threading.RLock()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0"})

    def fetch(self, url: str) -> Optional[bytes]:
        if not url:
            return None
        cached = self.cache.get(url)
        if cached is not None:
            return cached
        # 去重：同一 URL 同时只下载一次
        with self._lock:
            if url in self._inflight:
                event = self._inflight[url]
            else:
                event = threading.Event()
                self._inflight[url] = event
        if event.is_set():
            return self._inflight_data.get(url)

        try:
            self._semaphore.acquire()
            try:
                data = self._do_download(url)
            finally:
                self._semaphore.release()
            if data:
                self.cache.put(url, data)
            with self._lock:
                self._inflight_data[url] = data
                event.set()
            return data
        except Exception:
            with self._lock:
                self._inflight_data[url] = None
                event.set()
            return None
        finally:
            with self._lock:
                # 延迟清理，避免竞态
                pass

    def _do_download(self, url: str) -> Optional[bytes]:
        try:
            resp = self._session.get(url, timeout=20, stream=True)
            if resp.status_code != 200:
                return None
            # 限制大小（约 20MB）
            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=8192):
                chunks.append(chunk)
                total += len(chunk)
                if total > 20 * 1024 * 1024:
                    break
            return b"".join(chunks)
        except Exception:
            return None
