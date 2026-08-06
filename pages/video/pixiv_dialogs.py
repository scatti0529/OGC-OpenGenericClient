# -*- coding: utf-8 -*-
"""Pixiv 配置弹窗 / 功能清单弹窗"""
import os
import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QWidget, QFormLayout, QMessageBox, QLineEdit, QPushButton,
    QCheckBox, QComboBox, QSpinBox, QFrame, QGroupBox,
)

from qfluentwidgets import (
    FluentIcon as FIF, PrimaryPushButton, PushButton, LineEdit,
    InfoBar, InfoBarPosition, BodyLabel, CaptionLabel,
    ComboBox, SwitchButton, SubtitleLabel, StrongBodyLabel,
    MessageBoxBase, ProgressBar,
)

from core.config import config as CFG
from core.database import (
    get_pixiv_refresh_token,
)
from services.pixiv_service import PixivDownloader, LoginRequiredError
from ui.widgets.theme import theme_color
from ui.widgets.ui_utils import install_hover_tip


def show_info(parent, title, content, duration=3000):
    InfoBar.info(
        title=title, content=content,
        orient=Qt.Horizontal, isClosable=True,
        position=InfoBarPosition.TOP, duration=duration, parent=parent
    )


def show_success(parent, title, content, duration=3000):
    InfoBar.success(
        title=title, content=content,
        orient=Qt.Horizontal, isClosable=True,
        position=InfoBarPosition.TOP, duration=duration, parent=parent
    )


def show_error(parent, title, content, duration=5000):
    InfoBar.error(
        title=title, content=content,
        orient=Qt.Horizontal, isClosable=True,
        position=InfoBarPosition.BOTTOM_RIGHT, duration=duration, parent=parent
    )


