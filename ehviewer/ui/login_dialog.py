# -*- coding: utf-8 -*-
"""登录对话框：账号密码登录 / 手动导入 Cookie"""
import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel

from qfluentwidgets import (LineEdit, PasswordLineEdit, PrimaryPushButton, PushButton,
                            SubtitleLabel, BodyLabel, CaptionLabel, InfoBar,
                            InfoBarPosition, CardWidget, ComboBox, TextEdit, FluentIcon,
                            StrongBodyLabel)

from .. import session as sess
from ..config import set_cookies, set, is_login, clear_cookies
from ..session import make_session, save_cookies_from
from .. import urls


class SignInWorker(QThread):
    done = pyqtSignal(bool, str)
    cookiesReady = pyqtSignal(dict)

    def __init__(self, username, password, parent=None):
        super(SignInWorker, self).__init__(parent)
        self.username = username
        self.password = password

    def run(self):
        try:
            s = make_session()
            data = {
                "UserName": self.username,
                "PassWord": self.password,
                "submit": "Log me in",
                "CookieDate": "1",
                "temporary_https": "off",
            }
            headers = {
                "Referer": "https://forums.e-hentai.org/index.php?act=Login&CODE=00",
                "Origin": "https://forums.e-hentai.org",
            }
            r = s.post(urls.API_SIGN_IN, data=data, headers=headers, timeout=30,
                       allow_redirects=True)
            body = r.text
            if "Invalid Username or Password" in body or "Login Failed" in body:
                self.done.emit(False, "用户名或密码错误，登录失败。")
                return
            cookies = {k: v for k, v in s.cookies.items()}
            if cookies.get("ipb_pass_hash"):
                save_cookies_from(s)
                self.cookiesReady.emit(cookies)
                self.done.emit(True, "登录成功！")
            else:
                self.done.emit(False, "登录失败：未获取到有效 Cookie。")
        except Exception as e:
            self.done.emit(False, "网络错误：" + str(e))


class LoginDialog(QDialog):
    """登录对话框"""

    def __init__(self, parent=None):
        super(LoginDialog, self).__init__(parent)
        self.setWindowTitle("登录 E-Hentai")
        self.setFixedSize(420, 460)
        self._worker = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        title = SubtitleLabel("登录 E-Hentai 账户", self)
        lay.addWidget(title)
        tip = CaptionLabel("登录后可使用云收藏、评论、评分、签到、观看记录同步等功能。", self)
        tip.setStyleSheet("color: #888;")
        lay.addWidget(tip)

        self.tab_card = CardWidget(self)
        tab_lay = QVBoxLayout(self.tab_card)
        tab_lay.setContentsMargins(16, 14, 16, 14)
        tab_lay.setSpacing(8)

        self.user_edit = LineEdit(self)
        self.user_edit.setPlaceholderText("用户名")
        self.pass_edit = PasswordLineEdit(self)
        self.pass_edit.setPlaceholderText("密码")
        self.login_btn = PrimaryPushButton("登 录", self)
        self.login_btn.clicked.connect(self._do_login)

        tab_lay.addWidget(StrongBodyLabel("账号密码登录"))
        tab_lay.addWidget(self.user_edit)
        tab_lay.addWidget(self.pass_edit)
        tab_lay.addWidget(self.login_btn)
        lay.addWidget(self.tab_card)

        cookie_card = CardWidget(self)
        c_lay = QVBoxLayout(cookie_card)
        c_lay.setContentsMargins(16, 14, 16, 14)
        c_lay.setSpacing(8)
        c_lay.addWidget(StrongBodyLabel("Cookie 登录"))
        c_tip = CaptionLabel("用浏览器访问 e-hentai.org 后导出 Cookie（ipb_member_id / ipb_pass_hash / igneous），粘贴或从文件导入。", self)
        c_tip.setWordWrap(True)
        c_tip.setStyleSheet("color: #888;")
        c_lay.addWidget(c_tip)
        self.cookie_edit = TextEdit(self)
        self.cookie_edit.setPlaceholderText("Cookie 内容，格式：name=value; name2=value2 …")
        self.cookie_edit.setFixedHeight(80)
        c_lay.addWidget(self.cookie_edit)
        row = QHBoxLayout()
        import_btn = PushButton("从文件导入…", self)
        import_btn.clicked.connect(self._import_file)
        paste_btn = PushButton("粘贴", self)
        paste_btn.clicked.connect(self._paste)
        apply_btn = PrimaryPushButton("应用并登录", self)
        apply_btn.clicked.connect(self._apply_cookie)
        row.addWidget(import_btn)
        row.addWidget(paste_btn)
        row.addStretch(1)
        row.addWidget(apply_btn)
        c_lay.addLayout(row)
        lay.addWidget(cookie_card)

        lay.addStretch(1)
        close_btn = PushButton("取消", self)
        close_btn.clicked.connect(self.reject)
        lay.addWidget(close_btn, 0, Qt.AlignRight)

    def _do_login(self):
        u = self.user_edit.text().strip()
        p = self.pass_edit.text()
        if not u or not p:
            InfoBar.warning("", "请输入用户名和密码", position=InfoBarPosition.TOP, duration=3000, parent=self)
            return
        self.login_btn.setEnabled(False)
        self.login_btn.setText("登录中…")
        self._worker = SignInWorker(u, p, self)
        self._worker.done.connect(self._on_done)
        self._worker.cookiesReady.connect(self._on_cookies)
        self._worker.start()

    def _on_cookies(self, cookies):
        set_cookies(cookies)

    def _on_done(self, ok, msg):
        self.login_btn.setEnabled(True)
        self.login_btn.setText("登 录")
        if ok:
            InfoBar.success("", msg, position=InfoBarPosition.TOP, duration=2500, parent=self)
            self.accept()
        else:
            InfoBar.error("", msg, position=InfoBarPosition.TOP, duration=4000, parent=self)

    def _paste(self):
        from PyQt5.QtWidgets import QApplication
        clip = QApplication.clipboard()
        if clip and clip.text():
            self.cookie_edit.setPlainText(clip.text())

    def _import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Cookie 文件", "", "文本文件 (*.txt);;所有文件 (*)")
        if path:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    self.cookie_edit.setPlainText(f.read())
            except Exception as e:
                InfoBar.error("", "读取失败：" + str(e), position=InfoBarPosition.TOP, duration=3000, parent=self)

    def _apply_cookie(self):
        text = self.cookie_edit.toPlainText().strip()
        if not text:
            InfoBar.warning("", "请先粘贴 Cookie 内容", position=InfoBarPosition.TOP, duration=3000, parent=self)
            return
        cookies = {}
        for chunk in text.replace(";", " ").split():
            if "=" in chunk:
                k, v = chunk.split("=", 1)
                cookies[k.strip()] = v.strip()
        if not cookies.get("ipb_member_id") or not cookies.get("ipb_pass_hash"):
            InfoBar.warning("", "Cookie 中缺少 ipb_member_id 或 ipb_pass_hash", position=InfoBarPosition.TOP, duration=4000, parent=self)
            return
        set_cookies(cookies)
        InfoBar.success("", "Cookie 已应用", position=InfoBarPosition.TOP, duration=2500, parent=self)
        self.accept()
