# coding:utf-8
"""
视频迷你下载窗口（复用层）
=========================
对标 E-Hentai 模块的 MiniDownloadWindow：一个置顶的小窗口，输入链接
（支持多条，回车/英文逗号/空格分隔），点「开始下载」后直接解析并下载，
不在页面生成卡片。

按钮与 E-Hentai 迷你窗口一致（粘贴 / 停止 / 重试失败 / 开始下载），
并额外增加「追加粘贴」按钮。

实现说明：
- 解析复用 services.platform_parsers.get_parser(platform).parse(url)；
- 下载复用 services.download_manager.download_media(...)；
- 解析与下载都在后台线程完成（避免卡界面），通过信号转发进度/日志；
- 多链接按队列依次处理，全部完成后再做汇总（成功/失败）。
"""
import re

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QTextCursor, QTextCharFormat, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
)

from qfluentwidgets import (
    LineEdit, ToolButton, PushButton, PrimaryPushButton,
    ProgressBar, BodyLabel, CaptionLabel, InfoBar, InfoBarPosition,
    FluentIcon,
)

from services.download_manager import download_media, infer_file_type
from services.platform_parsers import get_parser, MediaItem

from ui.widgets.theme import theme_color


# ═══════════════════════════════════════════════════════════
#  后台线程：解析 → 下载 队列
# ═══════════════════════════════════════════════════════════
class _MiniParseDownloadWorker(QThread):
    """一条链接的「解析 + 下载 全部媒体」后台任务。"""

    log = pyqtSignal(str, str)        # (message, level)
    item_progress = pyqtSignal(int, int)   # (current, total)
    item_done = pyqtSignal(bool, str)      # (success, filename)
    finished = pyqtSignal(int, int, list)  # (success, failed, failed_urls)

    def __init__(self, platform: str, url: str, sessdata: str = '', parent=None):
        super().__init__(parent)
        self.platform = platform
        self.url = url
        self.sessdata = sessdata
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        success, failed = 0, 0
        failed_urls = []
        try:
            # 1. 解析
            self.log.emit(f"解析：{self.url}", "info")
            parser = get_parser(self.platform)
            if parser is None:
                self.log.emit(f"不支持的平台：{self.platform}", "error")
                return
            if self.platform == 'bilibili':
                items = parser.parse(self.url, sessdata=self.sessdata)
            else:
                items = parser.parse(self.url)
            if not items:
                self.log.emit("未找到可下载的媒体，请检查链接", "error")
                self.finished.emit(0, 1, [self.url])
                return
        except Exception as e:
            self.log.emit(f"解析失败：{e}", "error")
            self.finished.emit(0, 1, [self.url])
            return

        try:
            from core.database import record_usage
            record_usage('video', 'parse', self.platform)
        except Exception:
            pass

        # 2. 逐个下载
        total = len(items)
        for i, item in enumerate(items, 1):
            if self._stop:
                break
            title = self._safe_filename(item)
            file_type = infer_file_type(item.url, item.media_type, item.title)
            try:
                ok, msg, _ = download_media(
                    item.url, title, self.platform, file_type,
                    progress_callback=lambda c, t: self.item_progress.emit(c, t),
                    is_hls=getattr(item, 'is_hls', False),
                    referer=getattr(item, 'referer', ''),
                )
            except Exception as e:
                ok, msg = False, str(e)
            if ok:
                success += 1
                self.log.emit(msg, "success")
            else:
                failed += 1
                failed_urls.append(self.url)
                self.log.emit(msg, "error")
            self.item_done.emit(ok, title)
            self.item_progress.emit(total, total)
            if self._stop:
                break

        self.log.emit(f"完成：成功 {success} 个，失败 {failed} 个", "info" if failed == 0 else "error")
        self.finished.emit(success, failed, failed_urls)

    @staticmethod
    def _safe_filename(item: MediaItem) -> str:
        """仿 MediaCard 生成下载文件名（含扩展名补全）。"""
        title = item.title or 'untitled'
        file_type = infer_file_type(item.url, item.media_type, item.title)
        name = title
        if file_type == 'image' and not name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            name += '.jpg'
        elif file_type == 'video' and not name.lower().endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.ts')):
            name += '.mp4'
        elif file_type == 'audio' and not name.lower().endswith(('.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg')):
            name += '.mp3'
        return name