# ═══════════════════════════════════════════════════════════
#  配置弹窗
# ═══════════════════════════════════════════════════════════
class PixivConfigDialog(QDialog):
    """Pixiv 配置弹窗

    包含:
    - Refresh Token 获取 / 管理（存入数据库）
    - 一次性下载的图片数量
    - 抓取的页数
    - 最大帖子数 / 最大抓取图片数
    - 标签语言
    - 更新已存在文件夹 / 删除重复图片
    - 其他功能开关（跳过漫画等）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pixiv 配置")
        self.setModal(True)
        self.resize(560, 640)
        self.setMinimumSize(560, 640)
        self.setMinimumHeight(640)
        self._downloader = PixivDownloader(
            log_callback=lambda msg: self._on_log(msg))
        self._log_text = []

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── 标题 ──
        titleLabel = SubtitleLabel("Pixiv 配置与登录", self)
        layout.addWidget(titleLabel)
        caption = CaptionLabel(
            "配置下载参数并管理 Refresh Token（自动存储在数据库中）", self)
        caption.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + ";")
        layout.addWidget(caption)

        # ── 滚动区 ──
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scrollWidget = QWidget()
        formLayout = QVBoxLayout(scrollWidget)
        formLayout.setSpacing(8)
        formLayout.setContentsMargins(4, 4, 4, 4)

        # ═══ 登录区块 ═══
        loginGroup = QGroupBox("🔑 Refresh Token 登录", scrollWidget)
        loginLayout = QVBoxLayout(loginGroup)

        # Token 输入
        tokenRow = QHBoxLayout()
        self.tokenEdit = LineEdit(loginGroup)
        self.tokenEdit.setPlaceholderText("粘贴 Refresh Token，或点击下方按钮自动获取")
        self.tokenEdit.setText(get_pixiv_refresh_token())
        tokenRow.addWidget(self.tokenEdit, 1)
        loginLayout.addLayout(tokenRow)

        # 获取 Token / 保存 Token 按钮
        btnRow = QHBoxLayout()
        self.getTokenBtn = PrimaryPushButton(FIF.SYNC, "获取 Refresh Token", loginGroup)
        self.getTokenBtn.clicked.connect(self._on_get_token)
        btnRow.addWidget(self.getTokenBtn)
        self.saveTokenBtn = PushButton(FIF.SAVE, "保存到数据库", loginGroup)
        self.saveTokenBtn.clicked.connect(self._on_save_token)
        btnRow.addWidget(self.saveTokenBtn)
        loginLayout.addLayout(btnRow)

        # 授权 code 输入
        codeRow = QHBoxLayout()
        self.codeEdit = LineEdit(loginGroup)
        self.codeEdit.setPlaceholderText("粘贴浏览器回调地址或 code（若选择网页登录）")
        codeRow.addWidget(self.codeEdit, 1)
        self.completeLoginBtn = PushButton(FIF.ACCEPT, "完成登录", loginGroup)
        self.completeLoginBtn.clicked.connect(self._on_complete_login)
        codeRow.addWidget(self.completeLoginBtn)
        loginLayout.addLayout(codeRow)

        self.tokenStatus = CaptionLabel("", loginGroup)
        self.tokenStatus.setWordWrap(True)
        self.tokenStatus.setStyleSheet(
            "color: " + theme_color('#67C23A', '#67C23A') + "; font-size: 12px;")
        loginLayout.addWidget(self.tokenStatus)

        formLayout.addWidget(loginGroup)

        # ═══ 下载数量配置 ═══
        countGroup = QGroupBox("📊 下载数量配置", scrollWidget)
        countForm = QFormLayout(countGroup)
        countForm.setSpacing(8)

        self.imagesPerDownload = QSpinBox(countGroup)
        self.imagesPerDownload.setRange(1, 99999)
        self.imagesPerDownload.setValue(int(CFG.get('pixiv_images_per_download', 0) or 0))
        self.imagesPerDownload.setSpecialValueText("不限（0 = 全部）")
        self.imagesPerDownload.setToolTip("一次解析/下载任务最多下载的图片张数，0 表示不限")
        countForm.addRow("一次性下载图片数:", self.imagesPerDownload)

        self.crawlPages = QSpinBox(countGroup)
        self.crawlPages.setRange(1, 50)
        self.crawlPages.setValue(int(CFG.get('pixiv_crawl_pages', 3)))
        self.crawlPages.setToolTip("标签搜索/收藏/排行榜等抓取的页数（每页约 30 张）")
        countForm.addRow("抓取的页数:", self.crawlPages)

        self.maxPosts = QSpinBox(countGroup)
        self.maxPosts.setRange(0, 99999)
        self.maxPosts.setValue(int(CFG.get('pixiv_max_posts', 0) or 0))
        self.maxPosts.setSpecialValueText("不限（0 = 全部）")
        self.maxPosts.setToolTip("按画师 ID 下载时最多下载的作品数，0 表示不限")
        countForm.addRow("最大帖子数:", self.maxPosts)

        self.maxImages = QSpinBox(countGroup)
        self.maxImages.setRange(0, 99999)
        self.maxImages.setValue(int(CFG.get('pixiv_max_images', 0) or 0))
        self.maxImages.setSpecialValueText("不限（0 = 全部）")
        self.maxImages.setToolTip("最大抓取图片数，0 表示不限")
        countForm.addRow("最大抓取图片数:", self.maxImages)

        formLayout.addWidget(countGroup)

        # ═══ 下载行为配置 ═══
        behaviorGroup = QGroupBox("⚙️ 下载行为", scrollWidget)
        behaviorForm = QFormLayout(behaviorGroup)
        behaviorForm.setSpacing(8)

        self.tagLangCombo = ComboBox(behaviorGroup)
        self.tagLangCombo.addItems(["japanese", "translated", "original"])
        current_lang = CFG.get('pixiv_tag_language', 'japanese')
        if current_lang in self.tagLangCombo.items:
            self.tagLangCombo.setCurrentText(current_lang)
        behaviorForm.addRow("标签语言:", self.tagLangCombo)

        self.updateExistingSwitch = SwitchButton(behaviorGroup)
        self.updateExistingSwitch.setChecked(bool(CFG.get('pixiv_update_existing', True)))
        behaviorForm.addRow("更新已存在文件夹:", self.updateExistingSwitch)

        self.skipMangaSwitch = SwitchButton(behaviorGroup)
        self.skipMangaSwitch.setChecked(bool(CFG.get('pixiv_skip_manga', False)))
        behaviorForm.addRow("跳过漫画:", self.skipMangaSwitch)

        self.fastUpdateSwitch = SwitchButton(behaviorGroup)
        self.fastUpdateSwitch.setChecked(bool(CFG.get('pixiv_fast_update', True)))
        behaviorForm.addRow("快速更新:", self.fastUpdateSwitch)

        formLayout.addWidget(behaviorGroup)

        # ═══ 功能开关（源代码其他功能）═══
        featureGroup = QGroupBox("🔧 功能开关", scrollWidget)
        featureForm = QFormLayout(featureGroup)
        featureForm.setSpacing(6)

        self.metadataSwitch = SwitchButton(featureGroup)
        self.metadataSwitch.setChecked(bool(CFG.get('pixiv_metadata', False)))
        featureForm.addRow("获取作者详细信息:", self.metadataSwitch)

        self.metadataBookmarkSwitch = SwitchButton(featureGroup)
        self.metadataBookmarkSwitch.setChecked(bool(CFG.get('pixiv_metadata_bookmark', False)))
        featureForm.addRow("获取收藏信息:", self.metadataBookmarkSwitch)

        self.commentsSwitch = SwitchButton(featureGroup)
        self.commentsSwitch.setChecked(bool(CFG.get('pixiv_comments', False)))
        featureForm.addRow("下载评论区:", self.commentsSwitch)

        self.captionsSwitch = SwitchButton(featureGroup)
        self.captionsSwitch.setChecked(bool(CFG.get('pixiv_captions', False)))
        featureForm.addRow("下载作品说明:", self.captionsSwitch)

        self.relatedSwitch = SwitchButton(featureGroup)
        self.relatedSwitch.setChecked(bool(CFG.get('pixiv_related', False)))
        featureForm.addRow("相关作品:", self.relatedSwitch)

        self.coversSwitch = SwitchButton(featureGroup)
        self.coversSwitch.setChecked(bool(CFG.get('pixiv_covers', False)))
        featureForm.addRow("小说封面:", self.coversSwitch)

        self.ugoiraCombo = ComboBox(featureGroup)
        self.ugoiraCombo.addItems(["True", "original", "False"])
        current_ugoira = CFG.get('pixiv_ugoira', 'True')
        if current_ugoira in self.ugoiraCombo.items:
            self.ugoiraCombo.setCurrentText(current_ugoira)
        featureForm.addRow("动图 (Ugoira):", self.ugoiraCombo)

        formLayout.addWidget(featureGroup)

        # ═══ 工具按钮 ═══
        toolGroup = QGroupBox("🛠 工具", scrollWidget)
        toolLayout = QHBoxLayout(toolGroup)

        self.updateExistBtn = PushButton(FIF.SYNC, "更新已有文件夹", toolGroup)
        self.updateExistBtn.clicked.connect(self._on_update_existing)
        toolLayout.addWidget(self.updateExistBtn)

        self.removeRepeatBtn = PushButton(FIF.DELETE, "删除重复图片", toolGroup)
        self.removeRepeatBtn.clicked.connect(self._on_remove_repeat)
        toolLayout.addWidget(self.removeRepeatBtn)

        formLayout.addWidget(toolGroup)

        # ═══ 日志区 ═══
        self.logLabel = CaptionLabel("", scrollWidget)
        self.logLabel.setWordWrap(True)
        self.logLabel.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + ";")
        formLayout.addWidget(self.logLabel)

        # 移除 formLayout 中的 stretch，让滚动区正确占满可用空间
        # formLayout.addStretch()
        scroll.setWidget(scrollWidget)
        # 设置滚动区最小高度，确保内容不被底部按钮遮挡
        scroll.setMinimumHeight(480)
        layout.addWidget(scroll, 1)

        # ── 底部按钮 ──
        bottomRow = QHBoxLayout()
        bottomRow.addStretch()
        self.saveBtn = PrimaryPushButton(FIF.ACCEPT, "保存配置", self)
        self.saveBtn.clicked.connect(self._on_save)
        bottomRow.addWidget(self.saveBtn)
        self.closeBtn = PushButton(FIF.CLOSE, "关闭", self)
        self.closeBtn.clicked.connect(self.close)
        bottomRow.addWidget(self.closeBtn)
        layout.addLayout(bottomRow)

        # ── Pixiv 配置弹窗悬停功能简介（所有控件创建完成后安装）──
        install_hover_tip(self.tokenEdit, "Refresh Token", "粘贴 Pixiv Refresh Token，或点击下方按钮自动获取")
        install_hover_tip(self.getTokenBtn, "获取 Refresh Token", "打开 Pixiv 授权页面并获取 Refresh Token")
        install_hover_tip(self.saveTokenBtn, "保存到数据库", "验证并保存 Refresh Token 到数据库")
        install_hover_tip(self.codeEdit, "授权 code", "粘贴浏览器回调地址或授权 code 完成网页登录")
        install_hover_tip(self.completeLoginBtn, "完成登录", "使用授权 code 完成登录并保存 Token")
        install_hover_tip(self.imagesPerDownload, "一次性下载图片数", "一次解析/下载任务最多下载的图片张数，0 表示不限")
        install_hover_tip(self.crawlPages, "抓取的页数", "标签搜索/收藏/排行榜等抓取的页数（每页约 30 张）")
        install_hover_tip(self.maxPosts, "最大帖子数", "按画师 ID 下载时最多下载的作品数，0 表示不限")
        install_hover_tip(self.maxImages, "最大抓取图片数", "最大抓取图片数，0 表示不限")
        install_hover_tip(self.tagLangCombo, "标签语言", "下载时使用的标签语言（日文/翻译/原语言）")
        install_hover_tip(self.updateExistingSwitch, "更新已存在文件夹", "开启后重新下载并更新已存在的画师文件夹")
        install_hover_tip(self.skipMangaSwitch, "跳过漫画", "开启后跳过漫画类型的作品，仅下载插画")
        install_hover_tip(self.fastUpdateSwitch, "快速更新", "快速模式跳过检查，更新已存在文件夹时更快")
        install_hover_tip(self.metadataSwitch, "获取作者详细信息", "为每个作品获取并保存作者详细信息")
        install_hover_tip(self.metadataBookmarkSwitch, "获取收藏信息", "获取并保存作品的收藏信息")
        install_hover_tip(self.commentsSwitch, "下载评论区", "下载并保存作品的评论区内容")
        install_hover_tip(self.captionsSwitch, "下载作品说明", "下载并保存作品的说明文字")
        install_hover_tip(self.relatedSwitch, "相关作品", "下载与当前作品相关的作品")
        install_hover_tip(self.coversSwitch, "小说封面", "下载小说作品的封面图片")
        install_hover_tip(self.ugoiraCombo, "动图 (Ugoira)", "设置动图作品的下载方式（True/original/False）")
        install_hover_tip(self.updateExistBtn, "更新已有文件夹", "更新已存在的画师文件夹中的作品")
        install_hover_tip(self.removeRepeatBtn, "删除重复图片", "检查并删除本地重复的图片文件")
        install_hover_tip(self.saveBtn, "保存配置", "保存当前所有 Pixiv 配置")
        install_hover_tip(self.closeBtn, "关闭", "关闭配置弹窗")

    # ---- 日志 ----
    def _on_log(self, msg):
        self._log_text.append(str(msg))
        self.logLabel.setText("\n".join(self._log_text[-8:]))

    # ---- Token ----
    def _on_get_token(self):
        """获取 Refresh Token（打开 Pixiv 登录授权页）"""
        try:
            url, hint = self._downloader.get_login_url()
            self.tokenStatus.setText(
                "请在浏览器中打开授权地址并完成登录，然后将回调地址粘贴到上方输入框。")
            QDesktopServices.openUrl(QUrl(url))
            QMessageBox.information(self, "获取 Refresh Token", hint)
        except Exception as e:
            show_error(self, "获取失败", str(e))

    def _on_complete_login(self):
        """使用授权 code 完成登录"""
        code = self.codeEdit.text().strip()
        if not code:
            show_error(self, "提示", "请先粘贴浏览器回调地址或 code")
            return
        try:
            self._downloader.login_with_code(code)
            token = get_pixiv_refresh_token()
            self.tokenEdit.setText(token)
            self.tokenStatus.setText("✅ 登录成功，Refresh Token 已保存到数据库")
            show_success(self, "登录成功", "Refresh Token 已保存到数据库")
        except Exception as e:
            show_error(self, "登录失败", str(e))

    def _on_save_token(self):
        """手动保存 refresh token 到数据库"""
        token = self.tokenEdit.text().strip()
        if not token:
            show_error(self, "提示", "请输入 Refresh Token")
            return
        try:
            self._downloader.login_with_refresh_token(token)
            self.tokenStatus.setText("✅ Refresh Token 已保存到数据库")
            show_success(self, "已保存", "Refresh Token 已保存到数据库")
        except Exception as e:
            show_error(self, "验证失败", str(e))

    # ---- 工具 ----
    def _on_update_existing(self):
        """更新已存在的画师文件夹"""
        try:
            self._on_save(show_msg=False)
            self.logLabel.setText("正在更新已存在的文件夹...")
            fast = self.fastUpdateSwitch.isChecked()
            self._downloader.update_exist(fast=fast)
            show_success(self, "完成", "已更新存在的文件夹")
        except LoginRequiredError as e:
            show_error(self, "未登录", str(e))
        except Exception as e:
            show_error(self, "更新失败", str(e))

    def _on_remove_repeat(self):
        """删除重复图片"""
        try:
            self._on_save(show_msg=False)
            self.logLabel.setText("正在删除重复图片...")
            self._downloader.remove_repeat()
            show_success(self, "完成", "已完成删除重复图片")
        except Exception as e:
            show_error(self, "删除失败", str(e))

    # ---- 保存 ----
    def _on_save(self, show_msg=True):
        """保存配置到全局配置"""
        try:
            CFG['pixiv_images_per_download'] = self.imagesPerDownload.value()
            CFG['pixiv_crawl_pages'] = self.crawlPages.value()
            CFG['pixiv_max_posts'] = self.maxPosts.value()
            CFG['pixiv_max_images'] = self.maxImages.value()
            CFG['pixiv_tag_language'] = self.tagLangCombo.currentText()
            CFG['pixiv_update_existing'] = self.updateExistingSwitch.isChecked()
            CFG['pixiv_skip_manga'] = self.skipMangaSwitch.isChecked()
            CFG['pixiv_fast_update'] = self.fastUpdateSwitch.isChecked()
            CFG['pixiv_metadata'] = self.metadataSwitch.isChecked()
            CFG['pixiv_metadata_bookmark'] = self.metadataBookmarkSwitch.isChecked()
            CFG['pixiv_comments'] = self.commentsSwitch.isChecked()
            CFG['pixiv_captions'] = self.captionsSwitch.isChecked()
            CFG['pixiv_related'] = self.relatedSwitch.isChecked()
            CFG['pixiv_covers'] = self.coversSwitch.isChecked()
            CFG['pixiv_ugoira'] = self.ugoiraCombo.currentText()
            if show_msg:
                show_success(self, "已保存", "Pixiv 配置已保存")
        except Exception as e:
            show_error(self, "保存失败", str(e))


# ═══════════════════════════════════════════════════════════
#  功能清单弹窗
# ═══════════════════════════════════════════════════════════
class PixivFeatureDialog(QDialog):
    """Pixiv 功能清单弹窗

    展示源代码中解析出的其他功能开关（暂时不放在配置弹窗中的）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pixiv 功能清单")
        self.setModal(True)
        self.resize(520, 520)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        titleLabel = SubtitleLabel("Pixiv 功能清单", self)
        layout.addWidget(titleLabel)
        # 设置弹窗最小高度，确保内容不被底部按钮遮挡
        self.setMinimumSize(520, 520)
        self.setMinimumHeight(520)
        caption = CaptionLabel(
            "以下为 pixivd-3.3 与 gallery-dl 下载器提供的其他功能开关", self)
        caption.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + ";")
        layout.addWidget(caption)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scrollWidget = QWidget()
        formLayout = QVBoxLayout(scrollWidget)
        formLayout.setSpacing(8)

        # ═══ 功能开关列表 ═══
        group = QGroupBox("下载器功能开关", scrollWidget)
        gLayout = QVBoxLayout(group)

        def add_switch(key, label, desc, default=False):
            row = QWidget(group)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            s = SwitchButton(row)
            s.setChecked(bool(CFG.get(key, default)))
            rl.addWidget(s)
            rl.addSpacing(8)
            textCol = QVBoxLayout()
            nameLabel = BodyLabel(label, row)
            textCol.addWidget(nameLabel)
            if desc:
                descLabel = CaptionLabel(desc, row)
                descLabel.setStyleSheet(
                    "color: " + theme_color('#909399', '#8A8A8A') + ";")
                textCol.addWidget(descLabel)
            rl.addLayout(textCol, 1)
            gLayout.addWidget(row)
            return s

        self.sanitySwitch = add_switch(
            'pixiv_sanity', "安全过滤绕过",
            "对需要 R-18 确认的作品启用默认绕过", True)
        self.includeEntry = QLineEdit(group)
        self.includeEntry.setPlaceholderText("额外包含的内容（如 sketch = 草稿，all = 全部）")
        self.includeEntry.setText(CFG.get('pixiv_include', ''))
        gLayout.addWidget(BodyLabel("包含条目", group))
        gLayout.addWidget(self.includeEntry)

        self.embedsSwitch = add_switch(
            'pixiv_embeds', "嵌入内容",
            "获取小说中嵌入的图片/视频", False)
        self.noSkipSwitch = add_switch(
            'pixiv_no_skip', "覆盖已存在文件",
            "不跳过已下载的重复文件（强制重新下载）", False)
        self.metadataJsonSwitch = add_switch(
            'pixiv_metadata_json', "写元数据 JSON",
            "为每个文件生成 .json 元数据文件", False)

        formLayout.addWidget(group)

        # ═══ 说明 ═══
        infoLabel = CaptionLabel(
            "💡 以上开关对应 pixivd-3.3 / gallery-dl 的功能选项。\n"
            "配置弹窗中的开关与这里互补，构成完整功能集。", scrollWidget)
        infoLabel.setWordWrap(True)
        infoLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + ";")
        formLayout.addWidget(infoLabel)

        # 移除 stretch，让滚动区正确占满空间
        # formLayout.addStretch()
        scroll.setWidget(scrollWidget)
        # 设置滚动区最小高度
        scroll.setMinimumHeight(400)
        layout.addWidget(scroll, 1)

        # ── 底部 ──
        bottomRow = QHBoxLayout()
        bottomRow.addStretch()
        self.saveBtn = PrimaryPushButton(FIF.ACCEPT, "保存设置", self)
        self.saveBtn.clicked.connect(self._on_save)
        bottomRow.addWidget(self.saveBtn)
        self.closeBtn = PushButton(FIF.CLOSE, "关闭", self)
        self.closeBtn.clicked.connect(self.close)
        bottomRow.addWidget(self.closeBtn)
        layout.addLayout(bottomRow)

        # ── Pixiv 功能清单弹窗悬停提示 ──
        install_hover_tip(self.sanitySwitch, "安全过滤绕过", "对需要 R-18 确认的作品启用默认绕过")
        install_hover_tip(self.includeEntry, "包含条目", "额外包含的内容（如 sketch = 草稿，all = 全部）")
        install_hover_tip(self.embedsSwitch, "嵌入内容", "获取小说中嵌入的图片/视频")
        install_hover_tip(self.noSkipSwitch, "覆盖已存在文件", "不跳过已下载的重复文件（强制重新下载）")
        install_hover_tip(self.metadataJsonSwitch, "写元数据 JSON", "为每个文件生成 .json 元数据文件")
        install_hover_tip(self.saveBtn, "保存设置", "保存功能清单设置")
        install_hover_tip(self.closeBtn, "关闭", "关闭功能清单弹窗")

    def _on_save(self):
        """保存功能清单设置"""
        try:
            CFG['pixiv_sanity'] = self.sanitySwitch.isChecked()
            CFG['pixiv_include'] = self.includeEntry.text().strip()
            CFG['pixiv_embeds'] = self.embedsSwitch.isChecked()
            CFG['pixiv_no_skip'] = self.noSkipSwitch.isChecked()
            CFG['pixiv_metadata_json'] = self.metadataJsonSwitch.isChecked()
            show_success(self, "已保存", "功能清单设置已保存")
        except Exception as e:
            show_error(self, "保存失败", str(e))