# -*- coding: utf-8 -*-
"""本地画册：以卡片展示已下载漫画，按下载分类（DOWNLOAD_LABELS）分组"""
import os

from PyQt5.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QInputDialog)

from qfluentwidgets import (CardWidget, SubtitleLabel, CaptionLabel, StrongBodyLabel,
                            PushButton, ComboBox, InfoBar, InfoBarPosition,
                            FluentIcon, ToolButton, ScrollArea, FlowLayout, MessageBox,
                            BodyLabel)

from .. import constants as C
from .. import db
from ..config import get
from ..spiderinfo import find_gallery_dir, SUPPORTED_EXTS, page_file_name
from .bus import bus

DEFAULT_LABEL = "未分类"


class CoverTask(QRunnable):
    """本地封面加载任务"""

    def __init__(self, gid, cover_path, callback):
        super(CoverTask, self).__init__()
        self.gid = gid
        self.path = cover_path
        self.callback = callback

    def run(self):
        try:
            img = QImage(self.path)
            if img.isNull():
                return
            pix = QPixmap.fromImage(img).scaled(150, 210, Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation)
            self.callback(self.gid, pix)
        except Exception:
            pass


class _CoverBridge(QObject):
    coverReady = pyqtSignal(int, object)   # gid, QPixmap


class AlbumCard(CardWidget):
    cardClicked = pyqtSignal(object)

    def __init__(self, info, dirname, label, parent=None):
        super(AlbumCard, self).__init__(parent)
        self.info = info
        self.dirname = dirname
        self.label = label
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)
        self.cover = QLabel(self)
        self.cover.setFixedSize(90, 126)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background: rgba(127,127,127,0.15); border-radius: 6px; color:#888;")
        self.cover.setText("封面")
        lay.addWidget(self.cover)
        right = QVBoxLayout()
        right.setSpacing(4)
        self.title = StrongBodyLabel((info.title or info.title_jpn or dirname)[:60], self)
        self.title.setWordWrap(True)
        right.addWidget(self.title)
        meta = []
        if info.uploader:
            meta.append("上传者: " + info.uploader)
        if info.total:
            meta.append("页数: %d" % info.total)
        self.meta = CaptionLabel("  ·  ".join(meta), self)
        self.meta.setStyleSheet("color: #888;")
        right.addWidget(self.meta)
        self.state = CaptionLabel(label or DEFAULT_LABEL, self)
        self.state.setStyleSheet("background: #3F51B5; color: white; border-radius: 6px; padding: 1px 8px;")
        right.addWidget(self.state)
        right.addStretch(1)
        lay.addLayout(right, 1)
        self.setFixedHeight(148)

    def set_cover(self, pixmap):
        if pixmap is not None and not pixmap.isNull():
            self.cover.setPixmap(pixmap)
            self.cover.setText("")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.cardClicked.emit(self.info)
        super(AlbumCard, self).mouseReleaseEvent(event)


