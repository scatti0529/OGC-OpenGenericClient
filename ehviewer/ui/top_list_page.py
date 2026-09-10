# -*- coding: utf-8 -*-
"""排行榜页：类别（画廊/上传者/标签/H@H/Tracker/清理者）× 时间段（昨天/近一月/近一年/有史以来）"""
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from qfluentwidgets import (CardWidget, SubtitleLabel, ComboBox, PrimaryPushButton,
                            CaptionLabel, ScrollArea, StrongBodyLabel, BodyLabel,
                            InfoBar, InfoBarPosition)

from .. import engine
from .. import constants as C
from .. import db
from ..parsers import parse_top_list_names
from .gallery_list_page import GalleryListPage
from .bus import bus

# (类别码, 中文名, 是否画廊列表)
TOP_CATEGORIES = [
    ("1", "画廊", True),
    ("2", "上传者", False),
    ("3", "标签", False),
    ("4", "Hentai@Home", False),
    ("5", "EH Tracker", False),
    ("6", "清理者", False),
]
# 时间段 -> tl 末位
TOP_PERIODS = [("5", "昨天"), ("3", "近一月"), ("2", "近一年"), ("1", "有史以来")]


class _NameWorker(QThread):
    done = pyqtSignal(object, str)   # items, error

    def __init__(self, url, parent=None):
        super(_NameWorker, self).__init__(parent)
        self._url = url

    def run(self):
        try:
            body = engine.get_session().get(self._url, timeout=30).text
            self.done.emit(parse_top_list_names(body), "")
        except Exception as e:
            self.done.emit(None, str(e))


class TopListPage(QWidget):
    nameLoaded = pyqtSignal(object, str)

    def __init__(self, parent=None):
        super(TopListPage, self).__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        bar = CardWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(8)
        bl.addWidget(SubtitleLabel("排行榜"))
        self.cat_combo = ComboBox(self)
        for code, name, _g in TOP_CATEGORIES:
            self.cat_combo.addItem(name, userData=code)
        self.cat_combo.setFixedWidth(140)
        self.cat_combo.currentIndexChanged.connect(lambda _i: self._reload())
        bl.addWidget(self.cat_combo)
        self.period_combo = ComboBox(self)
        for code, name in TOP_PERIODS:
            self.period_combo.addItem(name, userData=code)
        self.period_combo.setFixedWidth(110)
        self.period_combo.currentIndexChanged.connect(lambda _i: self._reload())
        bl.addWidget(self.period_combo)
        self.refresh_btn = PrimaryPushButton("加载", self)
        self.refresh_btn.clicked.connect(lambda: self._reload(reset=True))
        bl.addWidget(self.refresh_btn)
        self.count_label = CaptionLabel("", self)
        bl.addWidget(self.count_label)
        bl.addStretch(1)
        root.addWidget(bar)

        # 画廊榜单：列表；其他：排名列表
        self.list_page = GalleryListPage("排行榜", self)
        self.list_page.set_loader(self._gallery_loader)
        root.addWidget(self.list_page, 1)

        self.name_scroll = ScrollArea(self)
        self.name_scroll.setWidgetResizable(True)
        self._name_container = QWidget(self.name_scroll)
        self._name_lay = QVBoxLayout(self._name_container)
        self._name_lay.setContentsMargins(8, 8, 8, 8)
        self._name_lay.setSpacing(6)
        self._name_lay.addStretch(1)
        self.name_scroll.setWidget(self._name_container)
        root.addWidget(self.name_scroll, 1)
        self.name_scroll.hide()

        self._loaded_once = False

    def showEvent(self, event):
        super(TopListPage, self).showEvent(event)
        if not self._loaded_once:
            self._loaded_once = True
            self._reload(reset=True)

    def _current(self):
        cat = self.cat_combo.currentData() or "1"
        per = self.period_combo.currentData() or "5"
        return cat, per

    def _is_gallery(self):
        cat, _ = self._current()
        for code, _n, g in TOP_CATEGORIES:
            if code == cat:
                return g
        return True

    def _reload(self, reset=False):
        if self._is_gallery():
            self.name_scroll.hide()
            self.list_page.show()
            self.list_page.reload()
        else:
            self.list_page.hide()
            self.name_scroll.show()
            self.refresh_btn.setEnabled(False)
            self.refresh_btn.setText("加载中…")
            self._name_worker = _NameWorker(self._url(), self)
            self._name_worker.done.connect(self._on_names_loaded)
            self._name_worker.start()

    def _on_names_loaded(self, items, err):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("加载")
        if err:
            self.count_label.setText("加载失败：" + err[:60])
            return
        self._render_names(items or [])

    def _url(self, token=0):
        cat, per = self._current()
        if isinstance(token, str) and token.startswith("http"):
            return token
        url = engine.urls.get_top_list_url() + "?tl=%s%s" % (cat, per)
        if token:
            url += "&p=%d" % token
        return url

    def _gallery_loader(self, token, page_size):
        result = engine.get_top_list("", self._url(token))
        self.count_label.setText("共 %d 项" % len(result.items))
        nxt = result.next_href or result.next_page
        return result.items, nxt

    def _render_names(self, items):
        # 清空
        while self._name_lay.count():
            item = self._name_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.count_label.setText("共 %d 项" % len(items))
        if not items:
            self._name_lay.addWidget(BodyLabel("（无数据，该榜单可能无法解析）"))
            self._name_lay.addStretch(1)
            return
        cat, _ = self._current()
        for it in items[:100]:
            row = CardWidget(self._name_container)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 6, 14, 6)
            rl.setSpacing(10)
            rank = StrongBodyLabel("#" + it["rank"])
            rank.setFixedWidth(56)
            score = CaptionLabel(it["score"])
            score.setFixedWidth(120)
            name = BodyLabel(it["name"])
            name.setTextInteractionFlags(Qt.TextSelectableByMouse)
            rl.addWidget(rank)
            rl.addWidget(score)
            rl.addWidget(name, 1)
            self._name_lay.insertWidget(self._name_lay.count() - 1, row)
            if it.get("href"):
                name.setToolTip("点击搜索：" + it["name"])
                row._href = it["href"]
                row.mouseReleaseEvent = lambda e, r=row: self._on_name_clicked(r)
        self._name_lay.addStretch(1)

    def _on_name_clicked(self, row):
        href = getattr(row, "_href", "") or ""
        if "/uploader/" in href:
            name = href.rsplit("/", 1)[-1]
            from urllib.parse import unquote
            bus.doSearch.emit(unquote(name), C.MODE_UPLOADER)
        elif "/tag/" in href:
            name = href.rsplit("/", 1)[-1]
            from urllib.parse import unquote
            bus.doSearch.emit(unquote(name), C.MODE_TAG)
        else:
            bus.notify.emit("info", "链接：" + href)
