# -*- coding: utf-8 -*-
"""
JMComic 在线阅读 + 离线阅读（OGC 集成版）
========================================
- OnlineReadTab：输入本子 ID -> 在线获取章节列表 -> 在线阅读（不落盘）；
- 离线阅读：扫描 jmcomic-download 下载目录，卡片展示已下载漫画，
  复用通用 ComicReaderPage（滚动 / 翻页 / 分页）。

下载目录形态（与拷贝漫画一致）：
    {下载根}/jmcomic-download/{漫画名}/{章节名}/{图片}   （多章）
    {下载根}/jmcomic-download/{漫画名}/{图片}           （单章省略章节名）
"""
from __future__ import annotations

import threading
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from services.comic_library import default_index_path, invalidate_index
from services.jmcomic_service import JMComicService
from ui.widgets.theme import text_primary, text_tertiary

from .comic_offline import (
    OfflineComicPage,
    OfflineLibraryTab,
    OfflineReaderPage,
)
from .easycopy_reader import ComicReaderPage
from .easycopy_widgets import (
    EmptyLabel,
    ErrorLabel,
    FlowLayout,
    LoadingLabel,
    SectionHeader,
)


# ═══════════════════════════════════════════
#  在线阅读标签页
# ═══════════════════════════════════════════
class OnlineReadTab(QWidget):
    """在线阅读：输入本子 ID -> 章节列表 -> 在线阅读。"""

    open_chapter_requested = pyqtSignal(str, str)  # (photo_id, title)

    def __init__(self, service: JMComicService, parent=None):
        super().__init__(parent)
        self.service = service
        self._episodes: List[tuple] = []
        self._album_id = ""
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)

        # 输入行
        row = QHBoxLayout()
        row.setSpacing(10)
        self.album_edit = LineEdit(self)
        self.album_edit.setPlaceholderText("输入 JM 本子 ID，如 123456")
        self.album_edit.setFixedHeight(36)
        self.album_edit.returnPressed.connect(self._load_episodes)
        row.addWidget(self.album_edit, 1)

        self.load_btn = PrimaryPushButton(FluentIcon.SYNC, "加载章节", self)
        self.load_btn.setFixedSize(110, 36)
        self.load_btn.clicked.connect(self._load_episodes)
        row.addWidget(self.load_btn)
        root.addLayout(row)

        # 章节列表区
        self._stack = QVBoxLayout()
        root.addLayout(self._stack, 1)

    def load_album(self, album_id: str):
        album_id = (album_id or "").strip()
        if not album_id:
            return
        self.album_edit.setText(album_id)
        self._load_episodes()

    def _load_episodes(self):
        album_id = self.album_edit.text().strip()
        if not album_id:
            InfoBar.warning("提示", "请输入本子 ID", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        self._album_id = album_id
        self._clear_content()
        self._stack.addWidget(LoadingLabel("正在加载章节列表…"))
        self.service.get_episodes(
            album_id,
            on_done=self._on_episodes_done,
            on_error=self._on_episodes_error,
        )

    def _on_episodes_done(self, episodes):
        self._clear_content()
        self._episodes = list(episodes or [])
        if not self._episodes:
            self._stack.addWidget(EmptyLabel("未获取到章节列表，请检查本子 ID。"))
            return
        self._stack.addWidget(SectionHeader(f"章节列表（共 {len(self._episodes)} 话）"))
        flow_widget = QWidget()
        flow = FlowLayout(flow_widget, spacing=8)
        for idx, (photo_id, title) in enumerate(self._episodes):
            flow.addWidget(self._build_chapter_cell(photo_id, title, idx + 1))
        self._stack.addWidget(flow_widget)
        self._stack.addStretch(1)

    def _on_episodes_error(self, etype, emsg):
        self._clear_content()
        self._stack.addWidget(ErrorLabel(f"加载章节失败：{emsg}"))

    def _build_chapter_cell(self, photo_id: str, title: str, idx: int) -> QWidget:
        cell = QWidget()
        cell.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 10px;")
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)

        label = QLabel(f"第 {idx} 话 · {title}")
        label.setStyleSheet(f"color: {text_primary()};")
        layout.addWidget(label, 1)

        read_btn = PushButton("在线阅读", cell)
        read_btn.clicked.connect(lambda: self.open_chapter_requested.emit(photo_id, title))
        layout.addWidget(read_btn)
        return cell

    def _clear_content(self):
        while self._stack.count():
            item = self._stack.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


