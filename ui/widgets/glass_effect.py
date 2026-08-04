# -*- coding: utf-8 -*-
"""
全局玻璃效果管理器（透明度 / 模糊度）
=====================================
统一管理整个 OGC 系统的界面透明度与模糊度：

    - 透明度 opacity  : 控制内容层（页面背景 / 登录面板遮罩 / 表格卡片背景）的
                       不透明度，数值越大越不透明。设有下限保护（150），
                       保证文字始终清晰可读。
    - 模糊度 blur    : 控制磨砂背景（登录面板 / 主窗口背景层）的模糊半径。

同时提供 FrostedPanel（磨砂玻璃面板），登录页与主窗口共用，
并自动跟随全局透明度 / 模糊度调节。

设计要点
--------
「保留各页面组件架构，透明化页面匣子，让主框架底层磨砂背景直接透出」：

    1. 窗口级 FrostedPanel 负责统一背景（覆盖导航栏/标题栏/全部页面区域）
    2. 页面容器（ScrollArea / SmoothScrollArea 等 '匣子'）的
       viewport / 内容 widget 及所有装饰性后代容器全部强制透明
    3. 交互与内容控件（按钮 / 输入框 / 表格 / 列表 / 卡片 / 文字标签等）
       保留可见，并给表格/列表/卡片叠加"半透明 + 深边框"保证文字清晰
    4. 导航栏、标题栏透明化，使整个窗口共享同一毛玻璃背景

使用 ::

    from ui.widgets.glass_effect import glass_manager, FrostedPanel

    glass_manager.load(opacity=225, blur_radius=15)      # 从配置加载
    glass_manager.set_opacity(180)                       # 实时调整透明度
    glass_manager.set_blur_radius(25)                    # 实时调整模糊度
    glass_manager.apply_to_window(main_window)           # 刷新表格/卡片/页面背景
"""
import os

from PyQt5.QtCore import Qt, QObject, QRect, QRectF, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QApplication, QTableView, QListWidget, QTreeView,
    QAbstractScrollArea, QAbstractItemView, QLabel, QFrame,
    QStackedWidget, QGraphicsBlurEffect, QGraphicsScene,
    QGraphicsPixmapItem, QPushButton, QLineEdit, QTextEdit,
    QComboBox, QCheckBox, QRadioButton, QSlider, QScrollBar,
    QSpinBox, QDoubleSpinBox, QDateTimeEdit,
)

from qfluentwidgets import (
    SimpleCardWidget, isDarkTheme, CardWidget, ToolButton,
    PrimaryPushButton, CheckBox as QFCheckBox, ComboBox as QFComboBox,
    LineEdit as QFLineEdit, SwitchButton,
)

from core.logger import logger

# 磨砂面板默认背景图
DEFAULT_BACKGROUND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'resources', 'images', 'background', 'background-2-2.jpg')

# 注入样式的标记（用于替换旧值，避免重复叠加）
_MARK_BEGIN = '/* __GLASS_BEGIN__ */'
_MARK_END = '/* __GLASS_END__ */'

# 内容 / 交互控件白名单：保留自身背景与文字，仅叠加半透明+边框
_CONTENT_KEEP_TYPES = (
    QAbstractItemView,          # 表格 / 列表 / 树
    SimpleCardWidget, CardWidget,
    QPushButton, QFCheckBox,
    QFLineEdit, QLineEdit,
    QTextEdit, QComboBox,
    QFComboBox, QCheckBox,
    QRadioButton, QSlider,
    QScrollBar, QSpinBox,
    QDoubleSpinBox, QDateTimeEdit,
    SwitchButton, ToolButton,
    PrimaryPushButton,
)


