# coding:utf-8
"""
个人资料页面 - 从数据库加载用户信息，支持编辑所有字段
"""
import os
import sys
import json
from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont, QDesktopServices
from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QSpacerItem,
    QSizePolicy, QFrame, QFileDialog, QScrollArea, QWidget
)
from qfluentwidgets import (
    CardWidget, AvatarWidget, SubtitleLabel, BodyLabel,
    HyperlinkButton, IconWidget, FluentIcon as FIF,
    PrimaryPushButton, InfoBar, InfoBarPosition,
    LineEdit, PushButton, ToolButton, Dialog
)

import webbrowser

from core.database import get_user_profile, update_user_profile, update_user_password, update_username
from ui.widgets.theme import theme_color, text_primary, text_secondary

# ── 默认头像 ──
from core.resource_paths import ABOUT_DEFAULT_AVATAR as _DEFAULT_AVATAR
from ui.widgets.ui_utils import install_hover_tip


class EditableProfileCard(CardWidget):
    """可编辑的个人资料卡片"""

    logoutRequested = pyqtSignal()
    usernameChanged = pyqtSignal(str, str)   # (old_username, new_username)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._editing = False
        self._current_avatar_path = _DEFAULT_AVATAR
        self._profile_data = {}
        self._parent_interface = parent
        self._is_admin_user = False

        self.setFixedHeight(220)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)

        # ── 头像 ──
        self.avatar = AvatarWidget(_DEFAULT_AVATAR)
        self.avatar.setRadius(80)
        self.avatar.setFixedSize(160, 160)
        self.avatar.mousePressEvent = lambda e: self._change_avatar()
        self.avatar.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.avatar)

        # ── 信息区 ──
        infoLayout = QVBoxLayout()
        infoLayout.setSpacing(12)

        # 用户名（可编辑，admin 不可改）
        self.nameLabel = SubtitleLabel("未登录")
        self.nameLabel.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        infoLayout.addWidget(self.nameLabel)
        # 编辑用户名输入框（默认隐藏）
        self.nameEdit = LineEdit()
        self.nameEdit.setPlaceholderText("输入新用户名（至少2个字符）")
        self.nameEdit.setFixedWidth(260)
        self.nameEdit.setVisible(False)
        infoLayout.addWidget(self.nameEdit)

        # 角色
        self.roleLabel = BodyLabel("")
        self.roleLabel.setStyleSheet("color: " + text_secondary() + "; font-size: 14px;")
        infoLayout.addWidget(self.roleLabel)

        # 签名（可编辑）
        self.mottoLabel = BodyLabel("")
        self.mottoLabel.setStyleSheet("color: " + theme_color('#0078D4', '#4FC3F7') + "; font-style: italic; font-size: 13px;")
        infoLayout.addWidget(self.mottoLabel)
        # 编辑签名输入框（默认隐藏）
        self.mottoEdit = LineEdit()
        self.mottoEdit.setPlaceholderText("输入个性签名")
        self.mottoEdit.setFixedWidth(260)
        self.mottoEdit.setVisible(False)
        infoLayout.addWidget(self.mottoEdit)

        # 按钮行
        btnLayout = QHBoxLayout()
        btnLayout.setSpacing(12)
        self.editBtn = PrimaryPushButton(FIF.EDIT, "编辑资料")
        self.editBtn.clicked.connect(self._parent_interface.toggleEdit if parent else None)
        self.editBtn.setFixedWidth(150)
        self.editBtn.setFixedHeight(36)
        install_hover_tip(self.editBtn, "编辑资料", "进入编辑模式，可修改头像、用户名、签名、联系方式和资料信息")
        btnLayout.addWidget(self.editBtn)

        # 退出登录按钮（点击切换账号）
        self.logoutBtn = PushButton()
        self.logoutBtn.setText("退出登录")
        # self.logoutBtn.setIcon(FIF.POWER_BUTTON)
        self.logoutBtn.setIconSize(self.logoutBtn.sizeHint())
        self.logoutBtn.setStyleSheet("""
            QPushButton {
                
                background-color: #f44336;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
            """)
        self.logoutBtn.setFixedSize(130, 36)
        self.logoutBtn.clicked.connect(self._on_logout_clicked)
        install_hover_tip(self.logoutBtn, "退出登录", "退出当前账号并返回登录界面，可切换其他账号")
        btnLayout.addWidget(self.logoutBtn)

        btnLayout.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        infoLayout.addLayout(btnLayout)

        infoLayout.addItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))
        layout.addLayout(infoLayout)

        # 头像悬停提示
        install_hover_tip(self.avatar, "更换头像", "点击头像可更换为本地图片（支持 png/jpg/jpeg/bmp/gif）")
        install_hover_tip(self.nameEdit, "编辑用户名", "输入新用户名（至少2个字符），管理员账号不可修改")
        install_hover_tip(self.mottoEdit, "编辑签名", "输入你的个性签名")

    def _on_logout_clicked(self):
        """点击退出登录"""
        w = Dialog(
            '退出登录',
            '确定要退出当前账号吗？\n退出后将返回登录界面。',
            self.window()
        )
        w.yesButton.setText('退出登录')
        w.cancelButton.setText('取消')
        if w.exec():
            self.logoutRequested.emit()

    def _change_avatar(self):
        """点击头像更换"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择头像", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            self._current_avatar_path = file_path
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                self.avatar.setPixmap(
                    pixmap.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )

    def updateFromProfile(self, profile: dict):
        """从数据库资料更新显示"""
        self._profile_data = profile
        self._current_avatar_path = profile.get('avatar_path', '') or _DEFAULT_AVATAR
        self._is_admin_user = (profile.get('username') == 'admin')
        self._username = profile.get('username', '')

        # 头像
        avatar_path = self._current_avatar_path
        if avatar_path and os.path.exists(avatar_path):
            pixmap = QPixmap(avatar_path)
            if not pixmap.isNull():
                self.avatar.setPixmap(
                    pixmap.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )

        self.nameLabel.setText(profile.get('username', '未登录'))
        self.roleLabel.setText(profile.get('role', ''))
        self.mottoLabel.setText(profile.get('motto', ''))

    def enterEditMode(self):
        """进入编辑模式：显示用户名/签名输入框"""
        self._editing = True
        self.nameEdit.setText(self.nameLabel.text())
        self.mottoEdit.setText(self.mottoLabel.text())
        self.nameEdit.setVisible(True)
        self.mottoEdit.setVisible(True)
        # 管理员不可修改用户名
        self.nameEdit.setEnabled(not self._is_admin_user)
        self.nameEdit.setPlaceholderText(
            "管理员账号不可修改用户名" if self._is_admin_user else "输入新用户名（至少2个字符）")

    def leaveEditMode(self):
        """退出编辑模式：隐藏输入框，返回 (name_text, motto_text)"""
        name_val = self.nameEdit.text().strip() if self.nameEdit.isVisible() else self._username
        motto_val = self.mottoEdit.text().strip() if self.mottoEdit.isVisible() else self.mottoLabel.text()
        self.nameEdit.setVisible(False)
        self.mottoEdit.setVisible(False)
        self._editing = False
        return name_val, motto_val

    def cancelEdit(self):
        """取消编辑：隐藏输入框"""
        self.nameEdit.setVisible(False)
        self.mottoEdit.setVisible(False)
        self._editing = False

    def updateDisplayFromDB(self, name: str, motto: str):
        """从数据库刷新显示"""
        self.nameLabel.setText(name)
        self.mottoLabel.setText(motto)
        self._username = name


class InfoSection(CardWidget):
    """信息区域（支持编辑）"""

    def __init__(self, title, items, parent=None):
        super().__init__(parent)
        self._editing = False
        self._parent_interface = parent
        self._items = items  # 保存原始数据用于编辑

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)

        # 标题
        self.titleLabel = SubtitleLabel(title)
        self.titleLabel.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        layout.addWidget(self.titleLabel)

        # 内容区
        self.contentWidget = QWidget()
        self.contentLayout = QVBoxLayout(self.contentWidget)
        self.contentLayout.setSpacing(6)
        self.contentLayout.setContentsMargins(0, 0, 0, 0)

        self._item_widgets = []  # 存储 (label_widget, value_widget)
        self._buildDisplay(items)

        layout.addWidget(self.contentWidget)

    def _clearLayout(self):
        """清空布局中所有 item"""
        while self.contentLayout.count():
            item = self.contentLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            if item.layout():
                # 递归清空子布局
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

    def _buildDisplay(self, items):
        """构建显示模式"""
        self._clearLayout()
        self._item_widgets.clear()

        from ui.widgets.theme import text_primary, text_secondary
        for label, value in items:
            row = QHBoxLayout()
            labelW = BodyLabel(label)
            labelW.setFixedWidth(120)
            labelW.setStyleSheet("font-weight: bold; color: " + text_primary() + ";")
            valueW = BodyLabel(value)
            valueW.setStyleSheet("color: " + text_secondary() + ";")
            row.addWidget(labelW)
            row.addWidget(valueW)
            row.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
            self.contentLayout.addLayout(row)
            self._item_widgets.append((labelW, valueW))

    def enterEditMode(self):
        """进入编辑模式 — 重建为 LineEdit"""
        self._editing = True
        self._edit_widgets = []

        # 收集当前值
        current_values = []
        for label, current_val in self._items:
            current_values.append(current_val)

        # 完全重建：用 LineEdit 替代 BodyLabel
        self._clearLayout()
        self._item_widgets.clear()

        from ui.widgets.theme import text_primary
        for idx, (label, _) in enumerate(self._items):
            val = current_values[idx] if idx < len(current_values) else ""
            row = QHBoxLayout()
            labelW = BodyLabel(label)
            labelW.setFixedWidth(120)
            labelW.setStyleSheet("font-weight: bold; color: " + text_primary() + ";")
            edit = LineEdit()
            edit.setText(val)
            edit.setFixedWidth(280)
            row.addWidget(labelW)
            row.addWidget(edit)
            row.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
            self.contentLayout.addLayout(row)
            self._edit_widgets.append(edit)

    def leaveEditMode(self):
        """退出编辑模式，收集数据"""
        # 从当前 LineEdit 获取值（如果有），否则从显示标签取
        if self._edit_widgets and len(self._edit_widgets) > 0:
            values = [edit.text() for edit in self._edit_widgets]
        else:
            # 兼容情况：从当前显示的 BodyLabel 取值
            values = []
            for i in range(self.contentLayout.count()):
                item = self.contentLayout.itemAt(i)
                if item and item.layout() and item.layout().count() >= 2:
                    w = item.layout().itemAt(1).widget()
                    if isinstance(w, BodyLabel):
                        values.append(w.text())

        # 重建显示
        new_items = []
        for idx, (label, _) in enumerate(self._items):
            val = values[idx] if idx < len(values) else ""
            new_items.append((label, val))

        self._buildDisplay(new_items)
        self._editing = False
        self._edit_widgets = []  # 清理引用
        return new_items

    def cancelEdit(self):
        """取消编辑，恢复原始"""
        self._buildDisplay(self._items)
        self._editing = False

    def setItems(self, items):
        self._items = items
        self._buildDisplay(items)


class ContactSection(CardWidget):
    """联系方式卡片（支持编辑）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._editing = False
        self._parent_interface = parent
        self._github_url = ""
        self._email_addr = ""
        self._qq_number = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)

        self.titleLabel = SubtitleLabel("📞 联系方式")
        self.titleLabel.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        layout.addWidget(self.titleLabel)

        # 按钮行
        self.buttonsLayout = QHBoxLayout()
        self.githubBtn = PrimaryPushButton(FIF.GITHUB, "GitHub")
        self.githubBtn.clicked.connect(self._openGithub)
        self.githubBtn.setFixedSize(120, 40)
        install_hover_tip(self.githubBtn, "GitHub", "跳转到你设置的 GitHub 主页")
        self.emailBtn = PrimaryPushButton(FIF.MAIL, "Email")
        self.emailBtn.clicked.connect(self._openEmail)
        self.emailBtn.setFixedSize(120, 40)
        install_hover_tip(self.emailBtn, "Email", "打开邮件客户端发送邮件到你的邮箱")
        self.qqBtn = PrimaryPushButton(FIF.PEOPLE, "QQ")
        self.qqBtn.clicked.connect(self._showQQ)
        self.qqBtn.setFixedSize(120, 40)
        install_hover_tip(self.qqBtn, "QQ", "查看你的 QQ 号码")

        self.buttonsLayout.addWidget(self.githubBtn)
        self.buttonsLayout.addWidget(self.emailBtn)
        self.buttonsLayout.addWidget(self.qqBtn)
        self.buttonsLayout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addLayout(self.buttonsLayout)

        # 编辑状态下的输入框
        self.editWidget = QWidget()
        self.editLayout = QVBoxLayout(self.editWidget)
        self.editLayout.setSpacing(6)
        self.editLayout.setContentsMargins(0, 0, 0, 0)
        self.editWidget.setVisible(False)
        layout.addWidget(self.editWidget)

        self._github_edit = None
        self._email_edit = None
        self._qq_edit = None

    def setData(self, github, email, qq):
        self._github_url = github
        self._email_addr = email
        self._qq_number = qq

    def enterEditMode(self):
        """进入编辑模式"""
        # 清空并重建编辑输入框
        while self.editLayout.count():
            item = self.editLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rows = [
            ("GitHub链接", self._github_url),
            ("邮箱", self._email_addr),
            ("QQ号", self._qq_number),
        ]
        edits = []
        for label, val in rows:
            row = QHBoxLayout()
            lbl = BodyLabel(label)
            lbl.setFixedWidth(100)
            # 注意：LineEdit(parent) — 不传 text 参数，之后 setText
            edit = LineEdit()
            edit.setText(val)
            edit.setClearButtonEnabled(True)
            edit.setFixedWidth(250)
            row.addWidget(lbl)
            row.addWidget(edit)
            row.addStretch()
            self.editLayout.addLayout(row)
            edits.append(edit)

        self._github_edit, self._email_edit, self._qq_edit = edits
        self.editWidget.setVisible(True)
        self.githubBtn.setEnabled(False)
        self.emailBtn.setEnabled(False)
        self.qqBtn.setEnabled(False)
        self._editing = True

    def leaveEditMode(self):
        """退出编辑模式"""
        if self._github_edit:
            self._github_url = self._github_edit.text().strip()
        if self._email_edit:
            self._email_addr = self._email_edit.text().strip()
        if self._qq_edit:
            self._qq_number = self._qq_edit.text().strip()
        self.editWidget.setVisible(False)
        self.githubBtn.setEnabled(True)
        self.emailBtn.setEnabled(True)
        self.qqBtn.setEnabled(True)
        self._editing = False

    def cancelEdit(self):
        """取消编辑"""
        self.editWidget.setVisible(False)
        self.githubBtn.setEnabled(True)
        self.emailBtn.setEnabled(True)
        self.qqBtn.setEnabled(True)
        self._editing = False

    def getData(self):
        return self._github_url, self._email_addr, self._qq_number

    def _openGithub(self):
        if self._github_url:
            webbrowser.open(self._github_url)
        else:
            InfoBar.info(
                title="提示", content="未设置GitHub链接",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=3000, parent=self
            )

    def _openEmail(self):
        if self._email_addr:
            webbrowser.open(f"mailto:{self._email_addr}")
        else:
            InfoBar.info(
                title="提示", content="未设置邮箱",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=3000, parent=self
            )

    def _showQQ(self):
        if self._qq_number:
            InfoBar.info(
                title="QQ联系方式", content=f"QQ号：{self._qq_number}",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
            )
        else:
            InfoBar.info(
                title="提示", content="未设置QQ号",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=3000, parent=self
            )


