# -*- coding: utf-8 -*-
"""
音乐界面（UI 层）
=================
搜索音乐 / 歌单解析 / 播放器 等 GUI 界面。

业务逻辑已提取至 app/services/netease_music.py。
"""
import os
import warnings

from PyQt5.QtCore import Qt, QUrl, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
    QMessageBox, QStackedWidget, QTableWidgetItem,
)

from qfluentwidgets import (
    setTheme, Theme, FluentWindow, NavigationItemPosition,
    FluentIcon, SearchLineEdit, PushButton, PrimaryPushButton,
    TableWidget, LineEdit, TextEdit, ComboBox,
    InfoBar, StateToolTip,
    BodyLabel, TitleLabel,
    SimpleCardWidget,
    SmoothScrollArea,
    MessageBox,
    ProgressBar,
    SwitchButton,
    TransparentToolButton,
    SegmentedWidget,
)

from core.logger import logger
from ui.widgets.ui_utils import install_hover_tip, success_flyout, info_flyout, warning_flyout, error_flyout
from ui.widgets.theme import theme_color
from services.netease_music import (
    NeteaseMusicClient, SongInfo, seconds2hms, safe_extract,
    legalize_string, extract_urls, MUSIC_QUALITIES,
)
from pages.music.music_player_engine import MusicPlayerEngine, PlayMode, PlayState, PlaylistItem
from pages.music.music_player_ui import BottomPlayBar, PlayerPage, PlaylistPanel, CoverLoader
from pages.music.music_playlist_manager_page import PlaylistManagerPage
from core.database import init_music_tables

warnings.filterwarnings('ignore')


# ============================================================
# 工作线程
# ============================================================
class SearchWorker(QThread):
    """搜索工作线程"""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    _limit = 10  # 默认搜索数量

    def __init__(self, keyword: str, client: NeteaseMusicClient):
        super().__init__()
        self.keyword = keyword
        self.client = client

    def run(self):
        try:
            results = self.client.search(self.keyword, limit=self._limit)
            logger.info(f"音乐搜索: '{self.keyword}' -> {len(results)} 个结果")
            self.finished.emit(results)
        except Exception as e:
            logger.error(f"音乐搜索线程异常: {e}")
            self.error.emit(str(e))


class ParseWorker(QThread):
    """解析工作线程"""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, search_result: dict, parse_official: bool,
                 parse_thirdparty: bool, client: NeteaseMusicClient,
                 quality: str = 'hires'):
        super().__init__()
        self.search_result = search_result
        self.parse_official = parse_official
        self.parse_thirdparty = parse_thirdparty
        self.client = client
        self.quality = quality

    def run(self):
        try:
            song_info = SongInfo()

            # 第三方API解析（优先）
            if self.parse_thirdparty:
                self.progress.emit(0, 2)
                thirdparty_info = self.client.parse_with_thirdparty(self.search_result)
                if thirdparty_info.with_valid_download_url:
                    song_info = thirdparty_info

            # 官方API解析
            if self.parse_official:
                self.progress.emit(1, 2)
                official_info = self.client.parse_with_official(
                    self.search_result, quality=self.quality)
                if official_info.with_valid_download_url:
                    if not song_info.with_valid_download_url or official_info.largerthan(song_info):
                        song_info = official_info

            # 补齐信息
            if not song_info.song_name:
                song_info.song_name = legalize_string(self.search_result.get('name'))
                song_info.singers = legalize_string(', '.join([
                    s.get('name') for s in (safe_extract(self.search_result, ['ar'], []) or [])
                    if isinstance(s, dict) and s.get('name')
                ]))
                song_info.album = legalize_string(safe_extract(self.search_result, ['al', 'name'], ''))
                song_info.identifier = str(self.search_result.get('id', ''))
                song_info.duration_s = float(self.search_result.get('dt', 0) or 0) / 1000
                song_info.duration = seconds2hms(song_info.duration_s)
                song_info.cover_url = safe_extract(self.search_result, ['al', 'picUrl'], '')

            self.progress.emit(2, 2)
            self.finished.emit(song_info)
        except Exception as e:
            self.error.emit(str(e))


class PlaylistWorker(QThread):
    """歌单解析工作线程"""

    finished = pyqtSignal(list, str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, url: str, client: NeteaseMusicClient):
        super().__init__()
        self.url = url
        self.client = client

    def run(self):
        try:
            song_infos, playlist_name = self.client.parse_playlist(self.url)
            logger.info(f"歌单解析: '{playlist_name}' -> {len(song_infos)} 首歌曲")
            self.progress.emit(len(song_infos), len(song_infos))
            self.finished.emit(song_infos, playlist_name)
        except Exception as e:
            self.error.emit(str(e))


class DownloadWorker(QThread):
    """下载工作线程"""

    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, song_infos: list, save_dir: str, client: NeteaseMusicClient):
        super().__init__()
        self.song_infos = song_infos
        self.save_dir = save_dir
        self.client = client

    def run(self):
        total = len(self.song_infos)
        success_count = 0
        for i, song_info in enumerate(self.song_infos):
            try:
                if self.client.download_song(song_info, self.save_dir):
                    success_count += 1
            except Exception:
                pass
            self.progress.emit(i + 1, total)
        logger.info(f"音乐下载完成: {success_count}/{total} 首 -> {self.save_dir}")
        self.finished.emit(success_count > 0, f"下载完成: {success_count}/{total} 首")


