# -*- coding: utf-8 -*-
"""
拷贝漫画详情页 + 阅读器（OGC 集成版）
====================================
- DetailPage：封面 / 简介 / 章节列表；每个章节可下载，也可「下载全部」。
  下载保存到 easycopy-download/漫画名/章节名/图片文件（与 douyin-download 同级）。
- ReaderPage：章节阅读器（整页滚动，逐图异步加载）。
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SubtitleLabel,
    TextEdit,
    ToolButton,
)

from services.easycopy.app import AppContext
from services.easycopy.downloader import (
    EasyCopyDownloadConfig,
    EasyCopyDownloader,
    EasyCopyProgress,
)
from services.easycopy.models import DetailChapterData, DetailPageData, ReaderPageData
from ui.widgets.theme import text_primary, text_secondary, text_tertiary

from .easycopy_reader import ComicReaderPage
from .easycopy_widgets import (
    CoverImage,
    EmptyLabel,
    ErrorLabel,
    LoadingLabel,
    SectionHeader,
)


# ═══════════════════════════════════════════
#  章节下载线程
# ═══════════════════════════════════════════
class _ChapterDownloadWorker(QThread):
    """后台下载一个（或多个）章节。"""

    log_emitted = pyqtSignal(str, str)
    progress_updated = pyqtSignal(object)
    finished_signal = pyqtSignal(object)

    def __init__(self, ctx, comic_title: str, chapters: List[tuple], parent=None):
        """
        chapters: [(label, href), ...]
        """
        super().__init__(parent)
        self.ctx = ctx
        self.comic_title = comic_title
        self.chapters = chapters
        self.downloader: Optional[EasyCopyDownloader] = None

    def run(self):
        from services.easycopy.downloader import EasyCopyDownloadConfig, EasyCopyDownloader

        for label, href in self.chapters:
            if self.downloader is not None and self.downloader.is_stopping():
                break
            config = EasyCopyDownloadConfig(
                comic_title=self.comic_title,
                chapter_label=label,
                chapter_href=href,
            )
            self.downloader = EasyCopyDownloader(config, ctx=self.ctx)
            self.downloader.set_listener(self)
            self.downloader.run()
        self.finished_signal.emit(True)

    def stop(self):
        if self.downloader is not None:
            self.downloader.stop()

    # ---- 下载器回调（子线程）----
    def on_log(self, msg: str, level: str = 'info') -> None:
        self.log_emitted.emit(msg, level)

    def on_progress(self, progress: EasyCopyProgress) -> None:
        self.progress_updated.emit(progress)

    def on_finished(self, progress: EasyCopyProgress) -> None:
        pass  # 由 finished_signal 统一收尾


# ═══════════════════════════════════════════
#  详情页
# ═══════════════════════════════════════════
class EasyCopyDetailPage(QWidget):
    """漫画详情页：信息 + 章节网格 + 下载。"""

    back_requested = pyqtSignal()
    open_chapter_requested = pyqtSignal(str)   # chapter href

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._page_uri = ""
        self._page: Optional[DetailPageData] = None
        self._cover = None
        self._worker: Optional[_ChapterDownloadWorker] = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 36, 24, 16)
        root.setSpacing(12)

        # 顶部：返回 + 标题
        top = QHBoxLayout()
        self.back_btn = PushButton("← 返回", self)
        self.back_btn.clicked.connect(self.back_requested.emit)
        top.addWidget(self.back_btn)
        top.addStretch(1)
        self.page_title = SubtitleLabel("漫画详情", self)
        top.addWidget(self.page_title)
        top.addStretch(1)
        root.addLayout(top)

        self._stack = QVBoxLayout()
        root.addLayout(self._stack, 1)

    # ---------------- 加载 ----------------
    def load(self, uri: str):
        self._page_uri = uri
        self._page = None
        self._clear_content()
        self._stack.addWidget(LoadingLabel("正在加载详情…"))
        self.ctx.load_page(uri, self._on_loaded)

    def _clear_content(self):
        while self._stack.count():
            item = self._stack.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cover = None

    def _on_loaded(self, page, error):
        self._clear_content()
        if error is not None:
            self._stack.addWidget(ErrorLabel(f"详情加载失败：{error}"))
            return
        if not isinstance(page, DetailPageData):
            self._stack.addWidget(ErrorLabel("数据格式异常"))
            return
        self._page = page
        self.page_title.setText(page.title or "漫画详情")
        self._build_view(page)

    def _build_view(self, page: DetailPageData):
        scroll = _DetailScroll(self)
        self._stack.addWidget(scroll, 1)
        self._scroll = scroll

        # ---- 信息卡 ----
        info_card = QFrame(scroll.content)
        info_card.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 20px;")
        info_layout = QHBoxLayout(info_card)
        info_layout.setContentsMargins(20, 20, 20, 20)
        info_layout.setSpacing(20)

        if page.cover_url:
            self._cover = CoverImage(page.cover_url, self.ctx.image_fetcher, radius=16, placeholder_text=page.title)
            self._cover.setFixedSize(150, 210)
            info_layout.addWidget(self._cover)

        text_box = QVBoxLayout()
        text_box.setSpacing(8)
        title = SubtitleLabel(page.title or "未知标题", info_card)
        title.setWordWrap(True)
        title.setStyleSheet(f"color: {text_primary()};")
        text_box.addWidget(title)

        meta_parts = []
        if page.author:
            meta_parts.append(f"作者：{page.author}")
        if page.status:
            meta_parts.append(page.status)
        if page.region:
            meta_parts.append(page.region)
        if meta_parts:
            meta = CaptionLabel(" · ".join(meta_parts), info_card)
            meta.setWordWrap(True)
            meta.setStyleSheet(f"color: {text_secondary()};")
            text_box.addWidget(meta)

        if page.tags:
            tags_label = CaptionLabel("标签：" + "、".join(page.tags), info_card)
            tags_label.setWordWrap(True)
            tags_label.setStyleSheet("color: #28AFE9;")
            text_box.addWidget(tags_label)

        if page.description:
            desc = BodyLabel(page.description, info_card)
            desc.setWordWrap(True)
            desc.setMaximumHeight(100)
            desc.setStyleSheet(f"color: {text_secondary()};")
            text_box.addWidget(desc)

        text_box.addStretch(1)
        info_layout.addLayout(text_box, 1)
        scroll.layout.addWidget(info_card)

        # ---- 下载工具条 ----
        toolbar = QWidget(scroll.content)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(10)

        self.download_all_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "下载全部", toolbar)
        self.download_all_btn.clicked.connect(lambda: self._download_all())
        toolbar_layout.addWidget(self.download_all_btn)

        self.stop_btn = PushButton(FluentIcon.CANCEL, "停止", toolbar)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_download)
        toolbar_layout.addWidget(self.stop_btn)

        self.dl_status = CaptionLabel("", toolbar)
        self.dl_status.setStyleSheet(f"color: {text_secondary()};")
        toolbar_layout.addWidget(self.dl_status, 1)
        scroll.layout.addWidget(toolbar)

        # ---- 下载进度条 ----
        self.progress_bar = ProgressBar(scroll.content)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        scroll.layout.addWidget(self.progress_bar)

        # ---- 章节列表 ----
        scroll.layout.addWidget(SectionHeader(f"章节列表（共 {len(page.chapters)} 话）", parent=scroll.content))
        if page.chapters:
            chapter_grid = QWidget(scroll.content)
            grid = QGridLayout(chapter_grid)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(8)
            for idx, ch in enumerate(page.chapters):
                cell = self._build_chapter_cell(ch)
                row, col = divmod(idx, 2)
                grid.addWidget(cell, row, col)
            scroll.layout.addWidget(chapter_grid)
        else:
            scroll.layout.addWidget(EmptyLabel("暂无章节信息。"))
        scroll.layout.addStretch(1)

        # ---- 下载日志 ----
        self.log_view = TextEdit(scroll.content)
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(90)
        self.log_view.setPlaceholderText("下载日志将显示在这里…")
        self.log_view.setStyleSheet(
            "background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.2);"
            "border-radius: 8px; padding: 8px; font-family: Consolas, monospace; font-size: 12px;"
        )
        self.log_view.setVisible(False)
        scroll.layout.addWidget(self.log_view)

    def _build_chapter_cell(self, chapter: DetailChapterData) -> QWidget:
        cell = QWidget()
        cell.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 10px;")
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(8)

        label = QLabel(chapter.label)
        label.setCursor(Qt.PointingHandCursor)
        label.setStyleSheet(f"color: {text_primary()};")
        label.mouseReleaseEvent = (lambda e: self.open_chapter_requested.emit(chapter.href))
        layout.addWidget(label, 1)

        dl_btn = ToolButton(FluentIcon.DOWNLOAD, cell)
        dl_btn.setToolTip("下载本话")
        dl_btn.setFixedSize(30, 30)
        dl_btn.clicked.connect(lambda: self._download_chapter(chapter))
        layout.addWidget(dl_btn)
        return cell

    # ---------------- 下载 ----------------
    def _current_comic_title(self) -> str:
        return self._page.title if self._page else "未知漫画"

    def _download_chapter(self, chapter: DetailChapterData):
        if self._worker is not None and self._worker.isRunning():
            InfoBar.warning("提示", "已有下载任务进行中", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        self._start_download([(chapter.label, chapter.href)])

    def _download_all(self):
        if self._page is None or not self._page.chapters:
            InfoBar.warning("提示", "暂无章节可下载", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        if self._worker is not None and self._worker.isRunning():
            InfoBar.warning("提示", "已有下载任务进行中", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        chapters = [(ch.label, ch.href) for ch in self._page.chapters]
        self._start_download(chapters)

    def _start_download(self, chapters: List[tuple]):
        if not chapters:
            return
        self._set_downloading(True)
        self._append_log(f"开始下载 {len(chapters)} 个章节 …", 'info')
        self.worker = _ChapterDownloadWorker(self.ctx, self._current_comic_title(), chapters, self)
        self.worker.log_emitted.connect(self._on_worker_log)
        self.worker.progress_updated.connect(self._on_worker_progress)
        self.worker.finished_signal.connect(self._on_worker_finished)
        self.worker.start()

    def _stop_download(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self._append_log("正在停止，请稍候…", 'warning')

    def _set_downloading(self, running: bool):
        self.download_all_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.progress_bar.setVisible(running)
        self.log_view.setVisible(True)
        if running:
            self.download_all_btn.setText("下载中…")

    def _on_worker_log(self, msg: str, level: str = 'info'):
        self._append_log(msg, level)

    def _append_log(self, msg: str, level: str = 'info'):
        if not hasattr(self, 'log_view') or self.log_view is None:
            return
        from PyQt5.QtGui import QColor, QTextCharFormat
        color_map = {
            'info': '#737a82', 'success': '#2ea44f', 'warning': '#d4a72c', 'error': '#cf222e',
        }
        cursor = self.log_view.textCursor()
        cursor.movePosition(cursor.End)
        if self.log_view.toPlainText():
            cursor.insertText('\n')
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color_map.get(level, '#737a82')))
        cursor.setCharFormat(fmt)
        cursor.insertText(msg)
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def _on_worker_progress(self, progress: EasyCopyProgress):
        if progress.total > 0:
            percent = int(progress.done / progress.total * 100)
            self.progress_bar.setValue(percent)
        self.dl_status.setText(
            f"{progress.title} · 完成 {progress.done}/{progress.total} · 失败 {progress.failed}"
        )

    def _on_worker_finished(self, _payload):
        self._set_downloading(False)
        self.download_all_btn.setText("下载全部")
        self.dl_status.setText("")
        if self.worker is not None and self.worker.downloader is not None and self.worker.downloader.is_stopping():
            InfoBar.warning("下载已停止", "任务已停止。", parent=self, position=InfoBarPosition.TOP, duration=3000)
        else:
            InfoBar.success(
                "下载完成",
                f"已保存到 easycopy-download/{self._current_comic_title()}/",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )

    def closeEvent(self, event):
        try:
            if self.worker is not None and self.worker.isRunning():
                self.worker.stop()
                self.worker.wait(1500)
        except Exception:
            pass
        super().closeEvent(event)


class _DetailScroll(QWidget):
    """详情页滚动容器（内容可滚动）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt5.QtWidgets import QScrollArea
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(0, 4, 0, 20)
        self.layout.setSpacing(14)
        self._scroll.setWidget(self.content)
        self._outer.addWidget(self._scroll)


