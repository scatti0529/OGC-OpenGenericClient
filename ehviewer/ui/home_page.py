# -*- coding: utf-8 -*-
"""主页：图片配额卡 + 热门/最新画廊列表"""
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (CardWidget, BodyLabel, CaptionLabel, StrongBodyLabel,
                            SubtitleLabel, PrimaryPushButton, PushButton, SegmentedWidget,
                            InfoBar, InfoBarPosition, ProgressBar, FluentIcon)

from .. import constants as C
from .. import engine
from ..config import is_login
from .gallery_list_page import GalleryListPage
from .bus import bus


class LimitWorker(QThread):
    done = pyqtSignal(object, str)

    def __init__(self, parent=None):
        super(LimitWorker, self).__init__(parent)

    def run(self):
        try:
            detail = engine.get_home_detail()
            self.done.emit(detail.limit_html, "")
        except Exception as e:
            self.done.emit(None, str(e))


class HomePage(QWidget):
    def __init__(self, parent=None):
        super(HomePage, self).__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 配额卡
        self.limit_card = CardWidget(self)
        lc = QHBoxLayout(self.limit_card)
        lc.setContentsMargins(16, 12, 16, 12)
        lc.setSpacing(12)
        self.limit_label = StrongBodyLabel("图片配额：未登录", self)
        self.limit_bar = ProgressBar(self)
        self.limit_bar.setRange(0, 100)
        self.limit_bar.setFixedWidth(220)
        self.limit_bar.setValue(0)
        self.reset_btn = PushButton("重置配额", self)
        self.reset_btn.setEnabled(False)
        self.reset_btn.clicked.connect(self._reset_limit)
        self.refresh_btn = PushButton("刷新", self)
        self.refresh_btn.clicked.connect(self._load_limit)
        lc.addWidget(self.limit_label)
        lc.addWidget(self.limit_bar)
        lc.addStretch(1)
        lc.addWidget(self.refresh_btn)
        lc.addWidget(self.reset_btn)
        root.addWidget(self.limit_card)

        # 分段：热门 / 最新
        self.seg = SegmentedWidget(self)
        self.seg.addItem(routeKey="hot", text="热门 (Popular)")
        self.seg.addItem(routeKey="latest", text="最新 (Latest)")
        self.seg.setCurrentItem("hot")
        self.seg.currentItemChanged.connect(self._on_seg_changed)
        root.addWidget(self.seg, 0, Qt.AlignHCenter)

        # 热门列表
        self.hot_page = GalleryListPage("热门画廊", self)
        self.hot_page.set_simple_mode(True)
        self.hot_page.set_loader(self._load_hot)
        self.latest_page = GalleryListPage("最新画廊", self)
        self.latest_page.set_simple_mode(True)
        self.latest_page.set_loader(self._load_latest)

        self.stack = QWidget(self)
        sv = QVBoxLayout(self.stack)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.addWidget(self.hot_page)
        sv.addWidget(self.latest_page)
        self.latest_page.hide()
        root.addWidget(self.stack, 1)

        bus.loginChanged.connect(lambda _l: self._load_limit())
        self._limit_worker = None

    def showEvent(self, event):
        super(HomePage, self).showEvent(event)
        if getattr(self, "_loaded_once", False) is False:
            self._loaded_once = True
            self.hot_page.reload()
            self._load_limit()

    def _on_seg_changed(self, key):
        if key == "hot":
            self.latest_page.hide()
            self.hot_page.show()
        else:
            self.hot_page.hide()
            self.latest_page.show()
            self.latest_page.reload()

    # ---------- 数据 ----------
    def _load_hot(self, token, page_size):
        """热门列表：支持页码与游标两种翻页"""
        if isinstance(token, str) and token:
            url = token
        else:
            url = engine.urls.get_popular_url()
            if token:
                url = url + ("?p=%d" % token)
        result = engine.get_gallery_list(url, C.MODE_WHATS_HOT)
        nxt = result.next_href or result.next_page
        if nxt is None and not isinstance(token, str) and len(result.items) >= page_size:
            nxt = (token or 0) + 1
        return result.items, nxt

    def _load_latest(self, token, page_size):
        """最新列表：使用 next= 游标翻页"""
        if isinstance(token, str) and token:
            url = token
        else:
            url = engine.urls.get_host()
        result = engine.get_gallery_list(url, C.MODE_NORMAL)
        nxt = result.next_href or None
        return result.items, nxt

    def _load_limit(self):
        if not is_login():
            self.limit_label.setText("图片配额：未登录（登录后可查看配额并重置）")
            self.limit_bar.setValue(0)
            self.reset_btn.setEnabled(False)
            return
        self._limit_worker = LimitWorker(self)
        self._limit_worker.done.connect(self._on_limit)
        self._limit_worker.start()

    def _on_limit(self, limit, err):
        if limit is not None and isinstance(limit, dict):
            used, total = limit.get("used", 0), limit.get("total", 0)
            pct = int(used * 100.0 / total) if total else 0
            self.limit_label.setText("图片配额：%s / %s （重置需 %s GP）" % (used, total, limit.get("reset_cost", "?")))
            self.limit_bar.setValue(min(100, pct))
            self.reset_btn.setEnabled(total > 0)
        elif err:
            self.limit_label.setText("图片配额：获取失败（%s）" % err[:60])

    def _reset_limit(self):
        def _do():
            try:
                engine.reset_image_limit()
                bus.notify.emit("success", "配额已重置")
            except Exception as e:
                bus.notify.emit("error", "重置失败：" + str(e))
        import threading
        threading.Thread(target=_do, daemon=True).start()
