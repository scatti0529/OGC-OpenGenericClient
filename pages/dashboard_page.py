# coding:utf-8
"""
仪表盘管理页面 - 管理员专用
=============================
展示程序运行统计数据、用户信息管理、权限控制、封禁/解封功能
"""
import os
import sys
import json
from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal, QDate, QSize
from PyQt5.QtGui import QPixmap, QFont, QColor
try:
    from PyQt5.QtChart import (
        QChart, QChartView, QBarSet, QBarSeries, QBarCategoryAxis,
        QValueAxis, QPieSeries, QPieSlice
    )
    QT_CHART_AVAILABLE = True
except ImportError:
    QT_CHART_AVAILABLE = False
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QGridLayout, QSizePolicy, QSpacerItem, QPushButton, QHeaderView,
    QTableWidgetItem, QAbstractItemView, QDialog, QDialogButtonBox
)
from qfluentwidgets import (
    CardWidget, AvatarWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    IconWidget, FluentIcon as FIF, PrimaryPushButton, PushButton,
    SwitchButton, InfoBar, InfoBarPosition, TableWidget, ToolButton,
    FlowLayout, StrongBodyLabel, TitleLabel, PixmapLabel, ScrollArea,
    ComboBox, LineEdit, Dialog
)

from core.database import (
    get_all_users, get_user_permissions, save_user_permissions,
    set_user_banned, delete_user, get_system_stats, is_admin,
    ALL_MODULES, ALL_FEATURES, get_default_permissions,
    init_usage_table, get_usage_stats,
)

from core.resource_paths import DASHBOARD_DEFAULT_AVATAR as _DEFAULT_AVATAR
from ui.widgets.theme import (
    theme_color, text_tertiary, text_primary,
    on_theme_changed, ensure_theme_connected,
)


# ═══════════════════════════════════════════════════════════
#  统计卡片（图文样式）
# ═══════════════════════════════════════════════════════════
class StatCard(CardWidget):
    """统计信息卡片：图标 + 数值 + 标题"""

    def __init__(self, icon: FIF, title: str, value, color: str = "#28afe9", parent=None):
        super().__init__(parent=parent)
        self.setFixedHeight(130)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(18)

        # 图标背景
        iconBg = QFrame(self)
        iconBg.setFixedSize(64, 64)
        iconBg.setStyleSheet(f"""
            QFrame {{
                background-color: {color}22;
                border-radius: 18px;
            }}
        """)
        iconLayout = QVBoxLayout(iconBg)
        iconLayout.setContentsMargins(0, 0, 0, 0)
        self.iconWidget = IconWidget(icon, iconBg)
        self.iconWidget.setFixedSize(32, 32)
        self.iconWidget.setStyleSheet(
            f"color: {color}; background: transparent;")
        iconLayout.addWidget(self.iconWidget, 0, Qt.AlignCenter)
        layout.addWidget(iconBg)

        # 文字信息
        textLayout = QVBoxLayout()
        textLayout.setSpacing(4)
        textLayout.setContentsMargins(0, 0, 0, 0)

        self.valueLabel = TitleLabel(str(value), self)
        self.valueLabel.setStyleSheet(f"font-size: 30px; font-weight: bold; color: {color};")

        self.titleLabel = CaptionLabel(title, self)
        self.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + theme_color('#8A8A8A', '#AAAAAA') + ";")

        textLayout.addWidget(self.valueLabel)
        textLayout.addWidget(self.titleLabel)
        textLayout.addStretch()
        layout.addLayout(textLayout)
        layout.addStretch()

    def setValue(self, value):
        self.valueLabel.setText(str(value))


