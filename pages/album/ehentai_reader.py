# -*- coding: utf-8 -*-
"""
E-Hentai 在线阅读 + 离线阅读（OGC 集成版）
========================================
- OnlineGalleryReader：输入画廊 URL -> 在线解析图片直链 -> 在线阅读（不落盘）；
- 离线阅读：扫描 E-Hentai 下载目录（output_dir），卡片展示已下载画廊。

下载目录形态（与拷贝漫画一致，E-Hentai 无章节层）：
    {output_dir}/{画廊名}/{图片文件}
"""
from __future__ import annotations

import os
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
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
    SubtitleLabel,
)

from services.ehentai_downloader import DownloadConfig, EhentaiDownloader
from services.comic_library import default_index_path, invalidate_index
from pages.album.ehentai_settings import ehentai_cfg as _eh_cfg, IMAGE_FORMAT_MAP  # noqa: F401
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
    LoadingLabel,
    SectionHeader,
)


def _do_resolve(url: str) -> tuple:
    """同步解析画廊图片直链（复用下载器解析逻辑）。"""
    config = DownloadConfig(url=url, output_dir=os.path.join(os.path.dirname(url), '_reader_tmp'))
    dl = EhentaiDownloader(config)
    dl.session = dl._build_session()

    title, page_total = dl._parse_gallery()
    urls = []
    for p in range(page_total):
        detail_urls = dl._get_page_image_urls(p)
        for detail in detail_urls:
            img = dl._resolve_image_url(detail)
            if img:
                urls.append(img)
    return (title, urls)


