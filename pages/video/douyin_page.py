# -*- coding: utf-8 -*-
"""抖音专用解析下载页面

集成 douyinDL-main 核心功能：
- 解析分享链接 → 下方生成媒体卡片（预览图 + 下载按钮）
- 点击卡片下载单个视频（自动按类型分类到 videos/images/audios）
- 下载日志弹窗
"""
import asyncio
import re
import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QGridLayout, QDialog, QTextEdit, QApplication,
    QStackedWidget,
)
from qfluentwidgets import (
    CardWidget, FluentIcon as FIF, PushButton, PrimaryPushButton,
    CaptionLabel, SubtitleLabel, TextEdit, ProgressBar,
    BodyLabel, InfoBar, InfoBarPosition,
)

from services.douyin_service import DouyinDownloader
from pages.video.douyin_dialogs import (
    DouyinConfigDialog, DouyinFeatureDialog,
    show_error, show_info, show_success,
)
from core.config import config as CFG
from ui.widgets.theme import theme_color
from ui.widgets.ui_utils import install_hover_tip


def extract_urls(text: str) -> list:
    found = re.findall(r"https?://[^\s，,]+", text or "")
    urls = [u.strip("`") for u in found if u.strip("`")]
    return list(dict.fromkeys(urls))


# ═══════════════════════════════════════════════════════════
#  日志弹窗
# ═══════════════════════════════════════════════════════════
class DouyinLogDialog(QDialog):
    """抖音下载日志弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("抖音下载日志")
        self.setModal(False)
        self.resize(640, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        titleLabel = SubtitleLabel("📋 下载日志", self)
        layout.addWidget(titleLabel)

        self.logEdit = QTextEdit(self)
        self.logEdit.setReadOnly(True)
        self.logEdit.setPlaceholderText("下载日志将显示在这里...")
        self.logEdit.setStyleSheet(
            "QTextEdit { background-color: " + theme_color('#F5F5F5', '#1E1E1E') +
            "; border: none; border-radius: 6px; font-family: Consolas, monospace; font-size: 12px; }")
        layout.addWidget(self.logEdit, 1)

        btnRow = QHBoxLayout()
        btnRow.addStretch()
        self.clearBtn = PushButton(FIF.DELETE, "清空日志", self)
        self.clearBtn.clicked.connect(lambda: self.logEdit.clear())
        btnRow.addWidget(self.clearBtn)
        self.closeBtn = PushButton(FIF.CLOSE, "关闭", self)
        self.closeBtn.clicked.connect(self.close)
        btnRow.addWidget(self.closeBtn)
        layout.addLayout(btnRow)

    def append_log(self, text):
        self.logEdit.append(text)
        sb = self.logEdit.verticalScrollBar()
        sb.setValue(sb.maximum())


# ═══════════════════════════════════════════════════════════
#  解析线程
# ═══════════════════════════════════════════════════════════
class DouyinParseThread(QThread):
    """抖音解析线程：解析链接并返回视频列表"""
    finished = pyqtSignal(object, str)   # (result, url)
    error = pyqtSignal(str, str)         # (message, url)
    log = pyqtSignal(str)

    def __init__(self, downloader, url, parent=None):
        super().__init__(parent)
        self.downloader = downloader
        self.url = url

    def run(self):
        try:
            result = asyncio.run(self.downloader.parse(
                self.url, log_callback=lambda m: self.log.emit(m)))
            result['url'] = self.url
            self.finished.emit(result, self.url)
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n{traceback.format_exc()}", self.url)


# ═══════════════════════════════════════════════════════════
#  单视频下载线程
# ═══════════════════════════════════════════════════════════
class DouyinDownloadThread(QThread):
    """单个视频下载线程"""
    done = pyqtSignal(bool, str, dict)
    progress = pyqtSignal(int, int)

    def __init__(self, downloader, video_data, kind, resource_id, mix_name,
                 share_url, index, total, parent=None):
        super().__init__(parent)
        self.downloader = downloader
        self.video_data = video_data
        self.kind = kind
        self.resource_id = resource_id
        self.mix_name = mix_name
        self.share_url = share_url
        self.index = index
        self.total = total

    def run(self):
        try:
            result = asyncio.run(self.downloader.download_single(
                self.video_data, self.kind, self.resource_id, self.mix_name,
                self.share_url, self.index, self.total,
                progress_callback=lambda c, t, i, n: self.progress.emit(c, t),
                log_callback=lambda m: None,
            ))
            ok = result.get('success', False)
            skipped = result.get('skipped', False)
            if ok:
                msg = '已跳过（已存在）' if skipped else '下载完成'
            else:
                msg = result.get('error', '下载失败')
            self.done.emit(ok, msg, result)
        except Exception as e:
            self.done.emit(False, str(e), {})


# ═══════════════════════════════════════════════════════════
#  媒体卡片
# ═══════════════════════════════════════════════════════════
class DouyinMediaCard(CardWidget):
    """抖音视频结果卡片（预览图 + 标题 + 类型 + 下载按钮）"""

    def __init__(self, video_data, index, total, parent=None,
                 src_url='', kind='one', resource_id='', mix_name=''):
        super().__init__(parent=parent)
        self.video_data = video_data
        self.index = index
        self.total = total
        self.src_url = src_url          # 来源链接
        self.kind = kind                # 来源解析类型
        self.resource_id = resource_id  # 来源资源ID
        self.mix_name = mix_name        # 来源合集名
        self._download_active = False
        self._preview_thread = None

        self.setFixedSize(220, 260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.previewLabel = QLabel("加载预览...", self)
        self.previewLabel.setAlignment(Qt.AlignCenter)
        self.previewLabel.setFixedSize(196, 130)
        self.previewLabel.setStyleSheet(theme_color(
            "background-color: rgba(0,0,0,0.08); border-radius: 6px;",
            "background-color: rgba(255,255,255,0.08); border-radius: 6px;"))
        layout.addWidget(self.previewLabel, 0, Qt.AlignCenter)

        desc = video_data.get('desc') or (f'视频 {index}' if total > 1 else '视频')
        if len(desc) > 30:
            desc = desc[:30] + '...'
        self.titleLabel = BodyLabel(desc, self)
        self.titleLabel.setStyleSheet("font-size: 12px; color: " + theme_color('#555555', '#CCCCCC') + ";")
        self.titleLabel.setWordWrap(True)
        layout.addWidget(self.titleLabel)

        media_type = 'video'
        type_text = '🎬 视频'
        if video_data.get('images'):
            media_type = 'image'
            type_text = '🖼 图片'
        self.typeLabel = CaptionLabel(type_text, self)
        self.typeLabel.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + ";")
        layout.addWidget(self.typeLabel)

        if total > 1:
            self.seqLabel = CaptionLabel(f"第 {index}/{total} 个", self)
            self.seqLabel.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + ";")
            layout.addWidget(self.seqLabel)

        layout.addStretch()

        self.downloadBtn = PrimaryPushButton(FIF.DOWNLOAD, "下载", self)
        self.downloadBtn.clicked.connect(self._download_clicked)
        layout.addWidget(self.downloadBtn)

        self.progressBar = ProgressBar(self)
        self.progressBar.setVisible(False)
        layout.addWidget(self.progressBar)

        self._load_preview()

    def _preview_url(self):
        for key in ('cover', 'video_cover', 'origin_cover', 'dynamic_cover'):
            url = self.video_data.get(key)
            if url:
                return url
        return ''

    def _load_preview(self):
        url = self._preview_url()
        if not url:
            self.previewLabel.setText("无预览")
            return
        self._preview_thread = _PreviewLoadThread(url, self)
        self._preview_thread.loaded.connect(self._on_preview_loaded)
        self._preview_thread.failed.connect(lambda: self.previewLabel.setText("预览加载失败"))
        self._preview_thread.start()

    def _on_preview_loaded(self, pixmap):
        try:
            scaled = pixmap.scaled(196, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.previewLabel.setPixmap(scaled)
        except Exception:
            self.previewLabel.setText("预览加载失败")

    def _download_clicked(self):
        if self._download_active:
            return
        page = self._find_douyin_page()
        if page is not None:
            page._enqueue_download(self)

    def source_context(self):
        """获取来源链接的解析上下文（kind, resource_id, mix_name, share_url）"""
        return (self.kind, self.resource_id, self.mix_name, self.src_url)

    def _find_douyin_page(self):
        page = self.parent()
        while page is not None and not hasattr(page, '_enqueue_download'):
            page = page.parent()
        return page

    def mark_queued(self):
        self._download_active = True
        self.downloadBtn.setEnabled(False)
        self.downloadBtn.setText("排队中")
        self.downloadBtn.setIcon(FIF.SYNC)
        self.downloadBtn.setStyleSheet("")

    def mark_downloading(self):
        self.downloadBtn.setEnabled(False)
        self.downloadBtn.setText("下载中")
        self.downloadBtn.setIcon(FIF.DOWNLOAD)
        self.downloadBtn.setStyleSheet("")
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)

    def mark_done(self):
        self._download_active = False
        self.downloadBtn.setEnabled(False)
        self.downloadBtn.setText("已下载")
        self.downloadBtn.setIcon(FIF.ACCEPT)
        self.downloadBtn.setStyleSheet(
            "color: #67C23A; border: 1px solid #67C23A; border-radius: 6px;")
        self.progressBar.setVisible(False)

    def mark_error(self):
        self._download_active = False
        self.downloadBtn.setEnabled(True)
        self.downloadBtn.setText("重试")
        self.downloadBtn.setIcon(FIF.DOWNLOAD)
        self.downloadBtn.setStyleSheet("")
        self.progressBar.setVisible(False)


class _PreviewLoadThread(QThread):
    """预览图加载线程"""
    loaded = pyqtSignal(object)
    failed = pyqtSignal()

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        # 低优先级，避免阻塞主界面绘制、提升流畅度（需在线程启动后设置）
        try:
            self.setPriority(QThread.LowPriority)
        except Exception:
            pass
        try:
            import requests
            resp = requests.get(self.url, timeout=10)
            pix = QPixmap()
            pix.loadFromData(resp.content)
            if not pix.isNull():
                self.loaded.emit(pix)
            else:
                self.failed.emit()
        except Exception:
            self.failed.emit()


# ═══════════════════════════════════════════════════════════
#  抖音页面
# ═══════════════════════════════════════════════════════════
class DouyinPage(QScrollArea):
    """抖音专用解析下载页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DouyinPage")
        self._parse_thread = None
        self._dl_thread = None
        self._download_queue = []
        self._download_active = False
        self._cards = []
        self._parsing = False
        self._downloading = False
        self._log_dialog = None
        self._parse_result = None

        self._kind = ''
        self._resource_id = ''
        self._mix_name = ''
        self._share_url = ''

        # 多链接解析队列（支持回车/英文逗号分隔，依次解析）
        self._parse_urls = []
        self._parse_queue = []
        self._queue_parsing = False
        self._active_parsers = []
        self._parse_total = 0
        self._parse_done = 0
        self._parse_failed = 0
        self._MAX_CONCURRENT = 2  # 同时最多并发解析条数，其余入队依次解析

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.view = QWidget(self)
        self.layout = QVBoxLayout(self.view)
        self.layout.setSpacing(12)
        self.setViewportMargins(0, 64, 0, 0)
        self.layout.setContentsMargins(24, 0, 24, 24)
        self.setWidget(self.view)

        self._build_input_card()
        self._build_results_area()

    # ── UI ──
    def _build_input_card(self):
        inputCard = CardWidget(self.view)
        inputLayout = QVBoxLayout(inputCard)
        inputLayout.setSpacing(10)
        inputLayout.setContentsMargins(16, 16, 16, 16)

        titleRow = QHBoxLayout()
        titleLabel = SubtitleLabel("🎬 抖音解析下载", inputCard)
        titleLabel.setStyleSheet("font-size: 16px; font-weight: bold;")
        titleRow.addWidget(titleLabel)
        titleRow.addStretch()
        inputLayout.addLayout(titleRow)

        urlRow = QHBoxLayout()
        self.urlEdit = TextEdit(inputCard)
        self.urlEdit.setPlaceholderText(
            "在此粘贴抖音分享链接或包含链接的完整分享文本\n"
            "支持多条链接（回车或英文逗号分隔）\n"
            "支持合集链接 / 单视频链接 / 分享短链")
        self.urlEdit.setAcceptRichText(False)  # 仅纯文本，避免粘贴黑条
        self.urlEdit.setFixedHeight(150)
        urlRow.addWidget(self.urlEdit, 1)

        btnCol = QVBoxLayout()
        self.pasteBtn = PushButton(FIF.PASTE, "粘贴", inputCard)
        self.pasteBtn.clicked.connect(self._on_paste)
        btnCol.addWidget(self.pasteBtn)
        self.appendBtn = PushButton(FIF.ADD, "追加粘贴", inputCard)
        self.appendBtn.setToolTip("若输入框已有内容，则在末尾回车后追加粘贴剪贴板内容")
        self.appendBtn.clicked.connect(self._on_append_paste)
        btnCol.addWidget(self.appendBtn)
        self.parseBtn = PrimaryPushButton(FIF.SYNC, "解析", inputCard)
        self.parseBtn.clicked.connect(self._on_parse)
        btnCol.addWidget(self.parseBtn)
        urlRow.addLayout(btnCol)

        inputLayout.addLayout(urlRow)

        # 功能按钮行：配置/功能清单/下载日志/重试失败记录（并入解析容器）
        funcRow = QHBoxLayout()
        funcRow.setSpacing(8)
        self.configBtn = PushButton(FIF.SETTING, "配置", inputCard)
        self.configBtn.clicked.connect(self._on_open_config)
        self.featureBtn = PushButton(FIF.MORE, "功能清单", inputCard)
        self.featureBtn.clicked.connect(self._on_open_features)
        self.logBtn = PushButton(FIF.DOCUMENT, "下载日志", inputCard)
        self.logBtn.clicked.connect(self._on_open_log)
        self.retryBtn = PushButton(FIF.SYNC, "重试失败记录", inputCard)
        self.retryBtn.clicked.connect(self._on_retry_failed)
        for btn in (self.configBtn, self.featureBtn, self.logBtn, self.retryBtn):
            btn.adjustSize()
            funcRow.addWidget(btn)
        funcRow.addStretch()
        inputLayout.addLayout(funcRow)

        # ── 抖音页面悬停功能简介 ──
        install_hover_tip(self.urlEdit, "链接输入", "粘贴抖音分享链接或完整分享文本，支持多条链接")
        install_hover_tip(self.pasteBtn, "粘贴", "清空输入框并粘贴剪贴板中的链接")
        install_hover_tip(self.appendBtn, "追加粘贴", "在输入框末尾追加粘贴剪贴板内容")
        install_hover_tip(self.parseBtn, "解析", "解析输入框中的链接，生成媒体卡片列表")
        install_hover_tip(self.configBtn, "配置", "打开抖音下载配置弹窗（下载/元数据/网络等）")
        install_hover_tip(self.featureBtn, "功能清单", "查看 douyinDL 支持的全部功能说明")
        install_hover_tip(self.logBtn, "下载日志", "打开下载日志弹窗，查看下载过程")
        install_hover_tip(self.retryBtn, "重试失败记录", "重试数据库中记录的失败下载任务")

        self.dirLabel = CaptionLabel(self._dir_hint(), inputCard)
        self.dirLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        self.dirLabel.setWordWrap(True)
        inputLayout.addWidget(self.dirLabel)

        self.layout.addWidget(inputCard)

    def _build_results_area(self):
        # 使用 QStackedWidget：无卡片时显示空提示，底部留空不拉长容器
        self._stack = QStackedWidget(self.view)
        self._stack.setStyleSheet("QStackedWidget { border: none; background: transparent; }")

        # 页面 0：结果卡片区
        self.resultsScroll = QScrollArea(self._stack)
        self.resultsScroll.setWidgetResizable(True)
        self.resultsScroll.setFrameShape(QFrame.NoFrame)
        self.resultsScroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.resultsView = QWidget()
        self.resultsGrid = QGridLayout(self.resultsView)
        self.resultsGrid.setSpacing(12)
        self.resultsGrid.setAlignment(Qt.AlignTop)
        self.resultsScroll.setWidget(self.resultsView)
        self._stack.addWidget(self.resultsScroll)  # index 0

        # 页面 1：空提示
        self.emptyWidget = QWidget(self._stack)
        self.emptyLayout = QVBoxLayout(self.emptyWidget)
        self.emptyLayout.setAlignment(Qt.AlignTop)
        self.emptyLabel = QLabel("输入链接后点击「解析」获取视频列表", self.emptyWidget)
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        self.emptyLabel.setStyleSheet(
            "color: " + theme_color('#AAAAAA', '#666666') + "; font-size: 14px;")
        self.emptyLayout.addWidget(self.emptyLabel)
        self._stack.addWidget(self.emptyWidget)  # index 1

        self.layout.addWidget(self._stack, 1)
        self._stack.setCurrentIndex(1)  # 默认显示空提示

    def _dir_hint(self):
        try:
            from services.douyin_service import get_douyin_output_dir
            return f"📁 下载目录: {get_douyin_output_dir()}（图片/视频/音频自动分类）"
        except Exception:
            return "📁 下载目录: douyin-download（图片/视频/音频自动分类）"

    # ── 交互 ──
    def _on_paste(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self.urlEdit.clear()
            self.urlEdit.setPlainText(text)
            show_info(self, "已粘贴", "剪贴板内容已填入输入框")
        else:
            show_info(self, "提示", "剪贴板为空")

    def _on_append_paste(self):
        """追加粘贴：若输入框已有内容，在末尾回车后粘贴；为空则直接粘贴"""
        text = QApplication.clipboard().text().strip()
        if not text:
            show_info(self, "提示", "剪贴板为空")
            return
        current = self.urlEdit.toPlainText()
        if current.strip():
            new_text = current.rstrip() + "\n" + text
        else:
            new_text = text
        self.urlEdit.setPlainText(new_text)
        show_info(self, "已追加", "剪贴板内容已追加到输入框")

    def _on_open_config(self):
        DouyinConfigDialog(self.window()).exec_()
        self.dirLabel.setText(self._dir_hint())

    def _on_open_features(self):
        DouyinFeatureDialog(self.window()).exec_()

    def _on_open_log(self):
        if self._log_dialog is None or not self._log_dialog.isVisible():
            self._log_dialog = DouyinLogDialog(self.window())
            self._log_dialog.show()
        else:
            self._log_dialog.raise_()
            self._log_dialog.activateWindow()

    def _append_log(self, text):
        if self._log_dialog is not None and self._log_dialog.isVisible():
            self._log_dialog.append_log(text)

    def _on_retry_failed(self):
        if self._parsing or self._queue_parsing or self._downloading:
            show_info(self, "任务运行中", "请等待当前任务完成后再操作")
            return

    def _on_parse(self):
        if self._parsing or self._queue_parsing:
            return
        if self._downloading:
            show_info(self, "下载进行中", "有文件正在下载，请等待完成后再解析")
            return

        text = self.urlEdit.toPlainText()
        urls = extract_urls(text)
        if not urls:
            show_info(self, "提示", "请先粘贴抖音分享链接")
            return

        # 先清空旧结果（会同时清理旧的解析队列/活动线程）
        self._clear_results()
        # 初始化多链接解析队列
        self._parse_urls = list(urls)
        self._parse_queue = list(urls)
        self._queue_parsing = True
        self._active_parsers = []
        self._parse_total = len(urls)
        self._parse_done = 0
        self._parse_failed = 0

        self.parseBtn.setEnabled(False)
        self.parseBtn.setText("解析中...")
        self.pasteBtn.setEnabled(False)
        self.appendBtn.setEnabled(False)
        self.urlEdit.setEnabled(False)
        self.emptyLabel.setText(f"正在解析 0/{self._parse_total} ...")
        self._stack.setCurrentIndex(1)

        # 启动解析（并发最多 _MAX_CONCURRENT 条，其余入队）
        for _ in range(min(self._MAX_CONCURRENT, len(self._parse_queue))):
            self._launch_next_parser()

    def _launch_next_parser(self):
        """从解析队列中取出下一条链接启动解析线程"""
        if not self._parse_queue:
            return
        url = self._parse_queue.pop(0)
        downloader = self._build_downloader()
        thread = DouyinParseThread(downloader, url, self)
        thread.log.connect(self._append_log)
        thread.finished.connect(
            lambda result, u=url: self._on_parse_finished(result, u))
        thread.error.connect(
            lambda msg, u=url: self._on_parse_error(msg, u))
        self._active_parsers.append(thread)
        thread.start()

    def _build_downloader(self):
        return DouyinDownloader(
            max_counts=int(CFG.get('douyin_max_counts', 0) or 0),
            config=_build_config(),
            force=bool(CFG.get('douyin_force', False)),
        )

    def _on_parse_finished(self, result, url):
        """单条链接解析完成，追加卡片"""
        self._remove_parser_of(url)
        self._parse_done += 1

        videos = result.get('videos', [])
        kind = result.get('kind', 'one')
        resource_id = result.get('resource_id', '')
        mix_name = result.get('mix_name', '')

        if videos:
            # 暂停重绘以提升大量卡片创建时的流畅度
            self.resultsView.setUpdatesEnabled(False)
            base_row = self.resultsGrid.rowCount()
            total = len(videos)
            for i, video_data in enumerate(videos, 1):
                card = DouyinMediaCard(
                    video_data, i, total, self.resultsView,
                    src_url=url, kind=kind,
                    resource_id=resource_id, mix_name=mix_name,
                )
                row = base_row + (i - 1) // 4
                col = (i - 1) % 4
                self.resultsGrid.addWidget(card, row, col)
                self._cards.append(card)
            self.resultsView.setUpdatesEnabled(True)
            self.resultsView.update()
            self._stack.setCurrentIndex(0)

        self._update_parse_progress()
        # 启动下一条（保持并发数）
        self._launch_next_parser()

    def _on_parse_error(self, message, url):
        """单条链接解析失败，记录后继续下一条"""
        self._remove_parser_of(url)
        self._parse_done += 1
        self._parse_failed += 1
        self._append_log(f"❌ 解析失败: {url} → {message[:200]}")
        self._update_parse_progress()
        # 启动下一条（保持并发数）
        self._launch_next_parser()

    def _update_parse_progress(self):
        """所有活动解析结束后，统一更新解析进度"""
        if self._active_parsers or self._parse_queue:
            self.emptyLabel.setText(
                f"正在解析 {self._parse_done}/{self._parse_total} ...")
            return

        # 全部解析完成
        self._queue_parsing = False
        self.parseBtn.setEnabled(True)
        self.parseBtn.setText("解析")
        self.pasteBtn.setEnabled(not self._downloading)
        self.appendBtn.setEnabled(not self._downloading)
        self.urlEdit.setEnabled(not self._downloading)

        if self._cards:
            self._stack.setCurrentIndex(0)
        else:
            self.emptyLabel.setText("解析失败，未获取到视频信息")
            self._stack.setCurrentIndex(1)

        # 汇总提示
        if self._parse_failed:
            msg = f"共 {self._parse_total} 条链接，成功 {self._parse_total - self._parse_failed} 条，失败 {self._parse_failed} 条"
            show_error(self, "部分链接解析失败", msg)
        else:
            total_media = len(self._cards)
            show_success(self, "解析完成", f"共 {self._parse_total} 条链接，找到 {total_media} 个视频")

    def _remove_parser_of(self, url: str):
        """从活动线程列表中移除指定链接对应的解析线程并回收"""
        for t in list(self._active_parsers):
            if getattr(t, 'url', None) == url:
                try:
                    if t.isRunning():
                        t.wait(500)
                    t.deleteLater()
                except (RuntimeError, Exception):
                    pass
                try:
                    self._active_parsers.remove(t)
                except ValueError:
                    pass
                return

    # ── 下载队列 ──
    def _enqueue_download(self, card):
        if card in self._download_queue or getattr(card, '_download_active', False):
            return
        card.mark_queued()
        self._download_queue.append(card)
        self._process_queue()

    def _process_queue(self):
        if self._download_active:
            return
        if not self._download_queue:
            return
        card = self._download_queue.pop(0)
        self._download_active = True
        self._download_current_card(card)

    def _download_current_card(self, card):
        card.mark_downloading()
        self._downloading = True
        self.parseBtn.setEnabled(False)
        self.pasteBtn.setEnabled(False)
        self.appendBtn.setEnabled(False)
        self.urlEdit.setEnabled(False)

        # 使用卡片自身来源链接的解析上下文（多链接场景下每张卡片可能来自不同链接）
        kind, resource_id, mix_name, share_url = card.source_context()
        downloader = self._build_downloader()
        self._dl_thread = DouyinDownloadThread(
            downloader, card.video_data,
            kind, resource_id, mix_name, share_url,
            card.index, card.total, self,
        )
        self._dl_thread.progress.connect(card.progressBar.setValue)
        self._dl_thread.done.connect(
            lambda ok, msg, result: self._on_download_finished(card, ok, msg))
        self._dl_thread.start()

    def _on_download_finished(self, card, success, message):
        self._download_active = False
        self._downloading = False
        if not self._parsing and not self._queue_parsing:
            self.parseBtn.setEnabled(True)
            self.pasteBtn.setEnabled(True)
            self.appendBtn.setEnabled(True)
            self.urlEdit.setEnabled(True)

        if success:
            card.mark_done()
            self._append_log(f"✅ {card.titleLabel.text()} {message}")
        else:
            card.mark_error()
            self._append_log(f"❌ {card.titleLabel.text()} 下载失败: {message}")

        self._process_queue()

    def _clear_results(self):
        self._download_queue = []
        self._download_active = False
        # 清空解析队列及活动解析线程
        self._parse_queue = []
        for t in list(getattr(self, '_active_parsers', [])):
            try:
                if t.isRunning():
                    t.wait(300)
                t.deleteLater()
            except (RuntimeError, Exception):
                pass
        self._active_parsers = []
        self._queue_parsing = False

        for card in list(self._cards):
            try:
                card.deleteLater()
            except Exception:
                pass
        self._cards = []

        while self.resultsGrid.count():
            item = self.resultsGrid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._stack.setCurrentIndex(1)  # 清空后回到空提示页

    def closeEvent(self, event):
        threads = []
        for attr in ('_parse_thread', '_dl_thread'):
            t = getattr(self, attr, None)
            if t is not None:
                threads.append(t)
        # 回收多链接解析的活动线程
        for t in list(getattr(self, '_active_parsers', [])):
            threads.append(t)
        for t in threads:
            try:
                if t.isRunning():
                    t.requestInterruption()
                    t.wait(1000)
                t.deleteLater()
            except (RuntimeError, Exception):
                pass
        self._active_parsers = []
        super().closeEvent(event)


def _build_config():
    """从全局配置构建 DouyinConfig"""
    from services.douyin_service import DouyinConfig
    cfg = DouyinConfig()
    cfg.save_metadata = bool(CFG.get('douyin_save_metadata', False))
    cfg.save_cover = bool(CFG.get('douyin_save_cover', True))
    cfg.save_desc = bool(CFG.get('douyin_save_desc', True))
    cfg.save_music = bool(CFG.get('douyin_save_music', True))
    cfg.save_json = bool(CFG.get('douyin_save_json', True))
    cfg.enable_progress = bool(CFG.get('douyin_enable_progress', True))
    return cfg