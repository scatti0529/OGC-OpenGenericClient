# coding:utf-8
import sys
import os
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl, QRectF
from PyQt5.QtWidgets import (QApplication, QWidget, QHBoxLayout, QVBoxLayout,QFrame, QLabel, QSizePolicy, QStackedWidget)
from PyQt5.QtGui import QPixmap, QPainter, QColor, QBrush, QPainterPath, QLinearGradient, QDesktopServices
from qfluentwidgets import ScrollArea, isDarkTheme, FluentIcon
from ui.widgets.common import cfg, HELP_URL, REPO_URL, EXAMPLE_URL, FEEDBACK_URL
from ui.widgets.common import Icon, FluentIconBase
from ui.widgets.common import LinkCardView
from ui.widgets.common import SampleCardView
from ui.widgets.common import StyleSheet
from qfluentwidgets import ImageLabel, HorizontalFlipView, HorizontalPipsPager, SegmentedWidget


WU_URL = 'https://www.wunderui.com/getting-started/'
from core.resource_paths import (
    HOME_ACHIEVEMENT_149, HOME_ACHIEVEMENT_150,
    HOME_ACHIEVEMENT_244, HOME_ACHIEVEMENT_245,
    HOME_BANNER
)
achievement_icon149 = HOME_ACHIEVEMENT_149
achievement_icon150 = HOME_ACHIEVEMENT_150
achievement_icon244 = HOME_ACHIEVEMENT_244
achievement_icon245 = HOME_ACHIEVEMENT_245
banner_img = HOME_BANNER


class AutoSizeLabel(QLabel):
    """自适应大小的标签：宽度占满容器，高度随内容自动贴合"""

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(0)

    def updateAutoHeight(self):
        """按当前宽度重新计算高度，使其贴合富文本内容"""
        h = self.heightForWidth(self.width())
        if h > 0:
            self.setFixedHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 宽度变化后按内容重新计算高度
        if e.size().width() != e.oldSize().width():
            self.updateAutoHeight()


