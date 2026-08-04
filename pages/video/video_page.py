# coding:utf-8
# ------------------------------------------------------
# 视频分析页面
# ------------------------------------------------------
import os
import sys
import time

import requests

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from qfluentwidgets import (
    FluentIcon, InfoBar, InfoBarPosition, ScrollArea, Theme,
)

from ui.widgets.common import CFG, InfoCardView, StyleSheet, Translator
from pages.gallery_interface_2 import GalleryInterface

# ── 平台图标（统一资源路径管理）──────────────────────────
from core.resource_paths import (
    VIDEO_PAGE_DOUYIN as _DOUYIN_ICON,
    VIDEO_PAGE_TWITTER as _X_ICON,
    VIDEO_PAGE_BILIBILI as _BILI_ICON,
    VIDEO_PAGE_APP_ICON as _APP_ICON,
)


# ═══════════════════════════════════════════════════════════
#  视频链接解析器（SnapAny）
# ═══════════════════════════════════════════════════════════
class SnapAnyExtractor:
    """SnapAny 视频链接解析器"""

    @staticmethod
    def extract_url(e):
        """从文本中提取 URL"""
        if not e:
            return None
        i = e.rfind("http://")
        if i == -1:
            i = e.rfind("https://")
        if i == -1:
            return None
        e = e[i:]
        r = e.rfind(" ")
        if r != -1:
            e = e[:r]
        return e

    @staticmethod
    def md5(message):
        """纯 Python 实现的 MD5（兼容性）"""
        import hashlib
        return hashlib.md5(message).hexdigest()

    def extract(self, input_url):
        """解析链接，返回媒体资源列表"""
        url = self.extract_url(input_url)
        if not url:
            return {"text": "", "resources": [{"type": "error"}]}

        timestamp = int(time.time() * 1000)
        input_str = url + "zh" + str(timestamp) + "6HTugjCXxR"
        footer = self.md5(input_str.encode())

        headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'G-Footer': footer,
            'G-Timestamp': str(timestamp),
            'Origin': 'https://snapany.com',
            'Referer': 'https://snapany.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
        }

        try:
            response = requests.post(
                'https://api.snapany.com/v1/extract',
                headers=headers,
                json={'link': url},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                result = {"text": data.get("text", ""), "resources": []}
                for media in data.get("medias", []):
                    if "media_type" in media and "resource_url" in media:
                        preview_url = media.get("preview_url", media["resource_url"])
                        result["resources"].append({
                            "text": data.get("text", ""),
                            "type": media["media_type"],
                            "resource_url": media["resource_url"],
                            "preview_url": preview_url
                        })
                return result
            return {"text": f"API Error: {response.status_code}",
                    "resources": []}
        except Exception as e:
            return {"text": f"Request Error: {str(e)}", "resources": []}


class Videos(ScrollArea):
    """视频解析结果展示"""

    def __init__(self, Platform=None, parent=None):
        super().__init__(parent=parent)
        self.Platform = Platform
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.__initWidget()

    def __initWidget(self):
        self.view.setObjectName('view')
        StyleSheet.HOME_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 36)
        self.vBoxLayout.setSpacing(40)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

    def search(self, text=None):
        """搜索并解析链接"""
        try:
            url = f'{text}'
            if not url:
                self._show_error('输入错误', '请检查输入内容是否正确！')
                return

            extractor = SnapAnyExtractor()
            result = extractor.extract(url)
            cover_urls = result['resources']
            save_path = CFG['video_save_path']
        except Exception:
            self._show_error('解析错误', '请检查网络，或者稍后重试！')
            return None
        self.build_group('video_info', cover_urls, save_path)

    def build_group(self, name, count, save_path):
        """构建结果卡片组"""
        view = InfoCardView(self.tr(name), self.view)
        try:
            for i, item in enumerate(count):
                view.addCard(
                    icon=item['preview_url'],
                    title=item['text'],
                    content=self.tr(item['type']),
                    url=item['resource_url'],
                    save_path=save_path,
                    fileType=item['type']
                )
        except Exception:
            self._show_error('生成卡片错误', '请检查网络，或者稍后重试！')
        self.vBoxLayout.addWidget(view)

    def _show_error(self, title, content):
        """显示错误提示"""
        InfoBar.error(
            title=title,
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=5000,
            parent=self
        )


