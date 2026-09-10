# -*- coding: utf-8 -*-
"""
通用离线阅读 UI（OGC 集成版）
==============================
- OfflineLibraryTab：扫描指定下载根目录，卡片展示已下载漫画；
- OfflineComicPage：某部漫画的本地章节列表；
- OfflineReaderPage：本地章节阅读（复用 ComicReaderPage，翻页/分页/滚动）。

通过注入 scan_root / 目录标题 供 JMComic / E-Hentai / 拷贝漫画 复用。
"""
from __future__ import annotations

import os
import threading
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    ComboBox,
    Dialog,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from services.comic_library import (
    LocalChapter,
    LocalComic,
    comic_download_time,
    default_index_path,
    delete_local_path,
    invalidate_index,
    scan_comics,
)
from ui.widgets.theme import text_primary, text_tertiary

from .easycopy_reader import ComicReaderPage
from .easycopy_widgets import (
    CoverImage,
    EmptyLabel,
    ErrorLabel,
    FlowLayout,
    LoadingLabel,
    SectionHeader,
)


class _LocalFetcher:
    """读取本地文件的 fetcher，兼容 CoverImage / ImageFetcher 接口。"""

    def fetch(self, path: str):
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            return None


class _OfflineComicCard(CardWidget):
    """本地漫画卡片：封面 + 标题 + 章节/图片数量。"""

    clicked = pyqtSignal(object)  # LocalComic

    def __init__(self, comic: LocalComic, fetcher, parent=None):
        super().__init__(parent)
        self.comic = comic
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("ogcOfflineCard")
        self.setFixedWidth(170)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.setSpacing(6)

        cover = CoverImage(comic.cover_url, fetcher, radius=14, placeholder_text=comic.title)
        cover.setFixedWidth(154)
        cover.setFixedHeight(205)
        layout.addWidget(cover, 0, Qt.AlignHCenter)

        title = QLabel(comic.title)
        title.setWordWrap(True)
        title.setMaximumHeight(40)
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        title.setStyleSheet(f"color: {text_primary()};")
        layout.addWidget(title)

        # 分类标签（来自 DOWNLOADS.LABEL，未分类为空则不显示）
        self._cat = ""
        try:
            from pages.album.ehentai_sync import comic_category
            self._cat = comic_category(getattr(comic, 'path', '') or '', comic.title) or ''
        except Exception:
            self._cat = ""
        if self._cat:
            cat = QLabel(self._cat)
            cat.setStyleSheet(
                "color: #8a6d1a; background: rgba(212,167,44,0.12); border-radius: 4px;"
                " padding: 1px 6px; font-size: 12px;")
            cat.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.addWidget(cat)

        meta = QLabel(f"{comic.total_chapters} 话 · {comic.total_images} 张")
        meta.setStyleSheet(f"color: {text_tertiary()}; font-size: 12px;")
        layout.addWidget(meta)

        self.setStyleSheet(
            """
            #ogcOfflineCard { background-color: transparent; border-radius: 20px; }
            #ogcOfflineCard:hover { background-color: rgba(128,128,128,0.10); }
            QLabel { background: transparent; border: none; }
            """
        )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.comic)


