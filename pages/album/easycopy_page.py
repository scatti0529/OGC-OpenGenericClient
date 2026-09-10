# -*- coding: utf-8 -*-
"""
拷贝漫画子模块页面（OGC 集成版）
================================
将独立程序 OGC-EasyCopy 的五个页面（首页 / 发现 / 排行榜 / 个人中心 / 设置）
合并为一个页面，顶部用分段导航栏（SegmentedWidget）切换；搜索放在首页内；
漫画详情页支持下载到 easycopy-download/漫画名/章节名/漫画文件；
新增「离线阅读」标签页：自动扫描本地已下载漫画并支持离线阅读（翻页/分页）。

结构：
    EasyCopyPage (QWidget)
    ├── 主视图（QStackedWidget 第 0 层）
    │   ├── 标题行（拷贝漫画 + 简介）
    │   ├── SegmentedWidget（首页 / 发现 / 排行 / 我的 / 设置 / 离线阅读）
    │   └── QStackedWidget（六个标签页）
    ├── 详情页（第 1 层，点击漫画卡片进入）
    ├── 在线阅读器（第 2 层，点击章节进入）
    ├── 离线漫画章节列表（第 3 层）
    └── 离线阅读器（第 4 层）
"""
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    CaptionLabel,
    SegmentedWidget,
    TitleLabel,
)

from services.easycopy.app import AppContext
from ui.widgets.theme import ensure_theme_connected, on_theme_changed, text_tertiary

from .easycopy_detail import EasyCopyDetailPage, EasyCopyReaderPage
from .easycopy_offline import (
    OfflineComicPage,
    OfflineReaderPage,
    OfflineTab,
)
from .easycopy_tabs import (
    DiscoverTab,
    HomeTab,
    ProfileTab,
    RankTab,
    SettingsTab,
)


