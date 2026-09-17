# -*- coding: utf-8 -*-
"""统一封面缓存服务（按 gid，{下载根}/.cache/ehentai/cache/covers/{gid}.img）。

所有页面（我的收藏 / 详情 / 历史 / 主页 / 搜索 / 排行榜）共用同一张封面：
- 收藏漫画时 enqueue 下载封面入本地缓存（并显示下载进度）。
- 已缓存则该漫画各处直接用缓存，不重复下载。
- 线程池并发下载，避免阻塞 UI。

注意缓存**不在 data/ 里**：封面图属于大体积可再生物，统一放下载根目录的
.cache/ 下，避免程序目录被撑大（见 core.config 模块开头的目录职责划分）。
"""
import os

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap

from core.config import config as CFG

COVER_DIR = CFG.cache_path('ehentai', 'cache', 'covers')


class _CoverWorker(QThread):
    """单个封面下载线程（复用 ehviewer 连接池会话）。"""

    def __init__(self, gid, url, parent=None):
        super().__init__(parent)
        self.gid = gid
        self.url = url
        self.data = None

    def run(self):
        try:
            from ehviewer.session import make_image_session
            s = make_image_session()
            r = s.get(self.url, headers={'Referer': 'https://e-hentai.org/'}, timeout=12)
            self.data = r.content if (r.status_code == 200 and r.content) else None
        except Exception:
            self.data = None


def cover_path(gid):
    try:
        return os.path.join(COVER_DIR, f"{int(gid)}.img")
    except Exception:
        return ''

def gid_from_key(key):
    """从形如 thumb:12345 / detail:12345 / pv:12345:3 的 key 中提取 gid。"""
    try:
        for p in str(key).split(':'):
            if p.isdigit():
                return int(p)
    except Exception:
        pass
    return None

def first_page_url(gid, token):
    """获取画廊【第一页】缩略图 URL（单画面，via 引擎详情页预览集），失败返回 ''。"""
    try:
        from ehviewer import engine
        detail = engine.get_gallery_detail(int(gid), token)
        ps = getattr(detail, 'preview_set', None) or []
        if ps and ps[0]:
            item0 = ps[0][0] if ps[0] else None
            u = getattr(item0, 'image_url', '') or ''
            if u:
                from ehviewer.urls import get_fixed_preview_thumb_url
                return get_fixed_preview_thumb_url(u) or u
    except Exception:
        pass
    return ''


def fetch_first_page_image(gid, token):
    """用下载画廊的最快逻辑解析漫画，下载【第一张页图】（返回字节），失败返回 None。

    用于「没有画廊缩略图/缩略图失效」时的封面兜底：进详情页主动解析链接下载第一张图。
    """
    try:
        from services.ehentai_downloader import EhentaiDownloader, DownloadConfig
        from pages.album.ehentai_settings import ehentai_cfg as _c
        url = 'https://e-hentai.org/g/%s/%s/' % (gid, token)
        cfg = DownloadConfig(
            url=url, cookies=_c.get(_c.KEY_COOKIES, ''), headers=_c.get(_c.KEY_HEADERS, ''),
            proxy=_c.get(_c.KEY_PROXY, ''), ignore_env_proxy=bool(_c.get(_c.KEY_IGNORE_ENV_PROXY, True)),
            output_dir='', concurrency=1, timeout=20, image_format='', per_file_retries=2)
        dl = EhentaiDownloader(cfg)
        dl.session = dl._build_session()
        try:
            _t, page_total = dl._parse_gallery()
        except Exception:
            page_total = 0
        if not page_total:
            return None
        detail_urls = dl._get_page_image_urls(0)
        if not detail_urls:
            return None
        direct = dl._resolve_image_url(detail_urls[0])
        if not direct:
            return None
        from ehviewer.session import make_image_session
        r = make_image_session().get(direct, headers={'Referer': 'https://e-hentai.org/'}, timeout=12)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:
        return None
    return None


class _CoverWorker(QThread):
    """单个封面下载线程（优先抓【第一页缩略图】，失败回退给定 url）。"""

    def __init__(self, gid, url, token=None, parent=None):
        super().__init__(parent)
        self.gid = gid
        self.url = url
        self.token = token
        self.data = None
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            # 1) 优先用「画廊缩略图」（排行榜/主页/搜索卡片那张），规范化 URL
            data = None
            if self.url:
                try:
                    from ehviewer.session import make_image_session
                    from ehviewer.urls import get_fixed_preview_thumb_url
                    target = get_fixed_preview_thumb_url(self.url) or self.url
                    s = make_image_session()
                    r = s.get(target, headers={'Referer': 'https://e-hentai.org/'}, timeout=12)
                    if r.status_code == 200 and r.content:
                        data = r.content
                except Exception:
                    data = None
            # 2) 兜底：没有可靠画廊缩略图时，主动解析漫画并用最快逻辑下载第一张图
            if not data and self.token:
                try:
                    data = fetch_first_page_image(self.gid, self.token)
                except Exception:
                    data = None
            self.data = data
        except Exception:
            self.data = None


