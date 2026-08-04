# -*- coding: utf-8 -*-
"""
公共组件兼容层
==============
本模块为旧代码提供兼容接口，内部复用 app 核心包：

    - LogManager / log_manager  →  app.logger
    - Config_info / CFG         →  app.config
    - Downloader / DownloadThread → app.downloader

同时保留 UI 组件（卡片、样式、配置类等）。
"""
import os
import sys
import logging
from enum import Enum

from PyQt5.QtCore import Qt, QUrl, QLocale, QObject, pyqtSignal, QEventLoop, QByteArray
from PyQt5.QtGui import QPixmap, QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QApplication, QPushButton
)
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from queue import Queue

from qfluentwidgets import (
    IconWidget, FluentIcon, TextWrap, CardWidget, FlowLayout,
    SingleDirectionScrollArea,
    qconfig, QConfig, ConfigItem, OptionsConfigItem, BoolValidator,
    OptionsValidator, RangeConfigItem, RangeValidator,
    FolderListValidator, FolderValidator, ConfigSerializer,
    StyleSheetBase, Theme, isDarkTheme,
    FluentIconBase, getIconColor, __version__,
    InfoBar, InfoBarPosition, ProgressBar,
)

# ── 复用 app 核心包 ─────────────────────────────────────────
from core.logger import LogManager, logger as log_manager  # noqa: F401
from core.config import ConfigManager, config as CFG       # noqa: F401
from services.downloader import Downloader, DownloadThread     # noqa: F401


# ==========================  兼容别名  ==========================
# 旧代码中 logger 直接使用 log_manager 实例
__all__ = [
    'LogManager', 'log_manager',
    'ConfigManager', 'CFG',
    'Downloader', 'DownloadThread',
    'SignalBus', 'signalBus',
    'SampleCard', 'SampleCardView',
    'Icon', 'Language', 'LanguageSerializer', 'isWin11',
    'Config', 'cfg', 'StyleSheet',
    'LinkCard', 'LinkCardView',
    'InfoCard', 'InfoCardView',
    'Translator', 'Trie',
    'HELP_URL', 'REPO_URL', 'EXAMPLE_URL', 'FEEDBACK_URL',
]


# ==========================  信号总线  ==========================
class SignalBus(QObject):
    """全局信号总线"""

    switchToSampleCard = pyqtSignal(str, int)
    micaEnableChanged = pyqtSignal(bool)
    supportSignal = pyqtSignal()


signalBus = SignalBus()


# ==========================  示例卡片  ==========================
class SampleCard(CardWidget):
    """示例卡片"""

    def __init__(self, icon, title, content, routeKey, index, parent=None):
        super().__init__(parent=parent)
        self.index = index
        self.routekey = routeKey

        self.iconWidget = IconWidget(icon, self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(TextWrap.wrap(content, 45, False)[0], self)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedSize(360, 90)
        self.iconWidget.setFixedSize(48, 48)

        self.hBoxLayout.setSpacing(28)
        self.hBoxLayout.setContentsMargins(20, 0, 0, 0)
        self.vBoxLayout.setSpacing(2)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)

        self.hBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addWidget(self.iconWidget)
        self.hBoxLayout.addLayout(self.vBoxLayout)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addWidget(self.contentLabel)
        self.vBoxLayout.addStretch(1)

        self.titleLabel.setObjectName('titleLabel')
        self.contentLabel.setObjectName('contentLabel')

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        signalBus.switchToSampleCard.emit(self.routekey, self.index)