# ═══════════════════════════════════════════════════════════
#  视频主界面
# ═══════════════════════════════════════════════════════════
class VideosInterface(GalleryInterface):
    """视频主界面：居中显示图标 + 三个平台入口按钮"""

    def __init__(self, parent=None):
        t = Translator()
        super().__init__(
            title=t.Analysis,
            subtitle="多平台解析下载",
            search=True,
            parent=parent
        )
        self.setObjectName('VideosInterface')

        # 子界面引用（由 Window 设置）
        self._douyin_sub = None
        self._tuite_sub = None
        self._bili_sub = None

        # ── 居中容器 ──────────────────────────────────────
        self._centerWidget = QWidget()
        self._centerLayout = QVBoxLayout(self._centerWidget)
        self._centerLayout.setAlignment(Qt.AlignCenter)
        self._centerLayout.setSpacing(30)

        # ── 大图标 200×200 ────────────────────────────────
        self._iconLabel = QLabel()
        self._iconLabel.setAlignment(Qt.AlignCenter)
        self._iconLabel.setFixedSize(200, 200)
        pixmap = QPixmap(_APP_ICON)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._iconLabel.setPixmap(pixmap)
        self._centerLayout.addWidget(self._iconLabel, 0, Qt.AlignCenter)

        # ── 三个平台按钮 ──────────────────────────────────
        btnLayout = QHBoxLayout()
        btnLayout.setAlignment(Qt.AlignCenter)
        btnLayout.setSpacing(40)

        self._douyinBtn = QPushButton(QIcon(_DOUYIN_ICON), '  抖音')
        self._tuiteBtn = QPushButton(QIcon(_X_ICON), '  推特')
        self._biliBtn = QPushButton(QIcon(_BILI_ICON), '  B站')

        for btn in (self._douyinBtn, self._tuiteBtn, self._biliBtn):
            btn.setIconSize(QSize(32, 32))
            btn.setFixedSize(150, 55)

        self._douyinBtn.clicked.connect(lambda: self._navigateTo(self._douyin_sub))
        self._tuiteBtn.clicked.connect(lambda: self._navigateTo(self._tuite_sub))
        self._biliBtn.clicked.connect(lambda: self._navigateTo(self._bili_sub))

        btnLayout.addWidget(self._douyinBtn)
        btnLayout.addWidget(self._tuiteBtn)
        btnLayout.addWidget(self._biliBtn)
        self._centerLayout.addLayout(btnLayout)

        # ── 加入 GalleryInterface 布局 ────────────────────
        while self.vBoxLayout.count():
            item = self.vBoxLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.vBoxLayout.addWidget(self._centerWidget, 1, Qt.AlignCenter)

    def setSubInterfaces(self, douyin, tuite, bili):
        """由 Window 设置三个子界面引用"""
        self._douyin_sub = douyin
        self._tuite_sub = tuite
        self._bili_sub = bili

    def _navigateTo(self, sub_interface):
        """切换到对应的子界面"""
        win = self.window()
        if win and sub_interface:
            win.switchTo(sub_interface)


class Videos_analysis_Interface(GalleryInterface):
    """视频分析子界面（抖音 / 推特 / B站）"""

    def __init__(self, title='None', Platform=None, parent=None):
        t = Translator()
        super().__init__(
            title=title,
            subtitle="多平台解析下载",
            search=True,
            parent=parent
        )
        self.setObjectName('Videos_analysis_Interface')

        self.VideosView = Videos(Platform=Platform, parent=self)
        self.vBoxLayout.addWidget(self.VideosView)

        if hasattr(self.toolBar, "searchSignal"):
            self.toolBar.searchSignal.connect(self.VideosView.search)


# ═══════════════════════════════════════════════════════════
#  独立测试入口
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    from qfluentwidgets import setTheme

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    setTheme(Theme.AUTO)
    w = VideosInterface()
    w.show()
    app.exec_()