class OfflineLibraryTab(QWidget):
    """离线阅读标签页：扫描本地下载目录，卡片展示已下载漫画。

    支持离线索引 JSON：传入 index_path 时优先读索引（更快），
    「刷新」按钮强制全量重建索引。
    """

    open_comic_requested = pyqtSignal(object)  # LocalComic
    scanned = pyqtSignal(object, object)       # (comics, error)

    def __init__(self, scan_root: str = "", empty_hint: str = "",
                 index_path: str = "", parent=None):
        super().__init__(parent)
        self.scan_root = scan_root
        self.index_path = index_path or default_index_path(scan_root, 'ogc')
        self.empty_hint = empty_hint or "暂无已下载的漫画。"
        self._fetcher = _LocalFetcher()
        self._cards = []
        self._comics = []
        self._sort_key = 'name'      # 'name' | 'time_desc' | 'time_asc'
        self._force_scan = False
        self.scanned.connect(self._on_scanned)
        self._build_ui()

    def set_scan_root(self, root: str) -> None:
        self.scan_root = root

    def set_index_path(self, index_path: str) -> None:
        self.index_path = index_path

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.refresh_btn = PrimaryPushButton(FluentIcon.SYNC, "刷新", self)
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn)

        # 排序方式：名称 / 下载时间
        self.sort_combo = ComboBox(self)
        self.sort_combo.addItems(['名称排序', '下载时间（新→旧）', '下载时间（旧→新）'])
        self.sort_combo.setFixedWidth(170)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        top.addWidget(self.sort_combo)

        top.addStretch(1)
        self.summary_label = CaptionLabel("", self)
        self.summary_label.setStyleSheet(f"color: {text_tertiary()};")
        top.addWidget(self.summary_label)
        root.addLayout(top)

        self._stack = QVBoxLayout()
        root.addLayout(self._stack, 1)

    def load(self, uri=None, force: bool = False):
        """加载本地漫画列表。force=True 时强制全量重建索引。"""
        self._force_scan = bool(force)
        self._clear_content()
        self._cards = []
        self._stack.addWidget(LoadingLabel("正在扫描本地漫画…"))
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def refresh(self):
        """强制重建索引并刷新列表。"""
        self.load(force=True)

    def _scan_worker(self):
        try:
            comics = scan_comics(self.scan_root, index_path=self.index_path,
                                 force=self._force_scan)
            self.scanned.emit(comics, "")
        except Exception as e:
            self.scanned.emit([], str(e))

    def _on_scanned(self, comics, error):
        self._clear_content()
        self._cards = []
        if error:
            self._stack.addWidget(ErrorLabel(f"扫描失败：{error}"))
            return
        if not comics:
            self._stack.addWidget(EmptyLabel(self.empty_hint))
            return
        self._comics = list(comics)
        self._rebuild_cards()

    # ---------- 排序 ----------
    def _on_sort_changed(self, index: int):
        if index <= 0:
            self._sort_key = 'name'
        elif index == 1:
            self._sort_key = 'time_desc'
        else:
            self._sort_key = 'time_asc'
        if self._comics:
            self._rebuild_cards()

    def _apply_sort(self, comics):
        if self._sort_key == 'name':
            from services.comic_library import natural_key
            comics.sort(key=lambda c: natural_key(c.title))
        elif self._sort_key == 'time_desc':
            comics.sort(key=lambda c: comic_download_time(c), reverse=True)
        else:
            comics.sort(key=lambda c: comic_download_time(c))
        return comics

    def _rebuild_cards(self):
        """按当前排序重建卡片列表。"""
        self._clear_content()
        self._cards = []
        comics = self._apply_sort(list(self._comics))
        if not comics:
            self._stack.addWidget(EmptyLabel(self.empty_hint))
            return

        self.summary_label.setText(f"共 {len(comics)} 部漫画")

        # 滚动容器：卡片数量多时可滚动查看，避免显示不全
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        flow_widget = QWidget()
        flow = FlowLayout(flow_widget, spacing=12)
        for comic in comics:
            card = _OfflineComicCard(comic, self._fetcher)
            card.clicked.connect(self.open_comic_requested.emit)
            self._cards.append(card)
            flow.addWidget(card)
        flow_widget.setSizePolicy(flow_widget.sizePolicy().Expanding, flow_widget.sizePolicy().Expanding)
        scroll.setWidget(flow_widget)
        self._stack.addWidget(scroll, 1)

    def _clear_content(self):
        while self._stack.count():
            item = self._stack.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