class SampleCardView(QWidget):
    """示例卡片视图"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent=parent)
        self.titleLabel = QLabel(title, self)
        self.vBoxLayout = QVBoxLayout(self)
        self.flowLayout = FlowLayout()

        self.vBoxLayout.setContentsMargins(36, 0, 36, 0)
        self.vBoxLayout.setSpacing(10)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setHorizontalSpacing(12)
        self.flowLayout.setVerticalSpacing(12)

        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addLayout(self.flowLayout, 1)

        self.titleLabel.setObjectName('viewTitleLabel')
        StyleSheet.SAMPLE_CARD.apply(self)

    def addSampleCard(self, icon, title, content, routeKey, index):
        card = SampleCard(icon, title, content, routeKey, index, self)
        self.flowLayout.addWidget(card)


class Icon(FluentIconBase, Enum):
    """图标枚举"""

    GRID = "Grid"
    MENU = "Menu"
    TEXT = "Text"
    PRICE = "Price"
    EMOJI_TAB_SYMBOLS = "EmojiTabSymbols"

    def path(self, theme=Theme.AUTO):
        return f":/gallery/images/icons/{self.value}_{getIconColor(theme)}.svg"


# ==========================  语言/配置  ==========================
class Language(Enum):
    """语言枚举"""

    CHINESE_SIMPLIFIED = QLocale(QLocale.Chinese, QLocale.China)
    CHINESE_TRADITIONAL = QLocale(QLocale.Chinese, QLocale.HongKong)
    ENGLISH = QLocale(QLocale.English)
    AUTO = QLocale()


class LanguageSerializer(ConfigSerializer):
    """语言序列化器"""

    def serialize(self, language):
        return language.value.name() if language != Language.AUTO else "Auto"

    def deserialize(self, value: str):
        return Language(QLocale(value)) if value != "Auto" else Language.AUTO


def isWin11():
    """判断是否 Windows 11"""
    return sys.platform == 'win32' and sys.getwindowsversion().build >= 22000


class Config(QConfig):
    """应用配置（基于 qfluentwidgets）"""

    # folders
    musicFolders = ConfigItem("Folders", "LocalMusic", [], FolderListValidator())
    downloadFolder = ConfigItem("Folders", "Download", "app/download", FolderValidator())

    # main window
    micaEnabled = ConfigItem("MainWindow", "MicaEnabled", isWin11(), BoolValidator())
    dpiScale = OptionsConfigItem(
        "MainWindow", "DpiScale", "Auto",
        OptionsValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]), restart=True)
    language = OptionsConfigItem(
        "MainWindow", "Language", Language.AUTO,
        OptionsValidator(Language), LanguageSerializer(), restart=True)

    # Material
    blurRadius = RangeConfigItem("Material", "AcrylicBlurRadius", 15, RangeValidator(0, 40))

    # Glass effect（全局透明度 / 模糊度）
    glassOpacity = RangeConfigItem(
        "Material", "GlassOpacity", 225, RangeValidator(150, 255))
    glassBlurRadius = RangeConfigItem(
        "Material", "GlassBlurRadius", 15, RangeValidator(0, 40))

    # splash screen（登录成功后的启动过渡画面）
    splashEnabled = ConfigItem("MainWindow", "SplashEnabled", True, BoolValidator())

    # download optimization（下载优化）
    downloadMode = OptionsConfigItem(
        "Download", "Mode", "auto",
        OptionsValidator(["auto", "parallel", "stream", "hls"]))
    downloadMaxThreads = RangeConfigItem(
        "Download", "MaxThreads", 8, RangeValidator(2, 16))
    downloadParallelThreshold = RangeConfigItem(
        "Download", "ParallelThreshold", 20, RangeValidator(5, 200))
    downloadRetryTimes = RangeConfigItem(
        "Download", "RetryTimes", 3, RangeValidator(0, 10))

    # software update
    checkUpdateAtStartUp = ConfigItem("Update", "CheckUpdateAtStartUp", True, BoolValidator())


YEAR = 2025
AUTHOR = "scatti"
VERSION = __version__
HELP_URL = "https://qfluentwidgets.com"
REPO_URL = "https://github.com/zhiyiYo/PyQt-Fluent-Widgets"
EXAMPLE_URL = "https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/master/examples"
FEEDBACK_URL = "https://github.com/zhiyiYo/PyQt-Fluent-Widgets/issues"
RELEASE_URL = "https://github.com/zhiyiYo/PyQt-Fluent-Widgets/releases/latest"

base_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(os.path.dirname(os.path.dirname(base_dir)), 'resources', 'config', 'config.json')
cfg = Config()
cfg.themeMode.value = Theme.AUTO
qconfig.load(config_path, cfg)


class StyleSheet(StyleSheetBase, Enum):
    """样式表"""

    LINK_CARD = "link_card"
    SAMPLE_CARD = "sample_card"
    HOME_INTERFACE = "home_interface"
    ICON_INTERFACE = "icon_interface"
    VIEW_INTERFACE = "view_interface"
    SETTING_INTERFACE = "setting_interface"
    GALLERY_INTERFACE = "gallery_interface"
    NAVIGATION_VIEW_INTERFACE = "navigation_view_interface"

    def path(self, theme=Theme.AUTO):
        qss_path = os.path.join(os.path.dirname(os.path.dirname(base_dir)), 'resources', 'qss')
        theme = qconfig.theme if theme == Theme.AUTO else theme
        return f"{qss_path}/{theme.value.lower()}/{self.value}.qss"


# ==========================  链接卡片  ==========================
class LinkCard(QFrame):
    """链接卡片"""

    def __init__(self, icon, title, content, url, parent=None):
        super().__init__(parent=parent)
        self.url = QUrl(url)
        self.setFixedSize(198, 220)
        self.iconWidget = IconWidget(icon, self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(TextWrap.wrap(content, 28, False)[0], self)
        self.urlWidget = IconWidget(FluentIcon.LINK, self)

        self.__initWidget()

    def __initWidget(self):
        self.setCursor(Qt.PointingHandCursor)

        self.iconWidget.setFixedSize(54, 54)
        self.urlWidget.setFixedSize(16, 16)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(24, 24, 0, 13)
        self.vBoxLayout.addWidget(self.iconWidget)
        self.vBoxLayout.addSpacing(16)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addSpacing(8)
        self.vBoxLayout.addWidget(self.contentLabel)
        self.vBoxLayout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.urlWidget.move(170, 192)

        self.titleLabel.setObjectName('titleLabel')
        self.contentLabel.setObjectName('contentLabel')

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        QDesktopServices.openUrl(self.url)


class LinkCardView(SingleDirectionScrollArea):
    """链接卡片视图"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Horizontal)
        self.view = QWidget(self)
        self.hBoxLayout = QHBoxLayout(self.view)

        self.hBoxLayout.setContentsMargins(36, 0, 0, 0)
        self.hBoxLayout.setSpacing(12)
        self.hBoxLayout.setAlignment(Qt.AlignLeft)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.view.setObjectName('view')
        StyleSheet.LINK_CARD.apply(self)

    def addCard(self, icon, title, content, url):
        card = LinkCard(icon, title, content, url, self.view)
        self.hBoxLayout.addWidget(card, 0, Qt.AlignLeft)