# ═══════════════════════════════════════════
#  在线画廊阅读页
# ═══════════════════════════════════════════
class OnlineGalleryReader(QWidget):
    """在线画廊阅读：输入 URL -> 解析直链 -> 复用 ComicReaderPage。"""

    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.url_edit = LineEdit(self)
        self.url_edit.setPlaceholderText("输入 E-Hentai 画廊 URL")
        self.url_edit.setFixedHeight(36)
        self.url_edit.returnPressed.connect(self._start)
        row.addWidget(self.url_edit, 1)

        self.load_btn = PrimaryPushButton(FluentIcon.SYNC, "在线阅读", self)
        self.load_btn.setFixedSize(110, 36)
        self.load_btn.clicked.connect(self._start)
        row.addWidget(self.load_btn)
        root.addLayout(row)

        self._stack = QVBoxLayout()
        root.addLayout(self._stack, 1)

    def start(self, url: str):
        if url:
            self.url_edit.setText(url)
            self._start()

    def _start(self):
        url = self.url_edit.text().strip()
        if not url:
            InfoBar.warning("提示", "请输入画廊 URL", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        self._clear_content()
        self._stack.addWidget(LoadingLabel("正在解析画廊…"))

        import requests

        # 复用下载器解析，后台线程避免卡 UI
        def _run():
            try:
                title, urls = _do_resolve(url)
                self._on_done(title, urls)
            except Exception as e:
                self._on_error(str(e))

        threading.Thread(target=_run, daemon=True).start()

    def _on_done(self, title: str, urls: List[str]):
        self._clear_content()
        urls = [u for u in urls if u]
        if not urls:
            self._stack.addWidget(ErrorLabel("未解析到图片，请检查 URL 或 Cookies 配置。"))
            return
        reader = _InlineReader(self)
        reader.load(title or "画廊阅读", urls, is_local=False)
        self._stack.addWidget(reader, 1)

    def _on_error(self, msg: str):
        self._clear_content()
        self._stack.addWidget(ErrorLabel(f"解析失败：{msg}"))

    def _clear_content(self):
        while self._stack.count():
            item = self._stack.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


class _InlineReader(ComicReaderPage):
    """内嵌在线阅读器（无章节导航按钮）。"""

    def __init__(self, parent=None):
        super().__init__(_requests_fetcher(), parent)
        self._prev_btn.setVisible(False)
        self._next_btn.setVisible(False)


def _requests_fetcher():
    """在线图片 fetcher（requests 后台线程下载）。"""
    import requests

    _session = requests.Session()
    _session.headers.update({"User-Agent": "Mozilla/5.0"})
    _session.headers.update({"Referer": "https://e-hentai.org/"})

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


# ═══════════════════════════════════════════
#  E-Hentai 阅读页（在线阅读 + 离线阅读）
# ═══════════════════════════════════════════
class EhentaiReaderPage(QWidget):
    """E-Hentai 阅读页：在线阅读 / 离线阅读 切换。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._root_stack)

        # ---- 主视图 ----
        self._main_view = QWidget(self)
        main_layout = QVBoxLayout(self._main_view)
        main_layout.setContentsMargins(0, 8, 0, 0)
        main_layout.setSpacing(12)

        self.pivot = SegmentedWidget(self._main_view)
        pivot_row = QHBoxLayout()
        pivot_row.setContentsMargins(24, 0, 24, 0)
        pivot_row.addWidget(self.pivot)
        main_layout.addLayout(pivot_row)

        self._tabs_stack = QStackedWidget(self._main_view)
        self.online_tab = OnlineGalleryReader(self)
        self.online_tab.setObjectName("ehOnlineTab")
        eh_root = _eh_cfg.get(_eh_cfg.KEY_OUTPUT_DIR, str(_default_output_dir()))
        self.offline_tab = OfflineLibraryTab(
            scan_root=eh_root,
            index_path=default_index_path(eh_root, 'ehentai'),
            empty_hint="暂无已下载的 E-Hentai 画廊。\n在「下载画廊」下载后，这里会自动显示。",
        )
        self.offline_tab.setObjectName("ehOfflineTab")

        self._tabs_stack.addWidget(self.online_tab)
        self._tabs_stack.addWidget(self.offline_tab)
        self.pivot.addItem(routeKey="ehOnlineTab", text="在线阅读")
        self.pivot.addItem(routeKey="ehOfflineTab", text="离线阅读")
        self._tabs_stack.setCurrentWidget(self.online_tab)
        self.pivot.setCurrentItem("ehOnlineTab")
        self.pivot.currentItemChanged.connect(self._on_pivot_changed)
        main_layout.addWidget(self._tabs_stack, 1)
        self._root_stack.addWidget(self._main_view)

        # ---- 离线漫画章节列表 / 阅读器 ----
        self.offline_comic_page = OfflineComicPage(self)
        self.offline_comic_page.setObjectName("ehOfflineComic")
        self.offline_comic_page.back_requested.connect(lambda: self._root_stack.setCurrentWidget(self._main_view))
        self.offline_comic_page.open_chapter_requested.connect(self._open_offline_chapter)
        # 删除功能：删除后使索引失效并刷新离线列表
        self.offline_comic_page.set_index_path(default_index_path(eh_root, 'ehentai'))
        self.offline_comic_page.chapter_deleted.connect(
            lambda _c: self.offline_tab.load(force=True))
        self.offline_comic_page.comic_deleted.connect(self._on_offline_comic_deleted)
        self._root_stack.addWidget(self.offline_comic_page)

        self.offline_reader_page = OfflineReaderPage(parent=self)
        self.offline_reader_page.setObjectName("ehOfflineReader")
        self.offline_reader_page.back_requested.connect(lambda: self._root_stack.setCurrentWidget(self.offline_comic_page))
        self._root_stack.addWidget(self.offline_reader_page)

        self.offline_tab.open_comic_requested.connect(self._open_offline_comic)
        self._root_stack.setCurrentWidget(self._main_view)

    # ------------------------------------------------------------------
    def _on_pivot_changed(self, routeKey: str):
        widget = self.findChild(QWidget, routeKey)
        if widget is not None:
            self._tabs_stack.setCurrentWidget(widget)
            if routeKey == "ehOfflineTab":
                new_root = _eh_cfg.get(_eh_cfg.KEY_OUTPUT_DIR,
                                       str(_default_output_dir()))
                # 原实现每次切到本标签页都 load()，等于**每切回来一次就重扫一遍
                # 本地画廊目录**（大目录要等好几秒）。现在只在两种情况下加载：
                #   1) 首次进入本标签页；2) 输出目录被改过（否则会一直显示旧目录的内容）。
                # 显式刷新仍由「刷新」按钮与 reload_offline() 提供。
                changed = os.path.abspath(new_root) != os.path.abspath(
                    self.offline_tab.scan_root or '')
                self.offline_tab.set_scan_root(new_root)
                if changed or not getattr(self, '_offline_loaded', False):
                    self._offline_loaded = True
                    self.offline_tab.load()

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
    def read_online(self, url: str):
        self._root_stack.setCurrentWidget(self._main_view)
        self.pivot.setCurrentItem("ehOnlineTab")
        self._tabs_stack.setCurrentWidget(self.online_tab)
        self.online_tab.start(url)

    def reload_offline(self):
        root = _eh_cfg.get(_eh_cfg.KEY_OUTPUT_DIR, str(_default_output_dir()))
        self.offline_tab.set_scan_root(root)
        self._offline_loaded = True
        self.offline_tab.load()


def _default_output_dir() -> str:
    try:
        from core.config import config as CFG
        return str(CFG.data / 'ehentai' / 'galleries')
    except Exception:
        return 'data/ehentai/galleries'
