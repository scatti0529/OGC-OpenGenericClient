# -*- coding: utf-8 -*-
"""抖音配置弹窗"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QWidget, QFormLayout, QGroupBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QFrame,
)
from qfluentwidgets import (
    FluentIcon as FIF, PrimaryPushButton, PushButton, LineEdit,
    InfoBar, InfoBarPosition, CaptionLabel, SubtitleLabel,
    SwitchButton, ComboBox,
)

from core.config import config as CFG
from ui.widgets.theme import theme_color


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
#  抖音配置弹窗
# ═══════════════════════════════════════════════════════════
class DouyinConfigDialog(QDialog):
    """抖音配置弹窗

    包含:
    - 输出目录
    - 最大下载数
    - 强制重新下载
    - 保存元数据（封面/文案/原声/JSON）
    - HTTP 相关配置（超时/重试/并发）
    - API 相关配置（分页/请求间隔）
    - 下载相关配置（下载间隔/限速/重试）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("抖音配置")
        self.setModal(True)
        self.resize(560, 680)
        self.setMinimumSize(560, 680)
        # 确保滚动区有足够的空间显示内容
        self.setMinimumHeight(680)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── 标题 ──
        titleLabel = SubtitleLabel("抖音下载配置", self)
        layout.addWidget(titleLabel)
        caption = CaptionLabel(
            "配置抖音视频/合集下载参数（自动保存到全局配置）", self)
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

        # ═══ 下载行为配置 ═══
        behaviorGroup = QGroupBox("⚙️ 下载行为", scrollWidget)
        behaviorForm = QFormLayout(behaviorGroup)
        behaviorForm.setSpacing(8)

        self.maxCountsSpin = QSpinBox(behaviorGroup)
        self.maxCountsSpin.setRange(0, 10000)
        self.maxCountsSpin.setValue(int(CFG.get('douyin_max_counts', 0) or 0))
        self.maxCountsSpin.setSpecialValueText("不限（0 = 全部）")
        self.maxCountsSpin.setToolTip("最大下载视频数，0 表示不限")
        behaviorForm.addRow("最大下载数:", self.maxCountsSpin)

        self.forceSwitch = SwitchButton(behaviorGroup)
        self.forceSwitch.setChecked(bool(CFG.get('douyin_force', False)))
        self.forceSwitch.setToolTip("忽略进度数据库记录，强制重新下载")
        behaviorForm.addRow("强制重新下载:", self.forceSwitch)

        self.enableProgressSwitch = SwitchButton(behaviorGroup)
        self.enableProgressSwitch.setChecked(bool(CFG.get('douyin_enable_progress', True)))
        self.enableProgressSwitch.setToolTip("启用后，已下载的视频会记录到数据库，再次下载自动跳过")
        behaviorForm.addRow("启用进度记录:", self.enableProgressSwitch)

        formLayout.addWidget(behaviorGroup)

        # ═══ 元数据保存配置 ═══
        metaGroup = QGroupBox("🎞 保存元数据", scrollWidget)
        metaForm = QFormLayout(metaGroup)
        metaForm.setSpacing(6)

        self.saveMetadataSwitch = SwitchButton(metaGroup)
        self.saveMetadataSwitch.setChecked(bool(CFG.get('douyin_save_metadata', False)))
        self.saveMetadataSwitch.setToolTip("开启后，每个视频额外保存封面/文案/原声/JSON")
        metaForm.addRow("保存元数据:", self.saveMetadataSwitch)

        self.saveCoverChk = QCheckBox("封面图 (.jpg)", metaGroup)
        self.saveCoverChk.setChecked(bool(CFG.get('douyin_save_cover', True)))
        metaForm.addRow("", self.saveCoverChk)

        self.saveDescChk = QCheckBox("文案 (.txt)", metaGroup)
        self.saveDescChk.setChecked(bool(CFG.get('douyin_save_desc', True)))
        metaForm.addRow("", self.saveDescChk)

        self.saveMusicChk = QCheckBox("原声 (.mp3)", metaGroup)
        self.saveMusicChk.setChecked(bool(CFG.get('douyin_save_music', True)))
        metaForm.addRow("", self.saveMusicChk)

        self.saveJsonChk = QCheckBox("信息 (.json)", metaGroup)
        self.saveJsonChk.setChecked(bool(CFG.get('douyin_save_json', True)))
        metaForm.addRow("", self.saveJsonChk)

        formLayout.addWidget(metaGroup)

        # ═══ HTTP / API 配置 ═══
        httpGroup = QGroupBox("🌐 HTTP / API 配置", scrollWidget)
        httpForm = QFormLayout(httpGroup)
        httpForm.setSpacing(8)

        self.timeoutSpin = QSpinBox(httpGroup)
        self.timeoutSpin.setRange(5, 120)
        self.timeoutSpin.setValue(int(CFG.get('douyin_timeout', 15)))
        self.timeoutSpin.setSuffix(" 秒")
        httpForm.addRow("请求超时:", self.timeoutSpin)

        self.maxRetriesSpin = QSpinBox(httpGroup)
        self.maxRetriesSpin.setRange(0, 20)
        self.maxRetriesSpin.setValue(int(CFG.get('douyin_max_retries', 5)))
        httpForm.addRow("API 最大重试:", self.maxRetriesSpin)

        self.maxTasksSpin = QSpinBox(httpGroup)
        self.maxTasksSpin.setRange(1, 10)
        self.maxTasksSpin.setValue(int(CFG.get('douyin_max_tasks', 1)))
        httpForm.addRow("最大并发任务:", self.maxTasksSpin)

        self.pageCountsSpin = QSpinBox(httpGroup)
        self.pageCountsSpin.setRange(1, 50)
        self.pageCountsSpin.setValue(int(CFG.get('douyin_page_counts', 10)))
        self.pageCountsSpin.setToolTip("合集 API 分页每页条数（不建议超过 20，可能触发风控）")
        httpForm.addRow("分页条数:", self.pageCountsSpin)

        self.apiIntervalSpin = QDoubleSpinBox(httpGroup)
        self.apiIntervalSpin.setRange(0.1, 30.0)
        self.apiIntervalSpin.setSingleStep(0.5)
        self.apiIntervalSpin.setValue(float(CFG.get('douyin_api_request_interval', 2.0)))
        self.apiIntervalSpin.setSuffix(" 秒")
        httpForm.addRow("API 请求间隔:", self.apiIntervalSpin)

        formLayout.addWidget(httpGroup)

        # ═══ 下载质量配置 ═══
        dlGroup = QGroupBox("📥 下载质量配置", scrollWidget)
        dlForm = QFormLayout(dlGroup)
        dlForm.setSpacing(8)

        self.mixIntervalSpin = QSpinBox(dlGroup)
        self.mixIntervalSpin.setRange(0, 600)
        self.mixIntervalSpin.setValue(int(CFG.get('douyin_mix_download_interval', 10)))
        self.mixIntervalSpin.setSuffix(" 秒")
        self.mixIntervalSpin.setToolTip("合集内视频下载间隔")
        dlForm.addRow("合集下载间隔:", self.mixIntervalSpin)

        self.downloadRetriesSpin = QSpinBox(dlGroup)
        self.downloadRetriesSpin.setRange(0, 10)
        self.downloadRetriesSpin.setValue(int(CFG.get('douyin_download_max_retries', 3)))
        self.downloadRetriesSpin.setToolTip("下载失败时的最大重试次数（0 表示不重试）")
        dlForm.addRow("下载失败重试:", self.downloadRetriesSpin)

        self.retryIntervalSpin = QDoubleSpinBox(dlGroup)
        self.retryIntervalSpin.setRange(0.5, 60.0)
        self.retryIntervalSpin.setSingleStep(0.5)
        self.retryIntervalSpin.setValue(float(CFG.get('douyin_download_retry_interval', 5.0)))
        self.retryIntervalSpin.setSuffix(" 秒")
        dlForm.addRow("重试间隔:", self.retryIntervalSpin)

        self.maxSpeedSpin = QSpinBox(dlGroup)
        self.maxSpeedSpin.setRange(0, 104857600)
        self.maxSpeedSpin.setSingleStep(1048576)
        self.maxSpeedSpin.setValue(int(CFG.get('douyin_max_download_speed', 10485760)))
        self.maxSpeedSpin.setSpecialValueText("不限速（0）")
        self.maxSpeedSpin.setToolTip("最大下载速度（字节/秒），0 表示不限速；10MB/s = 10485760")
        dlForm.addRow("最大下载速度:", self.maxSpeedSpin)

        formLayout.addWidget(dlGroup)

        # 移除 formLayout 中的 stretch，让滚动区正确占满可用空间
        # formLayout.addStretch()
        scroll.setWidget(scrollWidget)
        # 设置滚动区最小高度，确保内容不被底部按钮遮挡
        scroll.setMinimumHeight(500)
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

    def _on_save(self):
        """保存配置到全局配置"""
        try:
            CFG['douyin_max_counts'] = self.maxCountsSpin.value()
            CFG['douyin_force'] = self.forceSwitch.isChecked()
            CFG['douyin_enable_progress'] = self.enableProgressSwitch.isChecked()

            CFG['douyin_save_metadata'] = self.saveMetadataSwitch.isChecked()
            CFG['douyin_save_cover'] = self.saveCoverChk.isChecked()
            CFG['douyin_save_desc'] = self.saveDescChk.isChecked()
            CFG['douyin_save_music'] = self.saveMusicChk.isChecked()
            CFG['douyin_save_json'] = self.saveJsonChk.isChecked()

            CFG['douyin_timeout'] = self.timeoutSpin.value()
            CFG['douyin_max_retries'] = self.maxRetriesSpin.value()
            CFG['douyin_max_tasks'] = self.maxTasksSpin.value()
            CFG['douyin_page_counts'] = self.pageCountsSpin.value()
            CFG['douyin_api_request_interval'] = self.apiIntervalSpin.value()

            CFG['douyin_mix_download_interval'] = self.mixIntervalSpin.value()
            CFG['douyin_download_max_retries'] = self.downloadRetriesSpin.value()
            CFG['douyin_download_retry_interval'] = self.retryIntervalSpin.value()
            CFG['douyin_max_download_speed'] = self.maxSpeedSpin.value()

            show_success(self, "已保存", "抖音配置已保存")
        except Exception as e:
            show_error(self, "保存失败", str(e))