class OfflineComicPage(QWidget):
    """离线漫画页：展示本地章节列表，点击章节进入阅读；可删除章节 / 整部漫画。"""

    back_requested = pyqtSignal()
    open_chapter_requested = pyqtSignal(object)  # LocalChapter
    chapter_deleted = pyqtSignal(object)         # LocalChapter（删除章节后发出，供刷新列表）
    comic_deleted = pyqtSignal(object)           # LocalComic（删除整部后发出，供返回刷新）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._comic: Optional[LocalComic] = None
        self._index_path = ''
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.back_btn = PushButton("← 返回", self)
        self.back_btn.clicked.connect(self.back_requested.emit)
        top.addWidget(self.back_btn)
        top.addStretch(1)
        self.title_label = SubtitleLabel("本地漫画", self)
        self.title_label.setStyleSheet(f"color: {text_primary()};")
        top.addWidget(self.title_label)
        top.addStretch(1)
        # 设置该漫画的下载分类（写入 DOWNLOADS.LABEL，与下载画廊共享分类）
        self._cat = ''
        self._cat_btn = PushButton("分类", self)
        self._cat_btn.setToolTip("设置该漫画的下载分类")
        self._cat_btn.clicked.connect(self._set_category)
        top.addWidget(self._cat_btn)
        # 删除整部漫画
        self.delete_comic_btn = PushButton(FluentIcon.DELETE, "删除漫画", self)
        self.delete_comic_btn.setToolTip("删除整部漫画的本地文件")
        self.delete_comic_btn.clicked.connect(self._confirm_delete_comic)
        top.addWidget(self.delete_comic_btn)
        root.addLayout(top)

        self._stack = QVBoxLayout()
        root.addLayout(self._stack, 1)

    def set_index_path(self, index_path: str) -> None:
        """删除后使该离线索引失效（下次扫描重建）。"""
        self._index_path = index_path or ''

    def _set_category(self):
        """弹出选择框，把该漫画的分类写入 DOWNLOADS.LABEL。"""
        comic = getattr(self, '_comic', None)
        if comic is None:
            return
        try:
            from PyQt5.QtWidgets import QInputDialog
            from pages.album.ehentai_sync import set_comic_category, read_download_labels
            labels = ['未分类'] + [l['label'] for l in read_download_labels()]
            cur = self._cat or ''
            start = labels.index(cur) if cur in labels else 0
            text, ok = QInputDialog.getItem(self, '设置分类', '选择该漫画的下载分类：',
                                            labels, start, True)
            if not ok:
                return
            text = (text or '').strip()
            set_comic_category(getattr(comic, 'path', '') or '', comic.title,
                               '' if text == '未分类' else text)
            self._cat = '' if text == '未分类' else text
            self._cat_btn.setText(f"分类：{self._cat or '未分类'}")
            InfoBar.success('', '分类已切换', position=InfoBarPosition.TOP, duration=1500,
                            parent=self)
        except Exception:
            pass

    def load_comic(self, comic: LocalComic):
        self._comic = comic
        self.title_label.setText(comic.title or "本地漫画")
        try:
            from pages.album.ehentai_sync import comic_category
            self._cat = comic_category(getattr(comic, 'path', '') or '', comic.title) or ''
        except Exception:
            self._cat = ''
        self._cat_btn.setText(f"分类：{self._cat or '未分类'}")
        self._clear_content()
        if not comic.chapters:
            self._stack.addWidget(EmptyLabel("该漫画暂无本地章节。"))
            return

        self._stack.addWidget(SectionHeader(f"本地章节（共 {len(comic.chapters)} 话）"))
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        for idx, chapter in enumerate(comic.chapters):
            cell = self._build_chapter_cell(chapter)
            row, col = divmod(idx, 2)
            grid.addWidget(cell, row, col)
        # 章节很多时用滚动容器承载，避免撑爆窗口高度
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidget(grid_widget)
        self._stack.addWidget(scroll, 1)
        self._stack.addStretch(1)

    def _build_chapter_cell(self, chapter: LocalChapter) -> QWidget:
        cell = QWidget()
        cell.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 10px;")
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)

        label = QLabel(chapter.label)
        label.setCursor(Qt.PointingHandCursor)
        label.setStyleSheet(f"color: {text_primary()};")
        label.mouseReleaseEvent = (lambda e: self.open_chapter_requested.emit(chapter))
        layout.addWidget(label, 1)

        meta = CaptionLabel(f"{len(chapter.images)} 张{' · 已完成' if chapter.is_done else ''}", cell)
        meta.setStyleSheet(f"color: {text_tertiary()};")
        layout.addWidget(meta)

        read_btn = PushButton("阅读", cell)
        read_btn.clicked.connect(lambda: self.open_chapter_requested.emit(chapter))
        layout.addWidget(read_btn)

        # 删除章节
        del_btn = PushButton(FluentIcon.DELETE, "删除", cell)
        del_btn.setToolTip("删除该章节的本地文件")
        del_btn.clicked.connect(lambda: self._confirm_delete_chapter(chapter))
        layout.addWidget(del_btn)
        return cell

    # ---------- 删除 ----------
    def _confirm_delete_comic(self):
        if self._comic is None:
            return
        comic = self._comic
        w = Dialog(
            '确认删除',
            f'确定要删除漫画「{comic.title}」的所有本地文件吗？\n'
            f'路径：{comic.path}\n此操作不可恢复！',
            self.window(),
        )
        w.yesButton.setText('确认删除')
        w.cancelButton.setText('取消')
        if not w.exec():
            return
        if delete_local_path(comic.path):
            if self._index_path:
                invalidate_index(self._index_path)
            self.comic_deleted.emit(comic)

    def _confirm_delete_chapter(self, chapter: LocalChapter):
        if self._comic is None:
            return
        comic = self._comic
        w = Dialog(
            '确认删除',
            f'确定要删除章节「{chapter.label}」的本地文件吗？\n'
            f'路径：{chapter.path}\n此操作不可恢复！',
            self.window(),
        )
        w.yesButton.setText('确认删除')
        w.cancelButton.setText('取消')
        if not w.exec():
            return
        if not delete_local_path(chapter.path):
            return
        # 从内存中的漫画移除该章节
        if chapter in comic.chapters:
            comic.chapters.remove(chapter)
            comic.total_chapters = len(comic.chapters)
            comic.total_images = sum(len(c.images) for c in comic.chapters)
        if self._index_path:
            invalidate_index(self._index_path)
        self.chapter_deleted.emit(chapter)
        if comic.chapters:
            self.load_comic(comic)
        else:
            self.comic_deleted.emit(comic)

    def _clear_content(self):
        while self._stack.count():
            item = self._stack.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