# ═══════════════════════════════════════════════════════════
#  用户行卡片（列表中的一行）
# ═══════════════════════════════════════════════════════════
class UserRowCard(CardWidget):
    """用户列表行：头像 + 用户名 + 角色 + 状态 + 操作按钮"""

    onBanToggled = pyqtSignal(str, bool)      # (username, is_banned)
    onEditPermission = pyqtSignal(str)        # username
    onDeleteUser = pyqtSignal(str)            # username

    def __init__(self, user: dict, parent=None):
        super().__init__(parent=parent)
        self._user = user
        self.setFixedHeight(88)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(16)

        # 头像
        avatar_path = user.get('avatar_path', '')
        if not avatar_path or not os.path.exists(avatar_path):
            avatar_path = _DEFAULT_AVATAR
        self.avatar = AvatarWidget(avatar_path, self)
        self.avatar.setRadius(28)
        self.avatar.setFixedSize(56, 56)
        layout.addWidget(self.avatar)

        # 用户信息
        infoLayout = QVBoxLayout()
        infoLayout.setSpacing(4)

        nameRow = QHBoxLayout()
        nameRow.setSpacing(8)
        self.nameLabel = StrongBodyLabel(user.get('username', ''), self)
        self.nameLabel.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: " + text_primary() + ";")
        nameRow.addWidget(self.nameLabel)

        # 角色标签（空角色显示"普通用户"，无边框简洁样式）
        role = user.get('role', '') or '普通用户'
        roleLabel = QLabel(f"[{role}]", self)
        if role == '管理员':
            roleLabel.setStyleSheet(
                "color: #28afe9; font-size: 12px; background: transparent;")
        else:
            roleLabel.setStyleSheet(
                "color: #67C23A; font-size: 12px; background: transparent;")
        nameRow.addWidget(roleLabel)
        nameRow.addStretch()
        infoLayout.addLayout(nameRow)

        # 注册时间 / 最后登录
        timeText = f"注册: {user.get('created_at', '-')}"
        if user.get('last_login'):
            timeText += f"  |  最后登录: {user['last_login']}"
        self.timeLabel = CaptionLabel(timeText, self)
        self.timeLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        infoLayout.addWidget(self.timeLabel)

        layout.addLayout(infoLayout)
        layout.addStretch()

        # 封禁状态标签（无边框简洁样式）
        self.banLabel = QLabel("已封禁" if user.get('is_banned') else "正常", self)
        if user.get('is_banned'):
            self.banLabel.setStyleSheet(
                "color: #F56C6C; font-size: 12px; background: transparent;")
        else:
            self.banLabel.setStyleSheet(
                "color: #67C23A; font-size: 12px; background: transparent;")
        layout.addWidget(self.banLabel)

        # ── 操作按钮：使用 Qt 原生 QPushButton（图标+文字由 Qt 原生布局分隔）──
        self.editPermBtn = QPushButton(FIF.EDIT.icon(), "权限")
        self.editPermBtn.setFixedSize(80, 32)
        self.editPermBtn.setIconSize(QSize(16, 16))
        self.editPermBtn.setCursor(Qt.PointingHandCursor)
        self.editPermBtn.setStyleSheet(UserRowCard._btn_style('#28afe9'))
        self.editPermBtn.clicked.connect(
            lambda: self.onEditPermission.emit(user['username']))
        layout.addWidget(self.editPermBtn)

        # 封禁/解封按钮（图标 + 文字，初始状态读数据库）
        self.banBtn = QPushButton()
        self.banBtn.setFixedSize(80, 32)
        self.banBtn.setIconSize(QSize(16, 16))
        self.banBtn.setCursor(Qt.PointingHandCursor)
        self._is_banned = user.get('is_banned', False)
        self._update_ban_ui(self._is_banned)
        self.banBtn.clicked.connect(self._on_ban_clicked)
        layout.addWidget(self.banBtn)

        # 删除用户按钮（固定红色，admin 不显示）
        self.deleteBtn = QPushButton(FIF.DELETE.icon(), "删除")
        self.deleteBtn.setFixedSize(80, 32)
        self.deleteBtn.setIconSize(QSize(16, 16))
        self.deleteBtn.setCursor(Qt.PointingHandCursor)
        self.deleteBtn.setStyleSheet(UserRowCard._btn_style('#F56C6C'))
        self.deleteBtn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self.deleteBtn)
        if user.get('username') == 'admin':
            self.deleteBtn.setVisible(False)

    @staticmethod
    def _btn_style(color: str) -> str:
        """统一的按钮样式模板：三个操作按钮形状完全一致，仅颜色不同

        使用 Qt 原生 QPushButton，内部图标/文字布局由 Qt 处理，
        QSS 只控制颜色与圆角，不会导致图标文字重叠。
        """
        return f"""
            QPushButton {{
                color: {color};
                background-color: {color}1A;
                border: 1px solid {color}66;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {color}33;
                border: 1px solid {color};
            }}
            QPushButton:pressed {{
                background-color: {color}44;
            }}
        """

    def _on_ban_clicked(self):
        """封禁/解封点击确认"""
        username = self._user['username']
        # 实时读取数据库状态
        try:
            from core.database import is_user_banned
            self._user['is_banned'] = is_user_banned(username)
        except Exception:
            pass
        will_ban = not self._user['is_banned']
        # 乐观更新本地状态与按钮
        self._user['is_banned'] = will_ban
        self._update_ban_ui(will_ban)

        if will_ban:
            w = Dialog(
                '确认封禁',
                f'确定要封禁用户「{username}」吗？\n'
                '封禁后该用户将无法登录，但数据会被保留。',
                self.window()
            )
            w.yesButton.setText('确认封禁')
            w.cancelButton.setText('取消')
        else:
            w = Dialog(
                '确认解封',
                f'确定要解封用户「{username}」吗？\n'
                '解封后该用户可以正常登录。',
                self.window()
            )
            w.yesButton.setText('确认解封')
            w.cancelButton.setText('取消')

        if w.exec():
            self.onBanToggled.emit(username, will_ban)
        else:
            # 用户取消，回滚按钮显示
            self._user['is_banned'] = not will_ban
            self._update_ban_ui(not will_ban)

    def _update_ban_ui(self, banned: bool):
        """根据封禁状态更新按钮和标签（按钮形状保持不变，仅换颜色/图标/文字）"""
        if banned:
            self.banBtn.setIcon(FIF.ACCEPT.icon())
            self.banBtn.setText("解封")
            self.banBtn.setStyleSheet(UserRowCard._btn_style('#67C23A'))
            self.banLabel.setText("已封禁")
            self.banLabel.setStyleSheet(
                "color: #F56C6C; font-size: 12px; background: transparent;")
        else:
            self.banBtn.setIcon(FIF.CANCEL.icon())
            self.banBtn.setText("封禁")
            self.banBtn.setStyleSheet(UserRowCard._btn_style('#F56C6C'))
            self.banLabel.setText("正常")
            self.banLabel.setStyleSheet(
                "color: #67C23A; font-size: 12px; background: transparent;")

    def _on_delete_clicked(self):
        """删除用户确认"""
        username = self._user['username']
        w = Dialog(
            '确认删除',
            f'确定要删除用户「{username}」吗？\n'
            '删除后将永久移除该账号及其数据，且不可恢复！',
            self.window()
        )
        w.yesButton.setText('确认删除')
        w.cancelButton.setText('取消')
        if w.exec():
            self.onDeleteUser.emit(username)


