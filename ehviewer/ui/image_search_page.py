# -*- coding: utf-8 -*-
"""图片搜索页：以图搜图（对应 imgsrv image_lookup.php）"""
import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel

from qfluentwidgets import (CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
                            PrimaryPushButton, PushButton, CheckBox, InfoBar,
                            InfoBarPosition, FluentIcon, ToolButton)

from .. import engine
from .. import constants as C
from .gallery_list_page import GalleryListPage


class ImageSearchWorker(QThread):
    done = pyqtSignal(object, str)

    def __init__(self, path, uss, osc, se, parent=None):
        super(ImageSearchWorker, self).__init__(parent)
        self.path = path
        self.uss = uss
        self.osc = osc
        self.se = se

    def run(self):
        try:
            result = engine.image_search(self.path, self.uss, self.osc, self.se)
            self.done.emit(result, "")
        except Exception as e:
            self.done.emit(None, str(e))


class ImageSearchPage(QWidget):
    def __init__(self, parent=None):
        super(ImageSearchPage, self).__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        bar = CardWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(8)
        bl.addWidget(SubtitleLabel("图片搜索"))
        self.pick_btn = PushButton("选择图片…", self)
        self.pick_btn.clicked.connect(self._pick)
        bl.addWidget(self.pick_btn)
        self.img_label = QLabel("未选择图片", self)
        self.img_label.setFixedSize(96, 96)
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setStyleSheet("background: rgba(127,127,127,0.15); border-radius: 6px; color: #888;")
        bl.addWidget(self.img_label)
        self.cb_similar = CheckBox("使用相似搜索", self)
        self.cb_similar.setChecked(True)
        self.cb_covers = CheckBox("只搜索封面", self)
        self.cb_expunged = CheckBox("显示被删除的画廊", self)
        self.search_btn = PrimaryPushButton("开始搜索", self)
        self.search_btn.setEnabled(False)
        self.search_btn.clicked.connect(self._do_search)
        for w in (self.cb_similar, self.cb_covers, self.cb_expunged):
            bl.addWidget(w)
        bl.addStretch(1)
        bl.addWidget(self.search_btn)
        root.addWidget(bar)

        self.list_page = GalleryListPage("图片搜索结果", self)
        self.list_page.set_simple_mode(True)
        self.list_page.set_loader(self._loader)
        root.addWidget(self.list_page, 1)

        self._image_path = None
        self._result = None
        self._worker = None

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "",
                                              "图片文件 (*.jpg *.jpeg *.png *.gif *.webp);;所有文件 (*)")
        if path:
            self._image_path = path
            from PyQt5.QtGui import QPixmap
            pix = QPixmap(path)
            self.img_label.setPixmap(pix.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.img_label.setText("")
            self.search_btn.setEnabled(True)

    def _do_search(self):
        if not self._image_path:
            return
        self.search_btn.setEnabled(False)
        self.search_btn.setText("搜索中…")
        self._worker = ImageSearchWorker(
            self._image_path, self.cb_similar.isChecked(),
            self.cb_covers.isChecked(), self.cb_expunged.isChecked(), self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, result, err):
        self.search_btn.setEnabled(True)
        self.search_btn.setText("开始搜索")
        if err:
            InfoBar.error("", "搜索失败：" + err, position=InfoBarPosition.TOP, duration=5000, parent=self)
            return
        if result is None:
            InfoBar.warning("", "未找到匹配结果", position=InfoBarPosition.TOP, duration=3000, parent=self)
            self.list_page.set_items([])
            return
        self._result = result
        self.list_page.set_items(result.items)

    def _loader(self, page_index, page_size):
        if self._result is None:
            return [], None
        return self._result.items, None