# ═══════════════════════════════════════════════════════════
#  视频迷你下载窗口
# ═══════════════════════════════════════════════════════════
class VideoMiniDownloadWindow(QWidget):
    """视频平台迷你下载窗口（解析 + 下载，不生成卡片）。"""

    def __init__(self, platform: str, display_name: str, parent=None):
        # parent 仅用作逻辑归属 / 引用持有，不真正作为父窗口：
        # 若把主窗口设为父窗口，主窗口最小化时迷你窗口会一起隐藏，
        # 且点击迷你窗口会把主窗口重新带上来（Qt 父子窗口联动）。
        # 因此这里强制为独立顶层窗口（parent=None）。
        super().__init__(None)
        self.platform = platform
        self.display_name = display_name
        self.setWindowTitle(f'{display_name} 迷你下载')
        self.setFixedSize(460, 240)
        # 独立置顶浮窗：无任务栏按钮 + 总在最前；不随主窗口最小化
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        # 关闭迷你窗口不应退出整个应用（由页面持有引用并复用）
        self.setAttribute(Qt.WA_QuitOnClose, False)

        self._worker = None
        self._current = 0
        self._total = 0
        self._success = 0
        self._failed = 0
        self._running = False
        self._failed_urls = []
        self._pending_urls = []
        self._url_history = []
        self._sessdata = ''   # bilibili 专用（由页面在打开/开始时设置）

        self._build_ui()

    # ---------------- UI ----------------
    def set_owner(self, owner):
        """绑定逻辑归属窗口（主窗口/页面），主窗口销毁时自动关闭迷你窗口。

        注意：此 owner 不是 Qt 父窗口，仅用于生命周期管理；
        父窗口被销毁时迷你窗口随之一并关闭，避免残留置顶浮窗。
        """
        try:
            if owner is not None:
                owner.destroyed.connect(self._on_owner_destroyed)
        except Exception:
            pass

    def _on_owner_destroyed(self, *args):
        try:
            self.close()
        except Exception:
            pass

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 输入框（多行，支持多条链接）
        self.url_edit = QTextEdit(self)
        self.url_edit.setAcceptRichText(False)
        self.url_edit.setPlaceholderText(
            f"输入 {self.display_name} 分享链接，支持多条\n"
            "多条链接可用回车 / 英文逗号 / 空格分隔"
        )
        self.url_edit.setFixedHeight(56)
        root.addWidget(self.url_edit)

        # 按钮行：粘贴 / 追加粘贴 / 停止 / 重试失败 / 开始下载
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.paste_btn = ToolButton(FluentIcon.PASTE, self)
        self.paste_btn.setFixedSize(36, 32)
        self.paste_btn.setToolTip('清空输入框并粘贴剪贴板内容')
        self.paste_btn.clicked.connect(self._paste)
        btn_row.addWidget(self.paste_btn)

        self.append_btn = ToolButton(FluentIcon.ADD, self)
        self.append_btn.setFixedSize(36, 32)
        self.append_btn.setToolTip('在输入框末尾追加粘贴剪贴板内容')
        self.append_btn.clicked.connect(self._append_paste)
        btn_row.addWidget(self.append_btn)

        self.stop_btn = PushButton(FluentIcon.CANCEL, '停止', self)
        self.stop_btn.setFixedSize(76, 32)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_download)
        btn_row.addWidget(self.stop_btn)

        self.retry_btn = PushButton(FluentIcon.UPDATE, '重试失败', self)
        self.retry_btn.setFixedSize(108, 32)
        self.retry_btn.setEnabled(False)
        self.retry_btn.setToolTip('重新下载上次解析失败/下载失败的链接')
        self.retry_btn.clicked.connect(self._retry_failed)
        btn_row.addWidget(self.retry_btn)

        self.download_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, '开始下载', self)
        self.download_btn.setFixedSize(108, 32)
        self.download_btn.clicked.connect(self._start_download)
        btn_row.addWidget(self.download_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # 进度条 + 百分比
        prog_row = QHBoxLayout()
        prog_row.setSpacing(10)
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setStyleSheet("""
            QProgressBar { background: #eceff2; border: none; border-radius: 4px; }
            QProgressBar::chunk { background: #2ea44f; border-radius: 4px; }
        """)
        prog_row.addWidget(self.progress_bar, 1)
        self.percent_label = BodyLabel('0%', self)
        self.percent_label.setFixedWidth(44)
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percent_label.setStyleSheet('color: #57606a; font-size: 12px;')
        prog_row.addWidget(self.percent_label)
        root.addLayout(prog_row)

        self.detail_label = CaptionLabel('共 0 个 | 成功 0 个 | 失败 0 个', self)
        self.detail_label.setStyleSheet('color: #57606a; font-size: 12px;')
        root.addWidget(self.detail_label)

        # 日志区
        self.log_view = QTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(46)
        self.log_view.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.log_view.setPlaceholderText('日志将显示在这里...')
        self.log_view.setStyleSheet("""
            QTextEdit {
                background: #f7f8fa; border: 1px solid #e2e4e8; border-radius: 8px;
                padding: 4px 8px; font-family: Consolas, "Courier New", monospace; font-size: 11px;
            }
            QTextEdit:focus { border: 1px solid #2ea44f; }
        """)
        root.addWidget(self.log_view)

    # ---------------- 剪贴板 ----------------
    def _paste(self):
        from PyQt5.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_edit.setPlainText(text)

    def _append_paste(self):
        from PyQt5.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if not text:
            return
        cur = self.url_edit.toPlainText().strip()
        if cur:
            self.url_edit.setPlainText(cur + "\n" + text)
        else:
            self.url_edit.setPlainText(text)

    # ---------------- 下载流程 ----------------
    def _extract_urls(self, text: str) -> list:
        found = re.findall(r'https?://[^\s，,\n]+', text or '')
        urls = [u.strip('\u2018\u2019"\u201c') for u in found if u.strip('\u2018\u2019"\u201c')]
        seen, out = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _start_download(self):
        if self._running:
            return
        urls = self._extract_urls(self.url_edit.toPlainText())
        if not urls:
            InfoBar.warning('提示', '请输入下载链接', orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000, parent=self)
            return
        self._running = True
        self._failed_urls = []
        self._pending_urls = list(urls)
        self._url_history = list(urls)
        self._success = 0
        self._failed = 0
        self._stop_btn_state(True)
        self._reset_log()
        self._process_next()

    def _process_next(self):
        """处理队列中的下一条链接（串行）。"""
        if not self._pending_urls:
            self._on_all_done()
            return
        url = self._pending_urls.pop(0)
        self.log(f"开始处理：{url}", "info")
        sessdata = (self._sessdata or self._read_sessdata())
        self._worker = _MiniParseDownloadWorker(self.platform, url, sessdata, self)
        self._worker.log.connect(self.log)
        self._worker.item_progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_url_finished)
        self._worker.start()

    def _on_url_finished(self, success: int, failed: int, failed_urls: list):
        self._success += success
        self._failed += failed
        self._failed_urls.extend(failed_urls)
        # 队列下一条
        self._process_next()

    def _on_progress(self, current: int, total: int):
        if total > 0:
            pct = int(current / total * 100)
            self.progress_bar.setValue(pct)
            self.percent_label.setText(f"{pct}%")
        self.detail_label.setText(f"共 {self._success + self._failed} 个 | 成功 {self._success} 个 | 失败 {self._failed} 个")

    def _on_all_done(self):
        self._running = False
        self._stop_btn_state(False)
        self.retry_btn.setEnabled(bool(self._failed_urls))
        self.log(f"全部完成：成功 {self._success} 个，失败 {self._failed} 个", "success" if self._failed == 0 else "error")
        if self._failed:
            InfoBar.error('下载完成（有失败）', f"成功 {self._success} 个，失败 {self._failed} 个",
                          orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.BOTTOM_RIGHT,
                          duration=5000, parent=self)
        else:
            InfoBar.success('下载完成', f"成功下载 {self._success} 个媒体。",
                            orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP,
                            duration=3000, parent=self)

    def _stop_download(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self.stop_btn.setEnabled(False)
            self.log("正在停止，请稍候...", "warning")

    def _retry_failed(self):
        if self._running:
            return
        if not self._failed_urls:
            InfoBar.warning('提示', '没有可重试的失败链接。', orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000, parent=self)
            return
        self._running = True
        self._pending_urls = list(self._failed_urls)
        self._failed_urls = []
        self._success = 0
        self._failed = 0
        self._stop_btn_state(True)
        self._reset_log()
        self.log(f"开始重试 {len(self._pending_urls)} 条失败链接...", "info")
        self._process_next()

    # ---------------- 状态 & 工具 ----------------
    def _stop_btn_state(self, running: bool):
        self.stop_btn.setEnabled(running)
        self.download_btn.setEnabled(not running)
        self.url_edit.setEnabled(not running)
        self.paste_btn.setEnabled(not running)
        self.append_btn.setEnabled(not running)
        self.download_btn.setText('下载中' if running else '开始下载')
        if running:
            self.retry_btn.setEnabled(False)

    def set_sessdata(self, value: str):
        """设置 bilibili SESSDATA（由页面打开迷你窗口时传入）。"""
        self._sessdata = value or ''

    def _read_sessdata(self) -> str:
        """bilibili 平台页面若配有 SESSDATA 输入框，读取之（否则空）。"""
        try:
            page = self.parent()
            while page is not None:
                if hasattr(page, 'sessdataEdit'):
                    return page.sessdataEdit.text().strip()
                if hasattr(page, 'sessdata_edit'):
                    return page.sessdata_edit.text().strip()
                page = page.parent()
        except Exception:
            pass
        return ''

    def _reset_log(self):
        self.progress_bar.setValue(0)
        self.percent_label.setText('0%')
        self.detail_label.setText('共 0 个 | 成功 0 个 | 失败 0 个')
        self.log_view.clear()

    def log(self, msg: str, level: str = 'info'):
        color = {
            'info': '#1f6feb', 'success': '#2ea44f', 'error': '#cf222e', 'warning': '#bf8700',
        }.get(level, '#57606a')
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

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(1500)
        super().closeEvent(event)