# ============================================================
# UI 基类（公共方法）
# ============================================================
class MusicBaseInterface(SmoothScrollArea):
    """音乐界面公共基类"""

    def _cell(self, text):
        """创建表格单元格"""
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(Qt.AlignCenter)
        return item

    def show_error(self, title: str, message: str):
        """显示错误"""
        if getattr(self, 'state_tooltip', None):
            self.state_tooltip.setContent(f'错误: {message}')
            self.state_tooltip.setState(True)
            self.state_tooltip = None
        InfoBar.error(title, message, parent=self, duration=5000)
        try:
            error_flyout(title, message, self, self)
        except Exception:
            pass


# ============================================================
# 歌曲搜索界面
# ============================================================
class SearchMusicInterface(MusicBaseInterface):
    """搜索音乐界面"""

    QUALITY_LABELS = ['hires (Hi-Res)', 'lossless (无损)', 'exhigh (高音质)', 'standard (标准)']
    QUALITY_VALUES = ['hires', 'lossless', 'exhigh', 'standard']
    LIMIT_VALUES = [10, 15, 20, 25, 30]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = NeteaseMusicClient()
        self.search_results = []
        self.song_infos = {}
        self.current_worker = None
        self.setObjectName('searchInterface')
        self.setup_ui()

    def setup_ui(self):
        self.setWidgetResizable(True)
        container = QWidget(self)
        self.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题
        layout.addWidget(TitleLabel('🎵 网易云音乐搜索'))
        desc_label = BodyLabel('搜索歌曲、解析下载链接，支持高品质音频')
        desc_label.setStyleSheet('color: ' + theme_color('#888888', '#AAAAAA') + ';')
        layout.addWidget(desc_label)

        # 搜索栏
        search_card = SimpleCardWidget()
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(15, 15, 15, 15)

        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText('输入歌曲名称、歌手或关键词...')
        self.search_input.setMinimumWidth(400)
        self.search_input.searchSignal.connect(self.on_search)
        search_layout.addWidget(self.search_input)

        self.search_btn = PrimaryPushButton('搜索')
        self.search_btn.setIcon(FluentIcon.SEARCH)
        self.search_btn.clicked.connect(self.on_search)
        search_layout.addWidget(self.search_btn)

        # 结果数量选择
        self.limit_combo = ComboBox()
        self.limit_combo.addItems(['10 条', '15 条', '20 条', '25 条', '30 条'])
        search_layout.addWidget(self.limit_combo)

        # 品质选择
        self.quality_combo = ComboBox()
        self.quality_combo.addItems(self.QUALITY_LABELS)
        search_layout.addWidget(self.quality_combo)

        # 解析选项
        self.parse_official_switch = SwitchButton('官方API')
        self.parse_official_switch.setOnText('已开启')
        self.parse_official_switch.setOffText('已关闭')
        self.parse_official_switch.setChecked(True)
        search_layout.addWidget(self.parse_official_switch)

        self.parse_thirdparty_switch = SwitchButton('第三方API')
        self.parse_thirdparty_switch.setOnText('已开启')
        self.parse_thirdparty_switch.setOffText('已关闭')
        self.parse_thirdparty_switch.setChecked(True)
        search_layout.addWidget(self.parse_thirdparty_switch)

        layout.addWidget(search_card)

        # 进度条
        self.progress_bar = ProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.state_tooltip = None

        # 结果表格
        result_card = SimpleCardWidget()
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(10, 10, 10, 10)

        result_header = QHBoxLayout()
        result_header.addWidget(BodyLabel('搜索结果'))
        result_header.addStretch()

        self.download_btn = PushButton('下载选中')
        self.download_btn.setIcon(FluentIcon.DOWNLOAD)
        self.download_btn.clicked.connect(self.download_selected)
        self.download_btn.setEnabled(False)
        result_header.addWidget(self.download_btn)

        self.parse_all_btn = PushButton('解析全部')
        self.parse_all_btn.setIcon(FluentIcon.SYNC)
        self.parse_all_btn.clicked.connect(self.parse_all_results)
        self.parse_all_btn.setEnabled(False)
        result_header.addWidget(self.parse_all_btn)

        self.copy_link_btn = PushButton('复制链接')
        self.copy_link_btn.setIcon(FluentIcon.LINK)
        self.copy_link_btn.clicked.connect(self.copy_selected_link)
        self.copy_link_btn.setEnabled(False)
        result_header.addWidget(self.copy_link_btn)

        result_layout.addLayout(result_header)

        # 表格
        self.table = TableWidget()
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setWordWrap(False)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(['#', '歌曲名', '歌手', '专辑', '时长', '音质', '文件大小', '状态'])
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setSelectRightClickedRow(True)
        self.table.setSelectionMode(TableWidget.ExtendedSelection)
        self.table.setSelectionBehavior(TableWidget.SelectRows)

        for i, w in enumerate([50, 250, 200, 200, 100, 130, 100, 100]):
            self.table.setColumnWidth(i, w)

        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        result_layout.addWidget(self.table)
        layout.addWidget(result_card)

        # ── 按钮 / 开关悬停功能简介（移开鼠标自动消失）──
        install_hover_tip(self.search_btn, '搜索', '输入关键词后搜索网易云音乐')
        install_hover_tip(self.limit_combo, '结果数量', '设置每页搜索返回的结果条数')
        install_hover_tip(self.quality_combo, '音质选择', '选择解析/下载的音质（Hi-Res/无损/高音质/标准）')
        install_hover_tip(self.parse_official_switch, '官方API解析', '启用网易官方接口解析下载链接')
        install_hover_tip(self.parse_thirdparty_switch, '第三方API解析', '启用第三方接口解析下载链接（优先）')
        install_hover_tip(self.download_btn, '下载选中', '下载当前选中的歌曲到本地目录')
        install_hover_tip(self.parse_all_btn, '解析全部', '批量解析全部搜索结果的下载链接')
        install_hover_tip(self.copy_link_btn, '复制链接', '复制选中歌曲的下载链接到剪贴板')

    # ---------- 搜索 ----------
    def get_quality_value(self) -> str:
        """获取选择的品质"""
        idx = self.quality_combo.currentIndex()
        return self.QUALITY_VALUES[idx] if idx < len(self.QUALITY_VALUES) else 'hires'

    def on_search(self):
        """执行搜索"""
        keyword = self.search_input.text().strip()
        if not keyword:
            InfoBar.warning('提示', '请输入搜索关键词', parent=self, duration=3000)
            return
        from core.database import record_usage
        record_usage('music', 'search', keyword)

        limit_idx = self.limit_combo.currentIndex()
        limit = self.LIMIT_VALUES[limit_idx] if limit_idx < len(self.LIMIT_VALUES) else 10

        self.table.setRowCount(0)
        self.search_results = []
        self.song_infos = {}
        self.download_btn.setEnabled(False)
        self.parse_all_btn.setEnabled(False)
        self.copy_link_btn.setEnabled(False)

        self.state_tooltip = StateToolTip('搜索中', f'正在搜索 "{keyword}"...', self)
        self.state_tooltip.show()

        self.worker = SearchWorker(keyword, self.client)
        self.worker._limit = limit
        self.worker.finished.connect(self.on_search_finished)
        self.worker.error.connect(lambda e: self.show_error('搜索失败', e))
        self.worker.start()

    def on_search_finished(self, results: list):
        """搜索完成"""
        self.search_results = results

        if self.state_tooltip:
            self.state_tooltip.setContent(f'找到 {len(results)} 个结果')
            self.state_tooltip.setState(True)
            self.state_tooltip = None

        if not results:
            InfoBar.info('搜索结果', '未找到相关歌曲', parent=self, duration=3000)
            return

        self.table.setRowCount(len(results))
        for i, song in enumerate(results):
            name = song.get('name', '未知')
            artists = ', '.join([
                a.get('name', '') for a in (safe_extract(song, ['ar'], []) or [])
                if isinstance(a, dict)
            ]) or '未知'
            album = safe_extract(song, ['al', 'name'], '未知')
            duration_s = float(song.get('dt', 0) or 0) / 1000

            self.table.setItem(i, 0, self._cell(str(i + 1)))
            self.table.setItem(i, 1, self._cell(name))
            self.table.setItem(i, 2, self._cell(artists))
            self.table.setItem(i, 3, self._cell(album))
            self.table.setItem(i, 4, self._cell(seconds2hms(duration_s)))
            self.table.setItem(i, 5, self._cell('-'))
            self.table.setItem(i, 6, self._cell('-'))
            self.table.setItem(i, 7, self._cell('待解析'))

        self.parse_all_btn.setEnabled(True)
        InfoBar.success('搜索完成', f'找到 {len(results)} 个结果', parent=self, duration=3000)

    # ---------- 解析 ----------
    def parse_all_results(self):
        """解析所有搜索结果"""
        if not self.search_results:
            return

        self.parse_all_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.copy_link_btn.setEnabled(False)

        self.state_tooltip = StateToolTip('解析中', f'正在解析 0/{len(self.search_results)} 首歌曲...', self)
        self.state_tooltip.show()

        self._parse_index = 0
        self._parse_results = []
        self._parse_next()

    def _parse_next(self):
        """解析下一首歌曲"""
        if self._parse_index >= len(self.search_results):
            self.song_infos = {
                i: info for i, info in enumerate(self._parse_results)
                if info.with_valid_download_url
            }
            if self.state_tooltip:
                self.state_tooltip.setContent(
                    f'解析完成: {len(self._parse_results)} 首, 其中 {len(self.song_infos)} 首获取到链接')
                self.state_tooltip.setState(True)
                self.state_tooltip = None
            self.update_table_with_results()
            self.parse_all_btn.setEnabled(True)
            if self.song_infos:
                self.download_btn.setEnabled(True)
            return

        search_result = self.search_results[self._parse_index]
        quality = self.get_quality_value()

        self.worker = ParseWorker(
            search_result,
            self.parse_official_switch.isChecked(),
            self.parse_thirdparty_switch.isChecked(),
            self.client,
            quality
        )
        self.worker.finished.connect(self._on_parse_single_finished)
        self.worker.error.connect(self._on_parse_single_error)
        self.worker.start()

    def _on_parse_single_finished(self, song_info: SongInfo):
        """单首解析完成"""
        self._parse_results.append(song_info)
        row = self._parse_index
        if row < self.table.rowCount():
            if song_info.with_valid_download_url:
                ext = song_info.ext.upper().replace('.', '') if song_info.ext else ''
                self.table.setItem(row, 5, self._cell(f"{song_info.quality} [{ext}]"))
                self.table.setItem(row, 6, self._cell(song_info.file_size))
                self.table.setItem(row, 7, self._cell('✅ 已解析'))
            else:
                self.table.setItem(row, 7, self._cell('❌ 无链接'))

        self._parse_index += 1
        if self.state_tooltip:
            self.state_tooltip.setContent(
                f'正在解析 {self._parse_index}/{len(self.search_results)} 首歌曲...')
        self._parse_next()

    def _on_parse_single_error(self, error: str):
        """单首解析出错"""
        self._parse_results.append(SongInfo())
        row = self._parse_index
        if row < self.table.rowCount():
            self.table.setItem(row, 7, self._cell('❌ 解析失败'))
        self._parse_index += 1
        if self.state_tooltip:
            self.state_tooltip.setContent(
                f'正在解析 {self._parse_index}/{len(self.search_results)} 首歌曲...')
        self._parse_next()

    def update_table_with_results(self):
        """用解析结果更新表格"""
        for i, info in enumerate(self._parse_results):
            if i >= self.table.rowCount():
                continue
            if info.with_valid_download_url:
                ext = info.ext.upper().replace('.', '') if info.ext else ''
                self.table.setItem(i, 5, self._cell(f"{info.quality} [{ext}]"))
                self.table.setItem(i, 6, self._cell(info.file_size))
                self.table.setItem(i, 7, self._cell('✅ 已解析'))

    # ---------- 选择/下载/复制 ----------
    def on_selection_changed(self):
        """选择变化时"""
        selected = self.table.selectedItems()
        has_selection = len(selected) > 0
        has_parsed = False
        for item in selected:
            row = item.row()
            status = self.table.item(row, 7)
            if status and '✅' in status.text():
                has_parsed = True
                break
        self.copy_link_btn.setEnabled(has_parsed)
        self.download_btn.setEnabled(bool(self.song_infos) and has_selection)

    def download_selected(self):
        """下载选中的歌曲"""
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            InfoBar.warning('提示', '请先选择要下载的歌曲', parent=self, duration=3000)
            return

        to_parse = []
        to_download = []
        for row in selected_rows:
            if row in self.song_infos:
                to_download.append(self.song_infos[row])
            elif row < len(self.search_results):
                to_parse.append(row)

        if to_parse:
            InfoBar.info('提示', f'需先解析 {len(to_parse)} 首未解析的歌曲', parent=self, duration=3000)
            return

        if not to_download:
            InfoBar.warning('提示', '所选歌曲均无可用的下载链接', parent=self, duration=3000)
            return

        save_dir = QFileDialog.getExistingDirectory(self, '选择保存目录')
        if not save_dir:
            return

        self.state_tooltip = StateToolTip('下载中', f'正在下载 0/{len(to_download)} 首歌曲...', self)
        self.state_tooltip.show()

        self.download_worker = DownloadWorker(to_download, save_dir, self.client)
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.error.connect(lambda e: self.show_error('下载失败', e))
        self.download_worker.start()

    def on_download_finished(self, success: bool, message: str):
        """下载完成"""
        if self.state_tooltip:
            self.state_tooltip.setContent(message)
            self.state_tooltip.setState(True)
            self.state_tooltip = None
        from core.database import record_usage
        record_usage('music', 'download', message)
        InfoBar.success('下载完成', message, parent=self, duration=5000)

    def copy_selected_link(self):
        """复制选中歌曲的链接"""
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        links = []
        for row in selected_rows:
            if row in self.song_infos:
                info = self.song_infos[row]
                if info.with_valid_download_url:
                    url = info.download_url if isinstance(info.download_url, str) \
                        else info.download_url.get('url', '')
                    links.append(f"{info.song_name} - {info.singers}: {url}")

        if links:
            QApplication.clipboard().setText('\n'.join(links))
            InfoBar.success('已复制', f'已复制 {len(links)} 个链接到剪贴板', parent=self, duration=3000)
        else:
            InfoBar.warning('提示', '未选中任何有效链接', parent=self, duration=3000)


