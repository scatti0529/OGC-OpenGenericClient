# -*- coding: utf-8 -*-
"""Pixiv 主界面（独立模块）"""
import os
import re

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QGridLayout, QFrame, QRadioButton,
)
from qfluentwidgets import (
    CardWidget, FluentIcon as FIF, LineEdit, PrimaryPushButton,
    PushButton, CaptionLabel, SubtitleLabel,
)
from services.pixiv_service import PixivDownloader, LoginRequiredError
from core.config import config as CFG
from ui.widgets.theme import theme_color
from pages.video.pixiv_page import (
    PixivCard, PixivParseThread, PixivDownloadThread,
)
from pages.video.pixiv_dialogs import (
    PixivConfigDialog, PixivFeatureDialog,
    show_error, show_info, show_success,
)


class PixivPage(QScrollArea):
    """Pixiv 专用解析下载页面"""

    MODES = [
        ('artist', '按画师ID下载'),
        ('illust', '按作品ID下载'),
        ('tag', '按标签搜索下载'),
        ('ranking', '下载今日排行榜'),
        ('bookmarks', '下载收藏'),
        ('history_ranking', '下载历史排行榜'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("PixivPage")
        self._cards = []
        self._current_illusts = []
        self._parse_thread = None
        self._parsing = False
        self._downloading = False
        self._download_queue = []
        self._downloader = PixivDownloader(
            log_callback=lambda msg: self._on_log(msg))

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
        self._build_options_row()
        self._build_results_area()

    def _build_input_card(self):
        """第一排：搜索框 + 粘贴 + 解析 + 批量下载"""
        inputCard = CardWidget(self.view)
        inputLayout = QVBoxLayout(inputCard)
        inputLayout.setSpacing(10)
        inputLayout.setContentsMargins(16, 16, 16, 16)

        titleRow = QHBoxLayout()
        titleLabel = SubtitleLabel("🎨 Pixiv 解析下载", inputCard)
        titleLabel.setStyleSheet("font-size: 16px; font-weight: bold;")
        titleRow.addWidget(titleLabel)
        titleRow.addStretch()
        inputLayout.addLayout(titleRow)

        urlRow = QHBoxLayout()
        self.urlEdit = LineEdit(inputCard)
        self.urlEdit.setPlaceholderText(
            "请输入 Pixiv 链接 / 画师ID / 作品ID / 标签 / 日期(YYYY-MM-DD)...")
        self.urlEdit.setClearButtonEnabled(True)
        urlRow.addWidget(self.urlEdit, 1)

        self.pasteBtn = PushButton(FIF.PASTE, "粘贴", inputCard)
        self.pasteBtn.setFixedWidth(80)
        self.pasteBtn.clicked.connect(self._on_paste)
        urlRow.addWidget(self.pasteBtn)

        self.parseBtn = PrimaryPushButton(FIF.SYNC, "解析", inputCard)
        self.parseBtn.clicked.connect(self._on_parse)
        urlRow.addWidget(self.parseBtn)

        self.batchBtn = PrimaryPushButton(FIF.DOWNLOAD, "批量下载", inputCard)
        self.batchBtn.setVisible(False)
        self.batchBtn.clicked.connect(self._on_batch_download)
        urlRow.addWidget(self.batchBtn)

        inputLayout.addLayout(urlRow)

        self.dirLabel = CaptionLabel(self._dir_hint(), inputCard)
        self.dirLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        self.dirLabel.setWordWrap(True)
        inputLayout.addWidget(self.dirLabel)

        self.layout.addWidget(inputCard)

    def _build_options_row(self):
        """第二排：单选模式 + 配置 + 功能清单"""
        optionsCard = CardWidget(self.view)
        optionsLayout = QHBoxLayout(optionsCard)
        optionsLayout.setSpacing(12)
        optionsLayout.setContentsMargins(16, 10, 16, 10)

        self.radio_group = []
        for key, label in self.MODES:
            rb = QRadioButton(label, optionsCard)
            rb.setProperty('mode', key)
            rb.setStyleSheet("font-size: 13px;")
            optionsLayout.addWidget(rb)
            self.radio_group.append(rb)
        self.radio_group[1].setChecked(True)

        optionsLayout.addStretch()

        self.configBtn = PushButton(FIF.SETTING, "配置", optionsCard)
        self.configBtn.clicked.connect(self._on_open_config)
        optionsLayout.addWidget(self.configBtn)

        self.featureBtn = PushButton(FIF.MORE, "功能清单", optionsCard)
        self.featureBtn.clicked.connect(self._on_open_features)
        optionsLayout.addWidget(self.featureBtn)

        self.layout.addWidget(optionsCard)

    def _build_results_area(self):
        """结果区"""
        self.resultsScroll = QScrollArea(self.view)
        self.resultsScroll.setWidgetResizable(True)
        self.resultsScroll.setFrameShape(QFrame.NoFrame)
        # 隐藏内部滚动条（外层 PixivPage 已提供滚动）
        self.resultsScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.resultsScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.resultsScroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }")

        self.resultsView = QWidget()
        self.resultsGrid = QGridLayout(self.resultsView)
        self.resultsGrid.setSpacing(12)
        self.resultsGrid.setAlignment(Qt.AlignTop)
        self.resultsScroll.setWidget(self.resultsView)
        self.layout.addWidget(self.resultsScroll, 1)

        self.emptyLabel = QLabel("选择模式后输入内容点击「解析」开始", self.view)
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        self.emptyLabel.setStyleSheet(
            "color: " + theme_color('#AAAAAA', '#666666') + "; font-size: 14px;")
        self.layout.addWidget(self.emptyLabel)

        self.logLabel = CaptionLabel("", self.view)
        self.logLabel.setWordWrap(True)
        self.logLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        self.layout.addWidget(self.logLabel)

    def _dir_hint(self):
        try:
            from services.download_manager import get_download_root, PLATFORM_FOLDERS
            root = get_download_root()
            folder = PLATFORM_FOLDERS.get('pixiv', 'pixiv-download')
            return f"📁 下载目录: {os.path.join(root, folder)}（按画师/标签/日期自动分类）"
        except Exception:
            return "📁 下载目录: pixiv-download"

    def _current_mode(self):
        for rb in self.radio_group:
            if rb.isChecked():
                return rb.property('mode')
        return 'illust'

    def _on_log(self, msg):
        self.logLabel.setText(str(msg))

    def _on_paste(self):
        try:
            from PyQt5.QtWidgets import QApplication
            text = QApplication.clipboard().text().strip()
            if text:
                self.urlEdit.clear()
                self.urlEdit.setText(text)
                show_info(self, "已粘贴", "剪贴板内容已填入输入框")
            else:
                show_info(self, "提示", "剪贴板为空")
        except Exception as e:
            show_error(self, "粘贴失败", str(e))

    def _on_open_config(self):
        PixivConfigDialog(self.window()).exec_()

    def _on_open_features(self):
        PixivFeatureDialog(self.window()).exec_()

    def _on_parse(self):
        if self._parsing:
            return
        if self._downloading:
            show_info(self, "下载进行中", "有文件正在下载，请等待完成后再解析")
            return

        mode = self._current_mode()
        value = self.urlEdit.text().strip()

        if mode in ('ranking', 'bookmarks'):
            self._start_parse(mode, '')
            return
        if not value:
            show_info(self, "提示", "请输入内容")
            return

        if mode == 'illust':
            m = re.search(r'pixiv\.net/(?:en/)?artworks/(\d+)', value)
            if m:
                value = m.group(1)
        elif mode == 'artist':
            m = re.search(r'pixiv\.net/(?:en/)?users?/(\d+)', value)
            if m:
                value = m.group(1)

        self._start_parse(mode, value)

    def _start_parse(self, mode, value):
        self._parsing = True
        self.parseBtn.setEnabled(False)
        self.parseBtn.setText("解析中...")
        self.emptyLabel.setText("正在解析...")
        self.emptyLabel.setVisible(True)
        self.resultsScroll.setVisible(False)
        self.batchBtn.setVisible(False)
        self._clear_results()

        pages = int(CFG.get('pixiv_crawl_pages', 3) or 3)
        self._parse_thread = PixivParseThread(mode, value, pages, self)
        self._parse_thread.finished.connect(self._on_parse_finished)
        self._parse_thread.error.connect(self._on_parse_error)
        self._parse_thread.start()

    def _on_parse_finished(self, illusts):
        self._parsing = False
        self.parseBtn.setEnabled(True)
        self.parseBtn.setText("解析")
        try:
            self._parse_thread.deleteLater()
        except Exception:
            pass
        self._parse_thread = None

        self._current_illusts = illusts
        self.emptyLabel.setVisible(False)
        self.resultsScroll.setVisible(True)

        for i, illust in enumerate(illusts):
            rank = illust.get('rank', 0) if 'rank' in illust else 0
            card = PixivCard(illust, rank=rank, parent=self.resultsView)
            card.downloadRequested.connect(self._on_card_download_requested)
            row, col = divmod(i, 4)
            self.resultsGrid.addWidget(card, row, col)
            self._cards.append(card)

        self.batchBtn.setVisible(len(self._cards) > 2)
        show_success(self, "解析完成", f"找到 {len(illusts)} 个作品")

    def _on_parse_error(self, message):
        self._parsing = False
        self.parseBtn.setEnabled(True)
        self.parseBtn.setText("解析")
        try:
            self._parse_thread.deleteLater()
        except Exception:
            pass
        self._parse_thread = None

        self.emptyLabel.setVisible(True)
        self.emptyLabel.setText("解析失败")
        self.resultsScroll.setVisible(False)
        self.batchBtn.setVisible(False)
        show_error(self, "解析失败", message)

    def _on_card_download_requested(self, card):
        if card._queued:
            return
        card.mark_queued()
        self._download_queue.append(card)
        self._process_download()

    def _on_batch_download(self):
        if not self._cards:
            return
        if self._downloading:
            show_info(self, "下载中", "已有任务在下载，请等待完成")
            return
        self._download_queue = []
        for card in self._cards:
            if not card._queued:
                card.mark_queued()
                self._download_queue.append(card)
        self._process_download()

    def _process_download(self):
        if self._downloading:
            return
        if not self._download_queue:
            return
        card = self._download_queue.pop(0)
        self._downloading = True
        self._download_current_card(card)

    def _download_current_card(self, card):
        card.mark_downloading()
        try:
            self._downloader.api
            mode = self._current_mode()
            save_path = self._downloader.get_pixiv_save_path()
            illust = card.illust
            add_user_folder = mode in ('artist', 'illust', 'bookmarks')
            add_rank = mode in ('ranking', 'history_ranking')
            if mode == 'tag':
                save_path = os.path.join(save_path, 'tag ' + self.urlEdit.text().strip())
            elif mode == 'ranking':
                import datetime
                save_path = os.path.join(save_path, str(datetime.date.today()) + ' ranking')
            elif mode == 'history_ranking':
                save_path = os.path.join(save_path, self.urlEdit.text().strip() + ' ranking')

            # 使用 QThread + 信号，跨线程安全回调
            self._download_thread = PixivDownloadThread(
                self._downloader,
                illust,
                save_path,
                add_user_folder=add_user_folder,
                add_rank=add_rank,
                skip_manga=bool(CFG.get('pixiv_skip_manga', False)),
                max_images=int(CFG.get('pixiv_max_images', 0) or 0),
                parent=self,
            )
            self._download_thread.done.connect(
                lambda ok, msg: self._on_download_card_finished(card, ok, msg))
            self._download_thread.start()
        except LoginRequiredError as e:
            card.mark_error()
            self._downloading = False
            show_error(self, "未登录", str(e))
        except Exception as e:
            card.mark_error()
            self._downloading = False
            show_error(self, "下载失败", str(e))

    def _on_download_card_finished(self, card, success, msg=''):
        if success:
            card.mark_done()
        else:
            card.mark_error()
            show_error(self, "下载失败", msg)
        self._downloading = False
        self._process_download()

    def _clear_results(self):
        # 安全回收下载线程，避免旧线程信号访问已删除卡片
        try:
            dt = getattr(self, '_download_thread', None)
            if dt is not None:
                try:
                    if dt.isRunning():
                        dt.requestInterruption()
                        dt.wait(1000)
                except (RuntimeError, Exception):
                    pass
                try:
                    dt.deleteLater()
                except (RuntimeError, Exception):
                    pass
                self._download_thread = None
        except Exception:
            pass

        self._download_queue = []
        self._downloading = False
        for card in list(self._cards):
            try:
                card._preview_thread.deleteLater()
            except Exception:
                pass
            card.deleteLater()
        self._cards = []
        self._current_illusts = []

        while self.resultsGrid.count():
            item = self.resultsGrid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()