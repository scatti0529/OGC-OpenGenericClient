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
    CardWidget, FluentIcon as FIF, LineEdit, TextEdit, PrimaryPushButton,
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
from ui.widgets.ui_utils import install_hover_tip


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
        # 多条目解析队列（支持回车/英文逗号分隔，依次解析）
        self._parse_queue = []
        self._queue_parsing = False
        self._active_parsers = []
        self._parse_total = 0
        self._parse_done = 0
        self._parse_failed = 0
        self._MAX_CONCURRENT = 2  # 同时最多并发解析条数，其余入队依次解析
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
        self.urlEdit = TextEdit(inputCard)
        self.urlEdit.setPlaceholderText(
            "请输入 Pixiv 链接 / 画师ID / 作品ID / 标签 / 日期(YYYY-MM-DD)...\n"
            "支持多条内容（回车或英文逗号分隔），点击「解析」将依次解析"
        )
        self.urlEdit.setAcceptRichText(False)  # 仅纯文本，避免粘贴黑条
        self.urlEdit.setFixedHeight(100)
        urlRow.addWidget(self.urlEdit, 1)
        
        self.pasteBtn = PushButton(FIF.PASTE, "粘贴", inputCard)
        self.pasteBtn.setFixedWidth(80)
        self.pasteBtn.clicked.connect(self._on_paste)
        urlRow.addWidget(self.pasteBtn)

        self.appendBtn = PushButton(FIF.ADD, "追加", inputCard)
        self.appendBtn.setFixedWidth(90)
        self.appendBtn.setToolTip("若输入框已有内容，则在末尾回车后追加粘贴剪贴板内容")
        self.appendBtn.clicked.connect(self._on_append_paste)
        urlRow.addWidget(self.appendBtn)

        self.parseBtn = PrimaryPushButton(FIF.SYNC, "解析", inputCard)
        self.parseBtn.clicked.connect(self._on_parse)
        urlRow.addWidget(self.parseBtn)

        self.batchBtn = PrimaryPushButton(FIF.DOWNLOAD, "批量下载", inputCard)
        self.batchBtn.setVisible(False)
        self.batchBtn.clicked.connect(self._on_batch_download)
        urlRow.addWidget(self.batchBtn)

        inputLayout.addLayout(urlRow)

        # 模式单选行 + 配置/功能按钮（并入解析容器）
        modeRow = QHBoxLayout()
        modeRow.setSpacing(12)
        self.radio_group = []
        for key, label in self.MODES:
            rb = QRadioButton(label, inputCard)
            rb.setProperty('mode', key)
            rb.setStyleSheet("font-size: 13px;")
            modeRow.addWidget(rb)
            self.radio_group.append(rb)
        self.radio_group[1].setChecked(True)

        modeRow.addStretch()

        self.configBtn = PushButton(FIF.SETTING, "配置", inputCard)
        self.configBtn.clicked.connect(self._on_open_config)
        modeRow.addWidget(self.configBtn)

        self.featureBtn = PushButton(FIF.MORE, "功能清单", inputCard)
        self.featureBtn.clicked.connect(self._on_open_features)
        modeRow.addWidget(self.featureBtn)

        inputLayout.addLayout(modeRow)

        self.dirLabel = CaptionLabel(self._dir_hint(), inputCard)
        self.dirLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        self.dirLabel.setWordWrap(True)
        inputLayout.addWidget(self.dirLabel)

        # ── Pixiv 页面悬停功能简介 ──
        install_hover_tip(self.urlEdit, "输入内容", "输入 Pixiv 链接/画师ID/作品ID/标签/日期(YYYY-MM-DD)")
        install_hover_tip(self.pasteBtn, "粘贴", "清空输入框并粘贴剪贴板内容")
        install_hover_tip(self.appendBtn, "追加粘贴", "在输入框末尾追加粘贴剪贴板内容")
        install_hover_tip(self.parseBtn, "解析", "按所选模式解析输入内容，生成作品卡片列表")
        install_hover_tip(self.batchBtn, "批量下载", "将当前所有作品卡片加入下载队列")
        install_hover_tip(self.configBtn, "配置", "打开 Pixiv 配置与登录弹窗")
        install_hover_tip(self.featureBtn, "功能清单", "查看 Pixiv 下载器功能开关说明")
        for rb in self.radio_group:
            mode_tip = {
                'artist': '按画师 ID 下载该画师的全部作品',
                'illust': '按作品 ID 下载指定作品',
                'tag': '按标签搜索并下载相关作品',
                'ranking': '下载今日排行榜作品',
                'bookmarks': '下载当前账号收藏的作品',
                'history_ranking': '按日期下载历史排行榜作品（格式 YYYY-MM-DD）',
            }.get(rb.property('mode'), '选择解析模式')
            install_hover_tip(rb, rb.text(), mode_tip)

        self.layout.addWidget(inputCard)

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
                self.urlEdit.setPlainText(text)
                show_info(self, "已粘贴", "剪贴板内容已填入输入框")
            else:
                show_info(self, "提示", "剪贴板为空")
        except Exception as e:
            show_error(self, "粘贴失败", str(e))

    def _on_append_paste(self):
        """追加粘贴：若输入框已有内容，在末尾回车后粘贴；为空则直接粘贴"""
        try:
            from PyQt5.QtWidgets import QApplication
            text = QApplication.clipboard().text().strip()
            if not text:
                show_info(self, "提示", "剪贴板为空")
                return
            current = self.urlEdit.toPlainText()
            if current.strip():
                # 已有内容，在最后字符后加回车再粘贴
                new_text = current.rstrip() + "\n" + text
            else:
                new_text = text
            self.urlEdit.setPlainText(new_text)
            show_info(self, "已追加", "剪贴板内容已追加到输入框")
        except Exception as e:
            show_error(self, "追加粘贴失败", str(e))

    def _on_open_config(self):
        PixivConfigDialog(self.window()).exec_()

    def _on_open_features(self):
        PixivFeatureDialog(self.window()).exec_()

    def closeEvent(self, event):
        """关闭时回收所有活动解析/下载线程"""
        threads = []
        for t in list(getattr(self, '_active_parsers', [])):
            threads.append(t)
        dt = getattr(self, '_download_thread', None)
        if dt is not None:
            threads.append(dt)
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

    @staticmethod
    def _split_entries(text: str) -> list:
        """按回车 / 英文逗号 / 中文逗号 / 空白切分输入，返回去重列表"""
        parts = re.split(r'[\s,，]+', text or '')
        seen = set()
        result = []
        for p in parts:
            p = p.strip()
            if p and p not in seen:
                seen.add(p)
                result.append(p)
        return result

    def _on_parse(self):
        if self._parsing or self._queue_parsing:
            return
        if self._downloading:
            show_info(self, "下载进行中", "有文件正在下载，请等待完成后再解析")
            return

        mode = self._current_mode()
        raw = self.urlEdit.toPlainText().strip()

        # 排行榜 / 收藏：无需输入内容，直接解析
        if mode in ('ranking', 'bookmarks'):
            self._start_parse_queue(mode, [''])
            return

        if not raw:
            show_info(self, "提示", "请输入内容")
            return

        # 拆分多个条目（画师ID / 作品ID / 链接 / 标签等）
        entries = self._split_entries(raw)

        # 提取链接中的 ID（作品链接 → 作品ID，画师链接 → 画师ID）
        normalized = []
        for entry in entries:
            if mode == 'illust':
                m = re.search(r'pixiv\.net/(?:en/)?artworks/(\d+)', entry)
                normalized.append(m.group(1) if m else entry)
            elif mode == 'artist':
                m = re.search(r'pixiv\.net/(?:en/)?users?/(\d+)', entry)
                normalized.append(m.group(1) if m else entry)
            else:
                normalized.append(entry)

        self._start_parse_queue(mode, normalized)

    def _start_parse_queue(self, mode, entries):
        """初始化多条目解析队列并启动"""
        # 安全回收旧解析线程
        old_thread = self._parse_thread
        self._parse_thread = None
        if old_thread is not None:
            try:
                if old_thread.isRunning():
                    old_thread.wait(500)
                old_thread.deleteLater()
            except (RuntimeError, Exception):
                pass

        # 先清空旧结果（会同时清理旧的解析队列/活动线程）
        self._clear_results()
        # 初始化多条目解析队列
        self._parse_queue = list(entries)
        self._queue_parsing = True
        self._active_parsers = []
        self._parse_total = len(entries)
        self._parse_done = 0
        self._parse_failed = 0

        self.parseBtn.setEnabled(False)
        self.parseBtn.setText("解析中...")
        self.pasteBtn.setEnabled(False)
        self.appendBtn.setEnabled(False)
        self.urlEdit.setEnabled(False)
        self.emptyLabel.setVisible(True)
        self.emptyLabel.setText(f"正在解析 0/{self._parse_total} ...")
        self.resultsScroll.setVisible(False)
        self.batchBtn.setVisible(False)

        # 启动解析（并发最多 _MAX_CONCURRENT 条，其余入队）
        for _ in range(min(self._MAX_CONCURRENT, len(self._parse_queue))):
            self._launch_next_parser(_current_mode=mode)

    def _launch_next_parser(self, _current_mode=None):
        """从解析队列中取出下一条启动解析线程"""
        if not self._parse_queue:
            return
        entry = self._parse_queue.pop(0)
        mode = _current_mode or self._current_mode()
        pages = int(CFG.get('pixiv_crawl_pages', 3) or 3)

        thread = PixivParseThread(mode, entry, pages, self, entry=entry)
        thread.finished.connect(
            lambda illusts, e=entry: self._on_parse_finished(illusts, e))
        thread.error.connect(
            lambda msg, e=entry: self._on_parse_error(msg, e))
        self._active_parsers.append(thread)
        thread.start()

    def _on_parse_finished(self, illusts, entry):
        """单条解析完成，追加卡片"""
        self._remove_parser_of(entry)
        self._parse_done += 1

        self._current_illusts.extend(illusts)
        # 暂停重绘以提升大量卡片创建时的流畅度
        self.resultsView.setUpdatesEnabled(False)
        base_row = self.resultsGrid.rowCount()
        for i, illust in enumerate(illusts):
            rank = illust.get('rank', 0) if 'rank' in illust else 0
            card = PixivCard(illust, rank=rank, parent=self.resultsView)
            card.downloadRequested.connect(self._on_card_download_requested)
            row = base_row + i // 4
            col = i % 4
            self.resultsGrid.addWidget(card, row, col)
            self._cards.append(card)
        self.resultsView.setUpdatesEnabled(True)
        self.resultsView.update()

        self._update_parse_progress()
        # 启动下一条（保持并发数）
        self._launch_next_parser()

    def _on_parse_error(self, message, entry):
        """单条解析失败，记录后继续下一条"""
        self._remove_parser_of(entry)
        self._parse_done += 1
        self._parse_failed += 1
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
            self.emptyLabel.setVisible(False)
            self.resultsScroll.setVisible(True)
        else:
            self.emptyLabel.setVisible(True)
            self.emptyLabel.setText("解析失败")
            self.resultsScroll.setVisible(False)

        self.batchBtn.setVisible(len(self._cards) > 2)

        # 汇总提示
        if self._parse_failed:
            msg = f"共 {self._parse_total} 条输入，成功 {self._parse_total - self._parse_failed} 条，失败 {self._parse_failed} 条"
            show_error(self, "部分内容解析失败", msg)
        else:
            show_success(self, "解析完成", f"共 {self._parse_total} 条输入，找到 {len(self._cards)} 个作品")

    def _remove_parser_of(self, entry: str):
        """从活动线程列表中移除指定条目的解析线程并回收"""
        for t in list(self._active_parsers):
            if getattr(t, 'entry', None) == entry:
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
        # 禁用输入相关控件
        self.parseBtn.setEnabled(False)
        self.pasteBtn.setEnabled(False)
        self.appendBtn.setEnabled(False)
        self.urlEdit.setEnabled(False)
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
                save_path = os.path.join(save_path, 'tag ' + self.urlEdit.toPlainText().strip())
            elif mode == 'ranking':
                import datetime
                save_path = os.path.join(save_path, str(datetime.date.today()) + ' ranking')
            elif mode == 'history_ranking':
                save_path = os.path.join(save_path, self.urlEdit.toPlainText().strip() + ' ranking')

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
        # 恢复输入相关控件
        if not self._queue_parsing:
            self.parseBtn.setEnabled(True)
            self.pasteBtn.setEnabled(True)
            self.appendBtn.setEnabled(True)
            self.urlEdit.setEnabled(True)
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