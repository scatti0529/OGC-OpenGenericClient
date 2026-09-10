# coding:utf-8
"""
OGC-OpenGenericClient 首页
==================
遵循 SKILL.md「深蓝玻璃」视觉方向：

    签名元素：Hero 玻璃区 —— 品牌蓝冷色渐变 + 发光光斑，
              标题用展示型字重，下方用能力胶囊代替模板化的统计数字。
    布局：Hero（一句话价值主张 + 真实能力胶囊）→ 功能快捷入口卡片
          → 公告 / 更新 / 关于 分段内容。
"""
import sys
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QSizePolicy, QStackedWidget, QGridLayout, QGraphicsDropShadowEffect,
)
from PyQt5.QtGui import (
    QPainter, QColor, QPainterPath, QLinearGradient, QRadialGradient,
    QBrush, QPixmap,
)
from qfluentwidgets import (
    ScrollArea, isDarkTheme, FluentIcon as FIF, SegmentedWidget,
    CardWidget, BodyLabel, CaptionLabel, SubtitleLabel, IconWidget,
)
from ui.widgets.common import StyleSheet
from ui.widgets.theme import (
    theme_color, on_theme_changed, ensure_theme_connected,
    BRAND_PRIMARY, BRAND_PRIMARY_DEEP, BRAND_LIGHT,
    font_display, font_body,
)


# ═══════════════════════════════════════════════════════════
#  设计 token（集中定义，浅/深主题自动切换）
# ═══════════════════════════════════════════════════════════
def _brand() -> str:
    """当前主题的品牌主色"""
    return theme_color(BRAND_PRIMARY_DEEP, BRAND_LIGHT)


class AutoSizeLabel(QLabel):
    """自适应大小的标签：宽度占满容器，高度随内容自动贴合"""

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(0)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)

    def updateAutoHeight(self):
        h = self.heightForWidth(self.width())
        if h > 0:
            self.setFixedHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.size().width() != e.oldSize().width():
            self.updateAutoHeight()


