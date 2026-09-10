# -*- coding: utf-8 -*-
"""下载页：下载列表 + 状态/进度 + 批量操作"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QFrame, QMenu)

from qfluentwidgets import (CardWidget, BodyLabel, CaptionLabel, StrongBodyLabel,
                            SubtitleLabel, PushButton, PrimaryPushButton, ProgressBar,
                            InfoBar, InfoBarPosition, FluentIcon, ToolButton,
                            ComboBox, FlowLayout, ScrollArea)

from .. import constants as C
from .. import db
from ..config import get
from ..appctx import ctx
from .bus import bus


class DownloadCard(CardWidget):
    startClicked = pyqtSignal(int)
    pauseClicked = pyqtSignal(int)
    removeClicked = pyqtSignal(int)
    openClicked = pyqtSignal(object)

    def __init__(self, info, parent=None):
        super(DownloadCard, self).__init__(parent)
        self.info = info
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        right = QVBoxLayout()
        right.setSpacing(4)
        self.title = StrongBodyLabel(info.suitable_title(get("show_jpn_title", False)), self)
        self.title.setWordWrap(True)
        right.addWidget(self.title)
        meta = []
        if info.uploader:
            meta.append("上传者: " + info.uploader)
        if info.posted:
            meta.append(info.posted)
        self.meta = CaptionLabel("  ·  ".join(meta), self)
        self.meta.setStyleSheet("color: #888;")
        right.addWidget(self.meta)
        self.state_label = CaptionLabel("", self)
        right.addWidget(self.state_label)
        self.progress = ProgressBar(self)
        self.progress.setFixedHeight(6)
        self.progress.setRange(0, 100)
        right.addWidget(self.progress)
        lay.addLayout(right, 1)

        self.start_btn = ToolButton(FluentIcon.PLAY, self)
        self.start_btn.setToolTip("开始/恢复")
        self.start_btn.clicked.connect(lambda: self.startClicked.emit(self.info.gid))
        self.pause_btn = ToolButton(FluentIcon.PAUSE, self)
        self.pause_btn.setToolTip("暂停")
        self.pause_btn.clicked.connect(lambda: self.pauseClicked.emit(self.info.gid))
        self.remove_btn = ToolButton(FluentIcon.DELETE, self)
        self.remove_btn.setToolTip("删除")
        self.remove_btn.clicked.connect(lambda: self.removeClicked.emit(self.info.gid))
        self.open_btn = ToolButton(FluentIcon.VIEW, self)
        self.open_btn.setToolTip("打开阅读")
        self.open_btn.clicked.connect(lambda: self.openClicked.emit(self.info))
        for b in (self.start_btn, self.pause_btn, self.remove_btn, self.open_btn):
            b.setFixedSize(28, 28)
        btns = QVBoxLayout()
        btns.setSpacing(2)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.pause_btn)
        btns.addWidget(self.remove_btn)
        lay.addLayout(btns)

        self.refresh_state()

    def refresh_state(self):
        info = self.info
        st = info.state
        name = C.STATE_NAMES.get(st, "未知")
        if st == C.STATE_DOWNLOAD:
            self.state_label.setText("%s · %s/%s 页" % (name, info.finished, info.total or "?"))
            self.progress.setValue(int(info.finished * 100.0 / info.total) if info.total else 0)
            self.progress.show()
        elif st == C.STATE_FINISH:
            pages = info.total or info.finished
            self.state_label.setText("已完成 · 共 %s 页" % pages if pages else "已完成")
            self.progress.setValue(100)
            self.progress.show()
        elif st == C.STATE_FAILED:
            legacy = (info.total or info.finished or 0) - (info.finished or 0)
            self.state_label.setText("下载失败 · %d 页未完成" % legacy if legacy > 0 else "下载失败")
            self.progress.setValue(int(info.finished * 100.0 / info.total) if info.total else 0)
            self.progress.show()
        elif st == C.STATE_WAIT:
            self.state_label.setText("等待中…")
            self.progress.setValue(0)
            self.progress.show()
        else:
            self.state_label.setText("未启动")
            self.progress.hide()
        self.start_btn.setVisible(st in (C.STATE_NONE, C.STATE_FAILED, C.STATE_FINISH))
        self.pause_btn.setVisible(st in (C.STATE_WAIT, C.STATE_DOWNLOAD))


class DownloadsPage(QWidget):
    def __init__(self, parent=None):
        super(DownloadsPage, self).__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        bar = CardWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(8)
        bl.addWidget(SubtitleLabel("下载管理"))
        self.start_all = PushButton("全部开始", self)
        self.start_all.clicked.connect(self._start_all)
        self.stop_all = PushButton("全部停止", self)
        self.stop_all.clicked.connect(self._stop_all)
        self.retry_failed = PushButton("重试失败", self)
        self.retry_failed.clicked.connect(self._retry_failed)
        self.retry_all = PushButton("全部重试", self)
        self.retry_all.clicked.connect(self._retry_all)
        self.open_dir = PushButton("打开下载目录", self)
        self.open_dir.clicked.connect(self._open_dir)
        for b in (self.start_all, self.stop_all, self.retry_failed, self.retry_all, self.open_dir):
            bl.addWidget(b)
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
        root.addWidget(self.scroll, 1)

        self._cards = {}
        self._visible = 80
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        bus.downloadsChanged.connect(self._refresh)
        bus.downloadProgress.connect(self._on_progress)

    def showEvent(self, event):
        super(DownloadsPage, self).showEvent(event)
        self._all_items = getattr(self, "_all_items", [])
        self._refresh()

    def _refresh(self):
        items = db.list_downloads()
        self._all_items = items
        self.count_label.setText("共 %d 项" % len(items))
        self._ensure_visible()
        # 移除已删除的
        seen = {g.gid for g in items}
        for gid in list(self._cards.keys()):
            if gid not in seen:
                card = self._cards.pop(gid)
                self._flow.removeWidget(card)
                card.deleteLater()

    def _ensure_visible(self):
        """只渲染前 _visible 项，滚动到末尾再补充"""
        for g in self._all_items[:self._visible]:
            if g.gid in self._cards:
                card = self._cards[g.gid]
                card.info = g
                card.refresh_state()
                continue
            card = DownloadCard(g, self._container)
            card.startClicked.connect(self._start_one)
            card.pauseClicked.connect(self._pause_one)
            card.removeClicked.connect(self._remove_one)
            card.openClicked.connect(self._open_one)
            self._cards[g.gid] = card
            self._flow.addWidget(card)

    def _on_scrolled(self, _v):
        bar = self.scroll.verticalScrollBar()
        if bar.value() >= bar.maximum() - 150 and self._visible < len(self._all_items):
            self._visible += 80
            self._ensure_visible()

    def _on_progress(self, gid, finished, total, speed):
        card = self._cards.get(gid)
        if card is not None and card.info is not None:
            card.info.finished = finished
            card.info.total = total
            card.refresh_state()

    # ---------- 操作 ----------
    def _start_one(self, gid):
        if ctx.download_manager is not None:
            ctx.download_manager.resume(gid)

    def _pause_one(self, gid):
        if ctx.download_manager is not None:
            ctx.download_manager.pause(gid)

    def _remove_one(self, gid):
        from qfluentwidgets import MessageBox
        box = MessageBox("删除下载项", "确定从下载列表移除该画廊吗？（磁盘文件将保留）", self)
        if box.exec_():
            if ctx.download_manager is not None:
                ctx.download_manager.remove(gid)

    def _open_one(self, info):
        from .bus import bus
        bus.openReader.emit(info, 0)

    def _start_all(self):
        if ctx.download_manager is not None:
            for g in db.list_downloads():
                if g.state in (C.STATE_NONE, C.STATE_FAILED):
                    ctx.download_manager.resume(g.gid)

    def _stop_all(self):
        if ctx.download_manager is not None:
            ctx.download_manager.pause_all()

    def _retry_failed(self):
        if ctx.download_manager is not None:
            ctx.download_manager.retry_failed()

    def _retry_all(self):
        if ctx.download_manager is not None:
            ctx.download_manager.retry_all()

    def _open_dir(self):
        import os
        from PyQt5.QtGui import QDesktopServices
        from PyQt5.QtCore import QUrl
        d = get("download_dir")
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))
