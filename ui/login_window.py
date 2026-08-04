# -*- coding: utf-8 -*-
"""
OGC 登录程序 - 启动入口
包含登录/注册功能，登录成功后跳转主页
"""
import sys
import os
import logging
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTranslator, QLocale
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QApplication, QMessageBox, QFileDialog
from qfluentwidgets import setThemeColor, FluentTranslator, setTheme, Theme, FluentWidget, InfoBar, InfoBarPosition
from ui.login_ui import Ui_Form
from core.resource_paths import LOGIN_LOGO, LOGIN_USER_ICON3, LOGIN_SPLASH_BG, LOGIN_RESIZE_BG
from core.database import init_db, verify_login, register_user, get_user_avatar, get_user_profile

# ─────────────── 日志系统 + 配置 ───────────────
from core.logger import logger
from core.config import config as CFG

# ─────────────── 全局玻璃效果 ───────────────
# FrostedPanel 与 glass_manager 来自全局模块，登录页与主窗口共用同一套，
# 透明度 / 模糊度统一由「设置」页调节，登录页自动跟随。
from ui.widgets.glass_effect import FrostedPanel, glass_manager

# ─────────────── 全局 UI 提示工具 ───────────────
from ui.widgets.ui_utils import install_hover_tip, success_flyout, info_flyout, warning_flyout, error_flyout


