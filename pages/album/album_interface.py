# -*- coding: utf-8 -*-
"""
画册模块主页（OGC 集成版）
=========================
与视频模块结构一致：画册是一个导航父级，其下有多个子模块页面。
主页显示子模块入口卡片，点击跳转到对应子模块。

当前子模块：
- E-Hentai：画廊下载 / 我的收藏 / 设置（分段导航切换）
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon as FIF,
    IconWidget,
    SubtitleLabel,
    isDarkTheme,
)

from core.resource_paths import PROJECT_ROOT, NAV_JMCOMIC
from ui.widgets.theme import ensure_theme_connected, on_theme_changed, theme_color


class AlbumInterface(QScrollArea):
    """画册主页：显示子模块入口卡片，点击跳转到对应子模块"""

    # 子模块配置: (key, 显示名, 描述, 图标路径或 None)
    SUBMODULES = [
        ('easycopy', '拷贝漫画', '漫画首页 / 发现 / 排行 / 我的 / 设置 · 支持下载', None),
        ('ehentai', 'E-Hentai', '画廊下载 / 我的收藏 / 设置', None),
        ('jmcomic', 'JMComic', '漫画搜索 / 下载 / 打包 / 订阅', NAV_JMCOMIC),
    ]

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('AlbumInterface')
        self._sub_interfaces = {}
        self._sub_cards = {}

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet('QScrollArea { border: none; background: transparent; }')

        self.view = QWidget(self)
        self.layout = QVBoxLayout(self.view)
        self.layout.setSpacing(24)
        # 视口边距固定标题栏空间（不会随滚动移动）
        self.setViewportMargins(0, 64, 0, 0)
        self.layout.setContentsMargins(36, 0, 36, 36)
        self.setWidget(self.view)

        # 主题切换自动刷新入口卡片样式
        ensure_theme_connected()
        on_theme_changed(self._apply_theme_style)

        # 标题
        title_label = SubtitleLabel('画册', self.view)
        title_label.setStyleSheet('font-size: 24px; font-weight: bold;')
        self.layout.addWidget(title_label)

        self.desc_label = CaptionLabel('选择画册来源，下载与管理画廊图片', self.view)
        self.desc_label.setObjectName('albumDescLabel')
        self.layout.addWidget(self.desc_label)

        self.layout.addSpacing(16)

        # 子模块入口卡片网格
        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(16)
        self.cards_grid.setAlignment(Qt.AlignTop)
        self.layout.addLayout(self.cards_grid)

        for i, (key, name, desc, icon_path) in enumerate(self.SUBMODULES):
            card = self._create_sub_card(key, name, desc, icon_path)
            self._sub_cards[key] = card
            row, col = divmod(i, 3)
            self.cards_grid.addWidget(card, row, col)

        self._apply_theme_style()

        self.layout.addStretch()

    # ------------------------------------------------------------------
    def setSubInterfaces(self, subs: dict) -> None:
        """由 Window 设置子模块页面引用 {key: page}"""
        self._sub_interfaces = subs

    def setAllowedSubmodules(self, allowed_keys: set) -> None:
        """按权限过滤子模块入口卡片（隐藏被禁用的子模块）"""
        for key, card in self._sub_cards.items():
            card.setVisible(key in allowed_keys)

    def _create_sub_card(self, key: str, name: str, desc: str, icon_path: str):
        """创建单个子模块入口卡片，点击跳转到子模块"""
        card = CardWidget(self.view)
        card.setFixedSize(280, 150)
        card.setCursor(Qt.PointingHandCursor)
        card.setObjectName('albumSubCard')

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 20, 18, 18)
        card_layout.setSpacing(8)
        card_layout.setAlignment(Qt.AlignTop)

        # 图标（带品牌淡蓝玻璃圆角底座）
        icon_wrapper = QWidget(card)
        icon_wrapper.setFixedSize(46, 46)
        icon_wrapper.setObjectName('subIconWrapper')
        wrapper_layout = QHBoxLayout(icon_wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setAlignment(Qt.AlignCenter)

        icon_widget = QLabel(icon_wrapper)
        icon_widget.setAlignment(Qt.AlignCenter)
        icon_widget.setFixedSize(30, 30)
        if icon_path and os.path.exists(icon_path):
            from PyQt5.QtGui import QPixmap
            pix = QPixmap(icon_path).scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_widget.setPixmap(pix)
        else:
            icon = IconWidget(FIF.PHOTO, icon_wrapper)
            icon.setFixedSize(28, 28)
            icon.setStyleSheet('color: #28afe9; background: transparent;')
            icon_widget = icon
        wrapper_layout.addWidget(icon_widget)
        card_layout.addWidget(icon_wrapper, 0, Qt.AlignLeft)

        # 名称 + 描述
        name_label = BodyLabel(name, card)
        name_label.setStyleSheet('font-size: 15px; font-weight: 600;')
        card_layout.addWidget(name_label)

        desc_label = CaptionLabel(desc, card)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(
            'color: ' + theme_color('#7A8792', '#9AA7B5') + '; font-size: 12px;')
        card_layout.addWidget(desc_label)
        card_layout.addStretch(1)

        # 点击跳转（覆盖 mouseReleaseEvent 生效）
        card.mouseReleaseEvent = lambda e, k=key: self._navigate(k)
        return card

    def _navigate(self, key: str) -> None:
        """跳转到对应子模块页面"""
        sub = self._sub_interfaces.get(key)
        win = self.window()
        if win and sub:
            win.switchTo(sub)

    # ------------------------------------------------------------------
    # 主题切换自动刷新
    # ------------------------------------------------------------------
    def _apply_theme_style(self) -> None:
        if hasattr(self, 'desc_label'):
            self.desc_label.setStyleSheet(
                'color: ' + theme_color('#909399', '#8A8A8A') + '; font-size: 13px;')

        if isDarkTheme():
            card_bg = 'rgba(35, 38, 48, 0.85)'
            card_border = 'rgba(255, 255, 255, 0.09)'
            card_hover_bg = 'rgba(44, 50, 64, 0.92)'
            card_hover_border = 'rgba(76, 195, 247, 0.35)'
            icon_bg = 'rgba(76, 195, 247, 0.10)'
        else:
            card_bg = 'rgba(255, 255, 255, 0.86)'
            card_border = 'rgba(0, 0, 0, 0.06)'
            card_hover_bg = 'rgba(248, 252, 254, 0.95)'
            card_hover_border = 'rgba(14, 140, 192, 0.30)'
            icon_bg = 'rgba(14, 140, 192, 0.08)'

        for card in self._sub_cards.values():
            card.setStyleSheet(f"""
                QWidget#albumSubCard {{
                    background-color: {card_bg};
                    border: 1px solid {card_border};
                    border-radius: 14px;
                }}
                QWidget#albumSubCard:hover {{
                    background-color: {card_hover_bg};
                    border: 1px solid {card_hover_border};
                }}
                QWidget#subIconWrapper {{
                    background-color: {icon_bg};
                    border-radius: 12px;
                }}
            """)
            card.update()
