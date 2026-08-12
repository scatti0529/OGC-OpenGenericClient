# -*- coding: utf-8 -*-
"""抖音专用解析下载页面

完整移植自 douyin_parse-master/qt_app_fluent.py 的架构：
- VideoParseInterface：单内容 / 用户主页批量 模式切换
- 多链接并发解析队列（最大并发 2）
- CardResultArea：卡片结果区（QStackedWidget：空提示 / 卡片网格切换）
- 下载队列管理（排队 → 下载中 → 完成/失败 → 继续下一个）
- 封面预览异步加载（低优先级线程）

适配本系统：
- 卡片：DouyinMediaCard（CardWidget 网格布局 + 状态机 + 进度条）
- 下载：services/douyin_service → download_media()（videos//images//audios//sourcefiles/ 自动分类）
- 数据库：DouyinProgressDB（douyin_downloads 表）
"""
import os
import re

import requests
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, QUrl
from PyQt5.QtGui import QPixmap, QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QGridLayout, QDialog, QApplication, QStackedWidget,
)
from qfluentwidgets import (
    CardWidget, FluentIcon as FIF, PushButton, PrimaryPushButton,
    CaptionLabel, SubtitleLabel, TextEdit, ProgressBar,
    BodyLabel, SpinBox, ComboBox as FluentComboBox, InfoBar,
    IndeterminateProgressBar, isDarkTheme,
)

from services.douyin_service import DouyinDownloader
from pages.video.douyin_dialogs import (
    VideoConfigDialog, DouyinLogDialog, DouyinFeatureDialog,
    QualitySelectionDialog, show_info, show_success, show_error,
)
from core.config import config as CFG
from ui.widgets.theme import theme_color
from ui.widgets.ui_utils import install_hover_tip


# ═══════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════
CARDS_PER_ROW = 4          # 卡片网格每行数量
CARD_WIDTH = 220
CARD_HEIGHT = 280
MAX_CONCURRENT_PARSE = 2   # 最大并发解析数

DOUYIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


# ═══════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════
def extract_urls(text: str) -> list:
    """从文本中提取所有 URL"""
    found = re.findall(r"https?://[^\s，,]+", text or "")
    urls = [u.strip("`") for u in found if u.strip("`")]
    return list(dict.fromkeys(urls))


def load_pixmap(url: str, w: int, h: int, timeout: int = 10):
    """加载网络图片并缩放，失败返回 None"""
    try:
        resp = requests.get(url, timeout=timeout,
                            headers={"User-Agent": DOUYIN_UA})
        if resp.status_code != 200:
            return None
        pix = QPixmap()
        if pix.loadFromData(resp.content):
            return pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