# ═══════════════════════════════════════════════════════════
#  抖音功能清单弹窗
# ═══════════════════════════════════════════════════════════
class DouyinFeatureDialog(QDialog):
    """抖音功能清单弹窗（展示 douyinDL-main 的进阶功能）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("抖音功能清单")
        self.setModal(True)
        self.resize(520, 420)
        self.setMinimumSize(520, 420)
        self.setMinimumHeight(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        titleLabel = SubtitleLabel("抖音功能清单", self)
        layout.addWidget(titleLabel)
        caption = CaptionLabel(
            "douyinDL-main 提供的完整功能说明", self)
        caption.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + ";")
        layout.addWidget(caption)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scrollWidget = QWidget()
        formLayout = QVBoxLayout(scrollWidget)
        formLayout.setSpacing(8)

        # ═══ 功能列表 ═══
        group = QGroupBox("📋 功能说明", scrollWidget)
        gLayout = QVBoxLayout(group)

        features = [
            ("🎬 单视频下载", "支持分享短链接、PC Web 端链接等格式"),
            ("📚 合集下载", "自动识别合集链接，创建日期+合集名子目录"),
            ("🚫 无水印", "通过 f2 签名接口获取无水印视频"),
            ("🖼 封面保存", "保存视频封面图到 cover 目录"),
            ("📝 文案保存", "保存视频文案全文到 caption 目录"),
            ("🎵 原声保存", "保存视频原声 MP3 到 music 目录"),
            ("📄 JSON 元数据", "保存完整视频信息 JSON 到 metadata 目录"),
            ("🔄 断点续传", "已下载视频自动跳过，支持增量下载"),
            ("🔁 失败重试", "下载失败自动重试，并可一键重试全部失败记录"),
            ("⏱ 请求间隔", "合集视频间随机间隔，避免被风控识别"),
            ("🚀 速度限制", "可配置最大下载速度，避免占用全部带宽"),
        ]
        for name, desc in features:
            row = QWidget(group)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            nameLabel = QLabel(name, row)
            nameLabel.setStyleSheet("font-size: 13px; font-weight: bold;")
            rl.addWidget(nameLabel, 0)
            rl.addSpacing(12)
            descLabel = QLabel(desc, row)
            descLabel.setStyleSheet("font-size: 12px; color: " + theme_color('#909399', '#8A8A8A') + ";")
            descLabel.setWordWrap(True)
            rl.addWidget(descLabel, 1)
            gLayout.addWidget(row)

        formLayout.addWidget(group)

        infoLabel = CaptionLabel(
            "💡 配置弹窗中的「保存元数据」开启后，"
            "封面/文案/原声/JSON 会按类型分别放在 sourcefiles 目录中。", scrollWidget)
        infoLabel.setWordWrap(True)
        infoLabel.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + ";")
        formLayout.addWidget(infoLabel)

        # 移除 stretch，让滚动区正确占满空间
        # formLayout.addStretch()
        scroll.setWidget(scrollWidget)
        # 设置滚动区最小高度，确保内容不被底部按钮遮挡
        scroll.setMinimumHeight(320)
        layout.addWidget(scroll, 1)

        # ── 底部 ──
        bottomRow = QHBoxLayout()
        bottomRow.addStretch()
        self.closeBtn = PushButton(FIF.CLOSE, "关闭", self)
        self.closeBtn.clicked.connect(self.close)
        bottomRow.addWidget(self.closeBtn)
        layout.addLayout(bottomRow)