# ==========================  媒体信息卡片  ==========================
class InfoCard(QFrame):
    """带预览/下载按钮的媒体信息卡片"""

    def __init__(self, icon, title, content, url, save_path, fileType, parent=None):
        super().__init__(parent=parent)
        self.url = url
        self.title = title
        self.content = content
        self.save_path = save_path
        self.fileType = fileType
        self.setFixedSize(198, 220)

        self.iconWidget = IconWidget("", self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(TextWrap.wrap(content, 28, False)[0], self)
        self.urlWidget = IconWidget(FluentIcon.LINK, self)

        self.previewBtn = QPushButton("预览", self)
        self.downloadBtn = QPushButton("下载", self)
        self.progressBar = ProgressBar(self)
        self.progressBar.setVisible(False)

        self.__initWidget(icon)
        self.__connectSignal()

    def __initWidget(self, icon):
        self.setCursor(Qt.PointingHandCursor)
        self.iconWidget.setFixedSize(54, 54)
        self.urlWidget.setFixedSize(16, 16)

        # 动态加载图标
        if isinstance(icon, str) and (icon.startswith("http://") or icon.startswith("https://")):
            try:
                manager = QNetworkAccessManager()
                loop = QEventLoop()
                reply = manager.get(QNetworkRequest(QUrl(icon)))
                reply.finished.connect(loop.quit)
                loop.exec_()
                if reply.error() == reply.NoError:
                    data = reply.readAll()
                    pixmap = QPixmap()
                    pixmap.loadFromData(QByteArray(data))
                    self.iconWidget.setPixmap(pixmap)
                reply.deleteLater()
            except Exception:
                pass
        elif isinstance(icon, str) and (os.path.exists(icon) or icon.startswith(":/")):
            pixmap = QPixmap(icon)
            self.iconWidget.setPixmap(pixmap)

        # 布局
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(24, 24, 0, 13)
        self.vBoxLayout.addWidget(self.iconWidget)
        self.vBoxLayout.addSpacing(16)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addSpacing(8)
        self.vBoxLayout.addWidget(self.contentLabel)
        self.vBoxLayout.addStretch()

        self.btnLayout = QHBoxLayout()
        self.btnLayout.setContentsMargins(0, 0, 24, 13)
        self.btnLayout.addWidget(self.previewBtn)
        self.btnLayout.addWidget(self.downloadBtn)
        self.btnLayout.addStretch()
        self.vBoxLayout.addLayout(self.btnLayout)
        self.vBoxLayout.addWidget(self.progressBar)

        self.titleLabel.setObjectName('titleLabel')
        self.contentLabel.setObjectName('contentLabel')
        self.urlWidget.move(170, 192)

    def __connectSignal(self):
        self.previewBtn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self.url)))
        self.downloadBtn.clicked.connect(self.__startDownload)

    def __startDownload(self):
        self.previewBtn.setVisible(False)
        self.downloadBtn.setVisible(False)
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)

        savePath = CFG[f'{self.save_path}']
        fileType = self.fileType

        self.thread = DownloadThread(self.url, self.title, str(savePath), fileType)
        self.thread.progress.connect(self.__onProgress)
        self.thread.finished.connect(self.__onFinished)
        self.thread.start()

    def __onProgress(self, current, total):
        self.progressBar.setMaximum(total)
        self.progressBar.setValue(current)

    def __onFinished(self):
        InfoBar.success(
            title=self.tr('下载成功'),
            content="",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=5000,
            parent=self
        )
        self.progressBar.setVisible(False)
        self.previewBtn.setVisible(True)
        self.downloadBtn.setVisible(True)