#  工作线程（移植自 qt_app_fluent.py workers）
# ═══════════════════════════════════════════════════════════
class PreviewLoadThread(QThread):
    """封面预览加载线程（低优先级，避免阻塞主界面）"""
    loaded = pyqtSignal(object, str)   # (pixmap, card_key)
    failed = pyqtSignal(str)           # card_key

    def __init__(self, url: str, w: int, h: int, key: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.w = w
        self.h = h
        self.key = key

    def run(self):
        try:
            self.setPriority(QThread.LowPriority)
        except Exception:
            pass
        pix = load_pixmap(self.url, self.w, self.h)
        if pix:
            self.loaded.emit(pix, self.key)
        else:
            self.failed.emit(self.key)


class ParseSingleWorker(QThread):
    """单个链接解析线程"""
    finished = pyqtSignal(dict, str)  # (result, url)
    error = pyqtSignal(str, str)      # (message, url)

    def __init__(self, downloader: DouyinDownloader, url: str, parent=None):
        super().__init__(parent)
        self.downloader = downloader
        self.url = url

    def run(self):
        try:
            info = self.downloader.parse_single(self.url)
            info["url"] = self.url
            self.finished.emit(info, self.url)
        except Exception as e:
            self.error.emit(f"解析异常：{str(e)}", self.url)


class ParseUserWorker(QThread):
    """用户主页解析线程：获取所有 aweme URL 列表"""
    result = pyqtSignal(list, str)
    error = pyqtSignal(str)

    def __init__(self, downloader: DouyinDownloader, url: str,
                 max_pages: int, parent=None):
        super().__init__(parent)
        self.downloader = downloader
        self.url = url
        self.max_pages = max_pages

    def run(self):
        try:
            parser = self.downloader._get_parser()
            url = self.url
            if "douyin.com/video/" in url or "v.douyin.com/" in url:
                user_home = parser.get_user_home_from_video_url(url)
                if not user_home:
                    self.error.emit("无法从视频解析主页")
                    return
                urls = parser.get_user_aweme_urls(user_home, max_pages=self.max_pages)
                self.result.emit(urls, user_home)
                return
            urls = parser.get_user_aweme_urls(url, max_pages=self.max_pages)
            if not urls:
                self.error.emit("解析主页列表失败")
                return
            self.result.emit(urls, url)
        except Exception as e:
            self.error.emit(f"主页解析异常：{str(e)}")


class DownloadWorker(QThread):
    """单个内容下载线程（下载统一走 download_manager → download_media）"""
    progress = pyqtSignal(int, str)    # (percent, card_key)
    done = pyqtSignal(bool, str, str)  # (success, message, card_key)

    def __init__(self, downloader: DouyinDownloader, info: dict,
                 share_url: str = "", selected_quality: dict = None,
                 card_key: str = "", parent=None):
        super().__init__(parent)
        self.downloader = downloader
        self.info = info
        self.share_url = share_url or info.get("url", "")
        self.selected_quality = selected_quality
        self.card_key = card_key

    def run(self):
        try:
            result = self.downloader.download_single(
                self.info, self.share_url,
                selected_quality=self.selected_quality,
                progress_cb=lambda c, t: self.progress.emit(
                    int(c * 100 / t) if t else 0, self.card_key),
            )
            ok = result.get('success', False)
            skipped = result.get('skipped', False)
            if ok:
                msg = '已跳过（已存在）' if skipped else '下载完成'
                self.done.emit(True, msg, self.card_key)
            else:
                self.done.emit(False, result.get('error', '下载失败'), self.card_key)
        except Exception as e:
            self.done.emit(False, f"下载异常：{str(e)}", self.card_key)


# ═══════════════════════════════════════════════════════════
#  媒体卡片（保持本系统 DouyinMediaCard 风格 + 状态机）
# ═══════════════════════════════════════════════════════════
class DouyinMediaCard(CardWidget):
    """抖音内容卡片（封面 + 标题 + 类型 + 下载按钮 + 进度条）

    移植自 qt_app_fluent.py 的 MediaCard 状态机，
    同时保持本系统 DouyinMediaCard 的统一风格。
    """

    # 状态常量
    DOWNLOAD = "download"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DONE = "done"
    ERROR = "error"

    def __init__(self, info: dict, index: int, total: int, page,
                 card_key: str = "", parent=None):
        super().__init__(parent=parent)
        self.info = info
        self.index = index
        self.total = total
        self.page = page
        self.card_key = card_key or f"card_{id(self)}"
        self._preview_thread = None
        self._state = self.DOWNLOAD

        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 封面预览
        self.preview_label = QLabel("加载预览...", self)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedSize(CARD_WIDTH - 24, 140)
        self.preview_label.setStyleSheet(
            "background-color: rgba(255,255,255,0.08); border-radius: 6px; color: "
            + theme_color('#999999', '#888888') + ";")
        layout.addWidget(self.preview_label, 0, Qt.AlignCenter)

        # 类型标签
        content_type = self.info.get("content_type", "video")
        if content_type == "image":
            count = self.info.get("image_count", 0)
            is_live = self.info.get("is_live", False)
            if is_live:
                tt = f"🎥 Live图集 ({count}张)"
            else:
                tt = f"🖼 图集 ({count}张)"
            self.type_label = CaptionLabel(tt, self)
        else:
            qualities = self.info.get("qualities") or []
            top_ratio = qualities[0].get("ratio", "") if qualities else ""
            tt = f"🎬 视频 {top_ratio}" if top_ratio else "🎬 视频"
            self.type_label = CaptionLabel(tt, self)
        self.type_label.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + ";")
        layout.addWidget(self.type_label)

        # 标题
        desc = self.info.get("desc") or (f"内容 {index}" if total > 1 else "视频内容")
        if len(desc) > 30:
            desc = desc[:30] + "..."
        self.title_label = BodyLabel(desc, self)
        self.title_label.setStyleSheet(
            "font-size: 12px; color: " + theme_color('#555555', '#CCCCCC') + ";")
        self.title_label.setWordWrap(True)
        self.title_label.setFixedHeight(36)
        layout.addWidget(self.title_label)

        # 作者 + 序号
        author = self.info.get("author_nickname") or ""
        if total > 1:
            author_short = author[:15] if len(author) > 15 else author
            seq_text = f"👤 {author_short} · {index}/{total}"
        else:
            author_short = author[:20] if len(author) > 20 else author
            seq_text = f"👤 {author_short}"
        self.seq_label = CaptionLabel(seq_text, self)
        self.seq_label.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 11px;")
        layout.addWidget(self.seq_label)

        layout.addStretch()

        # 下载按钮 + 进度条
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)
        self.download_btn = PrimaryPushButton(FIF.DOWNLOAD, "下载", self)
        self.download_btn.setFixedHeight(30)
        self.download_btn.clicked.connect(self._on_download_clicked)
        bottom_row.addWidget(self.download_btn, 1)

        self.progress_bar = ProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setVisible(False)
        bottom_row.addWidget(self.progress_bar, 1)
        layout.addLayout(bottom_row)

        self._start_preview()

    # ── 预览 ──
    def _preview_url(self) -> str:
        for key in ('cover_url', 'cover', 'video_cover', 'origin_cover', 'dynamic_cover'):
            url = self.info.get(key)
            if url:
                return url
        return ""

    def _start_preview(self):
        url = self._preview_url()
        if not url:
            self.preview_label.setText("无预览")
            return
        self._preview_thread = PreviewLoadThread(
            url, CARD_WIDTH - 24, 140, self.card_key, self
        )
        self._preview_thread.loaded.connect(self._on_preview_loaded)
        self._preview_thread.failed.connect(
            lambda key: self.preview_label.setText("预览加载失败")
            if key == self.card_key else None)
        self._preview_thread.start()

    def _on_preview_loaded(self, pixmap, key):
        if key == self.card_key:
            self.preview_label.setPixmap(pixmap)

    # ── 下载状态机 ──
    def _on_download_clicked(self):
        if self._state == self.DOWNLOAD:
            self.page.enqueue_download(self)

    def mark_queued(self):
        self._state = self.QUEUED
        self.download_btn.setEnabled(False)
        self.download_btn.setText("排队中")
        self.download_btn.setIcon(FIF.SYNC)

    def mark_downloading(self):
        self._state = self.DOWNLOADING
        self.download_btn.setEnabled(False)
        self.download_btn.setText("下载中")
        self.download_btn.setIcon(FIF.DOWNLOAD)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

    def mark_done(self, msg: str = ""):
        self._state = self.DONE
        self.download_btn.setEnabled(False)
        self.download_btn.setText("已下载")
        self.download_btn.setIcon(FIF.ACCEPT)
        self.download_btn.setStyleSheet(
            "color: #67C23A; border: 1px solid #67C23A; border-radius: 6px;")
        self.progress_bar.setVisible(False)

    def mark_error(self, msg: str = ""):
        self._state = self.ERROR
        self.download_btn.setEnabled(True)
        self.download_btn.setText("重试")
        self.download_btn.setIcon(FIF.DOWNLOAD)
        self.download_btn.setStyleSheet("")
        self.progress_bar.setVisible(False)

    def set_progress(self, percent: int):
        self.progress_bar.setValue(percent)


