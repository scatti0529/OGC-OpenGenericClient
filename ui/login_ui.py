# -*- coding: utf-8 -*-
# Form implementation generated from reading ui file '...'
# Modified manually to add registration profile fields

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QScrollArea, QWidget, QVBoxLayout
from qfluentwidgets import BodyLabel, CheckBox, HyperlinkButton, LineEdit, PrimaryPushButton, PushButton
from core.resource_paths import LOGIN_BACKGROUND, LOGIN_LOGO, LOGIN_USER_ICON3


class Ui_Form(object):
    def setupUi(self, Form):
        Form.setObjectName("Form")
        Form.resize(1250, 809)
        Form.setMinimumSize(QtCore.QSize(700, 500))
        self.horizontalLayout = QtWidgets.QHBoxLayout(Form)
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.horizontalLayout.setSpacing(0)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.label = QtWidgets.QLabel(Form)
        self.label.setText("")
        self.label.setPixmap(QtGui.QPixmap(LOGIN_BACKGROUND))
        self.label.setScaledContents(True)
        self.label.setObjectName("label")
        self.horizontalLayout.addWidget(self.label)
        self.widget = QtWidgets.QWidget(Form)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.widget.sizePolicy().hasHeightForWidth())
        self.widget.setSizePolicy(sizePolicy)
        self.widget.setMinimumSize(QtCore.QSize(380, 0))
        self.widget.setMaximumSize(QtCore.QSize(400, 16777215))
        self.widget.setStyleSheet("QLabel{\n"
"    font: 13px \'Microsoft YaHei\'\n"
"}")
        self.widget.setObjectName("widget")
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(self.widget)
        self.verticalLayout_2.setContentsMargins(20, 20, 20, 20)
        self.verticalLayout_2.setSpacing(9)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        spacerItem = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout_2.addItem(spacerItem)
        self.label_2 = QtWidgets.QLabel(self.widget)
        self.label_2.setEnabled(True)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_2.sizePolicy().hasHeightForWidth())
        self.label_2.setSizePolicy(sizePolicy)
        self.label_2.setMinimumSize(QtCore.QSize(100, 100))
        self.label_2.setMaximumSize(QtCore.QSize(100, 100))
        self.label_2.setText("")
        self.label_2.setPixmap(QtGui.QPixmap(LOGIN_LOGO))
        self.label_2.setScaledContents(True)
        self.label_2.setObjectName("label_2")
        self.verticalLayout_2.addWidget(self.label_2, 0, QtCore.Qt.AlignHCenter)
        spacerItem1 = QtWidgets.QSpacerItem(20, 15, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.verticalLayout_2.addItem(spacerItem1)

        # ===================== 登录区域 =====================
        self.login_group = QtWidgets.QWidget(self.widget)
        self.login_group.setObjectName("login_group")
        self.login_layout = QtWidgets.QVBoxLayout(self.login_group)
        self.login_layout.setContentsMargins(0, 0, 0, 0)
        self.login_layout.setSpacing(9)
        self.login_layout.setObjectName("login_layout")

        self.gridLayout = QtWidgets.QGridLayout()
        self.gridLayout.setHorizontalSpacing(4)
        self.gridLayout.setVerticalSpacing(9)
        self.gridLayout.setObjectName("gridLayout")
        self.gridLayout.setColumnStretch(0, 2)
        self.gridLayout.setColumnStretch(1, 1)
        self.login_layout.addLayout(self.gridLayout)

        self.label_5 = BodyLabel(self.login_group)
        self.label_5.setObjectName("label_5")
        self.login_layout.addWidget(self.label_5)
        self.lineEdit_3 = LineEdit(self.login_group)
        self.lineEdit_3.setClearButtonEnabled(True)
        self.lineEdit_3.setObjectName("lineEdit_3")
        self.login_layout.addWidget(self.lineEdit_3)
        self.label_6 = BodyLabel(self.login_group)
        self.label_6.setObjectName("label_6")
        self.login_layout.addWidget(self.label_6)
        self.lineEdit_4 = LineEdit(self.login_group)
        self.lineEdit_4.setEchoMode(QtWidgets.QLineEdit.Password)
        self.lineEdit_4.setClearButtonEnabled(True)
        self.lineEdit_4.setObjectName("lineEdit_4")
        self.login_layout.addWidget(self.lineEdit_4)

        # 登录头像预览
        self.login_avatar_label = QtWidgets.QLabel(self.login_group)
        self.login_avatar_label.setFixedSize(60, 60)
        self.login_avatar_label.setAlignment(Qt.AlignCenter)
        self.login_avatar_label.setStyleSheet("border-radius: 30px; background-color: rgba(0,0,0,0.05);")
        self.login_avatar_label.setVisible(False)
        self.login_layout.addWidget(self.login_avatar_label, 0, Qt.AlignCenter)

        spacerItem2 = QtWidgets.QSpacerItem(20, 5, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.login_layout.addItem(spacerItem2)
        self.checkBox = CheckBox(self.login_group)
        self.checkBox.setChecked(True)
        self.checkBox.setObjectName("checkBox")
        self.login_layout.addWidget(self.checkBox)
        spacerItem3 = QtWidgets.QSpacerItem(20, 5, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.login_layout.addItem(spacerItem3)
        self.pushButton = PrimaryPushButton(self.login_group)
        self.pushButton.setObjectName("pushButton")
        self.login_layout.addWidget(self.pushButton)
        spacerItem4 = QtWidgets.QSpacerItem(20, 6, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.login_layout.addItem(spacerItem4)
        self.pushButton_2 = HyperlinkButton(self.login_group)
        self.pushButton_2.setObjectName("pushButton_2")
        self.login_layout.addWidget(self.pushButton_2)

        self.verticalLayout_2.addWidget(self.login_group)

        # ===================== 注册区域（默认隐藏） =====================
        self.register_group = QtWidgets.QWidget(self.widget)
        self.register_group.setObjectName("register_group")
        self.register_group.hide()
        self.register_layout = QtWidgets.QVBoxLayout(self.register_group)
        self.register_layout.setContentsMargins(0, 0, 0, 0)
        self.register_layout.setSpacing(6)
        self.register_layout.setObjectName("register_layout")

        # 标题
        self.register_title = BodyLabel(self.register_group)
        self.register_title.setObjectName("register_title")
        self.register_title.setAlignment(QtCore.Qt.AlignCenter)
        font = QtGui.QFont()
        font.setPointSize(16)
        font.setBold(True)
        self.register_title.setFont(font)
        self.register_layout.addWidget(self.register_title)

        # 注册表单用 ScrollArea 包裹（字段较多）
        self.register_scroll = QScrollArea(self.register_group)
        self.register_scroll.setWidgetResizable(True)
        self.register_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.register_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.register_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.register_scroll.setMaximumHeight(480)

        self.register_form_widget = QWidget()
        self.register_form_widget.setStyleSheet("""
            QWidget { background-color: transparent; }
            QLineEdit { 
                color: #000000; 
                background-color: #ffffff; 
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
        self.register_form_layout = QVBoxLayout(self.register_form_widget)
        self.register_form_layout.setSpacing(5)
        self.register_form_layout.setContentsMargins(0, 0, 0, 0)

        # --- 头像选择 ---
        self.reg_avatar_label = QtWidgets.QLabel()
        self.reg_avatar_label.setFixedSize(80, 80)
        self.reg_avatar_label.setAlignment(Qt.AlignCenter)
        default_pixmap = QtGui.QPixmap(LOGIN_USER_ICON3)
        if not default_pixmap.isNull():
            self.reg_avatar_label.setPixmap(
                default_pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.reg_avatar_label.setStyleSheet("border-radius: 40px; border: 2px solid #aaa;")
        self.register_form_layout.addWidget(self.reg_avatar_label, 0, Qt.AlignCenter)

        self.reg_avatar_btn = PushButton("选择头像（必选）")
        self.reg_avatar_btn.setFixedWidth(200)
        self.register_form_layout.addWidget(self.reg_avatar_btn, 0, Qt.AlignCenter)
        self._reg_avatar_path = ""

        spacer_av = QtWidgets.QSpacerItem(20, 5, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.register_form_layout.addItem(spacer_av)

        # --- 用户名 ---
        self.label_reg_user = BodyLabel("用户名 *")
        self.label_reg_user.setObjectName("label_reg_user")
        self.register_form_layout.addWidget(self.label_reg_user)
        self.lineEdit_reg_user = LineEdit(self.register_form_widget)
        self.lineEdit_reg_user.setClearButtonEnabled(True)
        self.lineEdit_reg_user.setObjectName("lineEdit_reg_user")
        self.lineEdit_reg_user.setPlaceholderText("请输入用户名（至少2个字符）")
        self.register_form_layout.addWidget(self.lineEdit_reg_user)

        # --- 密码 ---
        self.label_reg_pwd = BodyLabel("密码 *")
        self.label_reg_pwd.setObjectName("label_reg_pwd")
        self.register_form_layout.addWidget(self.label_reg_pwd)
        self.lineEdit_reg_pwd = LineEdit(self.register_form_widget)
        self.lineEdit_reg_pwd.setEchoMode(QtWidgets.QLineEdit.Password)
        self.lineEdit_reg_pwd.setClearButtonEnabled(True)
        self.lineEdit_reg_pwd.setObjectName("lineEdit_reg_pwd")
        self.lineEdit_reg_pwd.setPlaceholderText("请输入密码（至少6位）")
        self.register_form_layout.addWidget(self.lineEdit_reg_pwd)

        # --- 确认密码 ---
        self.label_reg_pwd2 = BodyLabel("确认密码 *")
        self.label_reg_pwd2.setObjectName("label_reg_pwd2")
        self.register_form_layout.addWidget(self.label_reg_pwd2)
        self.lineEdit_reg_pwd2 = LineEdit(self.register_form_widget)
        self.lineEdit_reg_pwd2.setEchoMode(QtWidgets.QLineEdit.Password)
        self.lineEdit_reg_pwd2.setClearButtonEnabled(True)
        self.lineEdit_reg_pwd2.setObjectName("lineEdit_reg_pwd2")
        self.lineEdit_reg_pwd2.setPlaceholderText("请再次输入密码")
        self.register_form_layout.addWidget(self.lineEdit_reg_pwd2)

        spacer_ps = QtWidgets.QSpacerItem(20, 4, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.register_form_layout.addItem(spacer_ps)

        # --- 角色（可选） ---
        self.label_reg_role = BodyLabel("角色（可选）")
        self.register_form_layout.addWidget(self.label_reg_role)
        self.lineEdit_reg_role = LineEdit(self.register_form_widget)
        self.lineEdit_reg_role.setClearButtonEnabled(True)
        self.lineEdit_reg_role.setPlaceholderText("例如：🛡️ 信息安全专业 | 网络安全爱好者")
        self.register_form_layout.addWidget(self.lineEdit_reg_role)

        # --- 签名（可选） ---
        self.label_reg_motto = BodyLabel("签名（可选）")
        self.register_form_layout.addWidget(self.label_reg_motto)
        self.lineEdit_reg_motto = LineEdit(self.register_form_widget)
        self.lineEdit_reg_motto.setClearButtonEnabled(True)
        self.lineEdit_reg_motto.setPlaceholderText("例如：✨\"无法触及，因而耀眼\"✨")
        self.register_form_layout.addWidget(self.lineEdit_reg_motto)

        # --- GitHub（可选） ---
        self.label_reg_github = BodyLabel("GitHub主页链接（可选）")
        self.register_form_layout.addWidget(self.label_reg_github)
        self.lineEdit_reg_github = LineEdit(self.register_form_widget)
        self.lineEdit_reg_github.setClearButtonEnabled(True)
        self.lineEdit_reg_github.setPlaceholderText("https://github.com/yourname")
        self.register_form_layout.addWidget(self.lineEdit_reg_github)

        # --- 邮箱（可选） ---
        self.label_reg_email = BodyLabel("邮箱（可选）")
        self.register_form_layout.addWidget(self.label_reg_email)
        self.lineEdit_reg_email = LineEdit(self.register_form_widget)
        self.lineEdit_reg_email.setClearButtonEnabled(True)
        self.lineEdit_reg_email.setPlaceholderText("example@qq.com")
        self.register_form_layout.addWidget(self.lineEdit_reg_email)

        # --- QQ（可选） ---
        self.label_reg_qq = BodyLabel("QQ号（可选）")
        self.register_form_layout.addWidget(self.label_reg_qq)
        self.lineEdit_reg_qq = LineEdit(self.register_form_widget)
        self.lineEdit_reg_qq.setClearButtonEnabled(True)
        self.lineEdit_reg_qq.setPlaceholderText("QQ号")
        self.register_form_layout.addWidget(self.lineEdit_reg_qq)

        self.register_scroll.setWidget(self.register_form_widget)
        self.register_layout.addWidget(self.register_scroll)

        # --- 注册按钮 ---
        spacerItem_reg2 = QtWidgets.QSpacerItem(20, 4, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.register_layout.addItem(spacerItem_reg2)
        self.register_btn = PrimaryPushButton(self.register_group)
        self.register_btn.setObjectName("register_btn")
        self.register_layout.addWidget(self.register_btn)

        spacerItem_reg3 = QtWidgets.QSpacerItem(20, 6, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.register_layout.addItem(spacerItem_reg3)

        self.back_to_login_btn = HyperlinkButton(self.register_group)
        self.back_to_login_btn.setObjectName("back_to_login_btn")
        self.register_layout.addWidget(self.back_to_login_btn)

        self.verticalLayout_2.addWidget(self.register_group)

        spacerItem5 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout_2.addItem(spacerItem5)
        self.horizontalLayout.addWidget(self.widget)

        self.retranslateUi(Form)
        QtCore.QMetaObject.connectSlotsByName(Form)

    def retranslateUi(self, Form):
        _translate = QtCore.QCoreApplication.translate
        Form.setWindowTitle(_translate("Form", "Form"))

        # 登录区域
        self.label_5.setText(_translate("Form", "用户名"))
        self.lineEdit_3.setPlaceholderText(_translate("Form", "请输入用户名"))
        self.label_6.setText(_translate("Form", "密码"))
        self.lineEdit_4.setPlaceholderText(_translate("Form", "••••••••••••"))
        self.checkBox.setText(_translate("Form", "记住密码"))
        self.pushButton.setText(_translate("Form", "登录"))
        self.pushButton_2.setText(_translate("Form", "注册账号"))

        # 注册区域
        self.register_title.setText(_translate("Form", "注册新账号"))
        self.label_reg_user.setText(_translate("Form", "用户名 *"))
        self.lineEdit_reg_user.setPlaceholderText(_translate("Form", "请输入用户名（至少2个字符）"))
        self.label_reg_pwd.setText(_translate("Form", "密码 *"))
        self.lineEdit_reg_pwd.setPlaceholderText(_translate("Form", "请输入密码（至少6位）"))
        self.label_reg_pwd2.setText(_translate("Form", "确认密码 *"))
        self.lineEdit_reg_pwd2.setPlaceholderText(_translate("Form", "请再次输入密码"))
        self.reg_avatar_btn.setText(_translate("Form", "选择头像（必选）"))
        self.register_btn.setText(_translate("Form", "注册"))
        self.back_to_login_btn.setText(_translate("Form", "已有账号？返回登录"))

from qfluentwidgets import BodyLabel, CheckBox, HyperlinkButton, LineEdit, PrimaryPushButton, PushButton
from resources import resource_rc