class EasyCopyPage(QWidget):
    """拷贝漫画子模块：分段导航切换六个标签页 + 详情/阅读器/离线阅读。"""

    TAB_HOME = 'easycopyHomeTab'
    TAB_DISCOVER = 'easycopyDiscoverTab'
    TAB_RANK = 'easycopyRankTab'
    TAB_PROFILE = 'easycopyProfileTab'
    TAB_SETTINGS = 'easycopySettingsTab'
    TAB_OFFLINE = 'easycopyOfflineTab'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('easycopyPage')

        # 上下文（数据保存在 data/easycopy）
        self.ctx = AppContext()

        # 根堆栈：主视图 / 详情 / 阅读器 / 离线列表 / 离线阅读器
        self._root_stack = QStackedWidget(self)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.addWidget(self._root_stack)

        # ---- 主视图 ----
        self._main_view = QWidget(self)
        self._main_layout = QVBoxLayout(self._main_view)
        self._main_layout.setContentsMargins(0, 36, 0, 0)
        self._main_layout.setSpacing(12)

        # 标题行
        header = QHBoxLayout()
        header.setContentsMargins(24, 0, 24, 0)
        header.setSpacing(12)
        self.title_label = TitleLabel('拷贝漫画', self._main_view)
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.desc_label = CaptionLabel('首页 · 发现 · 排行 · 我的 · 设置 · 离线阅读', self._main_view)
        self.desc_label.setStyleSheet(f'color: {text_tertiary()};')
        header.addWidget(self.desc_label)
        self._main_layout.addLayout(header)

        # 分段导航栏
        pivot_row = QHBoxLayout()
        pivot_row.setContentsMargins(24, 0, 24, 0)
        self.pivot = SegmentedWidget(self._main_view)
        pivot_row.addWidget(self.pivot)
        self._main_layout.addLayout(pivot_row)

        # 六个标签页
        self.stackedWidget = QStackedWidget(self._main_view)

        self.home_page = HomeTab(self.ctx, self._open_comic, self._navigate, self)
        self.home_page.setObjectName(self.TAB_HOME)
        self.discover_page = DiscoverTab(self.ctx, self._open_comic, self._navigate, self)
        self.discover_page.setObjectName(self.TAB_DISCOVER)
        self.rank_page = RankTab(self.ctx, self._open_comic, self._navigate, self)
        self.rank_page.setObjectName(self.TAB_RANK)
        self.profile_page = ProfileTab(self.ctx, self._open_comic, self)
        self.profile_page.setObjectName(self.TAB_PROFILE)
        self.settings_page = SettingsTab(self.ctx, self)
        self.settings_page.setObjectName(self.TAB_SETTINGS)
        self.offline_page = OfflineTab(ctx=self.ctx, parent=self)
        self.offline_page.setObjectName(self.TAB_OFFLINE)
        self.offline_page.open_comic_requested.connect(self._open_offline_comic)

        self.stackedWidget.addWidget(self.home_page)
        self.stackedWidget.addWidget(self.discover_page)
        self.stackedWidget.addWidget(self.rank_page)
        self.stackedWidget.addWidget(self.profile_page)
        self.stackedWidget.addWidget(self.settings_page)
        self.stackedWidget.addWidget(self.offline_page)

        self.pivot.addItem(routeKey=self.TAB_HOME, text='首页')
        self.pivot.addItem(routeKey=self.TAB_DISCOVER, text='发现')
        self.pivot.addItem(routeKey=self.TAB_RANK, text='排行')
        self.pivot.addItem(routeKey=self.TAB_PROFILE, text='我的')
        self.pivot.addItem(routeKey=self.TAB_SETTINGS, text='设置')
        self.pivot.addItem(routeKey=self.TAB_OFFLINE, text='离线阅读')
        self.stackedWidget.setCurrentWidget(self.home_page)
        self.pivot.setCurrentItem(self.TAB_HOME)
        self.pivot.currentItemChanged.connect(self._on_current_item_changed)

        self._main_layout.addWidget(self.stackedWidget, 1)
        self._root_stack.addWidget(self._main_view)

        # ---- 详情页 ----
        self.detail_page = EasyCopyDetailPage(self.ctx, self)
        self.detail_page.setObjectName('easycopyDetail')
        self.detail_page.back_requested.connect(self._back_to_main)
        self.detail_page.open_chapter_requested.connect(self._open_chapter)
        self._root_stack.addWidget(self.detail_page)

        # ---- 在线阅读器 ----
        self.reader_page = EasyCopyReaderPage(self.ctx, self)
        self.reader_page.setObjectName('easycopyReader')
        self.reader_page.back_requested.connect(self._back_to_main)
        self.reader_page.open_chapter_requested.connect(self._open_chapter)
        self._root_stack.addWidget(self.reader_page)

        # ---- 离线漫画章节列表 ----
        self.offline_comic_page = OfflineComicPage(self)
        self.offline_comic_page.setObjectName('easycopyOfflineComic')
        self.offline_comic_page.back_requested.connect(self._back_to_main)
        self.offline_comic_page.open_chapter_requested.connect(self._open_offline_chapter)
        # 删除功能：删除后使索引失效并刷新离线列表
        self.offline_comic_page.set_index_path(self.offline_page._index_path)
        self.offline_comic_page.chapter_deleted.connect(
            lambda _c: self.offline_page.load(force=True))
        self.offline_comic_page.comic_deleted.connect(self._on_offline_comic_deleted)
        self._root_stack.addWidget(self.offline_comic_page)

        # ---- 离线阅读器 ----
        self.offline_reader_page = OfflineReaderPage(parent=self)
        self.offline_reader_page.setObjectName('easycopyOfflineReader')
        self.offline_reader_page.back_requested.connect(self._back_offline)
        self._root_stack.addWidget(self.offline_reader_page)

        self._root_stack.setCurrentWidget(self._main_view)

        # 主题联动
        ensure_theme_connected()
        on_theme_changed(self._apply_theme_style)

        # 延迟首载（等窗口就绪）
        QTimer.singleShot(0, self._initial_load)

    # ------------------------------------------------------------------
    def _initial_load(self):
        try:
            self.home_page.load()
        except Exception:
            pass

    def _apply_theme_style(self) -> None:
        """主题切换时刷新（组件使用语义色，轻量处理即可）。"""
        try:
            self.desc_label.setStyleSheet(f'color: {text_tertiary()};')
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  分段导航
    # ------------------------------------------------------------------
    def _on_current_item_changed(self, routeKey: str) -> None:
        widget = self.findChild(QWidget, routeKey)
        if widget is not None:
            self.stackedWidget.setCurrentWidget(widget)
            self._refresh_current_tab(routeKey)

    def _refresh_current_tab(self, routeKey: str) -> None:
        if routeKey == self.TAB_HOME:
            self.home_page.load()
        elif routeKey == self.TAB_DISCOVER:
            self.discover_page.load()
        elif routeKey == self.TAB_RANK:
            self.rank_page.load()
        elif routeKey == self.TAB_PROFILE:
            self.profile_page.load()
        elif routeKey == self.TAB_SETTINGS:
            self.settings_page.load()
        elif routeKey == self.TAB_OFFLINE:
            self.offline_page.load()

    # ------------------------------------------------------------------
    #  导航：漫画卡片 / 章节
    # ------------------------------------------------------------------
    def _navigate(self, href: str):
        """打开链接（发现/筛选/排行/详情/章节）。"""
        if not href:
            return
        path = _path_of(href).lower()

        # 排行筛选 -> 排行标签页
        if path.startswith('/rank'):
            self.pivot.setCurrentItem(self.TAB_RANK)
            self.rank_page.load(href)
            return

        # 发现 / 筛选 / 专题等 -> 发现标签页
        if path.startswith(('/comics', '/filter', '/recommend', '/newest', '/author', '/topic', '/search')):
            self.pivot.setCurrentItem(self.TAB_DISCOVER)
            self.discover_page.load(href)
            return

        # 章节 -> 阅读器
        if '/chapter/' in path:
            self._open_chapter(href)
            return

        # 其余（含 /comic/ 详情）-> 详情页
        self._open_comic(href)

    def _open_comic(self, href: str):
        if not href:
            return
        path = _path_of(href).lower()
        if '/chapter/' in path:
            self._open_chapter(href)
            return
        if path.startswith('/rank'):
            self.pivot.setCurrentItem(self.TAB_RANK)
            self.rank_page.load(href)
            return
        if path.startswith(('/comics', '/filter', '/recommend', '/newest', '/author', '/topic')):
            self.pivot.setCurrentItem(self.TAB_DISCOVER)
            self.discover_page.load(href)
            return
        self._root_stack.setCurrentWidget(self.detail_page)
        self.detail_page.load(href)

    def _open_chapter(self, href: str):
        if not href:
            return
        self._root_stack.setCurrentWidget(self.reader_page)
        self.reader_page.load(href)

    # ------------------------------------------------------------------
    #  离线阅读导航
    # ------------------------------------------------------------------
    def _open_offline_comic(self, comic):
        self._root_stack.setCurrentWidget(self.offline_comic_page)
        self.offline_comic_page.load_comic(comic)

    def _open_offline_chapter(self, chapter):
        comic = self.offline_comic_page._comic
        if comic is None:
            return
        self._root_stack.setCurrentWidget(self.offline_reader_page)
        self.offline_reader_page.load_chapter(comic, chapter)

    def _back_offline(self) -> None:
        # 从离线阅读器返回章节列表
        self._root_stack.setCurrentWidget(self.offline_comic_page)

    def _on_offline_comic_deleted(self, _comic) -> None:
        """离线漫画被删除：返回主界面并强制刷新离线列表。"""
        self._root_stack.setCurrentWidget(self._main_view)
        self.offline_page.load(force=True)

    def _back_to_main(self) -> None:
        self._root_stack.setCurrentWidget(self._main_view)
        current = self.pivot.currentItem()
        self._refresh_current_tab(current)

    # ------------------------------------------------------------------
    #  外部接口
    # ------------------------------------------------------------------
    def set_url(self, url: str) -> None:
        """外部填充搜索框（可选）。"""
        try:
            self.home_page.search_edit.setText(url)
        except Exception:
            pass

    def apply_last_url(self) -> None:
        """启动时恢复上次使用的搜索词（可选）。"""
        try:
            last = self.ctx.settings.get('last_query', '')
            if last:
                self.home_page.search_edit.setText(last)
        except Exception:
            pass


def _path_of(href: str) -> str:
    from urllib.parse import urlparse
    return urlparse(href).path or ""
