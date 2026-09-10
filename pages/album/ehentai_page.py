# -*- coding: utf-8 -*-
"""
E-Hentai 子模块页面（OGC 集成版）
=================================
将独立程序 OGC-E-hentai 的「下载画廊」「我的收藏」「设置」三个页面
合并为一个页面，顶部用分段导航栏（SegmentedWidget）切换。

结构：
    EhentaiPage (QWidget)
    ├── 标题行（E-Hentai + 简介）
    ├── SegmentedWidget（下载画廊 / 我的收藏 / 设置）
    └── QStackedWidget
        ├── DownloadPage      —— 下载画廊（含迷你下载窗口）
        ├── FavoritesPage     —— 我的收藏（数据库可动态切换）
        └── SettingPage       —— 设置（含手动选择数据库文件）
"""
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SegmentedWidget,
    StrongBodyLabel,
    TextEdit,
    TitleLabel,
    ToolButton,
)

from services.ehentai_downloader import DownloadConfig, DownloadProgress, EhentaiDownloader
from pages.album.ehentai_favorites_page import FavoritesPage
from pages.album.ehentai_settings import SettingPage, ehentai_cfg, IMAGE_FORMAT_MAP

# EhViewer 子系统功能页（主页/搜索/历史/排行榜），就地并入本模块为分段页
from ehviewer.ui.home_page import HomePage
from ehviewer.ui.search_page import SearchPage
from ehviewer.ui.history_page import HistoryPage
from ehviewer.ui.top_list_page import TopListPage


# ============================================================
# 下载工作线程
# ============================================================
class DownloadWorker(QThread):
    """在后台线程中运行下载任务"""

    log_emitted = pyqtSignal(str, str)          # (message, level)
    progress_updated = pyqtSignal(object)       # DownloadProgress
    finished_signal = pyqtSignal(object)        # DownloadProgress

    def __init__(self, config: DownloadConfig, parent=None,
                 retry_failed: bool = False, downloader: EhentaiDownloader = None):
        super().__init__(parent)
        self.config = config
        self.retry_failed = retry_failed
        # 重试失败任务时复用上一次的 downloader（保留 _failed_tasks 和 _title）
        self.downloader = downloader if downloader is not None else EhentaiDownloader(config)
        self.downloader.set_listener(self)

    def run(self) -> None:
        if self.retry_failed:
            self.downloader.run_failed()
        else:
            self.downloader.run()

    def stop(self) -> None:
        self.downloader.stop()

    # ---- 下载器回调（在子线程中执行）----
    def on_log(self, msg: str, level: str = 'info') -> None:
        self.log_emitted.emit(msg, level)

    def on_progress(self, progress: DownloadProgress) -> None:
        self.progress_updated.emit(progress)

    def on_finished(self, progress: DownloadProgress) -> None:
        self.finished_signal.emit(progress)


# ============================================================
# 顶部输入栏卡片
# ============================================================
class DownloadCard(CardWidget):
    """顶部输入栏卡片：弹性布局、内嵌图标、响应式换行"""

    paste_requested = pyqtSignal()
    copy_requested = pyqtSignal()
    download_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    retry_requested = pyqtSignal()
    mini_window_requested = pyqtSignal()

    NARROW_WIDTH = 700  # 屏幕宽度阈值：以下切换为换行布局

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_vertical = False
        self._loading_state = 0
        self._build_ui()
        self._build_loading_timer()
        self._setup_horizontal_layout()
        self.setMinimumWidth(520)

    # ------------------------------------------------------------
    def _build_ui(self) -> None:
        # URL 输入框
        self.url_edit = LineEdit(self)
        self.url_edit.setFixedHeight(42)
        self.url_edit.setPlaceholderText(
            '输入 E-Hentai 画廊 URL，例如 https://e-hentai.org/g/4103360/b865187d64/')
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.textChanged.connect(self._on_url_changed)

        # 迷你窗口按钮（小号，弹出置顶的迷你下载窗口）
        self.mini_btn = ToolButton(FluentIcon.PROJECTOR, self)
        self.mini_btn.setFixedSize(42, 42)
        self.mini_btn.setToolTip('打开迷你下载窗口（置顶）')
        self.mini_btn.clicked.connect(self.mini_window_requested.emit)

        # 粘贴按钮（小号，高度匹配输入框）
        self.paste_btn = ToolButton(FluentIcon.PASTE, self)
        self.paste_btn.setFixedSize(42, 42)
        self.paste_btn.setToolTip('从剪贴板粘贴 URL')
        self.paste_btn.clicked.connect(self.paste_requested.emit)

        # 复制按钮（小号，高度匹配输入框）
        self.copy_btn = ToolButton(FluentIcon.COPY, self)
        self.copy_btn.setFixedSize(42, 42)
        self.copy_btn.setToolTip('复制 URL')
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self.copy_requested.emit)

        # 开始下载（主色）
        self.download_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, '开始下载', self)
        self.download_btn.setFixedSize(120, 42)
        self.download_btn.clicked.connect(self.download_requested.emit)

        # 停止（次要灰）
        self.stop_btn = PushButton(FluentIcon.CANCEL, '停止', self)
        self.stop_btn.setFixedSize(88, 42)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        # 重试失败（次要灰）
        self.retry_btn = PushButton(FluentIcon.UPDATE, '重试失败', self)
        self.retry_btn.setFixedSize(108, 42)
        self.retry_btn.setEnabled(False)
        self.retry_btn.setToolTip('重新下载上次失败的图片')
        self.retry_btn.clicked.connect(self.retry_requested.emit)

    def _build_loading_timer(self) -> None:
        """下载进行时「开始下载」按钮显示 loading 动画"""
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(400)
        self._loading_timer.timeout.connect(self._tick_loading)

    def _tick_loading(self) -> None:
        self._loading_state = (self._loading_state + 1) % 4
        self.download_btn.setText('下载中' + '.' * self._loading_state)

    def start_loading(self) -> None:
        self._loading_state = 0
        self.download_btn.setText('下载中')
        self.download_btn.setEnabled(False)
        self._loading_timer.start()

    def stop_loading(self) -> None:
        self._loading_timer.stop()
        self.download_btn.setText('开始下载')
        self.download_btn.setEnabled(True)

    # ------------------------------------------------------------
    def _on_url_changed(self, text: str) -> None:
        has_text = bool(text.strip())
        self.copy_btn.setEnabled(has_text)

    # ------------------------------------------------------------
    def _setup_horizontal_layout(self) -> None:
        """桌面宽屏：输入框 + 按钮一行对齐，输入框弹性占满"""
        layout = QHBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(self.url_edit, 1)
        layout.addWidget(self.mini_btn)
        layout.addWidget(self.paste_btn)
        layout.addWidget(self.copy_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.retry_btn)
        layout.addWidget(self.download_btn)
        self.setLayout(layout)
        self._main_layout = layout
        self._is_vertical = False

    def _setup_vertical_layout(self) -> None:
        """窄屏：输入框独占一行，按钮换行横向排列"""
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        row1.addWidget(self.url_edit, 1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addStretch(1)
        row2.addWidget(self.mini_btn)
        row2.addWidget(self.paste_btn)
        row2.addWidget(self.copy_btn)
        row2.addWidget(self.stop_btn)
        row2.addWidget(self.retry_btn)
        row2.addWidget(self.download_btn)
        layout.addLayout(row2)

        self.setLayout(layout)
        self._main_layout = layout
        self._is_vertical = True

    def _switch_layout(self, vertical: bool) -> None:
        if vertical == self._is_vertical:
            return
        old_layout = self.layout()
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    old_layout.removeWidget(widget)
                elif item.layout() is not None:
                    sub = item.layout()
                    while sub.count():
                        sub_item = sub.takeAt(0)
                        w = sub_item.widget()
                        if w is not None:
                            sub.removeWidget(w)
            # 立即销毁旧布局（sip.delete 同步销毁，避免 setLayout 冲突）
            from PyQt5 import sip
            sip.delete(old_layout)
        if vertical:
            self._setup_vertical_layout()
        else:
            self._setup_horizontal_layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        narrow = self.width() < self.NARROW_WIDTH
        self._switch_layout(narrow)

    # ------------------------------------------------------------
    def get_url(self) -> str:
        return self.url_edit.text().strip()

    def set_url(self, url: str) -> None:
        self.url_edit.setText(url)


# ============================================================
# 下载进度卡片
# ============================================================
class ProgressCard(CardWidget):
    """下载进度卡片：百分比 + 主题绿色进度条"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        # 标题行
        top_row = QHBoxLayout()
        self.title_label = StrongBodyLabel('下载进度', self)
        self.title_label.setStyleSheet('font-size: 16px; font-weight: 500;')
        top_row.addWidget(self.title_label)
        top_row.addStretch(1)
        self.status_label = CaptionLabel('等待开始', self)
        self.status_label.setStyleSheet('color: #57606a;')
        top_row.addWidget(self.status_label)
        layout.addLayout(top_row)

        # 进度条 + 百分比（进度条上下 14px 边距）
        layout.addSpacing(14)
        bar_row = QHBoxLayout()
        bar_row.setSpacing(12)
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #eceff2;
                border: none;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background: #2ea44f;
                border-radius: 5px;
            }
        """)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        bar_row.addWidget(self.progress_bar, 1)

        self.percent_label = BodyLabel('0%', self)
        self.percent_label.setFixedWidth(48)
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percent_label.setStyleSheet('color: #57606a; font-size: 14px;')
        bar_row.addWidget(self.percent_label)
        layout.addLayout(bar_row)
        layout.addSpacing(14)

        # 底部信息行（左右两端对齐）
        detail_row = QHBoxLayout()
        self.detail_label = CaptionLabel('共 0 张图片', self)
        self.detail_label.setStyleSheet('color: #57606a; font-size: 14px;')
        detail_row.addWidget(self.detail_label)
        detail_row.addStretch(1)
        self.page_label = CaptionLabel('分页 0/0', self)
        self.page_label.setStyleSheet('color: #57606a; font-size: 14px;')
        detail_row.addWidget(self.page_label)
        layout.addLayout(detail_row)

    def update_progress(self, p: DownloadProgress) -> None:
        if p.total > 0:
            percent = int(p.done / p.total * 100)
            self.progress_bar.setValue(percent)
        else:
            percent = 0
            self.progress_bar.setValue(0)

        self.percent_label.setText(f'{percent}%')
        self.detail_label.setText(f'完成 {p.done} / 共 {p.total}  |  失败 {p.failed}')
        self.page_label.setText(f'分页 {p.page}/{p.page_total}')

        if p.current:
            self.status_label.setText(p.current)
        elif p.finished:
            self.status_label.setText('已结束')
        elif p.total > 0:
            self.status_label.setText('下载中...')
        else:
            self.status_label.setText('解析中...')

    def reset(self) -> None:
        self.progress_bar.setValue(0)
        self.percent_label.setText('0%')
        self.status_label.setText('等待开始')
        self.detail_label.setText('共 0 张图片')
        self.page_label.setText('分页 0/0')