class AboutMeInterface(QFrame):
    """个人资料界面（查看/编辑）"""

    logoutRequested = pyqtSignal()
    usernameChanged = pyqtSignal(str)   # 新用户名

    def __init__(self):
        super().__init__()
        self.setObjectName("AboutMeInterface")
        self._current_username = None
        self._profile_data = {}
        self._editing = False

        self.initUI()

    def initUI(self):
        # 主布局（用 ScrollArea 包裹）
        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollArea.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.scrollContent = QWidget()
        self.mainLayout = QVBoxLayout(self.scrollContent)
        self.mainLayout.setSpacing(30)
        self.mainLayout.setContentsMargins(40, 40, 40, 40)

        from ui.widgets.theme import card_bg, card_border, on_theme_changed, ensure_theme_connected
        self._apply_card_theme()
        ensure_theme_connected()
        on_theme_changed(self._apply_card_theme)

        # ── 个人资料卡片 ──
        self.profileCard = EditableProfileCard(self)
        # 转发退出登录信号（卡片 → 界面 → 主窗口）
        self.profileCard.logoutRequested.connect(self.logoutRequested)
        self.mainLayout.addWidget(self.profileCard)

        # ── 信息卡片 ──
        default_items = [
            ("🎓 专业", "未设置"),
            ("💻 主要语言", "未设置"),
            ("🔧 开发工具", "未设置"),
            ("🔒 兴趣爱好", "未设置"),
            ("📚 学习方向", "未设置"),
        ]
        self.infoSection = InfoSection("📊 关于我", default_items, self)
        self.mainLayout.addWidget(self.infoSection)

        # ── 联系方式 ──
        self.contactSection = ContactSection(self)
        self.mainLayout.addWidget(self.contactSection)

        # ── 编辑/保存按钮 ──
        self.actionLayout = QHBoxLayout()
        self.saveBtn = PrimaryPushButton(FIF.SAVE, "保存修改")
        self.saveBtn.clicked.connect(self._saveProfile)
        self.saveBtn.setFixedWidth(150)
        self.saveBtn.setVisible(False)
        install_hover_tip(self.saveBtn, "保存修改", "保存对个人资料所做的所有修改")

        self.cancelBtn = PushButton("取消")
        self.cancelBtn.clicked.connect(self._cancelEdit)
        self.cancelBtn.setFixedWidth(100)
        self.cancelBtn.setVisible(False)
        install_hover_tip(self.cancelBtn, "取消", "取消编辑并恢复原始资料")

        self.changePwdBtn = PushButton("修改密码")
        self.changePwdBtn.clicked.connect(self._changePassword)
        self.changePwdBtn.setFixedWidth(120)
        self.changePwdBtn.setVisible(False)
        install_hover_tip(self.changePwdBtn, "修改密码", "修改当前账号的登录密码（需输入旧密码验证）")

        self.actionLayout.addWidget(self.saveBtn)
        self.actionLayout.addWidget(self.cancelBtn)
        self.actionLayout.addWidget(self.changePwdBtn)
        self.actionLayout.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.mainLayout.addLayout(self.actionLayout)

        # 弹性空间
        self.mainLayout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.scrollArea.setWidget(self.scrollContent)

        # 外部布局
        outerLayout = QVBoxLayout(self)
        outerLayout.setContentsMargins(0, 0, 0, 0)
        outerLayout.addWidget(self.scrollArea)

    def _apply_card_theme(self):
        """主题切换时重新应用卡片背景色"""
        from ui.widgets.theme import card_bg, card_border
        self.scrollContent.setStyleSheet(f"""
            QWidget {{
                background-color: transparent;
            }}
            CardWidget {{
                border-radius: 10px;
                background-color: {card_bg()};
                border: 1px solid {card_border()};
            }}
        """)

    # ═══════════════════════════════════════════════════
    #  公共方法 - 由 Window.setCurrentUser 调用
    # ═══════════════════════════════════════════════════

    def loadUserProfile(self, username: str):
        """加载指定用户的资料"""
        self._current_username = username
        profile = get_user_profile(username)
        if not profile:
            InfoBar.warning(
                title="提示", content="未找到用户资料",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=3000, parent=self
            )
            return

        self._profile_data = profile
        self.profileCard.updateFromProfile(profile)

        # 更新信息卡片
        info_items = profile.get('info_items', [])
        if not info_items:
            info_items = [
                ("🎓 专业", "未设置"),
                ("💻 主要语言", "未设置"),
                ("🔧 开发工具", "未设置"),
                ("🔒 兴趣爱好", "未设置"),
                ("📚 学习方向", "未设置"),
            ]
        self.infoSection.setItems(info_items)

        # 更新联系方式
        self.contactSection.setData(
            profile.get('github', ''),
            profile.get('email', ''),
            profile.get('qq', ''),
        )

    # ═══════════════════════════════════════════════════
    #  编辑控制
    # ═══════════════════════════════════════════════════

    def toggleEdit(self):
        """切换编辑/查看模式"""
        if not self._current_username:
            InfoBar.warning(
                title="提示", content="请先登录",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=3000, parent=self
            )
            return

        if not self._editing:
            # 进入编辑模式：备份当前所有数据，防止中途数据丢失
            self._backup = {
                'info_items': list(self.infoSection._items),  # 深拷贝
                'role': self.profileCard.roleLabel.text(),
                'motto': self.profileCard.mottoLabel.text(),
                'avatar': self.profileCard._current_avatar_path,
                'username': self.profileCard.nameLabel.text(),
            }
            self._editing = True
            self.profileCard.editBtn.setText("编辑中...")
            self.profileCard.enterEditMode()
            self.infoSection.enterEditMode()
            self.contactSection.enterEditMode()
            self.saveBtn.setVisible(True)
            self.cancelBtn.setVisible(True)
            self.changePwdBtn.setVisible(True)
        else:
            # 已经在编辑模式，忽略
            pass

    def _get_current_edit_data(self):
        """安全获取当前编辑数据（优先 LineEdit，后备用备份）"""
        # 1. 尝试从 LineEdit 获取
        if self.infoSection._edit_widgets and len(self.infoSection._edit_widgets) > 0:
            values = [edit.text() for edit in self.infoSection._edit_widgets]
            new_items = []
            for idx, (label, _) in enumerate(self.infoSection._items):
                val = values[idx] if idx < len(values) else ""
                new_items.append((label, val))
            if new_items and any(item[1] != '' for item in new_items):
                return new_items

        # 2. 尝试从显示标签获取
        saved_items = []
        for i in range(self.infoSection.contentLayout.count()):
            item = self.infoSection.contentLayout.itemAt(i)
            if item and item.layout() and item.layout().count() >= 2:
                w = item.layout().itemAt(1).widget()
                if isinstance(w, BodyLabel):
                    label_w = item.layout().itemAt(0).widget()
                    saved_items.append((label_w.text(), w.text()))
        if saved_items and any(item[1] != '' for item in saved_items):
            return saved_items

        # 3. 最后用备份
        if hasattr(self, '_backup') and self._backup.get('info_items'):
            return list(self._backup['info_items'])

        return []

    def _saveProfile(self):
        """保存资料到数据库"""
        if not self._current_username:
            return

        # ★ 第1步：在修改任何布局前，先收集所有数据 ★
        # 从信息卡片收集（尝试从 LineEdit，否则从标签，最后备用）
        raw_items = self._get_current_edit_data()
        # 从联系方式收集
        # 读取联系方式的当前输入（如果在编辑模式）
        contact_github = self.contactSection._github_url
        contact_email = self.contactSection._email_addr
        contact_qq = self.contactSection._qq_number
        if self.contactSection._editing and self.contactSection._github_edit:
            contact_github = self.contactSection._github_edit.text().strip()
            contact_email = self.contactSection._email_edit.text().strip()
            contact_qq = self.contactSection._qq_edit.text().strip()

        # 头像路径
        avatar_path = self.profileCard._current_avatar_path
        role_text = self.profileCard.roleLabel.text()
        # 从用户名/签名编辑框收集（编辑模式下）
        name_text = self.profileCard.nameEdit.text().strip() if self.profileCard._editing else self._current_username
        motto_text = self.profileCard.mottoEdit.text().strip() if self.profileCard._editing else self.profileCard.mottoLabel.text()

        old_username = self._current_username

        # ★ 第2步：现在安全地退出编辑模式 ★
        self.infoSection.leaveEditMode()
        # 用收集到的数据覆盖可能被 leaveEditMode 清空的数据
        if raw_items:
            self.infoSection._items = list(raw_items)
            self.infoSection._buildDisplay(raw_items)

        self.contactSection.leaveEditMode()
        self.profileCard.leaveEditMode()

        # ★ 第3步：更新用户名（非 admin 且用户名有变化）★
        username_updated = False
        if old_username != 'admin' and name_text and name_text != old_username:
            s_user, m_user = update_username(old_username, name_text)
            if s_user:
                username_updated = True
                self._current_username = name_text
                old_username = name_text
                # 通知主窗口更新用户状态
                self.usernameChanged.emit(name_text)
            else:
                InfoBar.error(
                    title="用户名修改失败", content=m_user,
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
                )

        # ★ 第4步：更新资料（签名等）★
        final_items = raw_items if raw_items else self.infoSection._items
        profile_update = {
            'avatar_path': avatar_path,
            'role': role_text,
            'motto': motto_text,
            'github': contact_github,
            'email': contact_email,
            'qq': contact_qq,
            'info_items': final_items,
        }

        success, msg = update_user_profile(old_username, profile_update)
        if success:
            InfoBar.success(
                title="成功", content="资料已保存",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
            # 重新读取资料，同步数据库返回的「持久化后」头像路径
            try:
                new_profile = get_user_profile(self._current_username)
                if new_profile and new_profile.get('avatar_path'):
                    self.profileCard._current_avatar_path = new_profile['avatar_path']
            except Exception:
                pass
        else:
            InfoBar.error(
                title="错误", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
            )

        # 刷新头像/名称/签名显示
        self.profileCard.updateDisplayFromDB(self._current_username, motto_text)

        # 退出编辑模式
        self._editing = False
        self.profileCard.editBtn.setText("编辑资料")
        self.saveBtn.setVisible(False)
        self.cancelBtn.setVisible(False)
        self.changePwdBtn.setVisible(False)

    def _cancelEdit(self):
        """取消编辑"""
        self.infoSection.cancelEdit()
        self.contactSection.cancelEdit()
        self.profileCard.cancelEdit()
        self._editing = False
        self.profileCard.editBtn.setText("编辑资料")
        self.saveBtn.setVisible(False)
        self.cancelBtn.setVisible(False)
        self.changePwdBtn.setVisible(False)
        # 重新加载原始数据
        if self._current_username:
            self.loadUserProfile(self._current_username)

    def _changePassword(self):
        """修改密码"""
        if not self._current_username:
            return

        from qfluentwidgets import Dialog
        # 简单对话框输入
        dialog = Dialog("修改密码", "请输入旧密码和新密码（重启后生效）", self)
        dialog.yesButton.setText("确定")
        dialog.cancelButton.setText("取消")

        # 创建输入框
        inputWidget = QWidget()
        inputLayout = QVBoxLayout(inputWidget)
        oldPwdEdit = LineEdit()
        oldPwdEdit.setEchoMode(LineEdit.Password)
        oldPwdEdit.setPlaceholderText("旧密码")
        newPwdEdit = LineEdit()
        newPwdEdit.setEchoMode(LineEdit.Password)
        newPwdEdit.setPlaceholderText("新密码（至少6位）")
        newPwdEdit2 = LineEdit()
        newPwdEdit2.setEchoMode(LineEdit.Password)
        newPwdEdit2.setPlaceholderText("确认新密码")
        inputLayout.addWidget(QLabel("旧密码:"))
        inputLayout.addWidget(oldPwdEdit)
        inputLayout.addWidget(QLabel("新密码:"))
        inputLayout.addWidget(newPwdEdit)
        inputLayout.addWidget(QLabel("确认新密码:"))
        inputLayout.addWidget(newPwdEdit2)
        dialog.yesButton.clicked.disconnect()

        def do_change():
            old_pwd = oldPwdEdit.text()
            new_pwd = newPwdEdit.text()
            new_pwd2 = newPwdEdit2.text()

            if not old_pwd or not new_pwd:
                InfoBar.error(title="错误", content="请填写所有密码字段",
                             orient=Qt.Horizontal, isClosable=True,
                             position=InfoBarPosition.BOTTOM_RIGHT, duration=3000, parent=self)
                return
            if new_pwd != new_pwd2:
                InfoBar.error(title="错误", content="两次新密码不一致",
                             orient=Qt.Horizontal, isClosable=True,
                             position=InfoBarPosition.BOTTOM_RIGHT, duration=3000, parent=self)
                return
            success, msg = update_user_password(self._current_username, old_pwd, new_pwd)
            if success:
                InfoBar.success(title="成功", content="密码已修改，重启后生效",
                               orient=Qt.Horizontal, isClosable=True,
                               position=InfoBarPosition.TOP, duration=3000, parent=self)
                dialog.accept()
            else:
                InfoBar.error(title="错误", content=msg,
                             orient=Qt.Horizontal, isClosable=True,
                             position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self)

        dialog.yesButton.clicked.connect(do_change)

        # 将输入控件放到对话框
        layout = dialog.layout()
        if layout:
            layout.insertWidget(1, inputWidget)

        dialog.exec_()