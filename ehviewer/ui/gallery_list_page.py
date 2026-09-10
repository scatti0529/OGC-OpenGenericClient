# -*- coding: utf-8 -*-
"""画廊列表页：异步加载 + 增量渲染（滚动分页、缩略图按需请求）"""
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (SearchLineEdit, ComboBox, ToolButton, FluentIcon,
                            SubtitleLabel, CaptionLabel, InfoBar, InfoBarPosition,
                            ScrollArea, FlowLayout)

from .. import constants as C
from .bus import bus
from .widgets import GalleryCard, EmptyHint


class _ListWorker(QThread):
    """后台加载一页列表数据"""
    done = pyqtSignal(object, object, str, int)   # items, next_idx, error, gen

    def __init__(self, loader, idx, size, gen, parent=None):
        super(_ListWorker, self).__init__(parent)
        self._loader = loader
        self._idx = idx
        self._size = size
        self._gen = gen

    def run(self):
        try:
            items, nxt = self._loader(self._idx, self._size)
            self.done.emit(items, nxt, "", self._gen)
        except Exception as e:
            self.done.emit(None, None, str(e), self._gen)


RENDER_STEP = 50   # 静态列表每次渲染的卡片数


class GalleryListPage(QWidget):
    """可复用的画廊列表页：loader(page_index, page_size) -> (items, next_token)"""
    requestDetail = pyqtSignal(object)

    PAGE_SIZE = 25

    def __init__(self, title="画廊", parent=None):
        super(GalleryListPage, self).__init__(parent)
        self._loader = None
        self._items = []
        self._next_index = None
        self._loading = False
        self._cards = []
        self._cover_map = {}
        self._gen = 0
        self._worker = None
        self._rendered = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title_label = SubtitleLabel(title, self)
        header.addWidget(self.title_label)
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("搜索关键词（支持标签、上传者、画廊 URL）")
        self.search_edit.setFixedWidth(320)
        self.search_edit.searchSignal.connect(self._on_search)
        self.search_edit.returnPressed.connect(self._on_search)
        header.addWidget(self.search_edit)
        self.cat_combo = ComboBox(self)
        self.cat_combo.addItem("全部分类", userData=C.ALL_CATEGORY)
        for v in C.CATEGORY_VALUES:
            self.cat_combo.addItem(C.get_category_name(v), userData=v)
        self.cat_combo.setFixedWidth(120)
        self.cat_combo.currentIndexChanged.connect(lambda _i: self._reload())
        header.addWidget(self.cat_combo)
        self.sort_combo = ComboBox(self)
        self.sort_combo.addItem("最新上传", userData="latest")
        self.sort_combo.addItem("热门", userData="popular")
        self.sort_combo.addItem("评分最高", userData="rated")
        self.sort_combo.setFixedWidth(110)
        self.sort_combo.currentIndexChanged.connect(lambda _i: self._reload())
        header.addWidget(self.sort_combo)
        self.adv_btn = ToolButton(FluentIcon.FILTER, self)
        self.adv_btn.setToolTip("高级筛选")
        self.adv_btn.clicked.connect(self._on_adv_filter)
        header.addWidget(self.adv_btn)
        self.refresh_btn = ToolButton(FluentIcon.SYNC, self)
        self.refresh_btn.setToolTip("刷新")
        self.refresh_btn.clicked.connect(lambda: self._reload(reset=True))
        header.addWidget(self.refresh_btn)
        header.addStretch(1)
        root.addLayout(header)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget(self.scroll)
        self.flow = FlowLayout(self.container, needAni=False)
        self.flow.setContentsMargins(4, 4, 4, 4)
        self.flow.setSpacing(8)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

        self.status = CaptionLabel("", self)
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: #888;")
        self.status.setFixedHeight(28)
        root.addWidget(self.status)

        self.empty = EmptyHint("这里空空如也", self)
        self.empty.hide()
        root.addWidget(self.empty, 1)

        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(200)
        self._load_timer.timeout.connect(self._maybe_load_more)
        self._adv_state = {}

    # ---------- 模式 ----------
    def set_simple_mode(self, simple=False):
        self.search_edit.setVisible(not simple)
        self.cat_combo.setVisible(not simple)
        self.sort_combo.setVisible(not simple)
        self.adv_btn.setVisible(not simple)

    # ---------- 数据 ----------
    def set_loader(self, loader):
        self._loader = loader

    def set_items(self, items):
        """静态数据（本地收藏/历史）：同步存储，滚动分页渲染"""
        self._loader = None
        self._items = list(items)
        self._next_index = None
        self._rendered = 0
        self._clear_cards()
        if self._items:
            self._render_more()
        else:
            self.empty.show()
            self.scroll.hide()
            self.status.setText("")

    def _on_search(self):
        self._reload(reset=True)

    def _reload(self, reset=False):
        if self._loader is None:
            return
        self._items = []
        self._next_index = None
        self._gen += 1
        self._rendered = 0
        self._clear_cards()
        self._loading = False
        self._maybe_load_more()

    def _clear_cards(self):
        for c in self._cards:
            self.flow.removeWidget(c)
            c.deleteLater()
        self._cards = []
        self._cover_map = {}

    def _maybe_load_more(self):
        if self._loading or self._loader is None:
            return
        if self._next_index is None and self._items:
            return
        self._loading = True
        self.status.setText("加载中…")
        self.empty.hide()
        self.scroll.show()
        idx = self._next_index if self._next_index is not None else self._cur_page()
        self._gen += 1
        gen = self._gen
        self._worker = _ListWorker(self._loader, idx, self.PAGE_SIZE, gen, self)
        self._worker.done.connect(self._on_loaded)
        self._worker.start()

    def _cur_page(self):
        return getattr(self, "_page_idx", 0)

    def _on_loaded(self, items, nxt, err, gen):
        if gen != self._gen:
            return  # 过期结果
        self._loading = False
        if err:
            self.status.setText("加载失败：" + err[:80])
            self._worker = None
            return
        if items is None:
            items = []
        self._page_idx = getattr(self, "_page_idx", 0)
        self._next_index = nxt
        if items:
            self._items.extend(items)
            self._append_cards(items)
        if nxt is None:
            self.status.setText("共 %d 项 · 已全部加载" % len(self._items))
        else:
            self.status.setText("已加载 %d 项" % len(self._items))
        self._worker = None

    # ---------- 渲染 ----------
    def _append_cards(self, items):
        """增量创建卡片（只对新增项）"""
        self.empty.hide()
        self.scroll.show()
        for info in items:
            card = GalleryCard(self.container)
            card.set_info(info)
            card.cardClicked.connect(self._on_card_clicked)
            self._cards.append(card)
            self.flow.addWidget(card)
            if info.thumb:
                key = "thumb:%d" % info.gid
                self._cover_map[key] = card
                self._request_cover(key, info.thumb, getattr(info, 'token', '') or '')

    def _render_more(self):
        """静态列表：继续渲染下一批"""
        end = min(self._rendered + RENDER_STEP, len(self._items))
        batch = self._items[self._rendered:end]
        self._rendered = end
        self._append_cards(batch)
        self.status.setText("共 %d 项" % len(self._items))

    def _request_cover(self, key, url, token=None):
        from ..appctx import ctx
        # 沿用之前的封面：用画廊缩略图（排行榜/主页/搜索等列表页一致），命中缓存则复用
        try:
            from pages.album.eh_cover import cover_service, gid_from_key
            gid = gid_from_key(key)
            if gid:
                pix = cover_service.load(gid)
                if pix is not None and not pix.isNull():
                    self._on_thumb(key, url, pix)
                    return
        except Exception:
            pass
        loader = ctx.image_loader
        if loader is None:
            return
        if not getattr(self, "_thumb_connected", False):
            loader.loaded.connect(self._on_thumb)
            self._thumb_connected = True
        loader.load(key, url, is_thumb=True)

    def _on_cover_gid(self, gid, pixmap):
        """cover_service 下载完成 -> 按 gid 更新对应卡片封面。"""
        if pixmap is None or pixmap.isNull():
            return
        key = "thumb:%d" % gid
        card = self._cover_map.get(key)
        if card is not None:
            try:
                card.set_cover_pixmap(pixmap)
            except Exception:
                pass

    def _on_thumb(self, key, url, pixmap):
        card = self._cover_map.get(key)
        if card is not None:
            try:
                card.set_cover_pixmap(pixmap)
            except Exception:
                pass
        # 保存到统一封面缓存（供收藏/详情/历史等处复用同一张）
        try:
            if pixmap is not None and not pixmap.isNull():
                from pages.album.eh_cover import cover_service, gid_from_key
                gid = gid_from_key(key)
                if gid:
                    cover_service.save(gid, pixmap)
        except Exception:
            pass

    def _on_scrolled(self, _v):
        bar = self.scroll.verticalScrollBar()
        near_bottom = bar.value() >= bar.maximum() - 150
        if not near_bottom:
            return
        if self._loader is None and self._rendered < len(self._items):
            self._render_more()
        else:
            self._load_timer.start()

    def _on_card_clicked(self, info):
        self.requestDetail.emit(info)
        bus.openDetail.emit(info)

    def _on_adv_filter(self):
        from .adv_filter_dialog import AdvFilterDialog
        dlg = AdvFilterDialog(self._adv_state, self)
        if dlg.exec_():
            self._adv_state = dlg.result_state()
            InfoBar.success("", "已应用高级筛选", position=InfoBarPosition.TOP,
                            duration=2000, parent=self)
            self._reload(reset=True)

    def reload(self):
        """公开重载入口"""
        self._reload(reset=True)