class segmented_widget(QWidget):
    """分页导航容器：公告 / 更新 / 关于"""

    def __init__(self):
        super().__init__()
        # 根据深浅主题自动适配文字与背景色
        from ui.widgets.theme import theme_color, on_theme_changed, ensure_theme_connected
        self._apply_theme_style()
        ensure_theme_connected()
        on_theme_changed(self._apply_theme_style)

        self.pivot = SegmentedWidget(self)
        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(10)

        self.Announcement = AutoSizeLabel(self._announcement_content(), self)
        self.UpdateInterface = AutoSizeLabel(self._update_content(), self)
        self.AboutInterface = AutoSizeLabel(self._about_content(), self)

        # add items to pivot
        self.addSubInterface(self.Announcement, 'Announcement', '公告')
        self.addSubInterface(self.UpdateInterface, 'UpdateInterface', '更新')
        self.addSubInterface(self.AboutInterface, 'AboutInterface', '关于')

        self.vBoxLayout.addWidget(self.pivot)
        self.vBoxLayout.addWidget(self.stackedWidget)

        self.stackedWidget.setCurrentWidget(self.Announcement)
        self.pivot.setCurrentItem(self.Announcement.objectName())
        self.pivot.currentItemChanged.connect(
            lambda k: self.stackedWidget.setCurrentWidget(self.findChild(QWidget, k)))

    def _apply_theme_style(self):
        """应用当前主题样式（主题切换时自动重新调用）"""
        from ui.widgets.theme import theme_color
        text_color = theme_color('rgb(51,51,51)', 'rgb(224,224,224)')
        bg_color = theme_color('rgb(242,242,242)', 'rgb(45,45,48)')
        self.setStyleSheet(f"""
            Demo{{background: transparent}}
            QLabel#Announcement, QLabel#UpdateInterface, QLabel#AboutInterface{{
                font-family: 'Microsoft YaHei', 'Segoe UI';
                color: {text_color};
                background: {bg_color};
                border-radius: 8px;
                padding: 16px 20px;
            }}
        """)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 宽度变化时，同步三个页面宽度并让其按内容贴合高度
        if e.size().width() != e.oldSize().width():
            self._syncPagesWidth()

    def _syncPagesWidth(self):
        """同步页面宽度跟随容器，并让每个页面按内容自适应高度"""
        w = self.stackedWidget.width()
        for label in (self.Announcement, self.UpdateInterface, self.AboutInterface):
            label.resize(w, label.height())
            label.updateAutoHeight()

    def addSubInterface(self, widget: QLabel, objectName, text):
        widget.setObjectName(objectName)
        widget.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(routeKey=objectName, text=text)

    # ---------------- 公告：最新公告 ----------------
    def _announcement_content(self):
        return """
        <div>
            <h2 style="margin:0 0 4px 0; font-size:20px; font-weight:bold; color:#1E88E5;">📢 OGC 工具箱正式上线公告</h2>
            <p style="margin:0 0 14px 0; font-size:12px; color:#909399;">2025-08-01 · 系统公告</p>

            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.8;">亲爱的用户：</p>
            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.8;">
                感谢您选择 <b>OGC 工具箱</b>！本工具致力于为您提供一站式的多媒体资源管理体验，
                目前已集成 <b>音乐播放</b>、<b>多平台视频解析</b>、<b>人物资料库</b> 等核心功能。
            </p>
            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.8;">
                我们仍在持续优化产品体验，如您在使用过程中遇到任何问题，
                欢迎前往「关于我」页面获取联系方式并提交反馈。
            </p>
            <p style="margin:0 0 0 0; font-size:14px; line-height:1.8;">祝您使用愉快！</p>
            <p style="margin:12px 0 0 0; font-size:14px; color:#606266;">—— OGC 开发团队</p>
        </div>
        """

    # ---------------- 更新：版本更新日志 ----------------
    def _update_content(self):
        return """
        <div>
            <h2 style="margin:0 0 4px 0; font-size:20px; font-weight:bold; color:#1E88E5;">v1.2.0 版本更新日志</h2>
            <p style="margin:0 0 14px 0; font-size:12px; color:#909399;">2025-07-15 · 更新日志</p>

            <p style="margin:0 0 6px 0; font-size:14px; font-weight:bold; color:#E6A23C;">✨ 新增功能</p>
            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.8;">
                • 新增音乐播放列表管理，支持本地音乐导入与在线试听<br>
                • 新增多平台视频解析（抖音 / 微博 / B站）<br>
                • 新增人物资料库卡片视图浏览模式
            </p>

            <p style="margin:0 0 6px 0; font-size:14px; font-weight:bold; color:#F56C6C;">🐛 问题修复</p>
            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.8;">
                • 修复部分视频解析超时导致程序无响应的问题<br>
                • 修复深色主题下部分界面文字对比度不足的问题<br>
                • 修复窗口最小化后导航栏状态显示异常的问题
            </p>

            <p style="margin:0 0 6px 0; font-size:14px; font-weight:bold; color:#67C23A;">📌 后续规划</p>
            <p style="margin:0; font-size:14px; line-height:1.8;">
                • 计划支持更多视频平台的解析<br>
                • 持续优化音乐播放引擎的稳定性与音质
            </p>
        </div>
        """

    # ---------------- 关于：软件信息 ----------------
    def _about_content(self):
        return """
        <div>
            <h2 style="margin:0 0 14px 0; font-size:20px; font-weight:bold; color:#1E88E5;">关于 OGC 工具箱</h2>

            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.8;">
                <b>版本：</b>v1.2.0
            </p>
            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.8;">
                <b>作者：</b>OGC 开发团队
            </p>
            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.8;">
                <b>开源协议：</b>MIT License
            </p>
            <p style="margin:0 0 0 0; font-size:14px; line-height:1.8;">
                OGC 工具箱是一款基于 <b>PyQt5</b> 与 <b>PyQt-Fluent-Widgets</b> 构建的多功能桌面应用，
                集成了音乐播放、多平台视频解析、人物资料管理等功能，采用现代化 Fluent Design 风格界面。
            </p>
            <p style="margin:12px 0 0 0; font-size:14px; line-height:1.8;">
                如您在使用过程中遇到任何问题，或有功能建议，欢迎提交反馈，帮助我们持续改进！
            </p>
            <p style="margin:12px 0 0 0; font-size:14px; color:#606266;">—— OGC 开发团队</p>
        </div>
        """