# ═══════════════════════════════════════════════════════════
#  公告 / 更新 / 关于 分段内容
# ═══════════════════════════════════════════════════════════
class AnnouncementWidget(QWidget):
    """分页导航容器：公告 / 更新 / 关于"""

    def __init__(self):
        super().__init__()
        self.setObjectName('AnnouncementWidget')

        self.pivot = SegmentedWidget(self)
        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(12)

        # 内容占位：先建空标签 + 结构，内容（富文本+高度自适应）延迟到 build_content()，加速首页首屏
        self.Announcement = AutoSizeLabel('', self)
        self.UpdateInterface = AutoSizeLabel('', self)
        self.AboutInterface = AutoSizeLabel('', self)
        self._content_built = False

        # 先应用样式，再注册主题切换回调（后续切换会实时刷新）
        self._apply_theme_style()
        ensure_theme_connected()
        on_theme_changed(self._apply_theme_style)

        self.addSubInterface(self.Announcement, 'Announcement', '公告')
        self.addSubInterface(self.UpdateInterface, 'UpdateInterface', '更新')
        self.addSubInterface(self.AboutInterface, 'AboutInterface', '关于')

        self.vBoxLayout.addWidget(self.pivot)
        self.vBoxLayout.addWidget(self.stackedWidget)

        self.stackedWidget.setCurrentWidget(self.Announcement)
        self.pivot.setCurrentItem(self.Announcement.objectName())
        self.pivot.currentItemChanged.connect(
            lambda k: self.stackedWidget.setCurrentWidget(self.findChild(QWidget, k)))

    def build_content(self):
        """延迟填充公告/更新/关于的富文本与高度（首屏先不计算，窗口显示后再调用）。"""
        if self._content_built:
            return
        self._content_built = True
        try:
            self.Announcement.setText(self._announcement_content())
            self.UpdateInterface.setText(self._update_content())
            self.AboutInterface.setText(self._about_content())
            for lbl in (self.Announcement, self.UpdateInterface, self.AboutInterface):
                lbl.updateAutoHeight()
        except Exception:
            pass

    def _apply_theme_style(self):
        text_color = theme_color('rgb(45,48,52)', 'rgb(230,233,240)')
        subtle = theme_color('rgb(110,115,122)', 'rgb(156,162,172)')
        bg = theme_color('rgba(255,255,255,0.72)', 'rgba(34,38,48,0.72)')
        border = theme_color('rgba(0,0,0,0.07)', 'rgba(255,255,255,0.09)')
        self.setStyleSheet(f"""
            AnnouncementWidget {{ background: transparent; }}
            QLabel#Announcement, QLabel#UpdateInterface, QLabel#AboutInterface {{
                font-family: {font_body()};
                color: {text_color};
                background: {bg};
                border: 1px solid {border};
                border-radius: 12px;
                padding: 18px 22px;
            }}
        """)
        # 富文本内次级文字颜色（分段内容里的 meta / 提款）
        self._subtle = subtle
        for lbl in (self.Announcement, self.UpdateInterface, self.AboutInterface):
            lbl.updateAutoHeight()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.size().width() != e.oldSize().width():
            self._syncPagesWidth()

    def _syncPagesWidth(self):
        w = self.stackedWidget.width()
        for label in (self.Announcement, self.UpdateInterface, self.AboutInterface):
            label.resize(w, label.height())
            label.updateAutoHeight()

    def addSubInterface(self, widget: QLabel, objectName, text):
        widget.setObjectName(objectName)
        widget.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(routeKey=objectName, text=text)

    # ---------------- 公告 ----------------
    def _announcement_content(self):
        return """
        <div>
            <h2 style="margin:0 0 6px 0; font-size:20px; font-weight:600;">📢 OGC-OpenGenericClient 正式上线</h2>
            <p style="margin:0 0 16px 0; font-size:12px; color:#889099;">2025-08-01 · 系统公告</p>
            <p style="margin:0 0 10px 0; font-size:14px; line-height:1.7;">
                感谢选择 <b>OGC-OpenGenericClient</b>，一个整合 <b>音乐播放</b>、
                <b>多平台视频解析</b> 与 <b>漫画资料库</b> 的多媒体客户端。
            </p>
            <p style="margin:0 0 10px 0; font-size:14px; line-height:1.7;">
                如有问题或建议，可前往「关于我」页面提交反馈，帮助我们持续改进。
            </p>
            <p style="margin:0; font-size:14px; line-height:1.7;">祝使用愉快。</p>
        </div>
        """

    # ---------------- 更新 ----------------
    def _update_content(self):
        return """
        <div>
            <h2 style="margin:0 0 6px 0; font-size:20px; font-weight:600;">v1.2.0 版本更新日志</h2>
            <p style="margin:0 0 16px 0; font-size:12px; color:#889099;">2025-07-15 · 更新日志</p>
            <p style="margin:0 0 6px 0; font-size:14px; font-weight:600; color:#E6A23C;">✨ 新增</p>
            <p style="margin:0 0 10px 0; font-size:14px; line-height:1.7;">
                • 音乐播放列表管理，支持本地导入与在线播放<br>
                • 多平台视频解析（抖音 / 哔哩哔哩 / 推特 / Pixiv 等）
            </p>
            <p style="margin:0 0 6px 0; font-size:14px; font-weight:600; color:#F56C6C;">🐛 修复</p>
            <p style="margin:0 0 10px 0; font-size:14px; line-height:1.7;">• 修复解析超时导致界面无响应的问题</p>
            <p style="margin:0 0 6px 0; font-size:14px; font-weight:600; color:#67C23A;">📌 规划</p>
            <p style="margin:0; font-size:14px; line-height:1.7;">• 计划支持更多视频平台解析</p>
        </div>
        """

    # ---------------- 关于 ----------------
    def _about_content(self):
        return """
        <div>
            <h2 style="margin:0 0 14px 0; font-size:20px; font-weight:600;">关于 OGC-OpenGenericClient</h2>
            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.7;"><b>版本：</b>v1.2.0</p>
            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.7;"><b>作者：</b>OGC-OpenGenericClient 开发团队</p>
            <p style="margin:0 0 8px 0; font-size:14px; line-height:1.7;"><b>协议：</b>MIT License</p>
            <p style="margin:0; font-size:14px; line-height:1.7;">
                基于 <b>PyQt5</b> 与 <b>PyQt-Fluent-Widgets</b> 构建的多功能桌面应用，
                集成了音乐播放、多平台视频解析、漫画资料管理等功能。
            </p>
        </div>
        """