# ═══════════════════════════════════════════
#  在线章节阅读页
# ═══════════════════════════════════════════
class OnlineChapterReader(QWidget):
    """在线章节阅读：复用 ComicReaderPage（图片直链异步加载）。"""

    back_requested = pyqtSignal()

    def __init__(self, service: JMComicService, parent=None):
        super().__init__(parent)
        self.service = service
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
        self.title_label = CaptionLabel("在线阅读", self)
        self.title_label.setStyleSheet(f"color: {text_primary()}; font-size: 15px; font-weight: 600;")
        top.addWidget(self.title_label, 1)
        root.addLayout(top)

        self.reader = ComicReaderPage(self._local_fetcher(), self)
        root.addWidget(self.reader, 1)

    def _local_fetcher(self):
        # 在线图使用 requests 下载（异步线程内），这里提供 fetch 接口
        import requests

        _session = requests.Session()
        _session.headers.update({"User-Agent": "Mozilla/5.0"})

        class _Fetcher:
            def fetch(self, url):
                try:
                    resp = _session.get(url, timeout=20, stream=True)
                    if resp.status_code != 200:
                        return None
                    chunks = []
                    total = 0
                    for chunk in resp.iter_content(chunk_size=8192):
                        chunks.append(chunk)
                        total += len(chunk)
                        if total > 20 * 1024 * 1024:
                            break
                    return b"".join(chunks)
                except Exception:
                    return None

        return _Fetcher()

    def load_chapter(self, photo_id: str, title: str):
        self.title_label.setText(title or "在线阅读")
        self.reader.load(f"加载中… {title}", [])
        self.service.read_chapter(
            photo_id,
            on_done=lambda urls: self._on_urls(title, urls),
            on_error=self._on_error,
        )

    def _on_urls(self, title: str, urls):
        urls = [u for u in (urls or []) if u]
        if not urls:
            self.reader.load("加载失败", [])
            self._show_error("未获取到图片，请检查网络或本子 ID。")
            return
        self.reader.load(title or "在线阅读", urls, is_local=False)

    def _on_error(self, etype, emsg):
        self.reader.load("加载失败", [])
        self._show_error(f"加载章节失败：{emsg}")

    def _show_error(self, msg: str):
        from .easycopy_widgets import ErrorLabel
        while self.reader._reader_layout.count():
            item = self.reader._reader_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.reader._reader_layout.addWidget(ErrorLabel(msg))