# ============================================================
# 运行日志卡片
# ============================================================
class LogCard(CardWidget):
    """运行日志卡片：等宽字体、颜色分级、自定义背景"""

    # 日志级别颜色
    LOG_COLORS = {
        'info': '#737a82',          # 普通灰
        'success': '#2ea44f',       # 成功绿
        'warning': '#d4a72c',       # 警告黄
        'error': '#cf222e',         # 错误红
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.title_label = StrongBodyLabel('运行日志', self)
        self.title_label.setStyleSheet('font-size: 16px; font-weight: 500;')
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.clear_btn = ToolButton(FluentIcon.BROOM, self)
        self.clear_btn.setToolTip('清空日志')
        self.clear_btn.setFixedSize(28, 28)
        header.addWidget(self.clear_btn)
        layout.addLayout(header)

        # 日志文本框：等宽字体、圆角、浅灰背景、自动换行
        self.log_view = TextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(40)
        self.log_view.setLineWrapMode(TextEdit.WidgetWidth)
        self.log_view.setPlaceholderText('日志将显示在这里...')
        self.log_view.setStyleSheet("""
            QTextEdit {
                background: #f7f8fa;
                border: 1px solid #e2e4e8;
                border-radius: 8px;
                padding: 8px 10px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #2ea44f;
            }
        """)
        layout.addWidget(self.log_view, 1)

    def append_log(self, msg: str, level: str = 'info') -> None:
        """追加日志（用 QTextCursor 设置颜色，避免 HTML 转义问题）"""
        color = self.LOG_COLORS.get(level, self.LOG_COLORS['info'])

        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)

        # 非空时先换行
        if self.log_view.toPlainText():
            cursor.insertText('\n')

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(msg)
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def clear_log(self) -> None:
        self.log_view.clear()


