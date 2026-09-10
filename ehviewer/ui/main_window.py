# -*- coding: utf-8 -*-
"""主窗口：FluentWindow + 左侧导航"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (FluentWindow, FluentIcon, NavigationItemPosition, SubtitleLabel,
                            PushButton, InfoBar, InfoBarPosition, BodyLabel, ToolButton,
                            isDarkTheme, setTheme, Theme)

from .. import constants as C
from ..config import is_login, get, set as cset
from .bus import bus
from .home_page import HomePage
from .search_page import SearchPage
from .favorites_page import FavoritesPage
from .downloads_page import DownloadsPage
from .history_page import HistoryPage
from .top_list_page import TopListPage
from .image_search_page import ImageSearchPage
from .album_page import AlbumPage
from .settings_page import SettingsPage


class MainWindow(FluentWindow):
    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)
        self.setWindowTitle("EhViewer PC — E-Hentai 阅读器")
        self.resize(1280, 860)

        # 页面
        self.home_page = HomePage(self)
        self.home_page.setObjectName("homePage")
        self.search_page = SearchPage(self)
        self.search_page.setObjectName("searchPage")
        self.favorites_page = FavoritesPage(self)
        self.favorites_page.setObjectName("favoritesPage")
        self.downloads_page = DownloadsPage(self)
        self.downloads_page.setObjectName("downloadsPage")
        self.history_page = HistoryPage(self)
        self.history_page.setObjectName("historyPage")
        self.top_list_page = TopListPage(self)
        self.top_list_page.setObjectName("topListPage")
        self.album_page = AlbumPage(self)
        self.album_page.setObjectName("albumPage")
        self.image_search_page = ImageSearchPage(self)
        self.image_search_page.setObjectName("imageSearchPage")
        self.settings_page = SettingsPage(self)
        self.settings_page.setObjectName("settingsPage")

        self.addSubInterface(self.home_page, FluentIcon.HOME, "主页")
        self.addSubInterface(self.search_page, FluentIcon.SEARCH, "搜索")
        self.addSubInterface(self.favorites_page, FluentIcon.HEART, "收藏")
        self.addSubInterface(self.downloads_page, FluentIcon.DOWNLOAD, "下载")
        self.addSubInterface(self.album_page, FluentIcon.LIBRARY, "本地画册")
        self.addSubInterface(self.history_page, FluentIcon.HISTORY, "历史")
        self.addSubInterface(self.top_list_page, FluentIcon.ALIGNMENT, "排行榜")
        self.addSubInterface(self.image_search_page, FluentIcon.PHOTO, "图片搜索")
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)

        # 登录状态按钮（放导航底部区域由设置页管理，此处直接连 bus）
        bus.loginChanged.connect(self._on_login_changed)
        bus.navigate.connect(self._navigate)

    def _navigate(self, key):
        m = {"home": self.home_page, "search": self.search_page,
             "favorites": self.favorites_page, "downloads": self.downloads_page,
             "history": self.history_page, "toplist": self.top_list_page,
             "imagesearch": self.image_search_page, "settings": self.settings_page}
        w = m.get(key)
        if w is not None:
            self.stackedWidget.setCurrentWidget(w)

    def _on_login_changed(self, logged):
        self.settings_page.refresh_login_state()

    def show_notify(self, level, content):
        """level: info/success/warning/error"""
        fn = {"info": InfoBar.info, "success": InfoBar.success,
              "warning": InfoBar.warning, "error": InfoBar.error}.get(level, InfoBar.info)
        fn("", content, InfoBarPosition.TOP_RIGHT, 3500, self)

    def closeEvent(self, event):
        from ..appctx import ctx
        if ctx.download_manager is not None:
            ctx.download_manager.shutdown()
        if ctx.image_loader is not None:
            ctx.image_loader.shutdown()
        super(MainWindow, self).closeEvent(event)