class CoverService(QObject):
    """按 gid 的统一封面缓存 + 并发下载队列"""

    loaded = pyqtSignal(int, object)      # (gid, QPixmap|None)
    progress = pyqtSignal(int, int)       # (done, total)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mem = {}
        self._workers = {}
        self._queue = []
        self._done = 0
        self._total = 0
        self._active = 0
        self._MAX = 4
        self._index = {}          # gid -> True（JSON 索引，加速加载）
        self._index_path = os.path.join(COVER_DIR, 'index.json')
        try:
            os.makedirs(COVER_DIR, exist_ok=True)
        except Exception:
            pass
        self._load_index()

    def _load_index(self):
        try:
            if os.path.isfile(self._index_path):
                with open(self._index_path, 'r', encoding='utf-8') as f:
                    import json as _j
                    data = _j.load(f)
                if isinstance(data, dict):
                    for k in data:
                        try:
                            self._index[int(k)] = True
                        except Exception:
                            pass
        except Exception:
            self._index = {}

    def _save_index(self):
        try:
            with open(self._index_path, 'w', encoding='utf-8') as f:
                import json as _j
                _j.dump({str(k): True for k in self._index}, f)
        except Exception:
            pass

    def load(self, gid):
        """读缓存封面；命中返回 QPixmap，否则 None。"""
        try:
            gid = int(gid)
        except Exception:
            return None
        if gid in self._mem:
            return self._mem[gid]
        p = cover_path(gid)
        if p and os.path.isfile(p):
            pix = QPixmap()
            if pix.load(p):
                self._mem[gid] = pix
                return pix
        return None

    def has(self, gid):
        try:
            gid = int(gid)
        except Exception:
            return False
        if gid in self._mem:
            return True
        if self._index.get(gid, False):
            return True
        return bool(cover_path(gid) and os.path.isfile(cover_path(gid)))

    def save(self, gid, pixmap):
        try:
            gid = int(gid)
            if pixmap is not None and not pixmap.isNull():
                self._mem[gid] = pixmap
                p = cover_path(gid)
                if p:
                    pixmap.save(p, 'PNG')
                self._index[gid] = True
                self._save_index()
        except Exception:
            pass

    def invalidate(self, gid):
        """删除某 gid 的缓存（内存+磁盘+索引），用于强制重新抓取。"""
        try:
            gid = int(gid)
            self._mem.pop(gid, None)
            self._index.pop(gid, None)
            p = cover_path(gid)
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
            self._save_index()
        except Exception:
            pass

    def enqueue(self, gid, url, token=None):
        """把某漫画封面加入下载队列（已缓存/正在下载则跳过）。token 用于抓第一页缩略图。"""
        try:
            gid = int(gid)
        except Exception:
            return
        if (not url and not token) or self.has(gid) or gid in self._workers or gid in self._queue_gids():
            return
        self._total += 1
        self._queue.append((gid, url, token))
        self._pump()

    def _queue_gids(self):
        return {g for g, _u, _t in self._queue}

    def _pump(self):
        while self._active < self._MAX and self._queue:
            gid, url, token = self._queue.pop(0)
            w = _CoverWorker(gid, url, token, self)
            self._workers[gid] = w
            w.finished.connect(lambda g=gid, t=w: self._on_done(g, t))
            self._active += 1
            w.start()

    def _on_done(self, gid, worker):
        self._active -= 1
        self._workers.pop(gid, None)
        self._done += 1
        data = getattr(worker, 'data', None)
        pix = QPixmap()
        ok = bool(data) and pix.loadFromData(data)
        if ok:
            self.save(gid, pix)
        self.loaded.emit(gid, pix if ok else None)
        self.progress.emit(self._done, self._total)
        self._pump()

    def shutdown(self):
        """停止并等待所有封面下载线程，避免退出时 QThread 运行中被销毁。"""
        self._queue = []
        for w in list(self._workers.values()):
            try:
                if hasattr(w, 'stop'):
                    w.stop()
                w.wait(2000)
            except Exception:
                pass
        self._workers.clear()


# 全局单例
cover_service = CoverService()


def _cleanup_threads():
    """程序退出前回收封面下载线程 + 清理阅读临时缓存（尽力而为）。"""
    try:
        cover_service.shutdown()
    except Exception:
        pass
    try:
        from ehviewer.ui.reader_window import clear_reader_cache
        clear_reader_cache()
    except Exception:
        pass


def ensure_exit_cleanup():
    """接线退出清理（幂等）。由宿主在子系统接线时调用。"""
    try:
        from PyQt5.QtWidgets import QApplication
        _app = QApplication.instance()
        if _app is not None:
            try:
                _app.aboutToQuit.disconnect(_cleanup_threads)
            except Exception:
                pass
            _app.aboutToQuit.connect(_cleanup_threads)
    except Exception:
        pass