# ═══════════════════════════════════════════════════════════
#  卡片结果区（QStackedWidget：空提示 / 卡片网格）
# ═══════════════════════════════════════════════════════════
class CardResultArea(QStackedWidget):
    """卡片结果区：空提示页 / 卡片网格页 切换（移植自 qt_app_fluent.py）"""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.cards = []
        self.card_keys = {}
        self._download_queue = []
        self._download_active = False
        self._active_dl_threads = []
        self.setStyleSheet("QStackedWidget { border: none; background: transparent; }")

        # 页面 0：结果卡片网格
        self.results_scroll = QScrollArea(self)
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setFrameShape(QFrame.NoFrame)
        self.results_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }")
        self.results_scroll.viewport().setAutoFillBackground(False)

        self.results_view = QWidget()
        self.results_view.setAutoFillBackground(False)
        self.results_view.setStyleSheet("background: transparent;")
        self.results_grid = QGridLayout(self.results_view)
        self.results_grid.setSpacing(12)
        self.results_grid.setAlignment(Qt.AlignTop)
        self.results_grid.setContentsMargins(4, 4, 4, 4)
        self.results_scroll.setWidget(self.results_view)
        self.addWidget(self.results_scroll)  # index 0

        # 页面 1：空提示
        self.empty_widget = QWidget(self)
        self.empty_widget.setAutoFillBackground(False)
        self.empty_widget.setStyleSheet("background: transparent;")
        self.empty_layout = QVBoxLayout(self.empty_widget)
        self.empty_layout.setAlignment(Qt.AlignTop)
        self.empty_label = QLabel("输入链接后点击「解析」获取内容卡片", self.empty_widget)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            "color: " + theme_color('#AAAAAA', '#666666') + "; font-size: 14px; padding-top: 60px;")
        self.empty_layout.addWidget(self.empty_label)
        self.addWidget(self.empty_widget)  # index 1

        self.setCurrentIndex(1)

    # ── 卡片管理 ──
    def clear_cards(self):
        """清空所有卡片和下载队列"""
        self._download_queue = []
        self._download_active = False
        for t in list(self._active_dl_threads):
            try:
                if t.isRunning():
                    t.wait(300)
                t.deleteLater()
            except (RuntimeError, Exception):
                pass
        self._active_dl_threads = []

        for card in list(self.cards):
            try:
                card.deleteLater()
            except Exception:
                pass
        self.cards = []
        self.card_keys = {}

        while self.results_grid.count():
            item = self.results_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.setCurrentIndex(1)

    def add_card(self, info: dict, index: int, total: int):
        """添加卡片到网格（每行 CARDS_PER_ROW 个）"""
        card_key = f"card_{id(info)}_{index}"
        card = DouyinMediaCard(info, index, total, self, card_key=card_key)
        row = self.cards_count() // CARDS_PER_ROW
        col = self.cards_count() % CARDS_PER_ROW
        self.results_grid.addWidget(card, row, col)
        self.cards.append(card)
        self.card_keys[card_key] = card
        self.setCurrentIndex(0)

    def cards_count(self) -> int:
        return len(self.cards)

    # ── 下载队列 ──
    def enqueue_download(self, card: DouyinMediaCard):
        if card in self._download_queue or card._state != DouyinMediaCard.DOWNLOAD:
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
        self._start_download(card)

    def _start_download(self, card: DouyinMediaCard):
        card.mark_downloading()

        info = card.info
        selected_quality = None
        # 视频且有多个质量选项时让用户选择
        qualities = info.get("qualities", [])
        if info.get("content_type", "video") == "video" and len(qualities) > 1:
            dialog = QualitySelectionDialog(qualities, self.page.window())
            if dialog.exec() == QDialog.Accepted:
                sel = dialog.get_selected_quality()
                if sel:
                    selected_quality = sel
            else:
                card.mark_error("已取消")
                self._download_active = False
                self._process_queue()
                return

        worker = DownloadWorker(
            self.page._get_downloader(), info,
            share_url=info.get("url", ""),
            selected_quality=selected_quality, card_key=card.card_key, parent=self,
        )
        worker.progress.connect(self._on_download_progress)
        worker.done.connect(self._on_download_done)
        self._active_dl_threads.append(worker)
        worker.start()

    def _on_download_progress(self, percent: int, key: str):
        card = self.card_keys.get(key)
        if card:
            card.set_progress(percent)

    def _on_download_done(self, success: bool, msg: str, key: str):
        card = self.card_keys.get(key)
        if card:
            if success:
                card.mark_done(msg)
            else:
                card.mark_error(msg)
                InfoBar.error("下载失败", msg, parent=self.page.window())

        # 清理线程
        for t in list(self._active_dl_threads):
            if getattr(t, "card_key", None) == key:
                try:
                    if t.isRunning():
                        t.wait(200)
                    t.deleteLater()
                except (RuntimeError, Exception):
                    pass
                try:
                    self._active_dl_threads.remove(t)
                except ValueError:
                    pass

        self._download_active = False
        self._process_queue()