# ═══════════════════════════════════════════
#  JMComic 阅读页面（在线阅读 + 离线阅读）
# ═══════════════════════════════════════════
class JMComicReaderPage(QWidget):
    """JMComic 阅读页：在线阅读 / 离线阅读 切换。"""

    def __init__(self, service: JMComicService, parent=None):
        super().__init__(parent)
        self.service = service

        self._root_stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._root_stack)

        # ---- 主视图：在线阅读 + 离线阅读 ----
        self._main_view = QWidget(self)
        main_layout = QVBoxLayout(self._main_view)
        main_layout.setContentsMargins(0, 8, 0, 0)
        main_layout.setSpacing(12)

        # 分段导航
        from qfluentwidgets import SegmentedWidget

        self.pivot = SegmentedWidget(self._main_view)
        pivot_row = QHBoxLayout()
        pivot_row.setContentsMargins(24, 0, 24, 0)
        pivot_row.addWidget(self.pivot)
        main_layout.addLayout(pivot_row)

        self._tabs_stack = QStackedWidget(self._main_view)
        self.online_tab = OnlineReadTab(self.service, self)
        self.online_tab.setObjectName("jmOnlineTab")
        offline_root = str(self.service.offline_root())
        self.offline_tab = OfflineLibraryTab(
            scan_root=offline_root,
            index_path=default_index_path(offline_root, 'jmcomic'),
            empty_hint="暂无已下载的 JM 漫画。\n在「下载中心」下载后，这里会自动显示。",
        )
        self.offline_tab.setObjectName("jmOfflineTab")

        self._tabs_stack.addWidget(self.online_tab)
        self._tabs_stack.addWidget(self.offline_tab)
        self.pivot.addItem(routeKey="jmOnlineTab", text="在线阅读")
        self.pivot.addItem(routeKey="jmOfflineTab", text="离线阅读")
        self._tabs_stack.setCurrentWidget(self.online_tab)
        self.pivot.setCurrentItem("jmOnlineTab")
        self.pivot.currentItemChanged.connect(self._on_pivot_changed)

        main_layout.addWidget(self._tabs_stack, 1)
        self._root_stack.addWidget(self._main_view)

        # ---- 在线章节阅读页 ----
        self.online_reader = OnlineChapterReader(self.service, self)
        self.online_reader.setObjectName("jmOnlineReader")
        self.online_reader.back_requested.connect(lambda: self._root_stack.setCurrentWidget(self._main_view))
        self.online_tab.open_chapter_requested.connect(self._open_online_chapter)
        self._root_stack.addWidget(self.online_reader)

        # ---- 离线漫画章节列表 / 阅读器 ----
        self.offline_comic_page = OfflineComicPage(self)
        self.offline_comic_page.setObjectName("jmOfflineComic")
        self.offline_comic_page.back_requested.connect(lambda: self._root_stack.setCurrentWidget(self._main_view))
        self.offline_comic_page.open_chapter_requested.connect(self._open_offline_chapter)
        # 删除功能：删除后使索引失效并刷新离线列表
        self.offline_comic_page.set_index_path(default_index_path(offline_root, 'jmcomic'))
        self.offline_comic_page.chapter_deleted.connect(
            lambda _c: self.offline_tab.load(force=True))
        self.offline_comic_page.comic_deleted.connect(self._on_offline_comic_deleted)
        self._root_stack.addWidget(self.offline_comic_page)

        self.offline_reader_page = OfflineReaderPage(parent=self)
        self.offline_reader_page.setObjectName("jmOfflineReader")
        self.offline_reader_page.back_requested.connect(lambda: self._root_stack.setCurrentWidget(self.offline_comic_page))
        self._root_stack.addWidget(self.offline_reader_page)

        self.offline_tab.open_comic_requested.connect(self._open_offline_comic)

        self._root_stack.setCurrentWidget(self._main_view)

    # ------------------------------------------------------------------
    def _on_pivot_changed(self, routeKey: str):
        widget = self.findChild(QWidget, routeKey)
        if widget is not None:
            self._tabs_stack.setCurrentWidget(widget)
            if routeKey == "jmOfflineTab":
                self.offline_tab.load()

    def _open_online_chapter(self, photo_id: str, title: str):
        self._root_stack.setCurrentWidget(self.online_reader)
        self.online_reader.load_chapter(photo_id, title)

    def _open_offline_comic(self, comic):
        self._root_stack.setCurrentWidget(self.offline_comic_page)
        self.offline_comic_page.load_comic(comic)

    def _open_offline_chapter(self, chapter):
        comic = self.offline_comic_page._comic
        if comic is None:
            return
        self._root_stack.setCurrentWidget(self.offline_reader_page)
        self.offline_reader_page.load_chapter(comic, chapter)

    def _on_offline_comic_deleted(self, _comic):
        """离线漫画被删除：返回主界面并强制刷新离线列表。"""
        self._root_stack.setCurrentWidget(self._main_view)
        self.offline_tab.load(force=True)

    # ---------- 对外 ----------
    def read_online(self, album_id: str):
        """外部入口：按本子 ID 在线阅读。"""
        self._root_stack.setCurrentWidget(self._main_view)
        self.pivot.setCurrentItem("jmOnlineTab")
        self._tabs_stack.setCurrentWidget(self.online_tab)
        self.online_tab.load_album(album_id)

    def reload_offline(self):
        self.offline_tab.load()