# ═══════════════════════════════════════════════════════════
#  Hero 玻璃区（签名元素）
# ═══════════════════════════════════════════════════════════
class HeroWidget(QWidget):
    """首页 Hero：品牌蓝冷色渐变玻璃 + 发光光斑 + 能力胶囊"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFixedHeight(236)
        self._apply_theme_style()
        ensure_theme_connected()
        on_theme_changed(self._apply_theme_style)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(32, 30, 32, 26)
        self.vBoxLayout.setSpacing(10)

        # eyebrow
        self.eyebrow = QLabel('OGC · OPEN GENERIC CLIENT', self)
        self.eyebrow.setObjectName('heroEyebrow')

        # 主标题
        self.title = QLabel('OGC-OpenGenericClient', self)
        self.title.setObjectName('heroTitle')

        # 副标题（一句话价值主张）
        self.subtitle = QLabel('一站式多媒体解析 · 下载 · 管理', self)
        self.subtitle.setObjectName('heroSubtitle')
        self.subtitle.setWordWrap(True)

        self.vBoxLayout.addWidget(self.eyebrow)
        self.vBoxLayout.addWidget(self.title)
        self.vBoxLayout.addWidget(self.subtitle)
        self.vBoxLayout.addStretch(1)

        # 能力胶囊（真实能力，非模板统计）
        self.chipLayout = QHBoxLayout()
        self.chipLayout.setSpacing(10)
        for cap in ('音乐播放', '多平台视频解析', '漫画图集', '权限管理'):
            self.chipLayout.addWidget(self._make_chip(cap))
        self.chipLayout.addStretch(1)
        self.vBoxLayout.addLayout(self.chipLayout)

    def _make_chip(self, text: str) -> QLabel:
        chip = QLabel(text, self)
        chip.setObjectName('heroChip')
        chip.setAlignment(Qt.AlignCenter)
        return chip

    def _apply_theme_style(self):
        on_dark = isDarkTheme()
        if on_dark:
            chip_bg = 'rgba(255,255,255,0.10)'
            chip_border = 'rgba(255,255,255,0.14)'
            chip_color = '#D8ECF7'
        else:
            chip_bg = 'rgba(255,255,255,0.55)'
            chip_border = 'rgba(40,175,233,0.18)'
            chip_color = '#0E5E82'
        self.setStyleSheet(f"""
            HeroWidget {{ background: transparent; }}
            QLabel#heroEyebrow {{
                font: 12px 'Segoe UI Semibold', 'Microsoft YaHei Semibold';
                color: {_brand()};
                letter-spacing: 2px;
            }}
            QLabel#heroTitle {{
                font: 38px {font_display()};
                color: {theme_color('#1B2733', '#F2F7FB')};
            }}
            QLabel#heroSubtitle {{
                font: 15px {font_body()};
                color: {theme_color('#5A6873', '#A9B6C4')};
            }}
            QLabel#heroChip {{
                font: 13px 'Microsoft YaHei', 'Segoe UI';
                color: {chip_color};
                background: {chip_bg};
                border: 1px solid {chip_border};
                border-radius: 15px;
                padding: 5px 14px;
            }}
        """)

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 14, 14)

        if isDarkTheme():
            # 蓝黑冷色玻璃底
            base = QLinearGradient(0, 0, w, h)
            base.setColorAt(0, QColor(34, 44, 58, 235))
            base.setColorAt(1, QColor(18, 22, 30, 235))
            painter.fillPath(path, QBrush(base))
            # 品牌蓝光斑
            glow = QRadialGradient(w * 0.18, h * 0.25, w * 0.7)
            glow.setColorAt(0, QColor(40, 175, 233, 90))
            glow.setColorAt(1, QColor(40, 175, 233, 0))
        else:
            # 冷蓝→玻璃白 渐变
            base = QLinearGradient(0, 0, w, h)
            base.setColorAt(0, QColor(235, 247, 252, 245))
            base.setColorAt(1, QColor(252, 253, 254, 245))
            painter.fillPath(path, QBrush(base))
            glow = QRadialGradient(w * 0.16, h * 0.2, w * 0.7)
            glow.setColorAt(0, QColor(40, 175, 233, 42))
            glow.setColorAt(1, QColor(40, 175, 233, 0))

        painter.fillPath(path, QBrush(glow))
        # 顶部发丝边框
        painter.setPen(QColor(40, 175, 233, 70))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


# ═══════════════════════════════════════════════════════════
#  功能快捷入口卡片
# ═══════════════════════════════════════════════════════════
class FeatureCard(CardWidget):
    """首页快捷入口卡片：图标 + 标题 + 描述，点击跳转对应页面"""

    def __init__(self, title: str, desc: str, icon, window_attr: str, accent: str,
                 parent=None):
        super().__init__(parent=parent)
        self._window_attr = window_attr
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        iconWidget = IconWidget(icon, self)
        iconWidget.setFixedSize(40, 40)
        iconWidget.setStyleSheet(f"color: {accent}; background: transparent;")

        titleLabel = SubtitleLabel(title, self)
        titleLabel.setStyleSheet("font-size: 15px; font-weight: 600;")

        descLabel = CaptionLabel(desc, self)
        descLabel.setWordWrap(True)
        descLabel.setStyleSheet(
            "color: " + theme_color('#7A8792', '#9AA7B5') + "; font-size: 12px;")

        layout.addWidget(iconWidget)
        layout.addWidget(titleLabel)
        layout.addWidget(descLabel)
        layout.addStretch(1)

        self._apply_shadow()

    def _apply_shadow(self):
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(15, 60, 90, 40))
        self.setGraphicsEffect(shadow)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        win = self.window()
        if win is not None and hasattr(win, 'switchTo'):
            target = getattr(win, self._window_attr, None)
            if target is not None:
                win.switchTo(target)


class Home(ScrollArea):

    # 功能快捷入口：(标题, 描述, 图标, 主窗口对应属性)
    FEATURES = [
        ('音乐收听', '搜索、歌单与在线播放', FIF.MUSIC, 'musicInterface'),
        ('视频解析', '抖音 / B站 / 推特 / Pixiv 等', FIF.VIDEO, 'videoInterface'),
        ('JMComic', '漫画检索、订阅与下载', FIF.PHOTO, 'JmComicPage'),
        ('偏好设置', '主题、玻璃效果与下载选项', FIF.SETTING, 'settingInterface'),
        ('关于我', '个人资料与账号信息', FIF.PEOPLE, 'about_me'),
        ('仪表盘', '管理员 · 用户与数据概览', FIF.HISTORY, 'dashboardInterface'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.hero = HeroWidget(self)
        self.announcements = AnnouncementWidget()
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)
        self.__initWidget()

    def __initWidget(self):
        self.view.setObjectName('view')
        self.setObjectName('Home')
        StyleSheet.HOME_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 36)
        self.vBoxLayout.setSpacing(28)
        self.vBoxLayout.addWidget(self.hero)

        # ---- 功能快捷入口标题 ----
        section = QLabel('快速开始', self.view)
        section.setObjectName('sectionLabel')
        section.setStyleSheet(
            f"font: 20px {font_display()}; "
            f"color: {theme_color('#2A363F', '#E6EDF4')};")
        self.vBoxLayout.addSpacing(4)
        self.vBoxLayout.addWidget(section)

        # ---- 功能入口网格（3 列自适应） ----
        gridWidget = QWidget(self.view)
        grid = QGridLayout(gridWidget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        for i, (title, desc, icon, attr) in enumerate(self.FEATURES):
            accent = '#0E8CC0' if not isDarkTheme() else '#4FC3F7'
            card = FeatureCard(title, desc, icon, attr, accent, gridWidget)
            row, col = divmod(i, 3)
            grid.addWidget(card, row, col)
        self.vBoxLayout.addWidget(gridWidget)

        # ---- 公告 / 更新 / 关于 ----
        self.vBoxLayout.addWidget(self.announcements)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

    def showEvent(self, e):
        """窗口显示后再填充公告内容（加速首屏显示）。"""
        super().showEvent(e)
        try:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, self._defer_build_home_content)
        except Exception:
            pass

    def _defer_build_home_content(self):
        try:
            if getattr(self, 'announcements', None) is not None:
                self.announcements.build_content()
        except Exception:
            pass


if __name__ == '__main__':
    from qfluentwidgets import setTheme, Theme
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    w = Home()
    w.resize(1080, 780)
    w.show()
    sys.exit(app.exec_())