# ═══════════════════════════════════════════════════════════
#  权限编辑对话框
# ═══════════════════════════════════════════════════════════
class PermissionDialog(QDialog):
    """权限编辑对话框：模块开关 + 功能开关"""

    def __init__(self, username: str, perms: dict, parent=None):
        super().__init__(parent)
        self._username = username
        self._perms = perms
        self.setWindowTitle(f"用户权限管理 - {username}")
        self.setModal(True)
        self.setFixedWidth(560)
        self.setMinimumHeight(500)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(16)

        # 标题
        titleLabel = SubtitleLabel(f"🔐 用户权限管理：{username}", self)
        titleLabel.setStyleSheet("font-size: 20px; font-weight: bold;")
        outer.addWidget(titleLabel)

        descLabel = CaptionLabel(
            "通过开关控制该用户可以访问的模块和使用的功能，修改后点击「保存」生效。",
            self)
        descLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        outer.addWidget(descLabel)

        # 滚动区域
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        contentLayout = QVBoxLayout(content)
        contentLayout.setSpacing(20)
        contentLayout.setContentsMargins(4, 4, 8, 4)

        # ── 模块权限 ──
        moduleCard = CardWidget(content)
        moduleLayout = QVBoxLayout(moduleCard)
        moduleLayout.setContentsMargins(20, 16, 20, 16)
        moduleLayout.setSpacing(8)

        moduleTitle = StrongBodyLabel("📂 模块访问权限", moduleCard)
        moduleTitle.setStyleSheet("font-size: 16px; font-weight: bold;")
        moduleLayout.addWidget(moduleTitle)

        self._module_switches = {}
        for key, name in ALL_MODULES:
            row = QHBoxLayout()
            row.setSpacing(12)
            label = BodyLabel(name, moduleCard)
            label.setStyleSheet("font-size: 14px;")
            row.addWidget(label)
            row.addStretch()
            sw = SwitchButton("关", moduleCard)
            sw.setChecked(bool(self._perms.get('modules', {}).get(key, True)))
            self._module_switches[key] = sw
            row.addWidget(sw)
            moduleLayout.addLayout(row)

        contentLayout.addWidget(moduleCard)

        # ── 功能权限 ──
        featureCard = CardWidget(content)
        featureLayout = QVBoxLayout(featureCard)
        featureLayout.setContentsMargins(20, 16, 20, 16)
        featureLayout.setSpacing(8)

        featureTitle = StrongBodyLabel("⚙️ 功能使用权限", featureCard)
        featureTitle.setStyleSheet("font-size: 16px; font-weight: bold;")
        featureLayout.addWidget(featureTitle)

        self._feature_switches = {}
        for key, name in ALL_FEATURES:
            row = QHBoxLayout()
            row.setSpacing(12)
            label = BodyLabel(name, featureCard)
            label.setStyleSheet("font-size: 14px;")
            row.addWidget(label)
            row.addStretch()
            sw = SwitchButton("关", featureCard)
            sw.setChecked(bool(self._perms.get('features', {}).get(key, True)))
            self._feature_switches[key] = sw
            row.addWidget(sw)
            featureLayout.addLayout(row)

        contentLayout.addWidget(featureCard)
        contentLayout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # ── 底部按钮 ──
        btnLayout = QHBoxLayout()
        btnLayout.addStretch()

        self.resetBtn = PushButton("恢复全部开启", self)
        self.resetBtn.clicked.connect(self._reset_all)
        btnLayout.addWidget(self.resetBtn)

        self.cancelBtn = PushButton("取消", self)
        self.cancelBtn.clicked.connect(self.reject)
        btnLayout.addWidget(self.cancelBtn)

        self.saveBtn = PrimaryPushButton(FIF.SAVE, "保存", self)
        self.saveBtn.clicked.connect(self._save)
        btnLayout.addWidget(self.saveBtn)

        outer.addLayout(btnLayout)

    def _reset_all(self):
        """恢复全部权限开启"""
        default = get_default_permissions()
        for key, _ in ALL_MODULES:
            self._module_switches[key].setChecked(True)
        for key, _ in ALL_FEATURES:
            self._feature_switches[key].setChecked(True)

    def _save(self):
        """保存权限"""
        perms = {
            'modules': {k: sw.isChecked() for k, sw in self._module_switches.items()},
            'features': {k: sw.isChecked() for k, sw in self._feature_switches.items()},
        }
        success, msg = save_user_permissions(self._username, perms)
        if success:
            InfoBar.success(
                title="保存成功", content=f"用户「{self._username}」的权限已更新",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
            self.accept()
        else:
            InfoBar.error(
                title="保存失败", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
            )

    @staticmethod
    def get_permissions(username: str, perms: dict, parent=None):
        """静态方法：打开对话框并返回是否修改"""
        dlg = PermissionDialog(username, perms, parent)
        return dlg.exec() == QDialog.Accepted


# ═══════════════════════════════════════════════════════════
#  仪表盘主页面
# ═══════════════════════════════════════════════════════════
class DashboardInterface(QScrollArea):
    """仪表盘管理页面"""

    HEADER_HEIGHT = 172  # 固定标题栏高度

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DashboardInterface")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }")

        from ui.widgets.theme import card_bg, card_border, theme_color, text_tertiary

        # ── 固定顶部标题区域（完全仿照设置页：控件直接定位在滚动区上方，不随滚动）──
        # 视口边距为顶部标题区域预留空间（数值与设置页一致）
        self.setViewportMargins(0, 80, 0, 20)

        # 标题图标（ScrollArea 自身子控件，move 定位）
        self.iconLabel = IconWidget(FIF.HISTORY, self)
        self.iconLabel.setFixedSize(32, 32)
        self.iconLabel.setStyleSheet("color: #28afe9; background: transparent;")
        self.iconLabel.move(36, 38)   # 36, 18

        # 主标题
        self.titleLabel = SubtitleLabel("系统仪表盘", self)
        self.titleLabel.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.titleLabel.move(80, 36)   # 80, 16

        # 副标题
        self.subLabel = CaptionLabel("监控程序运行状态，管理用户与权限", self)
        self.subLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        self.subLabel.move(80, 70)  # 80, 50

        # 刷新按钮（右上角，resizeEvent 里动态更新到最右侧）
        self.refreshBtn = PrimaryPushButton(FIF.SYNC, "刷新数据", self)
        self.refreshBtn.clicked.connect(self.refresh)
        # self.refreshBtn.move(110, 78)
        self.refreshBtn.setFixedSize(110, 38)  # 110，38

        # 初始定位刷新按钮到右上角
        self._layout_header()

        # ── 滚动内容 ──
        self.view = QWidget(self)
        self.mainLayout = QVBoxLayout(self.view)
        self.mainLayout.setSpacing(24)
        self.mainLayout.setContentsMargins(36, 20, 36, 36)
        self.setWidget(self.view)
        self.view.setStyleSheet(f"""
            QWidget {{ background-color: transparent; }}
            CardWidget {{
                border-radius: 12px;
                background-color: {card_bg()};
                border: 1px solid {card_border()};
            }}
        """)

        # ══ 统计卡片区 ══
        self.statsGrid = QGridLayout()
        self.statsGrid.setSpacing(16)
        self.statsGrid.setContentsMargins(0, 0, 0, 0)

        self.statUserCard = StatCard(FIF.PEOPLE, "注册用户", 0, "#28afe9")
        self.statBannedCard = StatCard(FIF.ROBOT, "封禁用户", 0, "#F56C6C")
        self.statMusicCard = StatCard(FIF.MUSIC, "音乐歌曲", 0, "#67C23A")
        self.statDownloadCard = StatCard(FIF.DOWNLOAD, "音乐下载", 0, "#E6A23C")
        self.statVideoCard = StatCard(FIF.VIDEO, "视频文件", 0, "#9C27B0")
        self.statPlaylistCard = StatCard(FIF.ALBUM, "播放列表", 0, "#FF9800")
        self.statJmSubCard = StatCard(FIF.BOOK_SHELF, "JM订阅", 0, "#00BCD4")
        self.statJmDownloadCard = StatCard(FIF.CLOUD, "JM下载", 0, "#FF5722")
        self.statMusicFileCard = StatCard(FIF.MUSIC, "音乐文件", 0, "#4CAF50")

        # 3列布局
        self.statsGrid.addWidget(self.statUserCard, 0, 0)
        self.statsGrid.addWidget(self.statBannedCard, 0, 1)
        self.statsGrid.addWidget(self.statMusicCard, 0, 2)
        self.statsGrid.addWidget(self.statDownloadCard, 1, 0)
        self.statsGrid.addWidget(self.statVideoCard, 1, 1)
        self.statsGrid.addWidget(self.statPlaylistCard, 1, 2)
        self.statsGrid.addWidget(self.statJmSubCard, 2, 0)
        self.statsGrid.addWidget(self.statJmDownloadCard, 2, 1)
        self.statsGrid.addWidget(self.statMusicFileCard, 2, 2)

        self.mainLayout.addLayout(self.statsGrid)

        # ══ 使用量统计区 ══
        usageCard = CardWidget(self.view)
        usageLayout = QVBoxLayout(usageCard)
        usageLayout.setContentsMargins(24, 20, 24, 20)
        usageLayout.setSpacing(12)

        usageHeader = QHBoxLayout()
        usageTitle = StrongBodyLabel("📊 模块使用量统计", usageCard)
        usageTitle.setStyleSheet("font-size: 18px; font-weight: bold;")
        usageHeader.addWidget(usageTitle)
        usageHeader.addStretch()
        # 日期筛选
        usageHeader.addWidget(CaptionLabel("开始日期:", usageCard))
        self.startDateEdit = LineEdit(usageCard)
        self.startDateEdit.setPlaceholderText("YYYY-MM-DD")
        self.startDateEdit.setFixedWidth(110)
        usageHeader.addWidget(self.startDateEdit)
        usageHeader.addWidget(CaptionLabel("结束日期:", usageCard))
        self.endDateEdit = LineEdit(usageCard)
        self.endDateEdit.setPlaceholderText("YYYY-MM-DD")
        self.endDateEdit.setFixedWidth(110)
        usageHeader.addWidget(self.endDateEdit)
        self.queryBtn = PushButton("查询", usageCard)
        self.queryBtn.clicked.connect(self._update_usage_chart)
        usageHeader.addWidget(self.queryBtn)
        usageLayout.addLayout(usageHeader)

        # 图表容器（柱状图 + 饼图）
        chartRow = QHBoxLayout()
        chartRow.setSpacing(16)
        if QT_CHART_AVAILABLE:
            # 柱状图：各模块使用量
            self.barChartView = QChartView(usageCard)
            self.barChartView.setMinimumHeight(280)
            chartRow.addWidget(self.barChartView, 2)
            # 饼图：视频子平台分布
            self.pieChartView = QChartView(usageCard)
            self.pieChartView.setMinimumHeight(280)
            chartRow.addWidget(self.pieChartView, 1)
        else:
            self.usageTextLabel = BodyLabel("QtChart 不可用，无法显示图表", usageCard)
            chartRow.addWidget(self.usageTextLabel)
        usageLayout.addLayout(chartRow)

        self.mainLayout.addWidget(usageCard)

        # ══ 用户管理区 ══
        userCard = CardWidget(self.view)
        userLayout = QVBoxLayout(userCard)
        userLayout.setContentsMargins(24, 20, 24, 20)
        userLayout.setSpacing(12)

        userHeader = QHBoxLayout()
        userTitle = StrongBodyLabel("👥 用户管理", userCard)
        userTitle.setStyleSheet("font-size: 18px; font-weight: bold;")
        userHeader.addWidget(userTitle)
        userHeader.addStretch()
        self.userCountLabel = CaptionLabel("", userCard)
        self.userCountLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 13px;")
        userHeader.addWidget(self.userCountLabel)
        userLayout.addLayout(userHeader)

        # 用户列表容器
        self.usersContainer = QWidget(userCard)
        self.usersLayout = QVBoxLayout(self.usersContainer)
        self.usersLayout.setSpacing(8)
        self.usersLayout.setContentsMargins(0, 0, 0, 0)
        self.usersLayout.addStretch()
        userLayout.addWidget(self.usersContainer)

        self.mainLayout.addWidget(userCard)

        self.mainLayout.addStretch()

        # 初始刷新
        self.refresh()

        # ── 主题切换时自动刷新样式 ──
        ensure_theme_connected()
        on_theme_changed(self._apply_theme_style)

    def _layout_header(self):
        """定位右上角刷新按钮（仿照设置页标题栏，控件直接 move 定位，不随滚动）"""
        try:
            # 刷新按钮固定到滚动区右上角（右侧留 36px 边距）
            self.refreshBtn.move(self.width() - 110 - 36, 36)
        except Exception:
            pass

    def showEvent(self, e):
        """首次显示时宽度就绪，重新定位标题栏"""
        super().showEvent(e)
        self._layout_header()

    def resizeEvent(self, e):
        """窗口尺寸变化时同步标题栏控件位置"""
        super().resizeEvent(e)
        self._layout_header()

    def _apply_theme_style(self):
        """主题切换时重新应用颜色"""
        from ui.widgets.theme import card_bg, card_border, theme_color
        self.view.setStyleSheet(f"""
            QWidget {{ background-color: transparent; }}
            CardWidget {{
                border-radius: 12px;
                background-color: {card_bg()};
                border: 1px solid {card_border()};
            }}
        """)
        # 头部副标题主题色
        self.subLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        # 用户数量文字主题色
        self.userCountLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 13px;")
        # 刷新统计卡片标题颜色
        self.statUserCard.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + text_tertiary() + ";")
        self.statBannedCard.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + text_tertiary() + ";")
        self.statMusicCard.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + text_tertiary() + ";")
        self.statDownloadCard.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + text_tertiary() + ";")
        self.statVideoCard.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + text_tertiary() + ";")
        self.statPlaylistCard.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + text_tertiary() + ";")
        self.statJmSubCard.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + text_tertiary() + ";")
        self.statJmDownloadCard.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + text_tertiary() + ";")
        self.statMusicFileCard.titleLabel.setStyleSheet(
            "font-size: 14px; color: " + text_tertiary() + ";")

    # ---------- 数据加载 ----------
    def refresh(self):
        """刷新统计数据与用户列表"""
        try:
            stats = get_system_stats()
            self.statUserCard.setValue(stats.get('user_count', 0))
            self.statBannedCard.setValue(stats.get('banned_count', 0))
            self.statMusicCard.setValue(stats.get('music_song_count', 0))
            self.statDownloadCard.setValue(stats.get('music_download_count', 0))
            self.statVideoCard.setValue(stats.get('video_file_count', 0))
            self.statPlaylistCard.setValue(stats.get('music_playlist_count', 0))
            self.statJmSubCard.setValue(stats.get('jmcomic_subscription_count', 0))
            self.statJmDownloadCard.setValue(stats.get('jmcomic_download_count', 0))
            self.statMusicFileCard.setValue(stats.get('music_file_count', 0))
        except Exception as e:
            InfoBar.error(
                title="加载统计失败", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
            )

        self._update_usage_chart()
        self._load_users()

    # ---------- 使用量图表 ----------
    def _update_usage_chart(self):
        """根据日期筛选更新使用量图表（柱状图 + 饼图）"""
        if not QT_CHART_AVAILABLE:
            return
        try:
            start = self.startDateEdit.text().strip()
            end = self.endDateEdit.text().strip()
            usage = get_usage_stats(start, end)

            # 模块中文名映射
            module_names = {'music': '音乐', 'video': '视频', 'people': '人物',
                            'home': '首页', 'jmcomic': 'JMComic', 'downloads': '总下载'}
            action_names = {'search': '搜索', 'play': '播放', 'download': '下载',
                            'parse': '解析', 'visit': '访问', 'pack': '打包',
                            'subscribe': '订阅', 'login': '登录', 'browse': '浏览'}

            # ── 柱状图：各模块的行为统计 ──
            barChart = QChart()
            barChart.setTitle(f"模块使用量统计（{'全部时间' if not start and not end else start + ' ~ ' + end}）")
            barChart.setAnimationOptions(QChart.SeriesAnimations)

            barSeries = QBarSeries()
            # 收集所有模块和动作
            modules = ['music', 'video', 'home', 'people', 'jmcomic']
            # 动作分组：一个动作一组柱，每个模块一个 set
            for action in ('search', 'play', 'download', 'parse', 'visit', 'pack', 'subscribe'):
                barSet = QBarSet(action_names.get(action, action))
                total = 0
                for mod in modules:
                    val = usage.get(mod, {}).get(action, 0)
                    barSet.append(val)
                    total += val
                if total > 0:  # 跳过全 0
                    barSeries.append(barSet)

            barChart.addSeries(barSeries)

            axisX = QBarCategoryAxis()
            axisX.append([module_names.get(m, m) for m in modules])
            barChart.addAxis(axisX, Qt.AlignBottom)
            barSeries.attachAxis(axisX)
            axisY = QValueAxis()
            axisY.setLabelFormat("%d")
            barChart.addAxis(axisY, Qt.AlignLeft)
            barSeries.attachAxis(axisY)
            barChart.legend().setVisible(True)
            barChart.legend().setAlignment(Qt.AlignBottom)

            self.barChartView.setChart(barChart)

            # ── 饼图：视频子平台分布 ──
            pieChart = QChart()
            pieChart.setTitle("视频子平台使用量")
            pieChart.setAnimationOptions(QChart.SeriesAnimations)

            pieSeries = QPieSeries()
            video_sub = usage.get('video_sub', {})
            platform_names = {'douyin': '抖音', 'bilibili': '哔哩哔哩', 'twitter': '推特(X)',
                              'pixiv': 'Pixiv', 'xvideo': 'Xvideo', 'youtube': 'YouTube'}
            if video_sub:
                for plat, count in video_sub.items():
                    slice_ = QPieSlice(platform_names.get(plat, plat), count)
                    pieSeries.append(slice_)
            else:
                pieSeries.append("暂无数据", 1)
                pieSeries.slices()[0].setLabelVisible(False)

            pieChart.addSeries(pieSeries)
            pieChart.legend().setVisible(True)
            pieChart.legend().setAlignment(Qt.AlignRight)

            self.pieChartView.setChart(pieChart)
        except Exception as e:
            InfoBar.error(
                title="图表更新失败", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
            )

    def _load_users(self):
        """加载用户列表"""
        # 清空现有用户行（保留末尾 stretch）
        while self.usersLayout.count() > 1:
            item = self.usersLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            users = get_all_users()
        except Exception as e:
            InfoBar.error(
                title="加载用户失败", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
            )
            return

        self.userCountLabel.setText(f"共 {len(users)} 位用户")

        for user in users:
            row = UserRowCard(user, self.usersContainer)
            row.onBanToggled.connect(self._toggle_ban)
            row.onEditPermission.connect(self._edit_permission)
            row.onDeleteUser.connect(self._delete_user)
            # 插入到 stretch 之前
            self.usersLayout.insertWidget(self.usersLayout.count() - 1, row)

    # ---------- 封禁/解封 ----------
    def _toggle_ban(self, username: str, banned: bool):
        """封禁 / 解封用户"""
        # 防止封禁 admin 和当前管理员自己
        current_admin = getattr(self.window(), '_current_username', '')
        if username == 'admin':
            InfoBar.warning(
                title="操作被拒绝", content="不能封禁管理员账户",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=4000, parent=self
            )
            return
        if username == current_admin:
            InfoBar.warning(
                title="操作被拒绝", content="不能封禁当前登录的管理员账户",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=4000, parent=self
            )
            return

        success, msg = set_user_banned(username, banned)
        if success:
            InfoBar.success(
                title="操作成功", content=f"用户「{username}」{'已封禁' if banned else '已解封'}",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
            self._load_users()
        else:
            InfoBar.error(
                title="操作失败", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
            )

    # ---------- 删除用户 ----------
    def _delete_user(self, username: str):
        """删除用户"""
        # 防止删除 admin 和当前管理员自己（双保险）
        current_admin = getattr(self.window(), '_current_username', '')
        if username == 'admin':
            InfoBar.warning(
                title="操作被拒绝", content="不能删除管理员账户",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=4000, parent=self
            )
            return
        if username == current_admin:
            InfoBar.warning(
                title="操作被拒绝", content="不能删除当前登录的管理员账户",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=4000, parent=self
            )
            return

        success, msg = delete_user(username)
        if success:
            InfoBar.success(
                title="删除成功", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
            self.refresh()  # 刷新统计和用户列表
        else:
            InfoBar.error(
                title="删除失败", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
            )

    # ---------- 权限编辑 ----------
    def _edit_permission(self, username: str):
        """打开权限编辑对话框"""
        perms = get_user_permissions(username)
        PermissionDialog.get_permissions(username, perms, self)


# =======================  独立测试  =======================
if __name__ == '__main__':
    from PyQt5.QtWidgets import QApplication
    from qfluentwidgets import setTheme, Theme

    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    w = DashboardInterface()
    w.resize(1080, 780)
    w.show()
    sys.exit(app.exec_())