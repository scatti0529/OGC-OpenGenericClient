# -*- coding: utf-8 -*-
"""收藏页：画廊收藏（云端/本地）+ 标签收藏（QUICK_SEARCH 表）"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QInputDialog

from qfluentwidgets import (CardWidget, ComboBox, PushButton, SubtitleLabel,
                            InfoBar, InfoBarPosition, SearchLineEdit, CaptionLabel,
                            BodyLabel, StrongBodyLabel, FluentIcon, ToolButton,
                            SegmentedWidget, ScrollArea, MessageBox)

from .. import constants as C
from .. import engine
from .. import db
from ..config import is_login
from .gallery_list_page import GalleryListPage
from .bus import bus


class FavoritesPage(QWidget):
    def __init__(self, parent=None):
        super(FavoritesPage, self).__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 分段：画廊收藏 / 标签收藏
        self.seg = SegmentedWidget(self)
        self.seg.addItem(routeKey="gallery", text="画廊收藏")
        self.seg.addItem(routeKey="tag", text="标签收藏")
        self.seg.setCurrentItem("gallery")
        self.seg.currentItemChanged.connect(self._on_seg)
        root.addWidget(self.seg, 0, Qt.AlignHCenter)

        # ---- 画廊收藏栏 ----
        bar = CardWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(8)
        bl.addWidget(SubtitleLabel("收藏"))
        self.cat_combo = ComboBox(self)
        self.cat_combo.addItem("全部收藏", userData=-1)
        for i in range(10):
            self.cat_combo.addItem(C.FAVORITE_CAT_NAMES[i], userData=i)
        self.cat_combo.setFixedWidth(130)
        self.cat_combo.currentIndexChanged.connect(lambda _i: self.reload())
        bl.addWidget(self.cat_combo)
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("在收藏中搜索")
        self.search_edit.setFixedWidth(240)
        self.search_edit.searchSignal.connect(lambda: self.reload())
        self.search_edit.returnPressed.connect(lambda: self.reload())
        bl.addWidget(self.search_edit)
        self.refresh_btn = ToolButton(FluentIcon.SYNC, self)
        self.refresh_btn.setToolTip("刷新")
        self.refresh_btn.clicked.connect(lambda: self.reload())
        bl.addWidget(self.refresh_btn)
        self.status = CaptionLabel("", self)
        bl.addWidget(self.status)
        bl.addStretch(1)
        self.gallery_bar = bar
        root.addWidget(bar)

        self.list_page = GalleryListPage("收藏", self)
        self.list_page.set_loader(self._loader)
        root.addWidget(self.list_page, 1)

        # ---- 标签收藏栏 ----
        tag_bar = CardWidget(self)
        tl = QHBoxLayout(tag_bar)
        tl.setContentsMargins(16, 10, 16, 10)
        tl.setSpacing(8)
        tl.addWidget(SubtitleLabel("标签收藏"))
        self.add_tag_btn = PushButton("添加标签…", self)
        self.add_tag_btn.clicked.connect(self._add_tag)
        tl.addWidget(self.add_tag_btn)
        self.tag_count = CaptionLabel("", self)
        tl.addWidget(self.tag_count)
        tl.addStretch(1)
        self.tag_bar = tag_bar
        root.addWidget(tag_bar)

        self.tag_scroll = ScrollArea(self)
        self.tag_scroll.setWidgetResizable(True)
        self._tag_container = QWidget(self.tag_scroll)
        self._tag_lay = QVBoxLayout(self._tag_container)
        self._tag_lay.setContentsMargins(8, 8, 8, 8)
        self._tag_lay.setSpacing(6)
        self._tag_lay.addStretch(1)
        self.tag_scroll.setWidget(self._tag_container)
        root.addWidget(self.tag_scroll, 1)

        # 初始显隐
        self.tag_bar.hide()
        self.tag_scroll.hide()

        self._items_cache = []
        self._next_idx = 0
        bus.loginChanged.connect(lambda _l: self.reload())

    def _on_seg(self, key):
        if key == "tag":
            self.gallery_bar.hide()
            self.list_page.hide()
            self.tag_bar.show()
            self.tag_scroll.show()
            self._render_tags()
        else:
            self.gallery_bar.show()
            self.list_page.show()
            self.tag_bar.hide()
            self.tag_scroll.hide()
            self.reload()

    def showEvent(self, event):
        super(FavoritesPage, self).showEvent(event)
        if getattr(self, "_loaded_once", False) is False:
            self._loaded_once = True
            self.reload()

    # ---------- 画廊收藏 ----------
    def reload(self):
        if not is_login():
            self.list_page.set_items(db.list_local_favorites())
            self.status.setText("本地收藏（未登录）")
            return
        self._items_cache = []
        self._next_idx = 0
        self.list_page.reload()

    def _loader(self, page_index, page_size):
        if not is_login():
            return db.list_local_favorites(), None
        url = engine.urls.get_favorites_url()
        params = []
        cat = self.cat_combo.currentData()
        if cat is not None and cat >= 0:
            params.append("favcat=%d" % cat)
        kw = self.search_edit.text().strip()
        if kw:
            from urllib.parse import quote
            params.append("f_search=" + quote(kw))
            params.append("sn=on")
            params.append("st=on")
            params.append("sf=on")
        if page_index:
            params.append("page=%d" % page_index)
        if params:
            url += "?" + "&".join(params)
        result = engine.get_favorites(url)
        nxt = None
        if result.next_page is not None:
            nxt = result.next_page
        elif len(result.items) >= page_size:
            nxt = page_index + 1
        return result.items, nxt

    # ---------- 标签收藏 ----------
    def _add_tag(self):
        text, ok = QInputDialog.getText(self, "添加标签收藏", "输入要收藏的标签（如 female:ahegao、artist:xxx）：")
        if ok and text.strip():
            tag = text.strip()
            db.add_tag_favorite(tag, name=tag)
            InfoBar.success("", "已收藏标签：" + tag, InfoBarPosition.TOP, 2000, self)
            self._render_tags()

    def _render_tags(self):
        while self._tag_lay.count():
            item = self._tag_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        tags = db.list_tag_favorites()
        self.tag_count.setText("共 %d 个标签" % len(tags))
        if not tags:
            self._tag_lay.addWidget(BodyLabel("暂无标签收藏，点击上方「添加标签…」收藏常用标签"))
            self._tag_lay.addStretch(1)
            return
        for t in tags:
            row = CardWidget(self._tag_container)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 6, 14, 6)
            rl.setSpacing(10)
            name = StrongBodyLabel(t["tag"])
            name.setToolTip("点击搜索该标签")
            rl.addWidget(name, 1)
            search_btn = ToolButton(FluentIcon.SEARCH, self)
            search_btn.setToolTip("搜索该标签")
            search_btn.clicked.connect(
                lambda _=False, tag=t["tag"], mode=t.get("mode", C.MODE_NORMAL):
                bus.doSearch.emit(tag, mode if mode in (C.MODE_NORMAL, C.MODE_UPLOADER, C.MODE_TAG) else C.MODE_NORMAL))
            del_btn = ToolButton(FluentIcon.DELETE, self)
            del_btn.setToolTip("删除")
            del_btn.clicked.connect(lambda _=False, tid=t["id"]: self._del_tag(tid))
            rl.addWidget(search_btn)
            rl.addWidget(del_btn)
            self._tag_lay.insertWidget(self._tag_lay.count() - 1, row)
        self._tag_lay.addStretch(1)

    def _del_tag(self, tid):
        db.delete_tag_favorite(tid)
        self._render_tags()