# ═══════════════════════════════════════════
#  阅读器（复用通用 ComicReaderPage）
# ═══════════════════════════════════════════
class EasyCopyReaderPage(QWidget):
    """章节阅读器：整页滚动 / 翻页分页，图片经 ImageFetcher 异步加载。"""

    back_requested = pyqtSignal()
    open_chapter_requested = pyqtSignal(str)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._page: Optional[ReaderPageData] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部返回栏
        top = QHBoxLayout()
        top.setContentsMargins(24, 12, 24, 0)
        top.setSpacing(8)
        self.back_btn = PushButton("← 返回", self)
        self.back_btn.clicked.connect(self.back_requested.emit)
        top.addWidget(self.back_btn)
        top.addStretch(1)
        root.addLayout(top)

        self.reader = _OnlineComicReader(self.ctx.image_fetcher, self)
        self.reader.prev_chapter_requested.connect(self._go_prev)
        self.reader.next_chapter_requested.connect(self._go_next)
        root.addWidget(self.reader, 1)

    def load(self, uri: str):
        self._page_uri = uri
        self._page = None
        self.reader.load("正在加载章节…", [])
        self.ctx.load_page(uri, self._on_loaded)

    def _on_loaded(self, page, error):
        if error is not None:
            self.reader.load("加载失败", [])
            self.reader.load_error(f"章节加载失败：{error}")
            return
        if not isinstance(page, ReaderPageData):
            self.reader.load("加载失败", [])
            self.reader.load_error("数据格式异常")
            return
        self._page = page
        self.reader.load(
            title=page.chapter_label or page.title or "阅读",
            sources=page.images,
            is_local=False,
            prev_href=page.prev_href or "",
            next_href=page.next_href or "",
        )

    def _go_prev(self, href: str):
        if href:
            self.open_chapter_requested.emit(href)

    def _go_next(self, href: str):
        if href:
            self.open_chapter_requested.emit(href)


class _OnlineComicReader(ComicReaderPage):
    """在线阅读器：增加错误信息展示能力。"""

    def load_error(self, msg: str):
        from .easycopy_widgets import ErrorLabel as _ErrorLabel
        if self._reader_layout is not None:
            # 清空占位内容后展示错误
            while self._reader_layout.count():
                item = self._reader_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            self._reader_layout.addWidget(_ErrorLabel(msg))
