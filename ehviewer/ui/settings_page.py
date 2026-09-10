# -*- coding: utf-8 -*-
"""设置页：账户 / 站点 / 显示 / 阅读 / 下载 / 网络 / 关于（全汉化）"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                             QScrollArea, QLayout)

from qfluentwidgets import (CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
                            PrimaryPushButton, PushButton, ComboBox, SwitchButton,
                            LineEdit, InfoBar, InfoBarPosition, ScrollArea,
                            StrongBodyLabel, FluentIcon, ToolButton, Slider,
                            MessageBox, ProgressBar)

from .. import constants as C
from .. import config as cfg
cfg_module = cfg
from ..config import get, set as cset, is_login, clear_cookies
from .login_dialog import LoginDialog
from .bus import bus


def _row(label, widget, tip=""):
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(10)
    lbl = BodyLabel(label)
    lbl.setFixedWidth(150)
    lay.addWidget(lbl)
    if isinstance(widget, QLayout):
        lay.addLayout(widget, 1)
    else:
        lay.addWidget(widget, 1)
    if tip:
        t = CaptionLabel(tip)
        t.setStyleSheet("color: #888;")
        lay.addWidget(t)
    return lay


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super(SettingsPage, self).__init__(parent)
        self._cache_size = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(SubtitleLabel("设置"))

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        container = QWidget(self.scroll)
        self._lay = QVBoxLayout(container)
        self._lay.setContentsMargins(4, 4, 4, 4)
        self._lay.setSpacing(10)
        self.scroll.setWidget(container)
        outer.addWidget(self.scroll, 1)

        self._build_account()
        self._build_site()
        self._build_display()
        self._build_read()
        self._build_download()
        self._build_network()
        self._build_filter()
        self._build_about()
        self._lay.addStretch(1)

    # ---------- 账户 ----------
    def _build_account(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("账户"))
        self.login_btn = PrimaryPushButton("登录 / 导入 Cookie", self)
        self.login_btn.clicked.connect(self._open_login)
        self.logout_btn = PushButton("退出登录", self)
        self.logout_btn.clicked.connect(self._logout)
        self.account_label = CaptionLabel("未登录", self)
        self.account_label.setStyleSheet("color: #888;")
        lay.addLayout(_row("登录状态", self.account_label))
        row = QHBoxLayout()
        row.addWidget(self.login_btn)
        row.addWidget(self.logout_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._lay.addWidget(card)
        self.refresh_login_state()

    def refresh_login_state(self):
        if is_login():
            self.account_label.setText("已登录（Cookie 有效）")
            self.login_btn.setText("切换账户")
            self.logout_btn.setEnabled(True)
        else:
            self.account_label.setText("未登录（云收藏、评论、评分需登录）")
            self.login_btn.setText("登录 / 导入 Cookie")
            self.logout_btn.setEnabled(False)

    def _open_login(self):
        dlg = LoginDialog(self.window())
        if dlg.exec_():
            self.refresh_login_state()
            bus.loginChanged.emit(True)

    def _logout(self):
        box = MessageBox("退出登录", "确定要退出登录吗？将清除本地保存的 Cookie。", self)
        if box.exec_():
            clear_cookies()
            self.refresh_login_state()
            bus.loginChanged.emit(False)
            InfoBar.success("", "已退出登录", position=InfoBarPosition.TOP, duration=2000, parent=self)

    # ---------- 站点 ----------
    def _build_site(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("站点"))
        # 已取消里站（exhentai.org），仅保留表站（e-hentai.org），固定不可切换。
        self.site_label = CaptionLabel("表站 e-hentai.org（已固定，仅保留表站）", self)
        lay.addLayout(_row("画廊站点", self.site_label, "功能已固定使用表站"))
        self._lay.addWidget(card)

    # ---------- 显示 ----------
    def _build_display(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("显示"))

        self.jpn_switch = SwitchButton(self)
        self.jpn_switch.setChecked(bool(get("show_jpn_title", False)))
        self.jpn_switch.checkedChanged.connect(lambda v: cset("show_jpn_title", v))
        lay.addLayout(_row("优先显示日文标题", self.jpn_switch))

        self.pages_switch = SwitchButton(self)
        self.pages_switch.setChecked(bool(get("show_gallery_pages", True)))
        self.pages_switch.checkedChanged.connect(lambda v: cset("show_gallery_pages", v))
        lay.addLayout(_row("列表显示页数", self.pages_switch))

        self.thumb_combo = ComboBox(self)
        self.thumb_combo.addItem("自动", userData=0)
        self.thumb_combo.addItem("250x", userData=1)
        self.thumb_combo.addItem("300x", userData=2)
        ti = self.thumb_combo.findData(get("thumb_resolution", 1))
        self.thumb_combo.setCurrentIndex(max(0, ti))
        self.thumb_combo.currentIndexChanged.connect(
            lambda i: cset("thumb_resolution", self.thumb_combo.currentData()))
        lay.addLayout(_row("缩略图分辨率", self.thumb_combo))
        self._lay.addWidget(card)

    # ---------- 阅读 ----------
    def _build_read(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("阅读"))

        self.img_size_combo = ComboBox(self)
        for key, name in C.IMAGE_SIZE_NAMES.items():
            self.img_size_combo.addItem(name, userData=key)
        ii = self.img_size_combo.findData(get("image_size", C.IMAGE_SIZE_AUTO))
        self.img_size_combo.setCurrentIndex(max(0, ii))
        self.img_size_combo.currentIndexChanged.connect(
            lambda i: cset("image_size", self.img_size_combo.currentData()))
        lay.addLayout(_row("图片分辨率", self.img_size_combo, "需在站点设置中启用"))

        self.read_style_combo = ComboBox(self)
        self.read_style_combo.addItem("翻页模式（横向）", userData="page")
        self.read_style_combo.addItem("卷轴模式（上下滚动）", userData="scroll")
        ri = self.read_style_combo.findData(get("read_style", "page"))
        self.read_style_combo.setCurrentIndex(max(0, ri))
        self.read_style_combo.currentIndexChanged.connect(
            lambda i: cset("read_style", self.read_style_combo.currentData()))
        lay.addLayout(_row("阅读模式", self.read_style_combo))

        self.direction_combo = ComboBox(self)
        self.direction_combo.addItem("从左至右", userData=0)
        self.direction_combo.addItem("从右至左", userData=1)
        di = self.direction_combo.findData(get("reading_direction", 1))
        self.direction_combo.setCurrentIndex(max(0, di))
        self.direction_combo.currentIndexChanged.connect(
            lambda i: cset("reading_direction", self.direction_combo.currentData()))
        lay.addLayout(_row("翻页方向", self.direction_combo))

        self.fit_combo = ComboBox(self)
        self.fit_combo.addItem("宽度适配", userData="width")
        self.fit_combo.addItem("整图适配", userData="whole")
        fi = self.fit_combo.findData(get("reader_fit", "width"))
        self.fit_combo.setCurrentIndex(max(0, fi))
        self.fit_combo.currentIndexChanged.connect(
            lambda i: cset("reader_fit", self.fit_combo.currentData()))
        lay.addLayout(_row("默认缩放", self.fit_combo))
        self._lay.addWidget(card)

    # ---------- 下载 ----------
    def _build_download(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("下载"))

        self.dir_edit = LineEdit(self)
        self.dir_edit.setText(get("download_dir", ""))
        self.dir_edit.setFixedWidth(360)
        self.dir_btn = PushButton("选择…", self)
        self.dir_btn.clicked.connect(self._pick_dir)
        self.dir_save = PushButton("应用", self)
        self.dir_save.clicked.connect(self._save_dir)
        row = QHBoxLayout()
        row.addWidget(self.dir_edit)
        row.addWidget(self.dir_btn)
        row.addWidget(self.dir_save)
        lay.addLayout(_row("下载目录", row))

        self.conc_combo = ComboBox(self)
        for n in (1, 2, 3, 4, 5, 6, 8):
            self.conc_combo.addItem("%d 个同时下载" % n, userData=n)
        ci = self.conc_combo.findData(get("download_concurrency", 3))
        self.conc_combo.setCurrentIndex(max(0, ci))
        self.conc_combo.currentIndexChanged.connect(self._on_concurrency)
        lay.addLayout(_row("并发下载数", self.conc_combo))

        self.orig_switch = SwitchButton(self)
        self.orig_switch.setChecked(bool(get("download_original", False)))
        self.orig_switch.checkedChanged.connect(lambda v: cset("download_original", v))
        lay.addLayout(_row("下载原图", self.orig_switch, "危险！会快速消耗配额与 GP"))

        self.sync_switch = SwitchButton(self)
        self.sync_switch.setChecked(bool(get("sync_download_on_read", False)))
        self.sync_switch.checkedChanged.connect(lambda v: cset("sync_download_on_read", v))
        lay.addLayout(_row("阅读时同步下载", self.sync_switch))
        self._lay.addWidget(card)

    def _pick_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)

    def _save_dir(self):
        p = self.dir_edit.text().strip()
        if p:
            os.makedirs(p, exist_ok=True)
            cset("download_dir", p)
            InfoBar.success("", "下载目录已更新", position=InfoBarPosition.TOP, duration=2000, parent=self)

    def _on_concurrency(self, _i):
        n = self.conc_combo.currentData()
        cset("download_concurrency", n)
        from ..appctx import ctx
        if ctx.download_manager is not None:
            ctx.download_manager.set_concurrency(n)

    # ---------- 网络 ----------
    def _build_network(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("网络"))

        self.proxy_edit = LineEdit(self)
        self.proxy_edit.setPlaceholderText("如 http://127.0.0.1:7890（留空不使用）")
        self.proxy_edit.setText(get("proxy", ""))
        self.proxy_edit.setFixedWidth(300)
        self.proxy_save = PushButton("应用", self)
        self.proxy_save.clicked.connect(self._save_proxy)
        row = QHBoxLayout()
        row.addWidget(self.proxy_edit)
        row.addWidget(self.proxy_save)
        lay.addLayout(_row("HTTP 代理", row))

        self.timeout_combo = ComboBox(self)
        for t in (10, 20, 30, 60, 120):
            self.timeout_combo.addItem("%d 秒" % t, userData=t)
        ti = self.timeout_combo.findData(get("timeout", 20))
        self.timeout_combo.setCurrentIndex(max(0, ti))
        self.timeout_combo.currentIndexChanged.connect(
            lambda i: cset("timeout", self.timeout_combo.currentData()))
        lay.addLayout(_row("请求超时", self.timeout_combo))
        self._lay.addWidget(card)

    def _save_proxy(self):
        cset("proxy", self.proxy_edit.text().strip())
        InfoBar.success("", "代理已保存（重启后完全生效）", position=InfoBarPosition.TOP, duration=2000, parent=self)

    # ---------- 屏蔽标签 ----------
    def _build_filter(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("屏蔽标签（FILTER）"))
        tip = CaptionLabel("被屏蔽的标签将不会出现在画廊列表中（需登录且列表含标签信息时生效）")
        tip.setStyleSheet("color: #888;")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.block_edit = LineEdit(self)
        self.block_edit.setPlaceholderText("输入要屏蔽的标签，如 female:xxx 或 artist:yyy")
        self.block_edit.setFixedWidth(300)
        self.block_add = PushButton("添加屏蔽", self)
        self.block_add.clicked.connect(self._add_block)
        row = QHBoxLayout()
        row.addWidget(self.block_edit)
        row.addWidget(self.block_add)
        row.addStretch(1)
        lay.addLayout(row)
        self._block_rows = QVBoxLayout()
        self._block_rows.setSpacing(4)
        lay.addLayout(self._block_rows)
        self._render_blocks()
        self._lay.addWidget(card)

    def _render_blocks(self):
        while self._block_rows.count():
            item = self._block_rows.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        import ehviewer.db as _db
        blocks = _db.list_blocked_tags()
        if not blocks:
            self._block_rows.addWidget(CaptionLabel("（暂无屏蔽标签）"))
            return
        for b in blocks:
            r = QHBoxLayout()
            lbl = CaptionLabel(b["text"])
            lbl.setStyleSheet("background: rgba(229,72,77,0.15); border-radius: 6px; padding: 2px 10px;")
            r.addWidget(lbl)
            r.addStretch(1)
            delb = ToolButton(FluentIcon.DELETE, self)
            delb.setToolTip("取消屏蔽")
            delb.clicked.connect(lambda _=False, fid=b["id"]: self._del_block(fid))
            r.addWidget(delb)
            self._block_rows.addLayout(r)

    def _add_block(self):
        import ehviewer.db as _db
        text = self.block_edit.text().strip()
        if not text:
            InfoBar.warning("", "请输入要屏蔽的标签", position=InfoBarPosition.TOP, duration=2500, parent=self)
            return
        _db.add_blocked_tag(text)
        self.block_edit.clear()
        InfoBar.success("", "已添加屏蔽：" + text, position=InfoBarPosition.TOP, duration=2000, parent=self)
        self._render_blocks()

    def _del_block(self, fid):
        import ehviewer.db as _db
        _db.delete_blocked_tag(fid)
        self._render_blocks()

    # ---------- 关于 / 清理 ----------
    def _build_about(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("关于"))

        self.cache_btn = PushButton("清理图片缓存", self)
        self.cache_btn.clicked.connect(self._clear_cache)
        lay.addLayout(_row("缓存", self.cache_btn, "清理缩略图与阅读图片缓存（data/ehentai/cache）"))

        ver = CaptionLabel("EhViewer PC %s — 基于 Ehviewer_CN_SXJ 源码复刻，仅用于学习交流，与 E-Hentai.org 无任何关系。" % C.APP_VERSION)
        ver.setWordWrap(True)
        ver.setStyleSheet("color: #888;")
        lay.addWidget(ver)
        self._lay.addWidget(card)

    def _clear_cache(self):
        import shutil
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "ehentai", "cache")
        try:
            if os.path.exists(cache_dir):
                shutil.rmtree(cache_dir, ignore_errors=True)
            InfoBar.success("", "图片缓存已清理", position=InfoBarPosition.TOP, duration=2000, parent=self)
        except Exception as e:
            InfoBar.error("", "清理失败：" + str(e), position=InfoBarPosition.TOP, duration=3000, parent=self)
