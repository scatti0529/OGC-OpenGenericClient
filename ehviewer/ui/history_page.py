# -*- coding: utf-8 -*-
"""历史页：浏览历史列表 + 清除"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (CardWidget, PushButton, SubtitleLabel, CaptionLabel,
                            InfoBar, InfoBarPosition, FluentIcon, ToolButton, MessageBox)

from .. import constants as C
from .. import db
from .. import urls
from .gallery_list_page import GalleryListPage
from .bus import bus


class HistoryPage(QWidget):
    def __init__(self, parent=None):
        super(HistoryPage, self).__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        bar = CardWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(8)
        bl.addWidget(SubtitleLabel("浏览历史"))
        self.count_label = CaptionLabel("", self)
        bl.addWidget(self.count_label)
        self.clear_btn = PushButton("清除全部", self)
        self.clear_btn.clicked.connect(self._clear_all)
        bl.addWidget(self.clear_btn)
        self.batch_btn = PushButton("批量删除", self)
        self.batch_btn.clicked.connect(self._batch_delete)
        bl.addWidget(self.batch_btn)
        self.refresh_btn = ToolButton(FluentIcon.SYNC, self)
        self.refresh_btn.clicked.connect(self._reload)
        bl.addWidget(self.refresh_btn)
        bl.addStretch(1)
        root.addWidget(bar)

        self.list_page = GalleryListPage("历史记录", self)
        self.list_page.set_loader(self._loader)
        root.addWidget(self.list_page, 1)

        # 封面缓存进度（左下角，与收藏页一致）
        self.cover_progress_label = CaptionLabel("", self)
        self.cover_progress_label.setStyleSheet("color: #57606a;")
        root.addWidget(self.cover_progress_label)
        try:
            from pages.album.eh_cover import cover_service
            cover_service.progress.connect(self._on_cover_progress)
        except Exception:
            pass

        bus.historyChanged.connect(lambda: self._reload())

    def _on_cover_progress(self, done: int, total: int) -> None:
        if total > 0:
            try:
                self.cover_progress_label.setText("封面缓存 %d/%d" % (done, total))
            except Exception:
                pass

    def showEvent(self, event):
        super(HistoryPage, self).showEvent(event)
        self._reload()

    def _reload(self):
        items = db.list_history(500)
        # 规范化封面缩略图 URL，让封面用当前可用的预览缩略图（更快/更稳）
        for gi in items:
            if gi.thumb:
                try:
                    gi.thumb = urls.get_fixed_preview_thumb_url(gi.thumb) or gi.thumb
                except Exception:
                    pass
        # 一次性：强制重取「新到旧前 10 个」封面的缓存（与排行榜/主页/搜索同源，修复个别错/加载中）
        if not getattr(self, '_refresh_batch_done', False):
            self._refresh_batch_done = True
            try:
                from pages.album.eh_cover import cover_service
                for gi in items[:10]:
                    if gi.thumb or gi.token:
                        cover_service.invalidate(gi.gid)
                        cover_service.enqueue(gi.gid, gi.thumb or '', gi.token or '')
            except Exception:
                pass
        self.count_label.setText("共 %d 条" % len(items))
        if items:
            self.list_page.set_items(items)
        else:
            self.list_page.set_items([])

    def _loader(self, page_index, page_size):
        items = db.list_history(500)
        return items, None

    def _clear_all(self):
        box = MessageBox("清除历史", "确定清除所有阅读历史吗？", self)
        if box.exec_():
            db.clear_history()
            self._reload()
            InfoBar.success("", "历史已清除", position=InfoBarPosition.TOP, duration=2000, parent=self)

    def _batch_delete(self):
        """批量删除：勾选历史记录，删除选中的条目。"""
        from PyQt5.QtWidgets import (QDialog, QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout)
        from qfluentwidgets import PushButton as _PB, PrimaryPushButton as _PPB
        items = db.list_history(500)
        if not items:
            InfoBar.info("", "没有历史记录。", position=InfoBarPosition.TOP, duration=2000, parent=self)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("删除选中的历史记录")
        dlg.resize(560, 520)
        lay = QVBoxLayout(dlg)
        lay.addWidget(CaptionLabel("勾选要删除的历史记录，点「删除选中」。", dlg))
        lst = QListWidget(dlg)
        lst.setStyleSheet(
            "QListWidget { color: #1f2328; background: #ffffff; font-size: 13px; }"
            " QListWidget::item { padding: 4px 8px; color: #1f2328; }"
        )
        for gi in items:
            it = QListWidgetItem("%s    [%s]   %s" % (
                (gi.title or '(无标题)')[:60], gi.gid, gi.posted or ''))
            it.setData(Qt.UserRole, gi.gid)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            lst.addItem(it)
        lay.addWidget(lst, 1)

        btn = QHBoxLayout()
        sel_all = _PB("全选", dlg)
        none = _PB("全不选", dlg)
        apply_btn = _PPB("删除选中", dlg)
        cancel_btn = _PB("取消", dlg)
        btn.addWidget(sel_all); btn.addWidget(none)
        btn.addStretch(1)
        btn.addWidget(apply_btn); btn.addWidget(cancel_btn)
        lay.addLayout(btn)

        def _sel_all():
            for i in range(lst.count()):
                lst.item(i).setCheckState(Qt.Checked)
        def _none():
            for i in range(lst.count()):
                lst.item(i).setCheckState(Qt.Unchecked)
        sel_all.clicked.connect(_sel_all)
        none.clicked.connect(_none)

        res = {'del': 0}
        def _apply():
            gids = []
            for i in range(lst.count()):
                it = lst.item(i)
                if it.checkState() == Qt.Checked:
                    gids.append(it.data(Qt.UserRole))
            for g in gids:
                try:
                    db.delete_history(g)
                except Exception:
                    pass
            res['del'] = len(gids)
            dlg.accept()
        apply_btn.clicked.connect(_apply)
        cancel_btn.clicked.connect(dlg.reject)
        dlg.exec_()
        if res['del']:
            self._reload()
            InfoBar.success("", "已删除 %d 条历史记录。" % res['del'],
                            position=InfoBarPosition.TOP, duration=2000, parent=self)
