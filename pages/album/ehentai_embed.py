# -*- coding: utf-8 -*-
"""E-Hentai 模块内嵌 EhViewer 子系统的辅助。

职责：
1. wire_ehviewer_subsystem()：让 ehviewer 子系统使用共享数据库 + 注入 ctx 全局对象（幂等）。
2. DetailPage / ReaderPage：把 EhViewer 的详情/阅读【就地】封装为可嵌页（带返回按钮 + 线程回收），
   替代原来的独立弹窗（DetailWindow / ReaderWindow）。
"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget

from qfluentwidgets import FluentIcon, PushButton

from ehviewer.appctx import ctx
from ehviewer.session import make_session
from ehviewer.image_cache import ImageLoader
from ehviewer.downloader import DownloadManager
from ehviewer.ui.detail_window import DetailWindow
from ehviewer.ui.reader_window import ReaderWindow

from pages.album.ehentai_settings import ehentai_cfg
from pages.album.ehentai_bridge import route_to_shared_db, sync_ogc_to_ehviewer


def wire_ehviewer_subsystem():
    """让 ehviewer 子系统共享数据库 + 注入 ctx 全局对象。幂等，可多次调用。

    注意：不在此设置 ctx.main_window（由宿主 EhentaiPage 设置并提供 show_notify）。
    """
    # 数据库已统一：route_to_shared_db 会返回统一库路径，并（若旧库还在）
    # 把旧库数据并进去。这里仍把配置值传给它，仅为兼容用户手工留在配置里的旧路径。
    dbp = ehentai_cfg.get(ehentai_cfg.KEY_DB_PATH) or ""
    route_to_shared_db(dbp)
    sync_ogc_to_ehviewer(ehentai_cfg)
    # 退出前回收封面下载线程，避免 QThread: Destroyed while running
    try:
        from pages.album.eh_cover import ensure_exit_cleanup
        ensure_exit_cleanup()
    except Exception:
        pass
    if ctx.session_factory is None:
        ctx.session_factory = make_session
    if ctx.image_loader is None:
        ctx.image_loader = ImageLoader(make_session)
    if ctx.download_manager is None:
        ctx.download_manager = DownloadManager()
    # 订阅下载进度/完成，便于宿主展示
    return ctx


def make_show_notify(owner):
    """返回一个 show_notify(level, content) 回调，路由到 owner 的 InfoBar。"""
    def show_notify(level, content):
        try:
            kw = dict(position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=owner)
            if level == 'success':
                InfoBar.success('', content, **kw)
            elif level == 'warning':
                InfoBar.warning('', content, **kw)
            elif level == 'error':
                InfoBar.error('', content, **kw)
            else:
                InfoBar.info('', content, **kw)
        except Exception:
            pass
    return show_notify


class DetailPage(QWidget):
    """画廊详情就地页（带返回按钮；下载请求转发给宿主）。"""
    back_requested = pyqtSignal()
    download_requested = pyqtSignal(object, object)   # (info, label)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 36, 8, 4)
        lay.setSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.back_btn = PushButton(FluentIcon.RETURN, "返回", self)
        self.back_btn.clicked.connect(self.back_requested.emit)
        bar.addWidget(self.back_btn)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.detail = DetailWindow(info, self)
        # 详情页「下载」-> 转发给宿主，转交下载画廊
        self.detail.downloadRequested.connect(self._on_download_requested)
        lay.addWidget(self.detail, 1)

    def _on_download_requested(self, info, label):
        self.download_requested.emit(info, label)

    def shutdown(self):
        """回收嵌入的 DetailWindow 后台线程，避免返回时 QThread 运行中被销毁。"""
        try:
            w = getattr(self.detail, '_worker', None)
            if w is not None and w.isRunning():
                w.wait(2500)
        except Exception:
            pass
        # 回收详情页预览下载线程
        try:
            pv = getattr(self.detail, '_pv_worker', None)
            if pv is not None and pv.isRunning():
                pv.stop()
                pv.wait(2500)
        except Exception:
            pass


class ReaderPage(QWidget):
    """阅读就地页（带返回按钮）。"""
    back_requested = pyqtSignal()

    def __init__(self, info, start_page=0, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 36, 8, 4)
        lay.setSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.back_btn = PushButton(FluentIcon.RETURN, "返回", self)
        self.back_btn.clicked.connect(self.back_requested.emit)
        bar.addWidget(self.back_btn)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.reader = ReaderWindow(info, start_page, self)
        lay.addWidget(self.reader, 1)

    def shutdown(self):
        """回收嵌入的 ReaderWindow 后台线程 / 线程池。"""
        try:
            r = self.reader
            cw = getattr(r, '_count_worker', None)
            if cw is not None and cw.isRunning():
                cw.wait(3000)
            pool = getattr(r, '_pool', None)
            if pool is not None:
                pool.waitForDone(3000)
        except Exception:
            pass