class AlbumPage(QWidget):
    def __init__(self, parent=None):
        super(AlbumPage, self).__init__(parent)
        self._cards = {}
        self._visible = 60
        self._all_items = []
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._bridge = _CoverBridge()
        self._bridge.coverReady.connect(self._on_cover)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        bar = CardWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(8)
        bl.addWidget(SubtitleLabel("本地画册"))
        self.label_combo = ComboBox(self)
        self.label_combo.setFixedWidth(140)
        self.label_combo.currentIndexChanged.connect(lambda _i: self._refresh())
        bl.addWidget(self.label_combo)
        self.add_label_btn = PushButton("新增分类", self)
        self.add_label_btn.clicked.connect(self._add_label)
        bl.addWidget(self.add_label_btn)
        self.del_label_btn = PushButton("删除当前分类", self)
        self.del_label_btn.clicked.connect(self._del_label)
        bl.addWidget(self.del_label_btn)
        self.refresh_btn = ToolButton(FluentIcon.SYNC, self)
        self.refresh_btn.setToolTip("刷新")
        self.refresh_btn.clicked.connect(lambda: self._refresh())
        bl.addWidget(self.refresh_btn)
        self.count_label = CaptionLabel("", self)
        bl.addWidget(self.count_label)
        bl.addStretch(1)
        root.addWidget(bar)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self._container = QWidget(self.scroll)
        self._flow = FlowLayout(self._container, needAni=False)
        self._flow.setContentsMargins(4, 4, 4, 4)
        self._flow.setSpacing(8)
        self.scroll.setWidget(self._container)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        root.addWidget(self.scroll, 1)

        bus.downloadsChanged.connect(self._refresh)

    def showEvent(self, event):
        super(AlbumPage, self).showEvent(event)
        self._refresh()

    # ---------- 数据 ----------
    def _labels(self):
        labels = [DEFAULT_LABEL]
        for l in db.list_labels():
            labels.append(l["label"])
        return labels

    def _refresh(self):
        # 刷新分类下拉
        cur = self.label_combo.currentText()
        self.label_combo.blockSignals(True)
        self.label_combo.clear()
        self.label_combo.addItem("全部", userData=None)
        for l in self._labels():
            self.label_combo.addItem(l, userData=l)
        idx = self.label_combo.findText(cur)
        self.label_combo.setCurrentIndex(max(0, idx))
        self.label_combo.blockSignals(False)

        sel = self.label_combo.currentData()
        root = get("download_dir")
        items = db.list_downloads()
        shown = []
        for info in items:
            label = info.label or DEFAULT_LABEL
            if sel and label != sel:
                continue
            dirname = db.get_download_dirname(info.gid)
            d = dirname if dirname else find_gallery_dir(root, info.gid)
            if d:
                shown.append((info, d, label))
        self._all_items = shown
        self._visible = 60
        self.count_label.setText("共 %d 本" % len(shown))
        # 只渲染前 _visible 张
        for gid, card in list(self._cards.items()):
            self._flow.removeWidget(card)
            card.deleteLater()
        self._cards = {}
        if not shown:
            self._flow.addWidget(BodyLabel("暂无本地画册。先去下载一些画廊吧。"))
            return
        self._render_range(0, self._visible)

    def _render_range(self, start, end):
        root = get("download_dir")
        for info, d, label in self._all_items[start:end]:
            if info.gid in self._cards:
                continue
            card = AlbumCard(info, d, label, self._container)
            card.cardClicked.connect(self._on_open)
            self._cards[info.gid] = card
            self._flow.addWidget(card)
            cover = self._find_cover(os.path.join(root, d))
            if cover:
                task = CoverTask(info.gid, cover, self._bridge.coverReady.emit)
                self._pool.start(task)

    def _on_scrolled(self, _v):
        bar = self.scroll.verticalScrollBar()
        if bar.value() >= bar.maximum() - 150 and self._visible < len(self._all_items):
            start = self._visible
            self._visible += 60
            self._render_range(start, self._visible)

    def _find_cover(self, d):
        for i in range(0, 3):
            for ext in SUPPORTED_EXTS:
                p = os.path.join(d, page_file_name(i, ext))
                if os.path.exists(p):
                    return p
        # 兜底：目录内任意图片
        try:
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(SUPPORTED_EXTS) and not f.startswith("."):
                    return os.path.join(d, f)
        except OSError:
            pass
        return None

    def _on_cover(self, gid, pixmap):
        card = self._cards.get(gid)
        if card is not None:
            card.set_cover(pixmap)

    def _on_open(self, info):
        from .reader_window import ReaderWindow
        bus.openReader.emit(info, 0)

    # ---------- 分类管理 ----------
    def _add_label(self):
        text, ok = QInputDialog.getText(self, "新增下载分类", "输入分类名称：")
        if ok and text.strip():
            db.add_label(text.strip())
            InfoBar.success("", "分类已新增", InfoBarPosition.TOP, 2000, self)
            self._refresh()

    def _del_label(self):
        label = self.label_combo.currentData()
        if not label or label == DEFAULT_LABEL:
            InfoBar.info("", "请先选择要删除的自定义分类", InfoBarPosition.TOP, 2500, self)
            return
        box = MessageBox("删除分类", "确定删除分类「%s」吗？该分类下的漫画将回到「未分类」。（文件不受影响）" % label, self)
        if box.exec_():
            for l in db.list_labels():
                if l["label"] == label:
                    db.delete_label(l["id"])
                    break
            InfoBar.success("", "分类已删除", InfoBarPosition.TOP, 2000, self)
            self._refresh()