class BannerWidget(QWidget):
    """ Banner widget """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFixedHeight(336)

        self.vBoxLayout = QVBoxLayout(self)
        self.galleryLabel = QLabel('OGC工具箱', self)
        self.banner = QPixmap(banner_img)
        # self.banner = QPixmap(down_img)
        self.linkCardView = LinkCardView(self)

        self.galleryLabel.setObjectName('galleryLabel')

        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 20, 0, 0)
        self.vBoxLayout.addWidget(self.galleryLabel)
        self.vBoxLayout.addWidget(self.linkCardView, 1, Qt.AlignBottom)
        self.vBoxLayout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.linkCardView.addCard(
            achievement_icon149,
            self.tr('Getting started'),
            self.tr('An overview of app development options and samples.'),
            HELP_URL
        )

        self.linkCardView.addCard(
            achievement_icon150,
            self.tr('GitHub repo'),
            self.tr(
                'The latest fluent design controls and styles for your applications.'),
            REPO_URL
        )

        self.linkCardView.addCard(
            achievement_icon244,
            self.tr('Code samples'),
            self.tr(
                'Find samples that demonstrate specific tasks, features and APIs.'),
            EXAMPLE_URL
        )

        self.linkCardView.addCard(
            achievement_icon245,
            self.tr('Send feedback'),
            self.tr('Help us improve PyQt-Fluent-Widgets by providing feedback.'),
            FEEDBACK_URL
        )

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        w, h = self.width(), self.height()
        path.addRoundedRect(QRectF(0, 0, w, h), 10, 10)
        path.addRect(QRectF(0, h-50, 50, 50))
        path.addRect(QRectF(w-50, 0, 50, 50))
        path.addRect(QRectF(w-50, h-50, 50, 50))
        path = path.simplified()

        # init linear gradient effect
        gradient = QLinearGradient(0, 0, 0, h)

        # draw background color
        if not isDarkTheme():
            gradient.setColorAt(0, QColor(207, 216, 228, 255))
            gradient.setColorAt(1, QColor(207, 216, 228, 0))
        else:
            gradient.setColorAt(0, QColor(0, 0, 0, 255))
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            
        painter.fillPath(path, QBrush(gradient))

        # draw banner image
        pixmap = self.banner.scaled(
            self.size(), transformMode=Qt.SmoothTransformation)
        painter.fillPath(path, QBrush(pixmap))

class Home(ScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.banner = BannerWidget(self)
        self.segmented_widget = segmented_widget()
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.__initWidget()

    def __initWidget(self):
        # ---------------- 路径准备 ----------------
        self.view.setObjectName('view')
        self.setObjectName('Home')
        StyleSheet.HOME_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        
        
        top_layout_container = QHBoxLayout()
        top_layout_container.addWidget(self.segmented_widget)

        # ---------------- 主布局 ----------------
        self.vBoxLayout.setContentsMargins(0, 0, 0, 36)
        self.vBoxLayout.setSpacing(40)
        self.vBoxLayout.addWidget(self.banner)
        self.vBoxLayout.addLayout(top_layout_container)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

if __name__ == '__main__':
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    w = Home()
    w.show()
    app.exec_()