# ============================================================
# 歌单解析界面
# ============================================================
class PlaylistInterface(MusicBaseInterface):
    """歌单解析界面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = NeteaseMusicClient()
        self.playlist_songs = []
        self.song_infos = {}
        self.setObjectName('playlistInterface')
        self.setup_ui()

    def setup_ui(self):
        self.setWidgetResizable(True)
        container = QWidget(self)
        self.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题
        layout.addWidget(TitleLabel('📋 歌单解析'))
        desc_label = BodyLabel('输入网易云音乐歌单链接，批量解析歌曲')
        desc_label.setStyleSheet('color: ' + theme_color('#888888', '#AAAAAA') + ';')
        layout.addWidget(desc_label)

        # 歌单链接输入
        card = SimpleCardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 15, 15, 15)

        input_layout = QHBoxLayout()
        self.url_input = LineEdit()
        self.url_input.setPlaceholderText('粘贴网易云音乐歌单链接...')
        self.url_input.setClearButtonEnabled(True)
        input_layout.addWidget(self.url_input)

        self.parse_btn = PrimaryPushButton('解析歌单')
        self.parse_btn.setIcon(FluentIcon.SYNC)
        self.parse_btn.clicked.connect(self.parse_playlist)
        input_layout.addWidget(self.parse_btn)
        card_layout.addLayout(input_layout)

        # 解析选项
        option_layout = QHBoxLayout()
        self.parse_all_switch = SwitchButton('自动解析所有歌曲')
        self.parse_all_switch.setOnText('开启')
        self.parse_all_switch.setOffText('关闭')
        self.parse_all_switch.setChecked(True)
        option_layout.addWidget(self.parse_all_switch)
        option_layout.addStretch()
        card_layout.addLayout(option_layout)

        layout.addWidget(card)

        # 进度
        self.progress_bar = ProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 歌单信息
        self.playlist_info_label = BodyLabel('')
        self.playlist_info_label.setVisible(False)
        layout.addWidget(self.playlist_info_label)

        # 结果表格
        result_card = SimpleCardWidget()
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(10, 10, 10, 10)

        result_header = QHBoxLayout()
        result_header.addWidget(BodyLabel('歌单歌曲'))
        result_header.addStretch()

        self.download_all_btn = PushButton('下载全部')
        self.download_all_btn.setIcon(FluentIcon.DOWNLOAD)
        self.download_all_btn.clicked.connect(self.download_all)
        self.download_all_btn.setEnabled(False)
        result_header.addWidget(self.download_all_btn)
        result_layout.addLayout(result_header)

        self.table = TableWidget()
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['#', '歌曲名', '歌手', '专辑', '时长', '状态'])
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setSelectionMode(TableWidget.ExtendedSelection)
        self.table.setSelectionBehavior(TableWidget.SelectRows)
        for i, w in enumerate([50, 300, 200, 200, 100, 100]):
            self.table.setColumnWidth(i, w)

        result_layout.addWidget(self.table)
        layout.addWidget(result_card)

        # 歌词显示区域
        lyric_card = SimpleCardWidget()
        lyric_layout = QVBoxLayout(lyric_card)
        lyric_layout.setContentsMargins(10, 10, 10, 10)

        lyric_header = QHBoxLayout()
        lyric_header.addWidget(BodyLabel('歌词'))
        lyric_header.addStretch()
        self.lyric_copy_btn = PushButton('复制歌词')
        self.lyric_copy_btn.setIcon(FluentIcon.COPY)
        self.lyric_copy_btn.clicked.connect(self.copy_lyric)
        self.lyric_copy_btn.setEnabled(False)
        lyric_header.addWidget(self.lyric_copy_btn)
        lyric_layout.addLayout(lyric_header)

        self.lyric_text = TextEdit()
        self.lyric_text.setReadOnly(True)
        self.lyric_text.setPlaceholderText('点击歌曲查看歌词')
        self.lyric_text.setMaximumHeight(200)
        lyric_layout.addWidget(self.lyric_text)
        layout.addWidget(lyric_card)

        # ── 歌单解析页悬停功能简介 ──
        install_hover_tip(self.url_input, '歌单链接', '粘贴网易云音乐歌单链接，支持自动提取 URL')
        install_hover_tip(self.parse_btn, '解析歌单', '获取歌单中的所有歌曲信息')
        install_hover_tip(self.parse_all_switch, '自动解析所有歌曲', '解析歌单后自动批量解析全部歌曲的下载链接')
        install_hover_tip(self.download_all_btn, '下载全部', '下载所有已解析成功的歌曲到本地目录')
        install_hover_tip(self.lyric_copy_btn, '复制歌词', '复制当前显示的歌词到剪贴板')
        install_hover_tip(self.lyric_text, '歌词显示', '点击歌单中的歌曲可查看其歌词')
        install_hover_tip(self.table, '歌曲列表', '显示歌单中的所有歌曲，双击可播放')

    # ---------- 解析流程 ----------
    def parse_playlist(self):
        """解析歌单"""
        url = self.url_input.text().strip()
        if not url:
            InfoBar.warning('提示', '请输入歌单链接', parent=self, duration=3000)
            return

        urls = extract_urls(url)
        if not urls:
            InfoBar.warning('提示', '未找到有效的链接', parent=self, duration=3000)
            return

        self.parse_btn.setEnabled(False)
        self.table.setRowCount(0)
        self.playlist_songs = []
        self.song_infos = {}
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.state_tooltip = StateToolTip('解析歌单', '正在获取歌单信息...', self)
        self.state_tooltip.show()

        self.worker = PlaylistWorker(urls[0], self.client)
        self.worker.finished.connect(self.on_playlist_finished)
        self.worker.error.connect(lambda e: self.show_error('解析失败', e))
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.start()

    def on_playlist_finished(self, song_infos: list, playlist_name: str):
        """歌单解析完成"""
        self.playlist_songs = song_infos

        if self.state_tooltip:
            self.state_tooltip.setContent(f'找到 {len(song_infos)} 首歌曲')
            self.state_tooltip.setState(True)
            self.state_tooltip = None

        self.progress_bar.setVisible(False)
        self.parse_btn.setEnabled(True)

        if not song_infos:
            InfoBar.info('歌单解析', '未找到歌曲或歌单不存在', parent=self, duration=3000)
            return

        self.playlist_info_label.setText(f'📁 {playlist_name} — 共 {len(song_infos)} 首歌曲')
        self.playlist_info_label.setVisible(True)

        self.table.setRowCount(len(song_infos))
        for i, info in enumerate(song_infos):
            self.table.setItem(i, 0, self._cell(str(i + 1)))
            self.table.setItem(i, 1, self._cell(info.song_name))
            self.table.setItem(i, 2, self._cell(info.singers))
            self.table.setItem(i, 3, self._cell(info.album))
            self.table.setItem(i, 4, self._cell(info.duration))
            self.table.setItem(i, 5, self._cell('待解析'))

        self.download_all_btn.setEnabled(True)

        if self.parse_all_switch.isChecked():
            self.parse_all_songs()

        InfoBar.success('歌单解析完成', f'共 {len(song_infos)} 首歌曲', parent=self, duration=3000)

    def parse_all_songs(self):
        """解析所有歌曲"""
        self.state_tooltip = StateToolTip(
            '解析中', f'正在解析 0/{len(self.playlist_songs)} 首歌曲...', self)
        self.state_tooltip.show()
        self.download_all_btn.setEnabled(False)

        self._parse_index = 0
        self._parse_next_song()

    def _parse_next_song(self):
        """解析下一首歌"""
        if self._parse_index >= len(self.playlist_songs):
            if self.state_tooltip:
                self.state_tooltip.setContent(f'解析完成: {len(self.song_infos)} 首获取到链接')
                self.state_tooltip.setState(True)
                self.state_tooltip = None
            self.download_all_btn.setEnabled(True)
            InfoBar.success('解析完成', f'{len(self.song_infos)} 首歌曲获取到下载链接',
                            parent=self, duration=3000)
            return

        song_info = self.playlist_songs[self._parse_index]
        search_data = {'id': song_info.identifier, 'name': song_info.song_name}

        self.worker = ParseWorker(
            search_data,
            parse_official=True,
            parse_thirdparty=True,
            client=self.client,
            quality='hires'
        )
        self.worker.finished.connect(self._on_parse_song_finished)
        self.worker.error.connect(self._on_parse_song_error)
        self.worker.start()

    def _on_parse_song_finished(self, result: SongInfo):
        """单首歌曲解析完成"""
        row = self._parse_index
        if result.with_valid_download_url:
            self.song_infos[self._parse_index] = result
            if row < self.table.rowCount():
                ext = result.ext.upper().replace('.', '') if result.ext else ''
                self.table.setItem(row, 5, self._cell(f'✅ {result.quality} [{ext}]'))
        else:
            if row < self.table.rowCount():
                self.table.setItem(row, 5, self._cell('❌ 无链接'))

        self._parse_index += 1
        if self.state_tooltip:
            self.state_tooltip.setContent(
                f'正在解析 {self._parse_index}/{len(self.playlist_songs)} 首歌曲...')
        self._parse_next_song()

    def _on_parse_song_error(self, error: str):
        """单首歌曲解析出错"""
        row = self._parse_index
        if row < self.table.rowCount():
            self.table.setItem(row, 5, self._cell('❌ 解析失败'))
        self._parse_index += 1
        if self.state_tooltip:
            self.state_tooltip.setContent(
                f'正在解析 {self._parse_index}/{len(self.playlist_songs)} 首歌曲...')
        self._parse_next_song()

    # ---------- 下载/复制 ----------
    def download_all(self):
        """下载所有已解析的歌曲"""
        if not self.song_infos:
            InfoBar.warning('提示', '请先解析歌曲', parent=self, duration=3000)
            return

        to_download = list(self.song_infos.values())
        if not to_download:
            InfoBar.warning('提示', '没有可下载的歌曲', parent=self, duration=3000)
            return

        save_dir = QFileDialog.getExistingDirectory(self, '选择保存目录')
        if not save_dir:
            return

        self.state_tooltip = StateToolTip('下载中', f'正在下载 0/{len(to_download)} 首歌曲...', self)
        self.state_tooltip.show()

        self.download_worker = DownloadWorker(to_download, save_dir, self.client)
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.error.connect(lambda e: self.show_error('下载失败', e))
        self.download_worker.start()

    def on_download_finished(self, success: bool, message: str):
        """下载完成"""
        if self.state_tooltip:
            self.state_tooltip.setContent(message)
            self.state_tooltip.setState(True)
            self.state_tooltip = None
        InfoBar.success('下载完成', message, parent=self, duration=5000)

    def copy_lyric(self):
        """复制歌词"""
        text = self.lyric_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            InfoBar.success('已复制', '歌词已复制到剪贴板', parent=self, duration=3000)


# ============================================================
# 音乐主界面（标签页切换）
# ============================================================
class MusicInterface(QWidget):
    """音乐主界面 - 搜索音乐 + 歌单解析 + 底部播放栏 + 播放页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('musicInterface')

        # ── 播放引擎（全局单例） ──────────────────────────
        self.engine = MusicPlayerEngine(self)

        # ── 主布局 ────────────────────────────────────────
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 48, 0, 0)

        # ── 内容区（含 SegmentedWidget 切换） ────────────
        self.pivot = SegmentedWidget(self)
        self.stackedWidget = QStackedWidget(self)

        init_music_tables()

        self.searchInterface = SearchMusicInterface(self)
        self.searchInterface.setObjectName('musicSearchTab')
        self.playlistInterface = PlaylistInterface(self)
        self.playlistInterface.setObjectName('musicPlaylistTab')
        self.playlistManagerPage = PlaylistManagerPage(self.engine, self)
        self.playlistManagerPage.setObjectName('musicPlaylistManagerTab')

        self.stackedWidget.addWidget(self.searchInterface)
        self.stackedWidget.addWidget(self.playlistInterface)
        self.stackedWidget.addWidget(self.playlistManagerPage)

        self.pivot.addItem(routeKey='musicSearchTab', text='搜索音乐')
        self.pivot.addItem(routeKey='musicPlaylistTab', text='歌单解析')
        self.pivot.addItem(routeKey='musicPlaylistManagerTab', text='我的列表')
        self.stackedWidget.setCurrentWidget(self.searchInterface)
        self.pivot.setCurrentItem('musicSearchTab')
        self.pivot.currentItemChanged.connect(self._onCurrentItemChanged)

        # ── 布局：内容页 + 播放页面 ───────────────────────
        self._main_container = QStackedWidget(self)
        self._content_widget = QWidget()
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.pivot)
        content_layout.addWidget(self.stackedWidget, 1)

        self.playerPage = PlayerPage(self.engine, self)
        self.playerPage.closeRequested.connect(self._close_player_page)

        self._main_container.addWidget(self._content_widget)  # index 0
        self._main_container.addWidget(self.playerPage)       # index 1
        self._main_container.setCurrentIndex(0)

        self.vBoxLayout.addWidget(self._main_container, 1)

        # ── 底部播放栏 ────────────────────────────────────
        self.bottomBar = BottomPlayBar(self.engine, self)
        self.bottomBar.showPlaylistRequested.connect(self._show_playlist)
        self.bottomBar.cover_label.mousePressEvent = self._on_cover_click
        self.vBoxLayout.addWidget(self.bottomBar)

        # ── 播放列表面板（悬浮式） ────────────────────────
        self.playlistPanel = PlaylistPanel(self)
        self.playlistPanel.playRequested.connect(self._on_playlist_play)
        self.playlistPanel.removeRequested.connect(self._on_playlist_remove)
        self.playlistPanel.moveRequested.connect(self._on_playlist_move)
        self.playlistPanel.clearRequested.connect(self._on_playlist_clear)
        self.engine.playlistChanged.connect(self._on_playlist_updated)

        # ── 连接搜索表格双击播放 ─────────────────────────
        self.searchInterface.table.cellDoubleClicked.connect(self._on_search_table_double_click)

        InfoBar.success('播放器就绪', '双击搜索结果即可播放', parent=self, duration=3000)

    # ── 分段切换 ──────────────────────────────────────────
    def _onCurrentItemChanged(self, routeKey: str):
        widget = self.findChild(QWidget, routeKey)
        if widget:
            self.stackedWidget.setCurrentWidget(widget)

    # ── 播放页切换 ────────────────────────────────────────
    def _open_player_page(self):
        """打开全屏播放页面"""
        self._main_container.setCurrentIndex(1)

    def _close_player_page(self):
        """关闭全屏播放页面"""
        self._main_container.setCurrentIndex(0)

    # ── 从搜索结果双击播放 ────────────────────────────────
    def _on_search_table_double_click(self, row: int, column: int):
        """双击搜索结果的某一行，播放该歌曲"""
        if row < 0 or row >= len(self.searchInterface.search_results):
            return
        search_result = self.searchInterface.search_results[row]

        # 已解析且有有效播放地址的直接播放
        if hasattr(self.searchInterface, 'song_infos') and row in self.searchInterface.song_infos:
            song_info = self.searchInterface.song_infos[row]
            if song_info.with_valid_download_url:
                item = PlaylistItem.from_song_info(song_info)
                self.engine.add_song(item)
                self.engine.play_index(len(self.engine.playlist) - 1)
                self._open_player_page()
                return

        # 解析列表中有且带有效播放地址
        if hasattr(self.searchInterface, '_parse_results') and row < len(self.searchInterface._parse_results):
            song_info = self.searchInterface._parse_results[row]
            if song_info.with_valid_download_url:
                item = PlaylistItem.from_song_info(song_info)
                self.engine.add_song(item)
                self.engine.play_index(len(self.engine.playlist) - 1)
                self._open_player_page()
                return

        # 未解析 / 解析失败无链接 - 重新解析再播放
        InfoBar.info('提示', f'正在重新解析 "{search_result.get("name", "未知")}"...',
                     parent=self, duration=2000)
        self._parse_and_play(search_result)

    def _parse_and_play(self, search_result: dict):
        """解析单首歌曲并立即播放"""
        quality = self.searchInterface.get_quality_value()
        self._parse_worker = ParseWorker(
            search_result,
            self.searchInterface.parse_official_switch.isChecked(),
            self.searchInterface.parse_thirdparty_switch.isChecked(),
            self.searchInterface.client,
            quality
        )
        self._parse_worker.finished.connect(lambda info: self._on_parsed_for_play(info))
        self._parse_worker.error.connect(lambda e: InfoBar.error('解析失败', e, parent=self))
        self._parse_worker.start()

    def _on_parsed_for_play(self, song_info):
        """解析完成后播放"""
        if not song_info.with_valid_download_url:
            self._parse_worker = None
            InfoBar.warning(
                '无法播放',
                f'歌曲 "{song_info.song_name or "未知"}" 暂时无法获取有效的播放地址，'
                '可能是版权限制、需VIP或网络问题。',
                parent=self, duration=4000)
            return
        item = PlaylistItem.from_song_info(song_info)
        self.engine.add_song(item)
        self.engine.play_index(len(self.engine.playlist) - 1)
        self._open_player_page()
        self._parse_worker = None

    # ── 播放列表 ──────────────────────────────────────────
    def _show_playlist(self):
        """显示播放列表面板"""
        self.playlistPanel.update_list(self.engine.playlist, self.engine.current_index)
        btn = self.bottomBar.playlist_btn
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        pw = self.playlistPanel.width()
        ph = self.playlistPanel.height()

        x = pos.x() - 380
        y = pos.y() - ph - 4

        win = self.window()
        if win:
            win_geo = win.geometry()
            if x + pw > win_geo.right():
                x = win_geo.right() - pw - 10
            if x < win_geo.left():
                x = win_geo.left() + 10
            if y < win_geo.top():
                y = win_geo.top() + 10
            if y + ph > win_geo.bottom():
                y = win_geo.bottom() - ph - 10

        self.playlistPanel.move(x, y)
        self.playlistPanel.show()

    def _on_playlist_play(self, index: int):
        self.engine.play_index(index)
        self.playlistPanel.hide()
        self._open_player_page()

    def _on_playlist_remove(self, index: int):
        self.engine.remove_song(index)
        self.playlistPanel.update_list(self.engine.playlist, self.engine.current_index)

    def _on_playlist_move(self, from_idx: int, to_idx: int):
        self.engine.move_song(from_idx, to_idx)

    def _on_playlist_clear(self):
        self.engine.clear_playlist()
        self.playlistPanel.update_list([], -1)
        self.playlistPanel.hide()

    def _on_cover_click(self, event):
        """封面点击 → 打开全屏播放页面"""
        self._open_player_page()

    def _on_playlist_updated(self):
        """播放列表更新时刷新面板"""
        if self.playlistPanel.isVisible():
            self.playlistPanel.update_list(self.engine.playlist, self.engine.current_index)