class GlassManager(QObject):
    """全局玻璃效果管理器（单例）"""

    changed = pyqtSignal()

    # 可读性保护：透明度下限（低于此值文字可能看不清）
    MIN_OPACITY = 150
    MAX_OPACITY = 255
    MAX_BLUR = 40

    def __init__(self):
        super().__init__()
        self._opacity = 225          # 内容层默认不透明度（0~255）
        self._blur_radius = 15       # 默认模糊半径

    # ---------- 只读属性 ----------
    @property
    def opacity(self) -> int:
        return self._opacity

    @property
    def blur_radius(self) -> int:
        return self._blur_radius

    # ---------- 初始化 ----------
    def load(self, opacity: int = None, blur_radius: int = None):
        """从配置加载并广播（可只传其一）"""
        if opacity is not None:
            self._opacity = self._clamp_opacity(opacity)
        if blur_radius is not None:
            self._blur_radius = self._clamp_blur(blur_radius)
        self.changed.emit()

    # ---------- 设置 ----------
    def set_opacity(self, value: int):
        """调整全局透明度（0~255，下限保护 150）"""
        value = self._clamp_opacity(value)
        if value != self._opacity:
            self._opacity = value
            self.changed.emit()

    def set_blur_radius(self, value: int):
        """调整全局模糊度（0~40）"""
        value = self._clamp_blur(value)
        if value != self._blur_radius:
            self._blur_radius = value
            self.changed.emit()

    # ---------- 辅助 ----------
    @classmethod
    def _clamp_opacity(cls, v):
        return max(cls.MIN_OPACITY, min(cls.MAX_OPACITY, int(v)))

    @classmethod
    def _clamp_blur(cls, v):
        return max(0, min(cls.MAX_BLUR, int(v)))

    # ---------- 颜色 ----------
    def content_bg_color(self) -> QColor:
        """内容层背景色（跟随主题）"""
        if isDarkTheme():
            return QColor(28, 28, 30, self._opacity)
        return QColor(255, 255, 255, self._opacity)

    def border_color(self) -> QColor:
        """加深后的边框色（保证列表/卡片边界清晰）"""
        if isDarkTheme():
            return QColor(255, 255, 255, 85)
        return QColor(0, 0, 0, 55)

    # ---------- QSS 构建 ----------
    def table_qss(self) -> str:
        """表格/列表统一样式：半透明背景 + 加深边框，条目文字保持默认前景色"""
        bg = self.content_bg_color().name(QColor.HexArgb)
        border = self.border_color().name(QColor.HexArgb)
        return (
            f"\nQTableView {{ background-color: {bg}; border: 1px solid {border}; }}"
            f"\nQTableView::item {{ border-bottom: 1px solid {border}; }}"
            f"\nQTreeView {{ background-color: {bg}; border: 1px solid {border}; }}"
            f"\nQTreeView::item {{ border-bottom: 1px solid {border}; }}"
            f"\nQListWidget {{ background-color: {bg}; border: 1px solid {border}; }}"
            f"\nQListWidget::item {{ border-bottom: 1px solid {border}; }}"
        )

    def card_qss(self) -> str:
        """内容卡片统一样式：半透明背景 + 加深边框（文字保持默认色）"""
        bg = self.content_bg_color().name(QColor.HexArgb)
        border = self.border_color().name(QColor.HexArgb)
        return (
            f"\nSimpleCardWidget {{ background-color: {bg}; "
            f"border: 1px solid {border}; border-radius: 8px; }}"
        )

    @staticmethod
    def transparent_qss(widget_type: str = 'QWidget') -> str:
        """使容器完全透明（让磨砂背景透出）"""
        return f"\n{widget_type} {{ background-color: transparent; border: none; }}"

    # ---------- 注入样式工具 ----------
    @staticmethod
    def _inject_qss(widget, css: str):
        """向控件注入带标记的样式段，重复调用时自动替换旧值"""
        try:
            orig = widget.property('_glass_orig_qss')
            if orig is None:
                orig = widget.styleSheet()
                # 防止首次记录时已包含旧注入段
                if _MARK_BEGIN in orig:
                    orig = orig.split(_MARK_BEGIN)[0] + \
                        (orig.split(_MARK_END)[-1] if _MARK_END in orig else '')
                widget.setProperty('_glass_orig_qss', orig)

            new = (orig + "\n" if orig else "") + \
                f"{_MARK_BEGIN}\n{css}\n{_MARK_END}"
            widget.setStyleSheet(new)
        except (RuntimeError, TypeError):
            pass

    # ---------- 透明化辅助 ----------
    @staticmethod
    def _force_transparent(widget):
        """强制控件背景透明（关闭 autoFill、set 透明样式、调色板透明）"""
        try:
            widget.setAutoFillBackground(False)
            widget.setAttribute(Qt.WA_TranslucentBackground, True)
            t = widget.palette()
            c = t.window().color()
            c.setAlpha(0)
            t.setColor(widget.backgroundRole(), c)
            widget.setPalette(t)
            GlassManager._inject_qss(
                widget,
                f"{type(widget).__name__} {{ background-color: transparent; "
                f"border: none; }}")
        except (RuntimeError, TypeError):
            pass

    @classmethod
    def _transparentize_container(cls, container):
        """递归透明化容器及其所有装饰性后代（白名单内容控件除外）

        保留白名单控件自身样式，其余 QWidget/QFrame/QLabel 容器背景透明。
        """
        # 1) 容器自身透明
        cls._force_transparent(container)

        # 2) 递归后代
        for child in container.findChildren(QWidget):
            # 跳过关键交互/内容控件
            if isinstance(child, _CONTENT_KEEP_TYPES):
                continue
            # 跳过自身
            if child is container:
                continue
            cls._force_transparent(child)

    # ---------- 应用 ----------
    def apply_to_window(self, window):
        """将当前透明度/模糊度应用到已打开的窗口（登录页 / 主窗口）

        统一处理：
            1. 页面匣子（ScrollArea 等滚动区域）自身、viewport、内容widget
               及其全部装饰性后代 -> 强制透明，露出底层磨砂
            2. 表格 / 列表 / 树：半透明背景 + 加深边框（文字清晰）
            3. 内容卡片：半透明背景 + 加深边框
            4. 导航栏 / 标题栏：透明化，使整个窗口共享同一磨砂背景
        """
        try:
            window_class = type(window).__name__
            logger.info(
                f"应用玻璃效果 -> {window_class} "
                f"opacity={self._opacity} blur={self._blur_radius}"
            )

            # 1. 主窗口页面区域：StackedWidget 及内层 view 透明
            if hasattr(window, 'stackedWidget'):
                sw = window.stackedWidget
                self._inject_qss(sw, self.transparent_qss('QStackedWidget'))
                self._force_transparent(sw)
                view = getattr(sw, 'view', None)
                if view is not None:
                    self._inject_qss(view, self.transparent_qss('QWidget'))
                    self._force_transparent(view)
                    # 所有页面匣子递归透明化
                    for i in range(view.count()):
                        page = view.widget(i)
                        if isinstance(page, QWidget):
                            self._transparentize_page(page)

            # 2. 其余滚动区域（登录页等）也透明化
            for scroll in window.findChildren(QAbstractScrollArea):
                if isinstance(scroll, _CONTENT_KEEP_TYPES):
                    continue
                self._transparentize_scroll_area(scroll)

            # 3. 内容控件叠加半透明 + 深边框
            for tb in window.findChildren(QTableView):
                self._inject_qss(tb, self.table_qss())
            for ls in window.findChildren(QListWidget):
                self._inject_qss(ls, self.table_qss())
            for tr in window.findChildren(QTreeView):
                self._inject_qss(tr, self.table_qss())
            for card in window.findChildren(SimpleCardWidget):
                self._inject_qss(card, self.card_qss())

            # 4. 导航面板与标题栏透明化（共享同一磨砂背景）
            nav = getattr(window, 'navigationInterface', None)
            if nav is not None:
                panel = getattr(nav, 'panel', nav)
                self._inject_qss(
                    panel,
                    "\nNavigationPanel, NavigationPanel[menu=true], "
                    "NavigationPanel[menu=false] {"
                    " background-color: transparent; border: none; }"
                )
            tb = getattr(window, 'titleBar', None)
            if tb is not None:
                alpha = max(100, int(200 * self._opacity / 255))
                self._inject_qss(
                    tb,
                    f"\nSplitTitleBar {{ background-color: "
                    f"rgba(255,255,255,{alpha}); border: none; }}"
                )

            logger.info(f"玻璃效果应用完成 -> {window_class}")
        except Exception as e:
            logger.error(f"应用玻璃效果失败: {e}", exc_info=True)

    # ---------- 页面透明化 ----------
    def _transparentize_page(self, page: QWidget):
        """透明化一个页面（自身 + viewport + 内容 widget + 装饰性后代）"""
        # 页面自身透明
        self._force_transparent(page)

        # 若是滚动区域：viewport + 内容 widget 透明
        if isinstance(page, QAbstractScrollArea):
            vp = page.viewport()
            if vp is not None:
                self._force_transparent(vp)
            try:
                content = page.widget()
                if content is not None:
                    self._transparentize_container(content)
            except (AttributeError, RuntimeError):
                pass

            # 页面内的装饰性后代（白名单内容控件除外）
            for child in page.findChildren(QWidget):
                key = (type(child).__name__, child.objectName())
                if isinstance(child, _CONTENT_KEEP_TYPES):
                    continue
                # 边框/圆角纯装饰容器清背景
                self._force_transparent(child)
        else:
            # 普通页面：递归透明化所有后代（保留白名单）
            for child in page.findChildren(QWidget):
                if isinstance(child, _CONTENT_KEEP_TYPES):
                    continue
                self._force_transparent(child)

    def _transparentize_scroll_area(self, scroll: QAbstractScrollArea):
        """透明化滚动区域的 自身 + viewport + 内容widget 三层背景"""
        self._force_transparent(scroll)
        vp = scroll.viewport()
        if vp is not None:
            self._force_transparent(vp)
        try:
            content = scroll.widget()
            if content is not None:
                self._transparentize_container(content)
        except (AttributeError, RuntimeError):
            pass


