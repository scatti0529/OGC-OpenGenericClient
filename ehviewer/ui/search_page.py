# -*- coding: utf-8 -*-
"""搜索页：一般搜索 / 订阅 / 上传者 / 标签 模式 + 高级筛选"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (SegmentedWidget, SearchLineEdit, ComboBox, PushButton,
                            ToolButton, FluentIcon, SubtitleLabel, InfoBar,
                            InfoBarPosition, CardWidget, StrongBodyLabel, CaptionLabel)

from .. import constants as C
from .. import engine
from .gallery_list_page import GalleryListPage
from .adv_filter_dialog import AdvFilterDialog


class SearchPage(QWidget):
    def __init__(self, parent=None):
        super(SearchPage, self).__init__(parent)
        self._adv_state = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 搜索条
        bar = CardWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(8)
        bl.addWidget(SubtitleLabel("搜索"))
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("输入关键词搜索（支持标签、上传者、画廊 URL）")
        self.search_edit.setFixedWidth(360)
        self.search_edit.searchSignal.connect(self._do_search)
        self.search_edit.returnPressed.connect(self._do_search)
        bl.addWidget(self.search_edit)
        self.mode_combo = ComboBox(self)
        self.mode_combo.addItem("一般搜索", userData=C.MODE_NORMAL)
        self.mode_combo.addItem("订阅", userData=C.MODE_SUBSCRIPTION)
        self.mode_combo.addItem("指定上传者", userData=C.MODE_UPLOADER)
        self.mode_combo.addItem("指定标签", userData=C.MODE_TAG)
        self.mode_combo.setFixedWidth(120)
        bl.addWidget(self.mode_combo)
        self.adv_btn = PushButton("高级筛选", self)
        self.adv_btn.clicked.connect(self._open_adv)
        bl.addWidget(self.adv_btn)
        self.go_btn = PushButton("搜索", self)
        self.go_btn.clicked.connect(self._do_search)
        bl.addWidget(self.go_btn)
        bl.addStretch(1)
        root.addWidget(bar)

        # 结果列表
        self.list_page = GalleryListPage("搜索结果", self)
        self.list_page.set_loader(self._loader)
        root.addWidget(self.list_page, 1)

        self._current_mode = C.MODE_NORMAL
        self._current_keyword = ""

    def _open_adv(self):
        dlg = AdvFilterDialog(self._adv_state, self)
        if dlg.exec_():
            self._adv_state = dlg.result_state()
            self._do_search()

    def _do_search(self):
        kw = self.search_edit.text().strip()
        mode = self.mode_combo.currentData()
        if not kw:
            InfoBar.warning("", "请输入搜索关键词", position=InfoBarPosition.TOP, duration=2500, parent=self)
            return
        # 支持直接粘贴画廊 URL：/g/123/abc.../
        if "/g/" in kw:
            import re
            m = re.search(r"/g/(\d+)/([0-9a-f]{10})", kw)
            if m:
                from ..models import GalleryInfo
                gi = GalleryInfo()
                gi.gid = int(m.group(1))
                gi.token = m.group(2)
                gi.title = kw
                from .bus import bus
                bus.openDetail.emit(gi)
                return
        self._current_mode = mode
        self._current_keyword = kw
        self.list_page.title_label.setText("搜索结果：%s" % kw[:30])
        self.list_page.reload()

    def _loader(self, page_index, page_size):
        lub = engine.urls.ListUrlBuilder(self._current_mode)
        lub.keyword = self._current_keyword
        lub.page_index = page_index
        adv = self._adv_state
        if adv.get("advance_search", -1) != -1:
            lub.advance_search = adv.get("advance_search")
            lub.min_rating = adv.get("min_rating", -1)
            lub.page_from = adv.get("page_from", -1)
            lub.page_to = adv.get("page_to", -1)
        url = lub.build()
        result = engine.get_gallery_list(url, self._current_mode)
        nxt = result.next_page if result.next_page is not None else (page_index + 1 if len(result.items) >= page_size else None)
        return result.items, nxt