class InfoCardView(SingleDirectionScrollArea):
    """媒体信息卡片视图"""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent, Qt.Horizontal)
        self.view = QWidget(self)
        self.hBoxLayout = QHBoxLayout(self.view)

        self.hBoxLayout.setContentsMargins(36, 0, 0, 0)
        self.hBoxLayout.setSpacing(12)
        self.hBoxLayout.setAlignment(Qt.AlignLeft)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.view.setObjectName('view')
        StyleSheet.LINK_CARD.apply(self)

        if title:
            self.titleLabel = QLabel(title, self)
            self.titleLabel.setObjectName('viewTitleLabel')
            self.vBoxLayout = QVBoxLayout(self)
            self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
            self.vBoxLayout.setSpacing(10)
            self.vBoxLayout.addWidget(self.titleLabel)
            self.vBoxLayout.addWidget(self.view)
            self.setLayout(self.vBoxLayout)

    def addCard(self, icon, title, content, save_path, fileType, url):
        card = InfoCard(icon, title, content, url, save_path, fileType, self.view)
        self.hBoxLayout.addWidget(card, 0, Qt.AlignLeft)


# ==========================  翻译器  ==========================
class Translator(QObject):
    """翻译器"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.text = self.tr('Text')
        self.Analysis = self.tr('Analysis')
        self.view = self.tr('View')
        self.menus = self.tr('Menus & toolbars')
        self.icons = self.tr('Icons')
        self.layout = self.tr('Layout')
        self.dialogs = self.tr('Dialogs & flyouts')
        self.scroll = self.tr('Scrolling')
        self.material = self.tr('Material')
        self.dateTime = self.tr('Date & time')
        self.navigation = self.tr('Navigation')
        self.basicInput = self.tr('Basic input')
        self.statusInfo = self.tr('Status & info')
        self.price = self.tr("Price")


# ==========================  字典树  ==========================
class Trie:
    """字符串前缀树"""

    def __init__(self):
        self.key = ''
        self.value = None
        self.children = [None] * 26
        self.isEnd = False

    def insert(self, key: str, value):
        key = key.lower()
        node = self
        for c in key:
            i = ord(c) - 97
            if not 0 <= i < 26:
                return
            if not node.children[i]:
                node.children[i] = Trie()
            node = node.children[i]
        node.isEnd = True
        node.key = key
        node.value = value

    def get(self, key, default=None):
        node = self.searchPrefix(key)
        if not (node and node.isEnd):
            return default
        return node.value

    def searchPrefix(self, prefix):
        prefix = prefix.lower()
        node = self
        for c in prefix:
            i = ord(c) - 97
            if not (0 <= i < 26 and node.children[i]):
                return None
            node = node.children[i]
        return node

    def items(self, prefix):
        node = self.searchPrefix(prefix)
        if not node:
            return []
        q = Queue()
        result = []
        q.put(node)
        while not q.empty():
            node = q.get()
            if node.isEnd:
                result.append((node.key, node.value))
            for c in node.children:
                if c:
                    q.put(c)
        return result