# ============================================================
# 原独立主窗口（保留，用于单独运行）
# ============================================================
class MainWindow(FluentWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('网易云音乐解析工具')
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        self.search_interface = SearchMusicInterface(self)
        self.playlist_interface = PlaylistInterface(self)

        self.addSubInterface(self.search_interface, FluentIcon.MUSIC, '搜索音乐')
        self.addSubInterface(self.playlist_interface, FluentIcon.LIBRARY, '歌单解析')

        self.navigationInterface.setExpandWidth(200)

        self.setting_btn = TransparentToolButton(FluentIcon.SETTING)
        self.setting_btn.clicked.connect(self.show_about)
        self.navigationInterface.addWidget(
            'settings',
            self.setting_btn,
            self.show_about,
            NavigationItemPosition.BOTTOM
        )

    def show_about(self):
        """显示关于信息"""
        content = """🎵 网易云音乐解析工具 v1.0

基于 QFluentWidgets 构建的高品质音乐解析工具。

功能：
• 关键词搜索歌曲
• 支持 Hi-Res / 无损 / 高音质解析
• 歌单批量解析
• 第三方 API 辅助解析

注意：本工具仅供学习研究使用，请遵守相关法律法规。
"""
        w = MessageBox('关于', content, self)
        w.yesButton.setText('确定')
        w.cancelButton.hide()
        w.exec_()


# ============================================================
# 程序入口
# ============================================================
def main():
    """主函数"""
    import sys

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    app.setApplicationName('网易云音乐解析工具')

    setTheme(Theme.AUTO)

    font = QFont('Microsoft YaHei UI', 9)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()