# ═══════════════════════════════════════════════════════════
#  抖音主页面（移植自 qt_app_fluent.py VideoParseInterface）
# ═══════════════════════════════════════════════════════════
class DouyinPage(QScrollArea):
    """抖音专用解析下载页面（单内容 / 用户主页批量 模式切换）"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DouyinPage")

        self._parse_threads = []        # 活动解析线程列表
        self._parse_queue = []          # 待解析 URL 队列
        self._queue_parsing = False
        self._parse_total = 0
        self._parse_done = 0
        self._parse_failed = 0
        self._parsing = False
        self._MAX_CONCURRENT = MAX_CONCURRENT_PARSE
        self._log_dialog = None
        self._downloader = None

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.viewport().setAutoFillBackground(False)

        self.view = QWidget(self)
        self.view.setAutoFillBackground(False)
        self.view.setStyleSheet("background: transparent;")
        self.layout = QVBoxLayout(self.view)
        self.layout.setSpacing(12)
        self.layout.setContentsMargins(24, 24, 24, 24)
        self.setWidget(self.view)

        self._build_input_card()
        self._build_results_area()

    # ── 下载器 ──
    def _get_downloader(self) -> DouyinDownloader:
        if self._downloader is None:
            self._downloader = DouyinDownloader()
        return self._downloader

    # ── UI ──
    def _build_input_card(self):
        input_card = CardWidget(self.view)
        input_layout = QVBoxLayout(input_card)
        input_layout.setSpacing(12)
        input_layout.setContentsMargins(20, 18, 20, 18)

        # 标题行（统一对齐：标题 16sp + 模式说明 11sp + 下拉 30px + 页数 30px）
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_label = SubtitleLabel("🎬 抖音解析下载", input_card)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_row.addWidget(title_label)

        # 模式提示（弱化视觉权重：更小字号 + 低透明度）
        mode_hint = CaptionLabel("解析模式", input_card)
        mode_hint.setStyleSheet(
            "color: " + theme_color('#B0B0B0', '#5A5F6A') + "; font-size: 10px;")
        title_row.addWidget(mode_hint)

        self.mode_combo = FluentComboBox(input_card)
        self.mode_combo.addItem("单内容", None, "single")
        self.mode_combo.addItem("主页批量", None, "user")
        self.mode_combo.setFixedWidth(110)
        self.mode_combo.setFixedHeight(30)
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.setToolTip("选择解析模式：单内容解析或用户主页批量下载")
        self._apply_mode_combo_style()
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        title_row.addWidget(self.mode_combo)

        # 最大页数（统一项目风格 SpinBox，切换模式时随模式显隐）
        self.max_pages_label = CaptionLabel("最大页数", input_card)
        self.max_pages_label.setStyleSheet(
            "font-size: 11px; color: " + theme_color('#606060', '#AAAAAA') + ";")
        self.max_pages_spin = SpinBox(input_card)
        self.max_pages_spin.setRange(1, 50)
        self.max_pages_spin.setValue(int(CFG.get('douyin_max_pages', 10) or 10))
        self.max_pages_spin.setSuffix(" 页")
        self.max_pages_spin.setFixedWidth(92)
        self.max_pages_spin.setFixedHeight(30)
        self.max_pages_spin.setVisible(False)
        self.max_pages_label.setVisible(False)
        self._apply_spinbox_style()
        title_row.addWidget(self.max_pages_label)
        title_row.addWidget(self.max_pages_spin)

        title_row.addStretch()

        input_layout.addLayout(title_row)

        # 顶部浅分割线（分隔顶部栏与下方输入区域）
        divider = QFrame(input_card)
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet(
            "QFrame { color: " + theme_color('rgba(0,0,0,0.08)', 'rgba(255,255,255,0.06)') + "; }")
        input_layout.addWidget(divider)

        # URL 输入区（输入框与右侧按钮组之间加大间距）
        url_row = QHBoxLayout()
        url_row.setSpacing(16)
        self.url_edit = TextEdit(input_card)
        self.url_edit.setPlaceholderText(
            "在此粘贴抖音分享链接或包含链接的完整分享文本\n\n"
            "支持多条链接（回车或英文逗号分隔，自动并发解析）\n"
            "支持单视频 / 图集 / 短链接 / 用户主页链接")
        self.url_edit.setAcceptRichText(False)
        self.url_edit.setFixedHeight(120)
        self._apply_textedit_style()
        url_row.addWidget(self.url_edit, 1)

        # 高频操作按钮组（右侧垂直排列：粘贴 / 追加粘贴 / 解析）
        btn_container = QFrame(input_card)
        btn_container.setObjectName("DouyinBtnGroup")
        btn_container.setFixedWidth(150)
        btn_container.setStyleSheet(
            "#DouyinBtnGroup { background: " + theme_color('rgba(0,0,0,0.04)', 'rgba(255,255,255,0.04)') + ";"
            " border: 1px solid " + theme_color('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.06)') + ";"
            " border-radius: 10px; }")

        # 按钮组使用内部滚动（窗口高度不足时可滚动，避免被截断）
        btn_scroll = QScrollArea(btn_container)
        btn_scroll.setWidgetResizable(True)
        btn_scroll.setFrameShape(QFrame.NoFrame)
        btn_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        btn_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 4px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(128,128,128,0.3);"
            " border-radius: 2px; min-height: 24px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(128,128,128,0.5); }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
        btn_scroll.viewport().setAutoFillBackground(False)

        btn_inner = QWidget()
        btn_inner.setAutoFillBackground(False)
        btn_inner.setStyleSheet("background: transparent;")
        btn_container_layout = QVBoxLayout(btn_inner)
        btn_container_layout.setContentsMargins(10, 10, 10, 10)
        btn_container_layout.setSpacing(8)
        btn_scroll.setWidget(btn_inner)

        _outer = QVBoxLayout(btn_container)
        _outer.setContentsMargins(0, 0, 0, 0)
        _outer.addWidget(btn_scroll)

        # 统一图标大小（16px）与文字间距
        icon_size = 16
        self.paste_btn = PushButton(FIF.PASTE, "  粘贴", btn_container)
        self.paste_btn.setIconSize(QSize(icon_size, icon_size))
        self.paste_btn.setFixedHeight(30)
        self.paste_btn.clicked.connect(self._on_paste)
        btn_container_layout.addWidget(self.paste_btn)

        self.append_btn = PushButton(FIF.ADD, "  追加", btn_container)
        self.append_btn.setIconSize(QSize(icon_size, icon_size))
        self.append_btn.setFixedHeight(30)
        self.append_btn.clicked.connect(self._on_append_paste)
        btn_container_layout.addWidget(self.append_btn)

        self.parse_btn = PrimaryPushButton(FIF.SYNC, "  解析", btn_container)
        self.parse_btn.setIconSize(QSize(icon_size, icon_size))
        self.parse_btn.setFixedHeight(32)
        self.parse_btn.clicked.connect(self._on_parse)
        btn_container_layout.addWidget(self.parse_btn)

        btn_container_layout.addStretch()

        url_row.addWidget(btn_container)
        input_layout.addLayout(url_row)

        # 低频工具按钮（下方水平一排：配置 / 功能 / 日志）
        tool_row = QHBoxLayout()
        tool_row.setSpacing(8)
        self.config_btn = PushButton(FIF.SETTING, "  配置", input_card)
        self.config_btn.setIconSize(QSize(icon_size, icon_size))
        self.config_btn.setFixedHeight(28)
        self.config_btn.clicked.connect(self._on_open_config)
        tool_row.addWidget(self.config_btn)

        self.feature_btn = PushButton(FIF.MORE, "  功能", input_card)
        self.feature_btn.setIconSize(QSize(icon_size, icon_size))
        self.feature_btn.setFixedHeight(28)
        self.feature_btn.clicked.connect(self._on_open_features)
        tool_row.addWidget(self.feature_btn)

        self.log_btn = PushButton(FIF.DOCUMENT, "  日志", input_card)
        self.log_btn.setIconSize(QSize(icon_size, icon_size))
        self.log_btn.setFixedHeight(28)
        self.log_btn.clicked.connect(self._on_open_log)
        tool_row.addWidget(self.log_btn)

        tool_row.addStretch()
        input_layout.addLayout(tool_row)

        # 目录提示行（文字自动换行 + 打开文件夹按钮）
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.dir_label = CaptionLabel(self._dir_hint(), input_card)
        self.dir_label.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        self.dir_label.setWordWrap(True)
        dir_row.addWidget(self.dir_label, 1)
        self.open_dir_btn = PushButton(FIF.FOLDER, "打开文件夹", input_card)
        self.open_dir_btn.setFixedHeight(28)
        self.open_dir_btn.setStyleSheet(
            "QPushButton { font-size: 12px; color: " + theme_color('#4A90D9', '#7EB8F0') + "; }")
        self.open_dir_btn.clicked.connect(self._on_open_dir)
        dir_row.addWidget(self.open_dir_btn)
        input_layout.addLayout(dir_row)

        self.layout.addWidget(input_card)

        # 悬停提示
        install_hover_tip(self.url_edit, "链接输入", "粘贴抖音分享链接或完整分享文本")
        install_hover_tip(self.paste_btn, "粘贴", "清空并粘贴剪贴板内容")
        install_hover_tip(self.append_btn, "追加粘贴", "在末尾追加剪贴板内容")
        install_hover_tip(self.parse_btn, "解析", "解析输入框中的链接")
        install_hover_tip(self.config_btn, "配置", "打开视频配置弹窗")
        install_hover_tip(self.feature_btn, "功能清单", "查看功能说明")
        install_hover_tip(self.log_btn, "下载日志", "查看下载日志")

    def _apply_textedit_style(self):
        """完善输入框 hover/focus 边框高亮样式（强化交互反馈）"""
        dark = isDarkTheme()
        bg = '#202530' if dark else '#FFFFFF'
        border = '#2b3142' if dark else '#DCDFE6'
        text = '#E6E6E6' if dark else '#303133'
        self.url_edit.setStyleSheet(
            f"QTextEdit {{"
            f" background-color: {bg}; color: {text};"
            f" border: 1px solid {border}; border-radius: 8px;"
            f" padding: 8px; font-size: 13px; }}"
            f"QTextEdit:hover {{"
            f" border-color: {'#3a4156' if dark else '#C0C4CC'}; }}"
            f"QTextEdit:focus {{"
            f" border-color: #3b82f6;"
            f" background-color: {bg}; }}"
        )

    def _apply_spinbox_style(self):
        """统一项目风格 SpinBox（深浅色主题适配）"""
        dark = isDarkTheme()
        bg = '#202530' if dark else '#FFFFFF'
        border = '#2b3142' if dark else '#DCDFE6'
        text = '#E6E6E6' if dark else '#303133'
        self.max_pages_spin.setStyleSheet(
            f"QSpinBox {{"
            f" background-color: {bg}; color: {text};"
            f" border: 1px solid {border}; border-radius: 6px;"
            f" padding: 4px 8px; font-size: 13px; outline: none; }}"
            f"QSpinBox:hover {{ border-color: {'#3a4156' if dark else '#C0C4CC'}; }}"
            f"QSpinBox:focus {{ border-color: #3b82f6; }}"
            f"QSpinBox::up-button {{ width: 20px; subcontrol-origin: border;"
            f" subcontrol-position: top right; border: none;"
            f" background: transparent; }}"
            f"QSpinBox::down-button {{ width: 20px; subcontrol-origin: border;"
            f" subcontrol-position: bottom right; border: none;"
            f" background: transparent; }}"
        )

    def _apply_mode_combo_style(self):
        """深色/浅色主题定制 QComboBox 样式"""
        dark = isDarkTheme()
        bg = '#202530' if dark else '#FFFFFF'
        hover_bg = '#2a3040' if dark else '#F0F2F5'
        border = '#2b3142' if dark else '#DCDFE6'
        text = '#E6E6E6' if dark else '#303133'
        sel_bg = '#2b4a6b' if dark else '#D9E7F5'
        self.mode_combo.setStyleSheet(
            f"QComboBox {{"
            f" background-color: {bg}; color: {text};"
            f" border: 1px solid {border}; border-radius: 6px;"
            f" padding: 6px 12px; font-size: 13px; outline: none; }}"
            f"QComboBox:hover {{ background-color: {hover_bg}; }}"
            f"QComboBox::drop-down {{ border: none; width: 26px; }}"
            f"QComboBox QAbstractItemView {{"
            f" background-color: {bg}; color: {text};"
            f" border: 1px solid {border}; border-radius: 8px;"
            f" selection-background-color: {sel_bg}; outline: none; padding: 4px; }}"
            f"QComboBox QAbstractItemView::item {{"
            f" height: 36px; padding-left: 14px; padding-right: 14px;"
            f" border-radius: 6px; font-size: 13px; }}"
        )

    def _build_results_area(self):
        # 状态提示（解析中显示进度）
        self.status_label = CaptionLabel("", self.view)
        self.status_label.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        self.status_label.setVisible(False)
        self.layout.addWidget(self.status_label)

        # 解析 loading 指示器（解析执行中显示，让用户感知正在运行）
        self.loading_bar = IndeterminateProgressBar(self.view)
        self.loading_bar.setFixedHeight(4)
        self.loading_bar.setVisible(False)
        self.layout.addWidget(self.loading_bar)

        # 卡片结果区（QStackedWidget：空提示 / 卡片网格）
        self.result_area = CardResultArea(self, self.view)
        self.layout.addWidget(self.result_area, 1)

    def _dir_hint(self) -> str:
        try:
            from services.douyin_service import get_douyin_output_dir
            return f"📁 下载目录: {get_douyin_output_dir()}（视频→videos/ 图片→images/ 音频→audios/ 源文件→sourcefiles/ 自动分类）"
        except Exception:
            return "📁 下载目录: douyin-download（自动分类）"

    # ── 交互 ──
    def _on_mode_changed(self, index):
        is_user = self.mode_combo.itemData(index) == "user"
        self.max_pages_spin.setVisible(is_user)
        self.max_pages_label.setVisible(is_user)

    def _on_paste(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_edit.clear()
            self.url_edit.setPlainText(text)
            show_info(self, "已粘贴", "剪贴板内容已填入输入框")
        else:
            show_info(self, "提示", "剪贴板为空")

    def _on_append_paste(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            show_info(self, "提示", "剪贴板为空")
            return
        current = self.url_edit.toPlainText()
        if current.strip():
            new_text = current.rstrip() + "\n" + text
        else:
            new_text = text
        self.url_edit.setPlainText(new_text)
        show_info(self, "已追加", "剪贴板内容已追加到输入框")

    def _on_open_dir(self):
        """打开下载目录文件夹"""
        try:
            from services.douyin_service import get_douyin_output_dir
            path = str(get_douyin_output_dir())
            os.makedirs(path, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            show_error(self, "打开失败", f"无法打开下载目录: {str(e)}")

    def _on_open_config(self):
        """打开视频配置弹窗（移植自 qt_app_fluent.py）"""
        dialog = VideoConfigDialog(self.window())
        dialog.set_max_pages(self.max_pages_spin.value())
        dialog.exec_()
        # 保存后应用配置并更新目录提示
        self.max_pages_spin.setValue(dialog.get_max_pages())
        self.dir_label.setText(self._dir_hint())
        # 重新创建下载器（应用新 Cookie）
        self._downloader = None

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

    # ── 解析 ──
    def _on_parse(self):
        if self._parsing or self._queue_parsing:
            return

        text = self.url_edit.toPlainText()
        urls = extract_urls(text)
        if not urls:
            show_info(self, "提示", "请先粘贴抖音分享链接")
            return

        mode = self.mode_combo.itemData(self.mode_combo.currentIndex())

        # 用户主页模式：先获取 URL 列表，再逐个解析生成卡片
        if mode == "user":
            self._clear_before_parse()
            self._parsing = True
            self.parse_btn.setEnabled(False)
            self.parse_btn.setText("解析主页中...")
            self.url_edit.setEnabled(False)
            self.status_label.setVisible(True)
            self.status_label.setText("正在获取用户主页列表...")

            self.user_worker = ParseUserWorker(
                self._get_downloader(), urls[0], self.max_pages_spin.value(), self
            )
            self.user_worker.result.connect(self._on_user_urls_result)
            self.user_worker.error.connect(self._on_user_error)
            self.user_worker.finished.connect(self._on_user_finished)
            self.user_worker.start()
            return

        # 单内容模式：多链接并发解析
        self._clear_before_parse()
        self._parse_queue = list(urls)
        self._queue_parsing = True
        self._parse_threads = []
        self._parse_total = len(urls)
        self._parse_done = 0
        self._parse_failed = 0

        self.parse_btn.setEnabled(False)
        self.parse_btn.setText("解析中...")
        self.paste_btn.setEnabled(False)
        self.append_btn.setEnabled(False)
        self.url_edit.setEnabled(False)
        self.status_label.setVisible(True)
        self.status_label.setText(f"正在解析 0/{self._parse_total} ...")

        # 启动并发解析
        for _ in range(min(self._MAX_CONCURRENT, len(self._parse_queue))):
            self._launch_next_parser()

    def _clear_before_parse(self):
        self.result_area.clear_cards()
        self.status_label.setVisible(True)
        self.loading_bar.setVisible(True)
        self.loading_bar.start()

    def _launch_next_parser(self):
        if not self._parse_queue:
            return
        url = self._parse_queue.pop(0)
        thread = ParseSingleWorker(self._get_downloader(), url, self)
        thread.finished.connect(lambda result, u=url: self._on_parse_finished(result, u))
        thread.error.connect(lambda msg, u=url: self._on_parse_error(msg, u))
        self._parse_threads.append(thread)
        thread.start()

    def _on_parse_finished(self, result: dict, url: str):
        self._remove_parser_of(url)
        self._parse_done += 1

        # 生成卡片
        self.result_area.add_card(result, self.result_area.cards_count() + 1, 1)

        self._update_parse_progress()
        self._launch_next_parser()

    def _on_parse_error(self, message: str, url: str):
        self._remove_parser_of(url)
        self._parse_done += 1
        self._parse_failed += 1
        self._append_log(f"❌ 解析失败: {url[:50]}... {message}")
        InfoBar.error("解析失败", f"{url[:50]}... {message}",
                      parent=self.window())
        self._update_parse_progress()
        self._launch_next_parser()

    def _update_parse_progress(self):
        if self._parse_threads or self._parse_queue:
            self.status_label.setText(
                f"正在解析 {self._parse_done}/{self._parse_total} ...")
            return

        # 全部解析完成
        self._queue_parsing = False
        self.parse_btn.setEnabled(True)
        self.parse_btn.setText("解析")
        self.paste_btn.setEnabled(True)
        self.append_btn.setEnabled(True)
        self.url_edit.setEnabled(True)
        self.status_label.setVisible(False)
        self.loading_bar.setVisible(False)
        self.loading_bar.stop()

        total_cards = self.result_area.cards_count()
        if self._parse_failed:
            msg = f"共 {self._parse_total} 条链接，成功 {self._parse_total - self._parse_failed} 条，失败 {self._parse_failed} 条"
            InfoBar.warning("部分链接解析失败", msg, parent=self.window())
        else:
            InfoBar.success("解析完成",
                            f"共 {self._parse_total} 条链接，生成 {total_cards} 个卡片",
                            parent=self.window())

    def _remove_parser_of(self, url: str):
        for t in list(self._parse_threads):
            if getattr(t, "url", None) == url:
                try:
                    if t.isRunning():
                        t.wait(300)
                    t.deleteLater()
                except (RuntimeError, Exception):
                    pass
                try:
                    self._parse_threads.remove(t)
                except ValueError:
                    pass
                return

    # ── 用户主页模式 ──
    def _on_user_urls_result(self, urls: list, user_home: str):
        if not urls:
            InfoBar.warning("提示", "主页未解析到任何内容", parent=self.window())
            self._on_user_finished()
            return
        self.status_label.setText(f"主页共 {len(urls)} 条，正在解析详情...")
        self._parse_total = len(urls)
        self._parse_done = 0
        self._parse_failed = 0
        self._parse_queue = list(urls)
        self._parse_threads = []

        # 启动并发解析
        for _ in range(min(self._MAX_CONCURRENT, len(self._parse_queue))):
            self._launch_next_parser()

    def _on_user_error(self, msg: str):
        InfoBar.error("主页解析失败", msg, parent=self.window())
        self._append_log(f"❌ 主页解析失败: {msg}")
        self.loading_bar.setVisible(False)
        self.loading_bar.stop()

    def _on_user_finished(self):
        self._parsing = False
        self.parse_btn.setEnabled(True)
        self.parse_btn.setText("解析")
        self.url_edit.setEnabled(True)
        self.status_label.setVisible(False)
        self.loading_bar.setVisible(False)
        self.loading_bar.stop()

    # ── 停止解析 ──
    def _stop_parsing(self):
        """停止当前解析（清空队列，回收线程）"""
        self._parse_queue = []
        for t in list(self._parse_threads):
            try:
                if t.isRunning():
                    t.wait(300)
                t.deleteLater()
            except (RuntimeError, Exception):
                pass
        self._parse_threads = []
        self._queue_parsing = False
        self._parsing = False
        self.parse_btn.setEnabled(True)
        self.parse_btn.setText("解析")
        self.paste_btn.setEnabled(True)
        self.append_btn.setEnabled(True)
        self.url_edit.setEnabled(True)
        self.status_label.setVisible(False)
        self.loading_bar.setVisible(False)
        self.loading_bar.stop()

    def closeEvent(self, event):
        self._stop_parsing()
        self.result_area.clear_cards()
        super().closeEvent(event)