class OfflineReaderPage(QWidget):
    """离线章节阅读：采用 ReaderWindow 系的阅读逻辑（翻页/卷轴、适配、进度），
    但读取下载目录里的本地图片（保留旧版取图方式）。"""

    back_requested = pyqtSignal()
    open_chapter_requested = pyqtSignal(object)  # LocalChapter

    def __init__(self, fetcher=None, parent=None):
        super().__init__(parent)
        self._comic: Optional[LocalComic] = None
        self._chapter_index = 0
        self._reader = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(24, 12, 24, 0)
        top.setSpacing(8)
        self.back_btn = PushButton("← 返回", self)
        self.back_btn.clicked.connect(self.back_requested.emit)
        top.addWidget(self.back_btn)
        top.addStretch(1)
        self.title_label = SubtitleLabel("", self)
        self.title_label.setStyleSheet(f"color: {text_primary()};")
        top.addWidget(self.title_label)
        top.addStretch(1)
        self.prev_btn = PushButton("上一章", self)
        self.prev_btn.clicked.connect(self._on_prev_chapter)
        self.next_btn = PushButton("下一章", self)
        self.next_btn.clicked.connect(self._on_next_chapter)
        top.addWidget(self.prev_btn)
        top.addWidget(self.next_btn)
        root.addLayout(top)

        self._holder = QWidget(self)
        self._holder_lay = QVBoxLayout(self._holder)
        self._holder_lay.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._holder, 1)

    def load_chapter(self, comic: LocalComic, chapter: LocalChapter):
        self._comic = comic
        if comic and chapter in comic.chapters:
            self._chapter_index = comic.chapters.index(chapter)
        self._render(chapter)

    def _render(self, chapter: LocalChapter):
        # 用 ReaderWindow 的阅读逻辑读本地图片（local_files 模式）
        from ehviewer.models import GalleryInfo
        from ehviewer.ui.reader_window import ReaderWindow
        gi = GalleryInfo()
        gi.gid = int(getattr(self._comic, 'gid', 0) or 0)
        gi.token = ''
        gi.pages = len(chapter.images or [])
        gi.title = chapter.label or ''
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            try:
                self._reader.deleteLater()
            except Exception:
                pass
            self._reader = None
        self._reader = ReaderWindow(gi, 0, self._holder, local_files=list(chapter.images or []))
        self._holder_lay.addWidget(self._reader, 1)
        self.title_label.setText(chapter.label or "")
        chapters = (self._comic.chapters if self._comic else []) or []
        self.prev_btn.setEnabled(self._chapter_index > 0)
        self.next_btn.setEnabled(self._chapter_index < len(chapters) - 1)

    def _on_prev_chapter(self, _href: str = None):
        if self._comic and self._chapter_index > 0:
            self._chapter_index -= 1
            self._render(self._comic.chapters[self._chapter_index])

    def _on_next_chapter(self, _href: str = None):
        if self._comic and self._chapter_index < len(self._comic.chapters) - 1:
            self._chapter_index += 1
            self._render(self._comic.chapters[self._chapter_index])