class FrostedPanel(QWidget):
    """磨砂玻璃面板（登录页 / 主窗口共用）

    绘制经过高斯模糊的背景图，并叠加主题色半透明遮罩，
    实现类似 iOS 毛玻璃的视觉效果。
    自动跟随 glass_manager 的透明度与模糊度。
    控件位于面板上层，保持清晰不受影响；鼠标事件穿透。
    """

    def __init__(self, parent=None, background_img: str = None):
        super().__init__(parent=parent)
        # 不拦截鼠标事件，保证子控件可正常点击
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._bg_pixmap = QPixmap(background_img or DEFAULT_BACKGROUND)
        self._blur_cache = None
        self._blur_radius = glass_manager.blur_radius
        self._alpha = glass_manager.opacity
        # 监听全局玻璃配置变化，实时刷新
        glass_manager.changed.connect(self._on_glass_changed)

    # ---------- 全局配置联动 ----------
    def _on_glass_changed(self):
        self._blur_radius = glass_manager.blur_radius
        self._alpha = glass_manager.opacity
        self._blur_cache = None
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        if self._bg_pixmap.isNull() or self.width() <= 0 or self.height() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # 1) 背景图按 KeepAspectRatioByExpanding 缩放并居中裁剪到面板大小
        scaled = self._bg_pixmap.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (scaled.width() - self.width()) // 2
        y = (scaled.height() - self.height()) // 2
        if x < 0:
            x = 0
        if y < 0:
            y = 0
        cropped = scaled.copy(QRect(x, y, self.width(), self.height()))

        # 2) 高斯模糊（带缓存，仅尺寸 / 模糊度变化时重新模糊）
        if self._blur_cache is None or self._blur_cache.size() != self.size() \
                or getattr(self, '_cached_radius', None) != self._blur_radius:
            self._cached_radius = self._blur_radius
            self._blur_cache = self._apply_blur(cropped)
        painter.drawPixmap(0, 0, self._blur_cache)

        # 3) 叠加主题色半透明遮罩（实现透明度可调）
        if isDarkTheme():
            painter.fillRect(self.rect(), QColor(20, 20, 22, self._alpha))
        else:
            painter.fillRect(self.rect(), QColor(255, 255, 255, self._alpha))

    def _apply_blur(self, pixmap):
        """对 pixmap 应用高斯模糊并返回结果（blur=0 时返回原图）"""
        if self._blur_radius <= 0:
            return pixmap

        scene = QGraphicsScene(self)
        item = QGraphicsPixmapItem(pixmap)
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(self._blur_radius)
        item.setGraphicsEffect(blur)
        scene.addItem(item)

        result = QPixmap(self.size())
        result.fill(Qt.transparent)
        painter = QPainter(result)
        scene.render(painter, QRectF(), QRectF(0, 0, self.width(), self.height()))
        painter.end()
        return result


# 全局单例
glass_manager = GlassManager()