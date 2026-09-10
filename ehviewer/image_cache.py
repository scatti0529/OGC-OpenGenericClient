# -*- coding: utf-8 -*-
"""图片缓存：磁盘缓存 + 内存缓存 + 后台加载线程池（缩略图与阅读图片共用，线程本地会话复用）"""
import hashlib
import os
import threading

from PyQt5.QtCore import QObject, QThreadPool, QRunnable, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QImageReader

from . import urls
from .config import get

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ehentai", "cache")
MAX_DISK_CACHE = 800 * 1024 * 1024
_lock = threading.Lock()
_sizes = None
_local = threading.local()          # 线程本地会话


def _cache_path(key):
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, h[:2], h + ".img")


def _disk_size():
    global _sizes
    with _lock:
        if _sizes is None:
            total = 0
            for root, _, files in os.walk(CACHE_DIR):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            _sizes = total
        return _sizes


def _bump_disk_size(delta):
    global _sizes
    with _lock:
        if _sizes is not None:
            _sizes += delta


def _trim_disk():
    try:
        while _disk_size() > MAX_DISK_CACHE:
            entries = []
            for root, _, files in os.walk(CACHE_DIR):
                for f in files:
                    p = os.path.join(root, f)
                    try:
                        entries.append((os.path.getmtime(p), p))
                    except OSError:
                        pass
            if not entries:
                break
            entries.sort()
            _, oldest = entries[0]
            try:
                sz = os.path.getsize(oldest)
                os.remove(oldest)
                _bump_disk_size(-sz)
            except OSError:
                _bump_disk_size(-1)
    except Exception:
        pass


def load_from_disk(key):
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            os.remove(path)
            return None
        max_dim = 4096
        if img.width() > max_dim or img.height() > max_dim:
            img = img.scaled(max_dim, max_dim, 1, 1)
        return QPixmap.fromImage(img)
    except Exception:
        return None


def save_to_disk(key, data):
    try:
        os.makedirs(os.path.dirname(_cache_path(key)), exist_ok=True)
        tmp = _cache_path(key) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, _cache_path(key))
        _bump_disk_size(len(data))
        _trim_disk()
    except Exception:
        pass


def _image_session():
    """线程本地轻量会话：无重试、连接池复用，用于图片下载"""
    s = getattr(_local, "session", None)
    if s is None:
        from .session import make_image_session
        s = make_image_session()
        _local.session = s
    return s


class FetchTask(QRunnable):
    """后台加载：内存 -> 磁盘 -> 网络（轻量会话）"""

    def __init__(self, key, url, referer, callback, is_thumb=False):
        super(FetchTask, self).__init__()
        self.key = key
        self.url = url
        self.referer = referer
        self.callback = callback
        self.is_thumb = is_thumb

    def run(self):
        pix = load_from_disk(self.key)
        if pix is not None and not pix.isNull():
            self.callback(self.key, self.url, pix)
            return
        headers = {"Referer": self.referer or urls.get_referer()}
        data = None
        for _attempt in (1, 2):  # 失败重试一次，降低瞬时失败导致的空白封面
            try:
                s = _image_session()
                r = s.get(self.url, headers=headers, timeout=8)
                if r.status_code == 200 and len(r.content) >= 100:
                    data = r.content
                    break
            except Exception:
                data = None
        if not data:
            return
        try:
            img = QImage.fromData(data)
            if img.isNull():
                return
            save_to_disk(self.key, data)
            pix = QPixmap.fromImage(img)
            if not pix.isNull():
                self.callback(self.key, self.url, pix)
        except Exception:
            pass


class PixmapCache(object):
    """内存 pixmap 缓存（简单 LRU，按数量上限）"""

    def __init__(self, max_count=800):
        self.max_count = max_count
        self._map = {}
        self._order = []

    def get(self, key):
        if key in self._map:
            self._order.remove(key)
            self._order.append(key)
            return self._map[key]
        return None

    def put(self, key, pixmap):
        if key in self._map:
            self._order.remove(key)
        self._map[key] = pixmap
        self._order.append(key)
        while len(self._order) > self.max_count:
            old = self._order.pop(0)
            self._map.pop(old, None)

    def clear(self):
        self._map.clear()
        self._order.clear()


class ImageLoader(QObject):
    """全局图片加载器：内存缓存优先，未命中走线程池并发抓取"""
    loaded = pyqtSignal(str, str, object)   # key, url, QPixmap

    def __init__(self, session_factory, parent=None):
        super(ImageLoader, self).__init__(parent)
        self._session_factory = session_factory
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(16)
        self._pending = {}
        self._mem = PixmapCache()

    def load(self, key, url, referer=None, is_thumb=False):
        pix = self._mem.get(key)
        if pix is not None and not pix.isNull():
            self.loaded.emit(key, url, pix)
            return
        if key in self._pending:
            return
        self._pending[key] = True
        task = FetchTask(key, url, referer, self._on_fetched, is_thumb)
        self._pool.start(task)

    def _on_fetched(self, key, url, pixmap):
        self._pending.pop(key, None)
        if pixmap is not None and not pixmap.isNull():
            self._mem.put(key, pixmap)
            self.loaded.emit(key, url, pixmap)

    def invalidate(self, key):
        self._mem.remove(key)

    def clear_memory(self):
        self._mem.clear()

    def shutdown(self):
        self._pool.clear()
        self._pending.clear()
        self._mem.clear()