# ============================================================
# 迷你下载窗口
# ============================================================
class MiniDownloadWindow(QWidget):
    """迷你下载窗口：置顶显示下载页面的核心功能（输入、按钮、进度、日志）"""

    def __init__(self, page: 'DownloadPage', parent=None):
        super().__init__(parent)
        self.page = page
        self.setWindowTitle('迷你下载')
        # 宽度刚好完整显示全部按钮，日志区域仅显示两行文字
        self.setFixedSize(400, 200)
        # 窗口置顶
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 第一排：输入框
        self.url_edit = LineEdit(self)
        self.url_edit.setFixedHeight(36)
        self.url_edit.setPlaceholderText('输入 E-Hentai 画廊 URL')
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.textChanged.connect(self._on_url_changed)
        root.addWidget(self.url_edit)

        # 第二排：四个按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.paste_btn = ToolButton(FluentIcon.PASTE, self)
        self.paste_btn.setFixedSize(36, 32)
        self.paste_btn.setToolTip('从剪贴板粘贴 URL')
        self.paste_btn.clicked.connect(self.page._paste_url)

        self.stop_btn = PushButton(FluentIcon.CANCEL, '停止', self)
        self.stop_btn.setFixedSize(76, 32)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.page._stop_download)

        self.retry_btn = PushButton(FluentIcon.UPDATE, '重试失败', self)
        self.retry_btn.setFixedSize(108, 32)
        self.retry_btn.setEnabled(False)
        self.retry_btn.setToolTip('重新下载上次失败的图片')
        self.retry_btn.clicked.connect(self.page._retry_failed)

        self.download_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, '开始下载', self)
        self.download_btn.setFixedSize(108, 32)
        self.download_btn.clicked.connect(self.page._start_download)

        btn_row.addWidget(self.paste_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.retry_btn)
        btn_row.addWidget(self.download_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # 第三排：进度条 + 小字
        prog_row = QHBoxLayout()
        prog_row.setSpacing(10)
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #eceff2;
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: #2ea44f;
                border-radius: 4px;
            }
        """)
        prog_row.addWidget(self.progress_bar, 1)
        self.percent_label = BodyLabel('0%', self)
        self.percent_label.setFixedWidth(44)
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percent_label.setStyleSheet('color: #57606a; font-size: 12px;')
        prog_row.addWidget(self.percent_label)
        root.addLayout(prog_row)

        # 小字：总数 / 成功 / 失败
        self.detail_label = CaptionLabel('共 0 张 | 成功 0 张 | 失败 0 张', self)
        self.detail_label.setStyleSheet('color: #57606a; font-size: 12px;')
        root.addWidget(self.detail_label)

        # 日志区域：固定高度仅显示两行文字（超出通过内部滚动查看）
        self.log_view = TextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(46)
        self.log_view.setLineWrapMode(TextEdit.WidgetWidth)
        self.log_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.log_view.setPlaceholderText('日志将显示在这里...')
        self.log_view.setStyleSheet("""
            QTextEdit {
                background: #f7f8fa;
                border: 1px solid #e2e4e8;
                border-radius: 8px;
                padding: 4px 8px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 11px;
            }
            QTextEdit:focus {
                border: 1px solid #2ea44f;
            }
        """)
        root.addWidget(self.log_view)

    # ------------------------------------------------------------
    # 与主下载页面的同步（由 DownloadPage 调用）
    # ------------------------------------------------------------
    def sync_url(self, url: str) -> None:
        """主页面 URL 变化 -> 同步到迷你窗口输入框"""
        if self.url_edit.text() != url:
            self.url_edit.setText(url)

    def sync_running_state(self, running: bool) -> None:
        """同步按钮运行状态"""
        self.stop_btn.setEnabled(running)
        self.download_btn.setEnabled(not running)
        self.url_edit.setEnabled(not running)
        if running:
            self.retry_btn.setEnabled(False)
            self.download_btn.setText('下载中')
        else:
            self.download_btn.setText('开始下载')

    def sync_progress(self, p: DownloadProgress) -> None:
        """同步进度条 + 小字"""
        if p.total > 0:
            percent = int(p.done / p.total * 100)
            self.progress_bar.setValue(percent)
        else:
            percent = 0
            self.progress_bar.setValue(0)
        self.percent_label.setText(f'{percent}%')
        self.detail_label.setText(
            f'共 {p.total} 张 | 成功 {p.done} 张 | 失败 {p.failed} 张')

    def sync_log(self, msg: str, level: str = 'info') -> None:
        """追加日志"""
        color = LogCard.LOG_COLORS.get(level, LogCard.LOG_COLORS['info'])
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self.log_view.toPlainText():
            cursor.insertText('\n')
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(msg)
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def sync_reset(self) -> None:
        """重置进度显示"""
        self.progress_bar.setValue(0)
        self.percent_label.setText('0%')
        self.detail_label.setText('共 0 张 | 成功 0 张 | 失败 0 张')
        self.log_view.clear()

    # ------------------------------------------------------------
    def _on_url_changed(self, text: str) -> None:
        """迷你窗口输入框变化 -> 同步到主页面（避免循环）"""
        if self.page.download_card.get_url() != text:
            self.page.download_card.set_url(text)

    def clear_log(self) -> None:
        self.log_view.clear()


# ============================================================
# 下载画廊页面
# ============================================================
class DownloadPage(QWidget):
    """下载画廊标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: DownloadWorker = None
        self._last_downloader: EhentaiDownloader = None
        self._last_config: DownloadConfig = None
        self._mini_window: MiniDownloadWindow = None
        # 下载队列：排队任务、当前任务、失败待处理标记
        self._queue: list = []
        self._current: dict = None
        self._running_url: str = ''
        self._task_waiting: bool = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        root.addWidget(TitleLabel('下载画廊', self))

        self.download_card = DownloadCard(self)
        self.download_card.download_requested.connect(self._start_download)
        self.download_card.stop_requested.connect(self._stop_download)
        self.download_card.retry_requested.connect(self._retry_failed)
        self.download_card.paste_requested.connect(self._paste_url)
        self.download_card.copy_requested.connect(self._copy_url)
        self.download_card.mini_window_requested.connect(self._toggle_mini_window)
        # 主页面 URL 变化 -> 同步迷你窗口
        self.download_card.url_edit.textChanged.connect(self._sync_mini_url)
        root.addWidget(self.download_card)

        # 下载分类（保存到数据库 DOWNLOAD_LABELS；下载完成后写入 DOWNLOADS.LABEL）
        cat_row = QHBoxLayout()
        cat_row.setSpacing(8)
        cat_lbl = CaptionLabel('下载分类', self)
        cat_lbl.setStyleSheet('font-size: 13px;')
        cat_row.addWidget(cat_lbl)
        self.category_combo = ComboBox(self)
        self.category_combo.setMinimumWidth(200)
        self.category_combo.setToolTip('把该画廊下载到指定分类（数据库 DOWNLOAD_LABELS）')
        self.category_combo.addItem('未分类', '')
        try:
            from pages.album.ehentai_sync import read_download_labels
            for it in read_download_labels():
                self.category_combo.addItem(it['label'], it['label'])
        except Exception:
            pass
        cat_row.addWidget(self.category_combo, 0)
        cat_row.addStretch(1)
        root.addLayout(cat_row)

        # 下载队列卡片：排队自动下载；当前任务失败/停止时停留，可「跳过」进入下一个
        self.queue_card = CardWidget(self)
        _ql = QVBoxLayout(self.queue_card)
        _ql.setContentsMargins(16, 10, 16, 10)
        _ql.setSpacing(6)
        _qtop = QHBoxLayout()
        _qtop.setSpacing(8)
        _qtitle = StrongBodyLabel('下载队列', self.queue_card)
        _qtop.addWidget(_qtitle)
        self.queue_state_lbl = CaptionLabel('空闲', self.queue_card)
        self.queue_state_lbl.setStyleSheet('color: #57606a;')
        _qtop.addWidget(self.queue_state_lbl)
        _qtop.addStretch(1)
        self.skip_btn = PushButton('跳过失败 → 下一个', self.queue_card)
        self.skip_btn.setToolTip('当前任务下载失败/已停止时可用：不处理失败的图片，直接下载队列里的下一个')
        self.skip_btn.setEnabled(False)
        self.skip_btn.clicked.connect(self._skip_current)
        _qtop.addWidget(self.skip_btn)
        self.clear_btn = PushButton('清空队列', self.queue_card)
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self._clear_queue)
        _qtop.addWidget(self.clear_btn)
        _ql.addLayout(_qtop)
        self.queue_text = CaptionLabel('', self.queue_card)
        self.queue_text.setWordWrap(True)
        self.queue_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.queue_text.hide()
        _ql.addWidget(self.queue_text)
        root.addWidget(self.queue_card)

        self.progress_card = ProgressCard(self)
        root.addWidget(self.progress_card)

        self.log_card = LogCard(self)
        self.log_card.clear_btn.clicked.connect(self.log_card.clear_log)
        root.addWidget(self.log_card, 1)

        # 按钮初始状态
        self._set_running_state(False)
        # 创建迷你窗口（隐藏）
        self._mini_window = MiniDownloadWindow(self)
        self._mini_window.hide()

    # ------------------------------------------------------------------
    # 内部逻辑
    # ------------------------------------------------------------------
    def set_url(self, url: str) -> None:
        if url:
            self.download_card.set_url(url)

    def set_category(self, label: str) -> None:
        """设置下载分类（供详情页「下载」调用）；不存在时加入下拉。"""
        try:
            label = label or ''
            idx = -1
            for i in range(self.category_combo.count()):
                if (self.category_combo.itemData(i) or '') == label:
                    idx = i
                    break
            if idx < 0:
                idx = self.category_combo.findText(label)
            if idx < 0 and label:
                # 分类不在下拉里 -> 补一项（分类最终在下载完成时写入 DOWNLOAD_LABELS）
                self.category_combo.addItem(label, label)
                idx = self.category_combo.count() - 1
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            self._pending_label = label
        except Exception:
            self._pending_label = label

    def current_category(self) -> str:
        """当前选中的下载分类（''=未分类）。

        优先返回显式 set_category() 设置的值（详情页下载流程）；
        否则用下拉当前文本（qfluentwidgets 的 itemData 不可靠，用文本判定）。
        """
        try:
            p = getattr(self, '_pending_label', None)
            if p:
                return p
            t = self.category_combo.currentText()
            return '' if t == '未分类' else (t or '')
        except Exception:
            return getattr(self, '_pending_label', '') or ''

    def _paste_url(self) -> None:
        from PyQt5.QtWidgets import QApplication
        url = QApplication.clipboard().text().strip()
        if url:
            self.download_card.set_url(url)

    def _copy_url(self) -> None:
        from PyQt5.QtWidgets import QApplication
        url = self.download_card.get_url()
        if url:
            QApplication.clipboard().setText(url)
            InfoBar.success(
                '已复制',
                'URL 已复制到剪贴板。',
                parent=self,
                position=InfoBarPosition.TOP,
                duration=1500,
            )

    def _toggle_mini_window(self) -> None:
        """切换迷你窗口显示"""
        if self._mini_window is None:
            return
        if self._mini_window.isVisible():
            self._mini_window.hide()
        else:
            # 同步当前 URL 后显示
            self._mini_window.sync_url(self.download_card.get_url())
            self._mini_window.show()
            self._mini_window.raise_()

    def _sync_mini_url(self, text: str) -> None:
        """主页面输入框变化 -> 同步迷你窗口"""
        if self._mini_window is not None:
            self._mini_window.sync_url(text)

    def _set_running_state(self, running: bool) -> None:
        self.download_card.stop_btn.setEnabled(running)
        if running:
            self.download_card.retry_btn.setEnabled(False)
            self.download_card.start_loading()
        else:
            self.download_card.stop_loading()
            self.download_card.url_edit.setEnabled(True)
        # 同步迷你窗口按钮状态
        if self._mini_window is not None:
            self._mini_window.sync_running_state(running)
            if not running:
                # 完成后恢复迷你窗口失败重试按钮
                has_failed = (self._last_downloader is not None
                              and len(self._last_downloader._failed_tasks) > 0)
                self._mini_window.retry_btn.setEnabled(has_failed)

    def _make_config(self, url: str) -> DownloadConfig:
        """从当前配置桥接构造 DownloadConfig。"""
        gui_fmt = ehentai_cfg.get(ehentai_cfg.KEY_IMAGE_FORMAT, '原始格式')
        image_format = IMAGE_FORMAT_MAP.get(gui_fmt, '')
        return DownloadConfig(
            url=url,
            cookies=ehentai_cfg.get(ehentai_cfg.KEY_COOKIES, ''),
            headers=ehentai_cfg.get(ehentai_cfg.KEY_HEADERS, ''),
            proxy=ehentai_cfg.get(ehentai_cfg.KEY_PROXY, ''),
            ignore_env_proxy=bool(ehentai_cfg.get(ehentai_cfg.KEY_IGNORE_ENV_PROXY, True)),
            output_dir=ehentai_cfg.get(ehentai_cfg.KEY_OUTPUT_DIR, './'),
            concurrency=int(ehentai_cfg.get(ehentai_cfg.KEY_CONCURRENCY, 4)),
            timeout=int(ehentai_cfg.get(ehentai_cfg.KEY_TIMEOUT, 30)),
            image_format=image_format,
            per_file_retries=int(ehentai_cfg.get(ehentai_cfg.KEY_PER_FILE_RETRIES, 3)),
        )

    # ---------- 下载队列 ----------
    def _url_short(self, url: str) -> str:
        u = (url or '').rstrip('/')
        if not u:
            return ''
        if '/g/' in u:
            parts = u.split('/')
            return 'g/' + parts[-2] + '/' + parts[-1]
        return u[-40:] if len(u) > 40 else u

    def _start_download(self) -> None:
        """点击「下载」：把当前输入 URL 加入下载队列（空闲时立即开始）。"""
        url = (self.download_card.get_url() or '').strip()
        if not url:
            InfoBar.warning('提示', '请输入画廊 URL。', parent=self,
                            position=InfoBarPosition.TOP, duration=3000)
            return
        self._enqueue(url, label=self.current_category())

    def _enqueue(self, url: str, label: str = '') -> None:
        """加入下载队列。重复（正在下载/排队中）URL 会提示并忽略。"""
        url = (url or '').strip()
        if not url:
            return
        base = url.rstrip('/')
        # 正在下载或已在队列中的 URL 不重复加入
        if self._running_url and self._running_url.rstrip('/') == base:
            InfoBar.info('已在下载', '该画廊正在下载中。', parent=self,
                         position=InfoBarPosition.TOP, duration=2500)
            return
        for t in self._queue:
            if (t.get('url') or '').rstrip('/') == base:
                InfoBar.info('已在队列', '该画廊已在下载队列中。', parent=self,
                             position=InfoBarPosition.TOP, duration=2500)
                return
        task = {'url': url, 'label': label or ''}
        self._queue.append(task)
        self._update_queue_ui()
        self._pump_queue()

    def _pump_queue(self) -> None:
        """空闲且有排队任务且无失败待处理时，自动开始下一个任务。"""
        if self.worker and self.worker.isRunning():
            return
        if self._task_waiting:
            return                      # 当前任务失败/已停止，等用户处理或点「跳过」
        if not self._queue:
            return
        task = self._queue.pop(0)
        self._launch_task(task)

    def _launch_task(self, task: dict) -> None:
        """启动单个下载任务。"""
        url = task.get('url') or ''
        label = task.get('label') or ''
        if not url:
            self._pump_queue()
            return
        self._current = task
        self._running_url = url
        self._task_waiting = False
        self._download_category = label

        # 记录最近 URL + 同步显示
        ehentai_cfg.set(ehentai_cfg.KEY_LAST_URL, url)
        self.download_card.set_url(url)
        if label:
            try:
                idx = -1
                for i in range(self.category_combo.count()):
                    if (self.category_combo.itemData(i) or '') == label:
                        idx = i
                        break
                if idx < 0:
                    idx = self.category_combo.findText(label)
                if idx < 0:
                    self.category_combo.addItem(label, label)
                    idx = self.category_combo.count() - 1
                if idx >= 0:
                    self.category_combo.setCurrentIndex(idx)
            except Exception:
                pass
        self._pending_label = label

        config = self._make_config(url)
        self.progress_card.reset()
        self.log_card.clear_log()
        self.log_card.append_log(f'开始下载：{url}', 'info')
        if self._mini_window is not None:
            self._mini_window.sync_reset()
            self._mini_window.sync_url(url)
            self._mini_window.sync_log(f'开始下载：{url}', 'info')
            self._mini_window.sync_running_state(True)

        self._set_running_state(True)
        self.download_card.download_btn.setEnabled(False)
        self.download_card.url_edit.setEnabled(False)
        self._last_config = config
        self.worker = DownloadWorker(config, self)
        self._last_downloader = self.worker.downloader
        self.worker.log_emitted.connect(self._on_worker_log)
        self.worker.progress_updated.connect(self._on_worker_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()
        self._update_queue_ui()

    def _current_has_failed(self) -> bool:
        try:
            return (self._last_downloader is not None
                    and len(self._last_downloader._failed_tasks) > 0)
        except Exception:
            return False

    def _update_queue_ui(self) -> None:
        """刷新队列卡片：状态行 / 等待列表 / 跳过与清空按钮可用性。"""
        try:
            busy = bool(self.worker and self.worker.isRunning())
            waiting = len(self._queue)
            short = self._url_short(self._running_url)
            if busy:
                state = '正在下载：' + (short or '…')
            elif self._task_waiting:
                state = '当前任务有失败/已停止，待处理：' + (short or '…')
            elif short:
                state = '空闲（刚完成：' + short + '）'
            else:
                state = '空闲'
            self.queue_state_lbl.setText(state)
            if waiting:
                lines = []
                for i, t in enumerate(self._queue, 1):
                    lines.append('%d. %s' % (i, self._url_short(t.get('url') or '')))
                self.queue_text.setText('等待中 %d 个：\n' % waiting + '\n'.join(lines))
                self.queue_text.show()
            else:
                self.queue_text.hide()
            # 跳过按钮：当前任务失败/停止 且 没有任务在跑时可用
            can_skip = (not busy and self._task_waiting
                        and (self._current_has_failed()
                             or (self._last_downloader is not None
                                 and self._last_downloader.is_stopping())))
            self.skip_btn.setEnabled(bool(can_skip))
            self.clear_btn.setEnabled(bool(waiting))
        except Exception:
            pass

    def _skip_current(self) -> None:
        """跳过当前失败/停止的任务，直接进入下一个排队任务。"""
        if self.worker and self.worker.isRunning():
            return
        short = self._url_short(self._running_url)
        self.log_card.append_log(
            f'已跳过当前任务（{short or "未知"}）的失败部分，进入下一个任务…', 'warning')
        if self._mini_window is not None:
            self._mini_window.sync_log(
                f'已跳过当前任务的失败部分，进入下一个任务…', 'warning')
        # 丢弃失败的记录，恢复界面
        try:
            if self._last_downloader is not None:
                self._last_downloader._failed_tasks.clear()
        except Exception:
            pass
        self._task_waiting = False
        self._running_url = ''
        self._current = None
        self._pending_label = ''
        self.download_card.retry_btn.setEnabled(False)
        if self._mini_window is not None:
            self._mini_window.retry_btn.setEnabled(False)
        self.progress_card.reset()
        self._update_queue_ui()
        if self._queue:
            QTimer.singleShot(250, self._pump_queue)
        else:
            InfoBar.info('队列已空', '没有更多排队任务。', parent=self,
                         position=InfoBarPosition.TOP, duration=2500)

    def _clear_queue(self) -> None:
        """清空等待中的任务（不影响正在下载的任务）。"""
        if self._queue:
            self._queue.clear()
            self.log_card.append_log('已清空下载队列。', 'warning')
            self._update_queue_ui()

    def _retry_failed(self) -> None:
        """重新下载上次失败的图片"""
        if self.worker and self.worker.isRunning():
            return
        if self._last_downloader is None or not self._last_downloader._failed_tasks:
            InfoBar.warning(
                '提示',
                '没有可重试的失败任务。',
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return

        failed_count = len(self._last_downloader._failed_tasks)
        self.progress_card.reset()
        self.log_card.clear_log()
        self.log_card.append_log(f'开始重试 {failed_count} 张失败图片...', 'info')
        # 同步迷你窗口
        if self._mini_window is not None:
            self._mini_window.sync_reset()
            self._mini_window.sync_log(f'开始重试 {failed_count} 张失败图片...', 'info')
            self._mini_window.sync_running_state(True)

        self._set_running_state(True)
        self.download_card.download_btn.setEnabled(False)
        self.download_card.url_edit.setEnabled(False)
        self._task_waiting = False      # 重试中：暂停标记清除，等结果再判定
        self._update_queue_ui()
        self.worker = DownloadWorker(
            self._last_config,
            self,
            retry_failed=True,
            downloader=self._last_downloader,
        )
        self.worker.log_emitted.connect(self._on_worker_log)
        self.worker.progress_updated.connect(self._on_worker_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _on_worker_log(self, msg: str, level: str = 'info') -> None:
        """工日志 -> 主页面 + 迷你窗口"""
        self.log_card.append_log(msg, level)
        if self._mini_window is not None:
            self._mini_window.sync_log(msg, level)

    def _on_worker_progress(self, progress: DownloadProgress) -> None:
        """进度更新 -> 主页面 + 迷你窗口"""
        self.progress_card.update_progress(progress)
        if self._mini_window is not None:
            self._mini_window.sync_progress(progress)

    def _stop_download(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            # 立即禁用停止按钮，防止重复触发
            self.download_card.stop_btn.setEnabled(False)
            if self._mini_window is not None:
                self._mini_window.stop_btn.setEnabled(False)
            self.log_card.append_log('正在停止，请稍候...', 'warning')
            if self._mini_window is not None:
                self._mini_window.sync_log('正在停止，请稍候...', 'warning')

    def _on_finished(self, progress: DownloadProgress) -> None:
        stopped = (self._last_downloader is not None
                   and self._last_downloader.is_stopping())
        self._set_running_state(False)
        self.download_card.url_edit.setEnabled(True)
        # 同步迷你窗口完成状态
        if self._mini_window is not None:
            self._mini_window.sync_progress(progress)
            self._mini_window.sync_running_state(False)
            has_failed = (self._last_downloader is not None
                          and len(self._last_downloader._failed_tasks) > 0)
            self._mini_window.retry_btn.setEnabled(has_failed)
            if stopped:
                self._mini_window.sync_log(
                    f'任务已停止：成功 {progress.done} 张，剩余 {progress.failed} 张。',
                    'warning',
                )
            else:
                self._mini_window.sync_log(
                    f'下载完成：成功 {progress.done} 张，失败 {progress.failed} 张。',
                    'success' if progress.failed == 0 else 'error',
                )

        # 有失败时启用「重试失败」按钮
        has_failed = (self._last_downloader is not None
                      and len(self._last_downloader._failed_tasks) > 0)
        if has_failed:
            self.download_card.retry_btn.setEnabled(True)
            if self._mini_window is not None:
                self._mini_window.retry_btn.setEnabled(True)

        if stopped:
            InfoBar.warning(
                '下载已停止',
                f'已下载 {progress.done} 张，剩余 {progress.failed} 张。\n'
                f'可用「重试失败」按钮继续下载剩余的图片。',
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
        elif progress.failed > 0:
            InfoBar.error(
                '下载完成（有失败）',
                f'成功 {progress.done} 张，失败 {progress.failed} 张。\n'
                f'可用「重试失败」按钮重新下载失败的图片。',
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
            # 有失败图片：弹出「手动补齐」弹窗（显示失败链接，粘贴本地文件地址按序回填）
            try:
                QTimer.singleShot(400, self._show_failed_fix_dialog)
            except Exception:
                pass
        else:
            # 完全成功：把画廊信息同步到数据库（DOWNLOADS + 分类），并写目录元数据
            try:
                self._sync_download()
            except Exception as e:
                self.log_card.append_log(f'同步数据库失败：{e}', 'warning')
            InfoBar.success(
                '下载完成',
                f'成功下载 {progress.done} 张图片。',
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )

        # ---- 下载队列推进 ----
        # 成功且无失败 -> 自动下载队列里的下一个；失败/停止 -> 停留等用户处理或「跳过」
        if stopped or progress.failed > 0:
            self._task_waiting = True
        else:
            self._task_waiting = False
            self._running_url = ''
            self._current = None
            self._pending_label = ''
        self._update_queue_ui()
        if not stopped and progress.failed == 0 and self._queue:
            QTimer.singleShot(300, self._pump_queue)

    # ------------------------------------------------------------------
    def _sync_download(self) -> None:
        """下载成功后把 画廊信息+分类 写入 DOWNLOADS，并在下载目录写 .ehentai_info.json。"""
        try:
            from pages.album.ehentai_sync import (
                extract_gid_token, sync_download_to_db, write_comic_metadata,
                add_label)
            url = self._last_config.url if self._last_config else ''
            title = ''
            if self._last_downloader is not None:
                title = getattr(self._last_downloader, '_title', '') or ''
            gid, token = extract_gid_token(url)
            label = getattr(self, '_download_category', '') or ''
            if label and label != '未分类':
                add_label(label)
            ok = sync_download_to_db(url, title, label=label, state=3, category=0x400)
            # 写目录元数据（供本地画册/详情对账）
            output_dir = ''
            try:
                if self._last_downloader is not None:
                    output_dir = getattr(self._last_downloader, '_output_path', '') or ''
            except Exception:
                pass
            if gid and output_dir:
                write_comic_metadata(output_dir, gid, token, title)
            if ok:
                self.log_card.append_log(
                    f'已同步数据库：gid={gid} 分类={label or "未分类"}', 'success')
            else:
                self.log_card.append_log('未能同步数据库（链接可能不含 gid/token）。', 'warning')
        except Exception as e:
            self.log_card.append_log(f'同步数据库异常：{e}', 'warning')

    def _show_failed_fix_dialog(self) -> None:
        """下载有失败图片时弹出弹窗：显示失败链接 + 让用户粘贴本地文件地址，按序回填到漫画目录。"""
        import os
        import shutil
        from PyQt5.QtWidgets import (QDialog, QTextEdit, QVBoxLayout, QHBoxLayout,
                                     QApplication as _QA)
        from qfluentwidgets import PushButton as _PB, PrimaryPushButton as _PPB, CaptionLabel as _CL

        dl = self._last_downloader
        if dl is None:
            return
        failed = list(getattr(dl, '_failed_tasks', []) or [])
        if not failed:
            InfoBar.info('提示', '没有失败的图片。', parent=self,
                         position=InfoBarPosition.TOP, duration=2000)
            return
        save_dir = getattr(dl, '_output_path', '') or ''
        rows = []
        for (page, num, url) in failed:
            if isinstance(page, tuple):
                # 兼容 task=(page_num, number, detail_url, known_img) 形式
                item = page
                if len(item) >= 3:
                    page, num, url = item[0], item[1], item[2]
            img_url = getattr(dl, '_task_image_urls', {}).get((page, num), url or '') or ''
            try:
                tname = dl._target_name(img_url, page, num)
            except Exception:
                tname = f'{page}-{num}.jpg'
            rows.append((img_url, tname))

        dlg = QDialog(self)
        dlg.setWindowTitle('手动补齐失败图片')
        dlg.resize(640, 560)
        # 固定浅色样式，避免在深色主题下黑屏看不清
        dlg.setStyleSheet(
            "QDialog { background: #ffffff; }"
            " QTextEdit { color: #1f2328; background: #ffffff;"
            " border: 1px solid rgba(128,128,128,0.35); border-radius: 6px; font-size: 13px; }"
            " QLabel { color: #1f2328; font-size: 13px; }"
        )
        lay = QVBoxLayout(dlg)
        lay.addWidget(_CL(
            '以下为下载失败的图片链接（每行一个）。请自行另存到本地后，把文件地址粘贴到下面编辑框'
            '（每行一个，顺序与上方一致），点「应用」即放入对应漫画文件夹。', dlg))
        lay.addWidget(_CL('① 失败图片链接：', dlg))
        url_box = QTextEdit(dlg)
        url_box.setReadOnly(True)
        url_box.setPlainText('\n'.join(r[0] for r in rows))
        lay.addWidget(url_box, 1)
        lay.addWidget(_CL('② 本地文件地址（每行一个，与上方顺序一致）：', dlg))
        path_box = QTextEdit(dlg)
        path_box.setPlaceholderText('E:\\...\\图片.jpg （每行一个，顺序对应上方链接）')
        lay.addWidget(path_box, 1)

        btn_row = QHBoxLayout()
        copy_btn = _PB('复制全部链接', dlg)
        copy_btn.clicked.connect(
            lambda: _QA.clipboard().setText('\n'.join(r[0] for r in rows)))
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        apply_btn = _PPB('应用', dlg)
        cancel_btn = _PB('取消', dlg)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

        result = {'ok': False, 'msg': ''}

        def _apply():
            paths = [l.strip() for l in path_box.toPlainText().splitlines() if l.strip()]
            ok = 0
            miss = 0
            for i, (_u, tname) in enumerate(rows):
                if i >= len(paths):
                    miss += 1
                    continue
                src = paths[i]
                if not os.path.isfile(src):
                    miss += 1
                    continue
                try:
                    if save_dir:
                        os.makedirs(save_dir, exist_ok=True)
                        shutil.copy2(src, os.path.join(save_dir, tname))
                    ok += 1
                except Exception:
                    miss += 1
            result['ok'] = True
            result['msg'] = f'已补齐 {ok} 张，{miss} 张缺少/未提供'
            dlg.accept()

        apply_btn.clicked.connect(_apply)
        cancel_btn.clicked.connect(dlg.reject)
        dlg.exec_()
        if result.get('ok'):
            InfoBar.success('补齐完成', result['msg'], parent=self,
                            position=InfoBarPosition.TOP, duration=3000)

    def closeEvent(self, event) -> None:
        """关闭时停止下载线程，防止 QThread: Destroyed while thread is still running"""
        try:
            if self.worker and self.worker.isRunning():
                self.worker.stop()
                self.worker.wait(1500)
        except Exception:
            pass
        super().closeEvent(event)


# ============================================================
# E-Hentai 子模块页面（分段导航）
# ============================================================
class EhentaiPage(QWidget):
    """E-Hentai 子模块：分段导航栏切换 主页/搜索/下载画廊/收藏/阅读/历史/排行榜/设置。

    拆散原『画廊中心』独立容器：主页/搜索/历史/排行榜 作为标头式分段页直接并进本模块；
    详情/阅读为模块内【就地】叠加页（不弹窗）。下载统一走下载画廊的 OGC 下载器并同步数据库。
    """

    TAB_HOME = 'ehHomeTab'
    TAB_SEARCH = 'ehSearchTab'
    TAB_DOWNLOAD = 'ehentaiDownloadTab'
    TAB_FAVORITES = 'ehentaiFavoritesTab'
    TAB_READER = 'ehentaiReaderTab'
    TAB_HISTORY = 'ehHistoryTab'
    TAB_TOP = 'ehTopTab'
    TAB_SETTINGS = 'ehentaiSettingsTab'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('ehentaiPage')

        # 根页栈：索引0=主内容(标头+分段页)，索引1+=就地叠加的详情/阅读页
        self._root_stack = QStackedWidget(self)
        self._overlays = []

        # 首次访问 ehviewer 功能页时再接线子系统（图片加载器/下载管理器/共享库路由）
        self._eh_wired = False

        self._build_main_ui()
        self._wire_bus()

        # 退出时回收就地叠加页线程（尽力而为）
        try:
            from PyQt5.QtWidgets import QApplication
            _app = QApplication.instance()
            if _app is not None:
                _app.aboutToQuit.connect(self._pop_all_overlays)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 主界面（标头 + 分段导航 + 各功能页）
    # ------------------------------------------------------------------
    def _build_main_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._root_stack.addWidget(self._make_main_widget())
        outer.addWidget(self._root_stack, 1)

    def _make_main_widget(self):
        main = QWidget(self)
        self.vBoxLayout = QVBoxLayout(main)
        self.vBoxLayout.setContentsMargins(0, 36, 0, 0)
        self.vBoxLayout.setSpacing(12)

        # ---- 标题行 ----
        header = QHBoxLayout()
        header.setContentsMargins(24, 0, 24, 0)
        header.setSpacing(12)
        self.title_label = TitleLabel('E-Hentai', main)
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.desc_label = CaptionLabel('画廊下载 · 浏览 · 收藏 · 设置', main)
        self.desc_label.setStyleSheet('color: #57606a;')
        header.addWidget(self.desc_label)
        self.vBoxLayout.addLayout(header)

        # ---- 分段导航栏 ----
        pivot_row = QHBoxLayout()
        pivot_row.setContentsMargins(24, 0, 24, 0)
        self.pivot = SegmentedWidget(main)
        pivot_row.addWidget(self.pivot)
        self.vBoxLayout.addLayout(pivot_row)

        # ---- 各功能页 ----
        self.stackedWidget = QStackedWidget(main)

        self.home_page = HomePage(self.stackedWidget)
        self.home_page.setObjectName(self.TAB_HOME)
        self.search_page = SearchPage(self.stackedWidget)
        self.search_page.setObjectName(self.TAB_SEARCH)
        self.download_page = DownloadPage(self.stackedWidget)
        self.download_page.setObjectName(self.TAB_DOWNLOAD)
        self.favorites_page = FavoritesPage(self.stackedWidget)
        self.favorites_page.setObjectName(self.TAB_FAVORITES)
        from pages.album.ehentai_reader import EhentaiReaderPage
        self.reader_page = EhentaiReaderPage(self.stackedWidget)
        self.reader_page.setObjectName(self.TAB_READER)
        self.history_page = HistoryPage(self.stackedWidget)
        self.history_page.setObjectName(self.TAB_HISTORY)
        self.top_page = TopListPage(self.stackedWidget)
        self.top_page.setObjectName(self.TAB_TOP)
        self.settings_page = SettingPage(self.stackedWidget)
        self.settings_page.setObjectName(self.TAB_SETTINGS)

        for w in (self.home_page, self.search_page, self.download_page,
                  self.favorites_page, self.reader_page, self.history_page,
                  self.top_page, self.settings_page):
            self.stackedWidget.addWidget(w)

        self.pivot.addItem(routeKey=self.TAB_HOME, text='主页')
        self.pivot.addItem(routeKey=self.TAB_SEARCH, text='搜索')
        self.pivot.addItem(routeKey=self.TAB_DOWNLOAD, text='下载画廊')
        self.pivot.addItem(routeKey=self.TAB_FAVORITES, text='我的收藏')
        self.pivot.addItem(routeKey=self.TAB_READER, text='阅读')
        self.pivot.addItem(routeKey=self.TAB_HISTORY, text='历史')
        self.pivot.addItem(routeKey=self.TAB_TOP, text='排行榜')
        self.pivot.addItem(routeKey=self.TAB_SETTINGS, text='设置')
        self.stackedWidget.setCurrentWidget(self.download_page)
        self.pivot.setCurrentItem(self.TAB_DOWNLOAD)
        self.pivot.currentItemChanged.connect(self._on_current_item_changed)

        self.vBoxLayout.addWidget(self.stackedWidget, 1)

        # ---- 页面间联动 ----
        # 收藏卡片「下载」-> 切换到下载画廊并开始下载
        self.favorites_page.download_requested.connect(self._start_download_from_favorite)
        # 收藏卡片「阅读」-> 切换到阅读页在线阅读
        self.favorites_page.read_requested.connect(self._read_from_favorite)
        # 设置保存 -> 刷新收藏数据（代理 / 网络等可能变化）
        self.settings_page.settings_saved.connect(self._on_settings_saved)
        # 手动切换数据库 -> 刷新收藏页数据 + ehviewer 共享库
        self.settings_page.db_file_changed.connect(self._on_db_file_changed)

        return main

    # ------------------------------------------------------------------
    # ehviewer 子系统接线（首次访问功能页时）
    # ------------------------------------------------------------------
    def _ensure_eh_wired(self):
        if self._eh_wired:
            return
        self._eh_wired = True
        from pages.album.ehentai_embed import wire_ehviewer_subsystem, make_show_notify
        wire_ehviewer_subsystem()
        from ehviewer.appctx import ctx
        ctx.main_window = self
        self._eh_show_notify = make_show_notify(self)

    def show_notify(self, level, content):
        from qfluentwidgets import InfoBar as _Inf, InfoBarPosition as _Pos
        try:
            kw = dict(position=_Pos.TOP_RIGHT, duration=3000, parent=self)
            if level == 'success':
                _Inf.success('', content, **kw)
            elif level == 'warning':
                _Inf.warning('', content, **kw)
            elif level == 'error':
                _Inf.error('', content, **kw)
            else:
                _Inf.info('', content, **kw)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # bus 接线
    # ------------------------------------------------------------------
    def _wire_bus(self):
        from ehviewer.ui.bus import bus
        if getattr(self, '_bus_wired', False):
            return
        self._bus_wired = True
        self._bus = bus
        bus.openDetail.connect(self._open_detail)
        bus.openReader.connect(self._open_reader)
        bus.doSearch.connect(self._do_search)
        bus.notify.connect(self.show_notify)
        bus.downloadsChanged.connect(self._on_downloads_changed)

    def _on_downloads_changed(self):
        try:
            self.download_page._on_downloads_changed()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 就地 详情 / 阅读 叠加
    # ------------------------------------------------------------------
    def _push_overlay(self, widget):
        widget.back_requested.connect(self._pop_overlay)
        self._root_stack.addWidget(widget)
        self._overlays.append(widget)
        self._root_stack.setCurrentWidget(widget)

    def _pop_overlay(self):
        if not self._overlays:
            self._root_stack.setCurrentIndex(0)
            return
        top = self._overlays.pop()
        self._root_stack.removeWidget(top)
        try:
            if hasattr(top, 'shutdown'):
                top.shutdown()
        except Exception:
            pass
        try:
            top.deleteLater()
        except Exception:
            pass
        if self._overlays:
            self._root_stack.setCurrentWidget(self._overlays[-1])
        else:
            self._root_stack.setCurrentWidget(self._root_stack.widget(0))

    def _pop_all_overlays(self):
        while self._overlays:
            self._pop_overlay()

    def _open_detail(self, info):
        self._ensure_eh_wired()
        from pages.album.ehentai_embed import DetailPage
        p = DetailPage(info, self)
        p.download_requested.connect(self._on_detail_download_requested)
        self._push_overlay(p)

    def _open_reader(self, info, start_page=0):
        self._ensure_eh_wired()
        from pages.album.ehentai_embed import ReaderPage
        self._push_overlay(ReaderPage(info, start_page, self))

    def _do_search(self, keyword, mode):
        self._ensure_eh_wired()
        self.pivot.setCurrentItem(self.TAB_SEARCH)
        try:
            self.search_page.mode_combo.setCurrentIndex(
                self.search_page.mode_combo.findData(mode))
            self.search_page.search_edit.setText(keyword or "")
            self.search_page._do_search()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 详情页下载请求 -> 转交下载画廊
    # ------------------------------------------------------------------
    def _on_detail_download_requested(self, info, label=""):
        url = _info_to_url(info)
        if not url:
            InfoBar.warning('提示', '无法从画廊信息构造下载链接。',
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        self.pivot.setCurrentItem(self.TAB_DOWNLOAD)
        self.stackedWidget.setCurrentWidget(self.download_page)
        self.download_page.set_url(url)
        self.download_page.set_category(label)      # 供下载画廊设置下载分类
        self.download_page._start_download()

    # ------------------------------------------------------------------
    def _on_current_item_changed(self, routeKey: str) -> None:
        # 先接线 ehviewer 子系统（否则卡片/封面在 ctx.image_loader 未就绪时加载不到）
        if routeKey in (self.TAB_HOME, self.TAB_SEARCH, self.TAB_HISTORY, self.TAB_TOP):
            self._ensure_eh_wired()
        widget = self.findChild(QWidget, routeKey)
        if widget is not None:
            self.stackedWidget.setCurrentWidget(widget)
        if routeKey == self.TAB_READER:
            self.reader_page.reload_offline()
        # 首次激活的收藏页：延迟加载数据（读全量收藏库），避免启动阶段卡顿
        try:
            if routeKey == self.TAB_FAVORITES:
                self.favorites_page.ensure_loaded()
        except Exception:
            pass

    def _read_from_favorite(self, url: str) -> None:
        """收藏卡片点击「阅读」：切换到阅读页并在线阅读"""
        self.pivot.setCurrentItem(self.TAB_READER)
        self.stackedWidget.setCurrentWidget(self.reader_page)
        self.reader_page.read_online(url)

    def _on_settings_saved(self) -> None:
        """设置保存后刷新收藏页（重新应用代理并重读数据库）"""
        self.favorites_page.thumbnail_loader._apply_proxy()
        self.favorites_page.reload()

    def _on_db_file_changed(self, db_path: str) -> None:
        """手动切换数据库 -> 收藏页 + ehviewer 共享库同步"""
        self.favorites_page.set_db_path(db_path)
        from pages.album.ehentai_bridge import route_to_shared_db
        route_to_shared_db(db_path)
        self._ensure_eh_wired()
        for p in (self.home_page, self.history_page, self.top_page):
            try:
                p.showEvent  # no-op here; pages reload on show
            except Exception:
                pass

    def _start_download_from_favorite(self, url: str) -> None:
        """收藏卡片点击「下载」：填充 URL、切换到下载画廊并开始下载"""
        self.pivot.setCurrentItem(self.TAB_DOWNLOAD)
        self.stackedWidget.setCurrentWidget(self.download_page)
        self.download_page.set_url(url)
        self.download_page._start_download()

    def set_url(self, url: str) -> None:
        """外部填充 URL（用于恢复上次输入）"""
        self.download_page.set_url(url)

    def apply_last_url(self) -> None:
        """启动时恢复上次使用的 URL"""
        last = ehentai_cfg.get(ehentai_cfg.KEY_LAST_URL, '')
        if last:
            self.download_page.set_url(last)

    def closeEvent(self, event) -> None:
        """关闭时回收收藏封面加载线程与下载线程，避免 QThread: Destroyed while running"""
        self._pop_all_overlays()
        try:
            self.favorites_page.thumbnail_loader.shutdown()
        except Exception:
            pass
        try:
            if self.download_page.worker and self.download_page.worker.isRunning():
                self.download_page.worker.stop()
                self.download_page.worker.wait(1500)
        except Exception:
            pass
        super().closeEvent(event)


def _info_to_url(info) -> str:
    """由 GalleryInfo 构造画廊 URL：https://e-hentai.org/g/{gid}/{token}/"""
    try:
        gid = getattr(info, 'gid', 0)
        token = getattr(info, 'token', '') or ''
        if gid and token:
            return 'https://e-hentai.org/g/%s/%s/' % (gid, token)
    except Exception:
        pass
    return ''