class LoginWindow(FluentWidget, Ui_Form):
    """登录窗口"""

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        setThemeColor('#28afe9')

        logger.info("初始化登录窗口")
        self._current_username = None

        if sys.platform != "darwin":
            self.titleBar.titleLabel.setTextColor(Qt.GlobalColor.white, Qt.GlobalColor.white)

        # 标题栏置顶
        self.titleBar.raise_()

        # ── 磨砂玻璃面板接入 ──
        # 将右侧面板背景透明化，露出底层磨砂面板
        self.widget.setStyleSheet(
            "QWidget#widget{background-color: transparent;}"
            "QLabel{font: 13px 'Microsoft YaHei';}"
        )
        # 创建磨砂面板并置于最底层（按钮/输入框等子控件在其上层，保持清晰）
        self.frosted_panel = FrostedPanel(self.widget)
        self.frosted_panel.setGeometry(0, 0, self.widget.width(), self.widget.height())
        self.frosted_panel.lower()

        self.label.setScaledContents(False)

        self.setWindowTitle('OGC 用户登录')
        self.setWindowIcon(QIcon(LOGIN_LOGO))
        # 与主窗口 OGChome 保持一致尺寸，避免登录→过渡动画→主页切换时画面突兀
        self.resize(1080, 780)

        desktop = QApplication.desktop().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

        # ── 信号绑定 ──
        self.pushButton.clicked.connect(self._on_login_clicked)          # 登录按钮
        self.pushButton_2.clicked.connect(self._show_register)           # 切换到注册
        self.register_btn.clicked.connect(self._on_register_clicked)     # 注册按钮
        self.back_to_login_btn.clicked.connect(self._show_login)         # 返回登录
        self.reg_avatar_btn.clicked.connect(self._select_avatar)        # 选择头像

        # 用户名输入时实时查询头像
        self.lineEdit_3.textChanged.connect(self._on_username_changed)

        # 回车键触发登录
        self.lineEdit_4.returnPressed.connect(self._on_login_clicked)

        # ── 按钮 / 开关悬停功能简介（移开鼠标自动消失）──
        install_hover_tip(self.pushButton, '登录', '输入账号密码后，点击登录进入主页')
        install_hover_tip(self.pushButton_2, '注册账号', '还没有账号？点击注册新账号')
        install_hover_tip(self.register_btn, '注册', '填写信息并选择头像后注册新账号')
        install_hover_tip(self.back_to_login_btn, '返回登录', '已有账号？返回登录界面')
        install_hover_tip(self.reg_avatar_btn, '选择头像', '从本地选择图片作为注册头像（必选）')
        install_hover_tip(self.checkBox, '记住密码', '勾选后下次登录自动填充密码')
        install_hover_tip(self.lineEdit_3, '用户名输入', '输入您的用户名')
        install_hover_tip(self.lineEdit_4, '密码输入', '输入您的登录密码，回车可快速登录')

        logger.info("登录窗口初始化完成")

    # ---------- 头像选择 ----------
    def _select_avatar(self):
        """打开文件对话框选择头像"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择头像图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            self._reg_avatar_path = file_path
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                self.reg_avatar_label.setPixmap(
                    pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self.reg_avatar_btn.setText("已选择头像")

    # ---------- 登录用户名输入时查询头像 ----------
    def _on_username_changed(self, text):
        """输入用户名时查询头像并预览"""
        text = text.strip()
        if not text:
            self.login_avatar_label.setVisible(False)
            return
        avatar_path = get_user_avatar(text)
        if avatar_path and os.path.exists(avatar_path):
            pixmap = QPixmap(avatar_path)
            if not pixmap.isNull():
                self.login_avatar_label.setPixmap(
                    pixmap.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self.login_avatar_label.setVisible(True)
                return
        self.login_avatar_label.setVisible(False)

    # ---------- 错误提示 ----------
    def createErrorInfoBar(self, title, content):
        """使用 InfoBar 显示错误提示，5秒后自动消失"""
        InfoBar.error(
            title=title,
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=5000,
            parent=self
        )

    # ---------- 界面切换 ----------
    def _show_register(self):
        """切换到注册界面"""
        logger.info("切换到注册界面")
        self.login_group.hide()
        self.register_group.show()

    def _show_login(self):
        """切换回登录界面"""
        logger.info("切换回登录界面")
        self.register_group.hide()
        self.login_group.show()
        # 清空注册输入
        self.lineEdit_reg_user.clear()
        self.lineEdit_reg_pwd.clear()
        self.lineEdit_reg_pwd2.clear()
        self.lineEdit_reg_role.clear()
        self.lineEdit_reg_motto.clear()
        self.lineEdit_reg_github.clear()
        self.lineEdit_reg_email.clear()
        self.lineEdit_reg_qq.clear()
        self._reg_avatar_path = ""
        self.reg_avatar_btn.setText("选择头像（必选）")
        default_pixmap = QPixmap(LOGIN_USER_ICON3)
        if not default_pixmap.isNull():
            self.reg_avatar_label.setPixmap(
                default_pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    # ---------- 登录逻辑 ----------
    def _on_login_clicked(self):
        """登录按钮点击处理"""
        username = self.lineEdit_3.text().strip()
        password = self.lineEdit_4.text()

        logger.info(f"用户尝试登录: {username}")

        success, message = verify_login(username, password)

        if success:
            # info_flyout('登录成功', f"正在进入 OGC 主页，请稍候…", self.pushButton, self)
            logger.info(f"用户登录成功: {username}")
            self._current_username = username
            self._login_success(username)
        else:
            logger.warning(f"用户登录失败: {username} - {message}")
            self.createErrorInfoBar("登录失败", message)
            error_flyout(
                '登录失败', f"请检查用户名或密码是否正确：{message}",
                self.pushButton, self)

    def _login_success(self, username):
        """登录成功后展示启动过渡动画，再进入主窗口

        优化：先立即切换到过渡动画页面（无卡顿），
        再在过渡图覆盖下构造主窗口（耗时被过渡图遮挡）。
        """
        logger.info(f"准备跳转到主页，用户: {username}")
        try:
            # ── 是否开启启动过渡动画（splashScreen）──
            splash_enabled = True
            try:
                from ui.widgets.common import cfg as app_cfg
                splash_enabled = bool(app_cfg.get(app_cfg.splashEnabled))
            except Exception:
                splash_enabled = True

            if splash_enabled:
                # 1. 先切换为过渡动画页面（立即显示占满窗口的背景图）
                from PyQt5.QtWidgets import QLabel
                from PyQt5.QtCore import QTimer
                self.widget.hide()          # 右侧登录面板
                self.label.hide()           # 左侧背景图
                self._splash_label = QLabel(self)
                self._splash_label.setObjectName("splashLabel")
                self._splash_label.setScaledContents(False)
                self._update_splash_image(self.size())
                self._splash_label.lower()
                self._splash_label.show()
                if hasattr(self, 'titleBar'):
                    self.titleBar.raise_()

                # 2. 强制过渡图立即绘制上屏（避免构造阻塞造成卡顿感）
                QApplication.processEvents()
                self.repaint()

                # 3. 延迟创建主窗口：过渡图已完整显示，
                #    之后构造 HomeWindow 的耗时被过渡图覆盖，用户无卡顿感知
                self._login_username = username
                QTimer.singleShot(150, self._async_load_home)

                # 4. 过渡图停留 1 秒后进入主窗口（构造耗时也在此覆盖）
                QTimer.singleShot(1000, self._enter_home)
            else:
                # 无过渡动画：直接构造主窗口并进入
                self._load_home_window(username)
                self._enter_home()

        except Exception as e:
            logger.error(f"跳转主页失败: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"无法打开主页：{str(e)}")

    def _async_load_home(self):
        """事件循环空闲时构造主窗口（过渡图已显示，耗时被覆盖）"""
        try:
            self._load_home_window(self._login_username)
        except Exception as e:
            logger.error(f"构造主窗口失败: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"无法打开主页：{str(e)}")

    def _load_home_window(self, username):
        """创建主窗口并设置尺寸与位置（耗时操作）"""
        # 延迟导入，避免循环依赖
        from ui.main_window import Window as HomeWindow
        self.home_window = HomeWindow()
        self.home_window.setCurrentUser(username)
        self.home_window.resize(self.width(), self.height())
        self.home_window.move(self.x(), self.y())

    def _update_splash_image(self, size):
        """按窗口大小裁剪并显示过渡背景图（KeepAspectRatioByExpanding 居中裁剪）"""
        if not hasattr(self, '_splash_label'):
            return
        pixmap = QPixmap(LOGIN_SPLASH_BG)
        if pixmap.isNull():
            self._splash_label.setStyleSheet(
                f"background-color: rgb(28, 28, 30);")
            return
        w, h = size.width(), size.height()
        scaled = pixmap.scaled(
            w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        # 居中裁剪到窗口大小
        x = (scaled.width() - w) // 2
        y = (scaled.height() - h) // 2
        if x < 0:
            x = 0
        if y < 0:
            y = 0
        cropped = scaled.copy(x, y, w, h)
        self._splash_label.setPixmap(cropped)
        self._splash_label.setGeometry(0, 0, w, h)

    def _enter_home(self):
        """移除过渡页面，进入主窗口并关闭登录窗口"""
        try:
            # 移除过渡页面（若存在）
            if hasattr(self, '_splash_label'):
                self._splash_label.deleteLater()
                del self._splash_label

            self.home_window.show()
            logger.info(f"主页窗口已打开，用户: {self._current_username}")
            self.close()
        except Exception as e:
            logger.error(f"进入主页失败: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "错误", f"无法打开主页：{str(e)}")

    # ---------- 注册逻辑 ----------
    def _on_register_clicked(self):
        """注册按钮点击处理"""
        username = self.lineEdit_reg_user.text().strip()
        password = self.lineEdit_reg_pwd.text()
        password2 = self.lineEdit_reg_pwd2.text()

        logger.info(f"用户尝试注册: {username}")

        # 前端校验
        if not username or len(username) < 2:
            self.createErrorInfoBar("注册失败", "用户名至少为2个字符")
            return
        if not password or len(password) < 6:
            self.createErrorInfoBar("注册失败", "密码长度至少为6位")
            return
        if password != password2:
            self.createErrorInfoBar("注册失败", "两次输入的密码不一致")
            return
        if not self._reg_avatar_path:
            self.createErrorInfoBar("注册失败", "请选择头像")
            return

        # 收集可选资料
        profile = {
            'avatar_path': self._reg_avatar_path,
            'role': self.lineEdit_reg_role.text().strip(),
            'motto': self.lineEdit_reg_motto.text().strip(),
            'github': self.lineEdit_reg_github.text().strip(),
            'email': self.lineEdit_reg_email.text().strip(),
            'qq': self.lineEdit_reg_qq.text().strip(),
            'info_items': [],
        }

        success, message = register_user(username, password, profile)

        if success:
            logger.info(f"用户注册成功: {username}")
            InfoBar.success(
                title='注册成功',
                content="注册成功，请登录",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
            # 自动填充用户名
            self.lineEdit_3.setText(username)
            self._show_login()
        else:
            logger.warning(f"用户注册失败: {username} - {message}")
            self.createErrorInfoBar("注册失败", message)

    # ---------- 窗口事件 ----------
    def resizeEvent(self, e):
        super().resizeEvent(e)
        pixmap = QPixmap(LOGIN_RESIZE_BG).scaled(
            self.label.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.label.setPixmap(pixmap)
        # 同步磨砂面板尺寸（布局可能已随窗口变化）
        if hasattr(self, 'frosted_panel'):
            self.frosted_panel.setGeometry(0, 0, self.widget.width(), self.widget.height())
        # 过渡动画页面跟随窗口尺寸重新裁剪
        if hasattr(self, '_splash_label'):
            self._update_splash_image(self.size())

    def showEvent(self, e):
        """首次显示时确保磨砂面板尺寸正确"""
        super().showEvent(e)
        if hasattr(self, 'frosted_panel'):
            self.frosted_panel.setGeometry(0, 0, self.widget.width(), self.widget.height())

    def closeEvent(self, e):
        logger.info("登录窗口关闭")
        super().closeEvent(e)


if __name__ == '__main__':
    # ── 初始化日志系统 ──
    logger.initialize(
        op_log_path=CFG['operation_log_path'],
        err_log_path=CFG['error_log_path']
    )

    # ── 初始化数据库 ──
    try:
        init_db()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}", exc_info=True)
        sys.exit(1)

    # ── 自检下载目录结构 ──
    try:
        from services.download_manager import ensure_download_dirs
        ensure_download_dirs()
        logger.info("下载目录自检完成")
    except Exception as e:
        logger.error(f"下载目录自检失败: {str(e)}")

    # ── 加载全局玻璃效果配置 ──
    try:
        from ui.widgets.common import cfg as app_cfg
        glass_manager.load(
            opacity=app_cfg.get(app_cfg.glassOpacity),
            blur_radius=app_cfg.get(app_cfg.glassBlurRadius)
        )
    except Exception as e:
        logger.error(f"加载玻璃效果配置失败: {e}")

    # enable dpi scale
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)

    # Internationalization
    translator = FluentTranslator(QLocale())
    app.installTranslator(translator)

    w = LoginWindow()
    w.show()
    logger.info("应用程序启动")
    app.exec_()
    logger.info("应用程序退出")