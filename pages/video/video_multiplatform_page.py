# coding:utf-8
"""
多平台视频解析页面
===================
视频主页显示六大平台入口，每个平台是子模块页面，
可通过导航栏子项或主页图标按钮跳转。
"""
import os
import re
import sys
import time

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRectF
from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
    QScrollArea, QFrame, QGridLayout, QSizePolicy, QPushButton,
    QDialog, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QApplication
)
from qfluentwidgets import (
    CardWidget, FluentIcon as FIF, InfoBar, InfoBarPosition,
    SegmentedWidget, LineEdit, TextEdit, PrimaryPushButton, PushButton,
    BodyLabel, SubtitleLabel, ProgressBar, StateToolTip,
    ScrollArea, CaptionLabel, StrongBodyLabel, IconWidget
)

from services.download_manager import (
    download_media, ensure_download_dirs, get_platform_dir, infer_file_type,
    get_download_root,
)
from services.platform_parsers import get_parser, MediaItem

from core.resource_paths import (
    VIDEO_DOUYIN_ICON as _ICON_DOUYIN,
    VIDEO_TWITTER_ICON as _ICON_X,
    VIDEO_BILIBILI_ICON as _ICON_BILI,
    VIDEO_XVIDEO_ICON as _ICON_Xvideo,
    VIDEO_PIXIV_ICON as _ICON_Pixiv,
    VIDEO_YOUTUBE_ICON as _ICON_Youtube,
    VIDEO_LOGO as _ICON_LOGO,
)
from ui.widgets.theme import theme_color, on_theme_changed, ensure_theme_connected


# ═══════════════════════════════════════════════════════════
#  线程类（必须在模块级别定义，避免 PyQt 元对象崩溃）
# ═══════════════════════════════════════════════════════════
class ParseThread(QThread):
    """解析线程"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, platform: str, url: str, sessdata: str = '', parent=None,
                 use_backup_parser: bool = False):
        super().__init__(parent)
        self.platform = platform
        self.url = url
        self.sessdata = sessdata
        self.use_backup_parser = use_backup_parser  # True时使用备用解析器（如 gallery-dl）

    def run(self):
        try:
            if self.use_backup_parser and self.platform == 'twitter':
                # 备用解析：调用 gallery-dl 专用推特下载器
                from services.platform_parsers import TwitterGalleryDLParser
                parser = TwitterGalleryDLParser()
                items = parser.parse(self.url)
            else:
                parser = get_parser(self.platform)
                if not parser:
                    self.error.emit(f"不支持的平台: {self.platform}")
                    return
                if self.platform == 'bilibili':
                    items = parser.parse(self.url, sessdata=self.sessdata)
                else:
                    items = parser.parse(self.url)
            if not items:
                self.error.emit("未找到可下载的媒体，请检查链接")
                return
            self.finished.emit(items)
        except Exception as e:
            self.error.emit(f"解析失败: {str(e)}")


class PreviewLoadThread(QThread):
    """独立预览图加载线程"""
    loaded = pyqtSignal()
    failed = pyqtSignal()

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self._pix = None

    def run(self):
        # 低优先级，避免阻塞主界面绘制、提升流畅度（需在线程启动后设置）
        try:
            self.setPriority(QThread.LowPriority)
        except Exception:
            pass
        try:
            import requests
            resp = requests.get(self.url, timeout=8)
            pix = QPixmap()
            pix.loadFromData(resp.content)
            if not pix.isNull():
                self._pix = pix
                self.loaded.emit()
            else:
                self.failed.emit()
        except Exception:
            self.failed.emit()


class MediaDownloadThread(QThread):
    """独立媒体下载线程
    通过信号转发进度，避免子线程直接操作 GUI 控件导致闪退
    """
    done = pyqtSignal(bool, str)
    progress = pyqtSignal(int, int)   # (current, total)

    def __init__(self, url, filename, platform, file_type, parent=None,
                 is_hls=False, referer=''):
        super().__init__(parent)
        self.url = url
        self.filename = filename
        self.platform = platform
        self.file_type = file_type
        self.is_hls = is_hls
        self.referer = referer

    def run(self):
        try:
            def _safe_progress(current, total):
                # 仅转发信号，不操作 GUI
                self.progress.emit(current, total)

            success, msg, path = download_media(
                self.url, self.filename, self.platform, self.file_type,
                progress_callback=_safe_progress,
                is_hls=self.is_hls,
                referer=self.referer
            )
            self.done.emit(success, msg)
        except Exception as e:
            self.done.emit(False, f"下载异常: {str(e)}")


class ZoomGraphicsView(QGraphicsView):
    """支持滚轮缩放的图形视图"""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._zoom = 1.0
        self._min_zoom = 0.2
        self._max_zoom = 5.0

        self.setRenderHints(QPainter.SmoothPixmapTransform)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(Qt.black)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem(pixmap)
        scene.addItem(self._item)
        self.setScene(scene)

        # 初始适配窗口
        self.fitInView(self._item, Qt.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def wheelEvent(self, event):
        """滚轮缩放（保持鼠标位置为中心）"""
        delta = event.angleDelta().y()
        factor = 1.25 if delta > 0 else 0.8
        new_zoom = self._zoom * factor
        if new_zoom < self._min_zoom:
            factor = self._min_zoom / self._zoom
        elif new_zoom > self._max_zoom:
            factor = self._max_zoom / self._zoom
        self.scale(factor, factor)
        self._zoom *= factor

    def mouseReleaseEvent(self, event):
        """点击图片区域不关闭；点击图片外区域由 Dialog 负责"""
        super().mouseReleaseEvent(event)


class PreviewZoomDialog(QDialog):
    """预览图放大窗口

    - 点击放大图外部关闭
    - 鼠标在放大图上滚动滚轮缩放（0.2x - 5x）
    """

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("预览")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.view = ZoomGraphicsView(pixmap, self)
        self._layout.addWidget(self.view)

        # 全屏显示（点击外部关闭）
        self.showFullScreen()
        self._screen_rect = self.geometry()

    def keyPressEvent(self, event):
        """按 ESC 关闭"""
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """点击放大图外部关闭"""
        pos = event.pos()
        if not self._is_inside_image(pos):
            self.close()
            return
        super().mousePressEvent(event)

    def _is_inside_image(self, pos) -> bool:
        """判断点击位置是否在放大图区域内"""
        try:
            # 将视图坐标映射到场景坐标
            scene_pos = self.view.mapToScene(pos)
            if self.view.scene().itemAt(scene_pos, self.view.transform()) is not None:
                return True
        except Exception:
            pass
        return False


# ═══════════════════════════════════════════════════════════
#  媒体卡片（预览 + 下载）
# ═══════════════════════════════════════════════════════════
class MediaCard(CardWidget):
    """媒体结果卡片"""

    def __init__(self, item: MediaItem, platform: str, parent=None):
        super().__init__(parent=parent)
        self.item = item
        self.platform = platform
        self._download_active = False
        self._page_disabled = False
        self._queued = False
        self._dl_thread = None
        self._original_pixmap = None
        # 用智能推断修正显示类型（解决解析器误报图片为视频）
        self.display_type = infer_file_type(item.url, item.media_type, item.title)
        item.media_type = self.display_type
        self.setFixedSize(220, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 预览图（异步加载，点击放大）
        self.previewLabel = QLabel("加载预览...", self)
        self.previewLabel.setAlignment(Qt.AlignCenter)
        self.previewLabel.setFixedSize(196, 130)
        self.previewLabel.setCursor(Qt.PointingHandCursor)
        self.previewLabel.setToolTip("点击预览图放大查看")
        self.previewLabel.setStyleSheet(theme_color(
            "background-color: rgba(0,0,0,0.08); border-radius: 6px;",
            "background-color: rgba(255,255,255,0.08); border-radius: 6px;"))
        self.previewLabel.mousePressEvent = self._on_preview_click
        layout.addWidget(self.previewLabel, 0, Qt.AlignCenter)

        # 标题
        title = item.title
        if len(title) > 30:
            title = title[:30] + '...'
        self.titleLabel = BodyLabel(title, self)
        self.titleLabel.setStyleSheet("font-size: 12px; color: " + theme_color('#555555', '#CCCCCC') + ";")
        self.titleLabel.setWordWrap(True)
        layout.addWidget(self.titleLabel)

        # 类型标识 + 清晰度
        type_text = {'image': '🖼 图片', 'video': '🎬 视频', 'audio': '🎵 音频'}.get(item.media_type, item.media_type)
        if item.quality:
            type_text += f'  [{item.quality}]'
        typeLabel = CaptionLabel(type_text, self)
        typeLabel.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + ";")
        layout.addWidget(typeLabel)

        layout.addStretch()

        # 下载按钮
        self.downloadBtn = PrimaryPushButton(FIF.DOWNLOAD, "下载", self)
        self.downloadBtn.clicked.connect(self._download)
        layout.addWidget(self.downloadBtn)

        # 进度条
        self.progressBar = ProgressBar(self)
        self.progressBar.setVisible(False)
        layout.addWidget(self.progressBar)

        # 异步加载预览图
        self._load_preview()

    def _load_preview(self):
        """异步加载预览图"""
        if not self.item.preview_url:
            self.previewLabel.setText("无预览")
            return

        self._load_thread = PreviewLoadThread(self.item.preview_url, self)
        self._load_thread.loaded.connect(self._on_preview_loaded)
        self._load_thread.failed.connect(lambda: self.previewLabel.setText("预览加载失败"))
        self._load_thread.start()

    def _on_preview_loaded(self):
        try:
            pix = self._load_thread._pix
            self._original_pixmap = pix
            scaled = pix.scaled(196, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.previewLabel.setPixmap(scaled)
        except Exception:
            self.previewLabel.setText("预览加载失败")

    def _on_preview_click(self, event):
        """点击预览图：打开放大查看窗口"""
        if self._original_pixmap is None:
            return
        dialog = PreviewZoomDialog(self._original_pixmap, self.window())
        dialog.exec_()

    def _download(self):
        """点击下载按钮：将当前卡片加入下载队列（按顺序依次下载）"""
        if self._download_active:
            return
        # 请求所属页面将本卡片加入队列
        page = self._find_page()
        if page is not None:
            page._enqueue_download(self)

    def _find_page(self):
        """向上查找所属 PlatformPage"""
        page = self.parent()
        while page is not None and not hasattr(page, '_enqueue_download'):
            page = page.parent()
        return page

    def mark_queued(self):
        """标记为排队中（加入下载队列后调用）"""
        self._download_active = True
        self._queued = True
        self.downloadBtn.setEnabled(False)
        self.downloadBtn.setText("排队中")
        self.downloadBtn.setIcon(FIF.SYNC)
        self.downloadBtn.setStyleSheet("")

    def mark_downloading(self):
        """标记为下载中（队列轮到本卡片时调用）"""
        self._queued = False
        self.downloadBtn.setEnabled(False)
        self.downloadBtn.setText("下载中")
        self.downloadBtn.setIcon(FIF.DOWNLOAD)
        self.downloadBtn.setStyleSheet("")
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)
        # 通知页面进入下载状态（禁用解析等防误触）
        self._notify_page_downloading(True)

    def start_download(self):
        """由页面队列调度器调用：启动本卡片的下载线程"""
        self.mark_downloading()

        # 根据 URL/文件名/Content-Type 智能推断最终实际类型（解决解析器误报）
        file_type = infer_file_type(self.item.url, self.item.media_type, self.item.title)
        filename = f"{self.item.title}"
        if file_type == 'image' and not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            filename += '.jpg'
        elif file_type == 'video' and not filename.lower().endswith(('.mp4', '.mkv', '.webm')):
            filename += '.mp4'
        elif file_type == 'audio' and not filename.lower().endswith(('.mp3', '.m4a', '.aac')):
            filename += '.mp3'

        # 使用独立下载线程，进度通过信号转发（避免子线程操作 GUI 闪退）
        self._dl_thread = MediaDownloadThread(
            self.item.url, filename, self.platform, file_type, self,
            is_hls=getattr(self.item, 'is_hls', False),
            referer=getattr(self.item, 'referer', '')
        )
        self._dl_thread.done.connect(self._on_download_finished)
        self._dl_thread.progress.connect(self._on_download_progress)
        self._dl_thread.start()

    def _notify_page_downloading(self, active: bool = True):
        """通知所属页面下载状态变化（供页面级防误触）"""
        page = self._find_page()
        if page is not None and hasattr(page, '_on_child_download_changed'):
            page._on_child_download_changed(active)

    def on_page_downloading_changed(self, downloading: bool):
        """页面进入/退出下载状态时，由页面统一调用

        下载中不禁止其他卡片入队（允许继续点击加入下载队列），
        因此这里仅保持自身按钮状态，不强制禁用其他卡片。
        """
        if downloading:
            # 自己未在下载/排队时才记录页面级禁用
            if not self._download_active:
                self._page_disabled = True
        else:
            # 页面退出下载状态，恢复按钮（仅当本卡片未在下载中）
            if not self._download_active:
                self._page_disabled = False
                self.downloadBtn.setEnabled(True)

    def _on_download_progress(self, current: int, total: int):
        """下载进度更新（主线程）"""
        try:
            if total > 0:
                self.progressBar.setMaximum(total)
                self.progressBar.setValue(current)
        except Exception:
            pass

    def _on_download_finished(self, success: bool, message: str):
        self._download_active = False
        # 通知页面退出下载状态（若没有其他卡片在下载，则恢复解析按钮）
        self._notify_page_downloading(False)
        # 通知页面队列调度下一个下载任务
        page = self._find_page()
        if page is not None and hasattr(page, '_on_download_completed'):
            page._on_download_completed(self)
        self.progressBar.setVisible(False)
        # 若页面已被页面级禁用（其它卡片下载中），保持禁用
        if getattr(self, '_page_disabled', False):
            self.downloadBtn.setEnabled(False)
        else:
            self.downloadBtn.setEnabled(True)
        if success:
            # 标记为"已下载"（提示作用，仍可再次点击下载）
            self.downloadBtn.setText("已下载")
            self.downloadBtn.setIcon(FIF.ACCEPT)
            self.downloadBtn.setStyleSheet(
                "color: #67C23A; border: 1px solid #67C23A; border-radius: 6px;"
            )
            InfoBar.success(
                title="下载完成", content=message,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self.window()
            )
        else:
            self.downloadBtn.setText("下载")
            InfoBar.error(
                title="下载失败", content=message,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self.window()
            )


# ═══════════════════════════════════════════════════════════
#  单平台子页面
# ═══════════════════════════════════════════════════════════
class PlatformPage(QScrollArea):
    """单个平台的解析下载子页面（可独立导航）"""

    def __init__(self, platform: str, display_name: str, parent=None):
        super().__init__(parent=parent)
        self.platform = platform
        self.display_name = display_name
        self._items = []
        self._cards = []
        # 防误触状态：解析中 / 下载中
        self._parsing = False
        self._downloading = False
        self._parse_thread = None
        # 解析重试机制
        self._parse_url = ''
        self._parse_sessdata = ''
        self._parse_retry_count = 0
        self._parse_retry_max = 3
        # 多链接解析队列（支持回车/英文逗号分隔，依次解析）
        self._parse_queue = []
        self._queue_parsing = False
        self._active_parsers = []
        self._parse_total = 0
        self._parse_done = 0
        self._parse_failed = 0
        self._parse_retry_map = {}
        self._parse_fail_msgs = []
        # 已启用备用解析（gallery-dl）的链接集合：原解析重试耗尽后启用
        self._parse_backup_done = set()
        self._MAX_CONCURRENT = 2  # 同时最多并发解析条数，其余入队依次解析
        # 下载队列（依次串行下载）
        self._download_queue = []
        self._queue_active = False

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.view = QWidget(self)
        self.layout = QVBoxLayout(self.view)
        self.layout.setSpacing(12)
        # 视口边距固定标题栏空间（不会随滚动移动）
        self.setViewportMargins(0, 64, 0, 0)
        self.layout.setContentsMargins(24, 0, 24, 24)
        self.setWidget(self.view)

        # 输入区
        inputCard = CardWidget(self.view)
        inputLayout = QVBoxLayout(inputCard)
        inputLayout.setSpacing(10)
        inputLayout.setContentsMargins(16, 16, 16, 16)

        titleRow = QHBoxLayout()
        titleLabel = StrongBodyLabel(f"🔗 {display_name} 链接解析", inputCard)
        titleLabel.setStyleSheet("font-size: 16px; font-weight: bold;")
        titleRow.addWidget(titleLabel)
        titleRow.addStretch()
        inputLayout.addLayout(titleRow)

        urlRow = QHBoxLayout()
        urlRow.setSpacing(10)
        self.urlEdit = TextEdit(inputCard)
        self.urlEdit.setPlaceholderText(
            f"请输入{display_name}分享链接，支持多条链接\n"
            "多个链接可用回车或英文逗号分隔，点击「解析」将依次解析"
        )
        self.urlEdit.setAcceptRichText(False)  # 仅纯文本，避免粘贴黑条
        self.urlEdit.setFixedHeight(100)
        urlRow.addWidget(self.urlEdit, 1)

        # 右侧按钮列：第一行 粘贴+追加粘贴，第二行 解析
        btnCol = QVBoxLayout()
        btnCol.setSpacing(8)
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.pasteBtn = PushButton(FIF.PASTE, "粘贴", inputCard)
        self.pasteBtn.setFixedWidth(84)
        self.pasteBtn.setFixedHeight(30)
        self.pasteBtn.setToolTip("清空输入框并粘贴剪贴板内容")
        self.pasteBtn.clicked.connect(self._paste_from_clipboard)
        row1.addWidget(self.pasteBtn)

        self.appendBtn = PushButton(FIF.ADD, "追加", inputCard)
        self.appendBtn.setFixedWidth(84)
        self.appendBtn.setFixedHeight(30)
        self.appendBtn.setToolTip("若输入框已有内容，则在末尾回车后追加粘贴剪贴板内容")
        self.appendBtn.clicked.connect(self._append_paste_from_clipboard)
        row1.addWidget(self.appendBtn)
        btnCol.addLayout(row1)

        self.parseBtn = PrimaryPushButton(FIF.SYNC, "解析", inputCard)
        self.parseBtn.setFixedHeight(34)
        self.parseBtn.clicked.connect(self._parse)
        btnCol.addWidget(self.parseBtn)
        urlRow.addLayout(btnCol)
        inputLayout.addLayout(urlRow)

        # B站额外 SESSDATA 输入（用 QWidget 容器以便控制显示）
        self.sessdataWidget = QWidget(inputCard)
        self.sessdataRow = QHBoxLayout(self.sessdataWidget)
        self.sessdataRow.setContentsMargins(0, 0, 0, 0)
        self.sessdataEdit = LineEdit(self.sessdataWidget)
        self.sessdataEdit.setPlaceholderText("输入哔哩哔哩 SESSDATA（可选，获取高清画质）")
        self.sessdataEdit.setClearButtonEnabled(True)
        self.sessdataRow.addWidget(self.sessdataEdit, 1)
        self.sessdataWidget.setVisible(platform == 'bilibili')
        inputLayout.addWidget(self.sessdataWidget)

        # 下载目录提示（动态读取配置，设置修改后自动同步）
        self.dirLabel = CaptionLabel(self._dir_hint(), inputCard)
        self.dirLabel.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        self.dirLabel.setWordWrap(True)
        inputLayout.addWidget(self.dirLabel)

        self.layout.addWidget(inputCard)

        # 结果区
        self.resultsScroll = QScrollArea(self.view)
        self.resultsScroll.setWidgetResizable(True)
        self.resultsScroll.setFrameShape(QFrame.NoFrame)
        self.resultsScroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.resultsView = QWidget()
        self.resultsGrid = QGridLayout(self.resultsView)
        self.resultsGrid.setSpacing(12)
        self.resultsGrid.setAlignment(Qt.AlignTop)
        self.resultsScroll.setWidget(self.resultsView)
        self.layout.addWidget(self.resultsScroll, 1)

        self.emptyLabel = QLabel("输入链接后点击「解析」开始", self.view)
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        self.emptyLabel.setStyleSheet("color: " + theme_color('#AAAAAA', '#666666') + "; font-size: 14px;")
        self.layout.addWidget(self.emptyLabel)

    def _dir_hint(self):
        root = get_download_root()
        return f"📁 下载目录: {os.path.join(root, self.platform + '-download')}（图片/视频/音频自动分类）"

    def closeEvent(self, event):
        """关闭时回收所有活动解析/下载线程"""
        threads = []
        for t in list(getattr(self, '_active_parsers', [])):
            threads.append(t)
        for card in list(self._cards):
            t = getattr(card, '_dl_thread', None)
            if t is not None:
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

    def _paste_from_clipboard(self):
        """清空输入框并填入刚刚复制的内容"""
        try:
            from PyQt5.QtWidgets import QApplication
            text = QApplication.clipboard().text().strip()
            if text:
                self.urlEdit.clear()
                self.urlEdit.setPlainText(text)
                InfoBar.success(
                    title="已粘贴", content="剪贴板内容已填入输入框",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=2000, parent=self
                )
            else:
                InfoBar.warning(
                    title="提示", content="剪贴板为空",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=2000, parent=self
                )
        except Exception as e:
            InfoBar.error(
                title="粘贴失败", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=3000, parent=self
            )

    def _append_paste_from_clipboard(self):
        """追加粘贴：若输入框已有内容，在末尾回车后粘贴；为空则直接粘贴"""
        try:
            from PyQt5.QtWidgets import QApplication
            text = QApplication.clipboard().text().strip()
            if not text:
                InfoBar.warning(
                    title="提示", content="剪贴板为空",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=2000, parent=self
                )
                return
            current = self.urlEdit.toPlainText()
            if current.strip():
                new_text = current.rstrip() + "\n" + text
            else:
                new_text = text
            self.urlEdit.setPlainText(new_text)
            InfoBar.success(
                title="已追加", content="剪贴板内容已追加到输入框",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=2000, parent=self
            )
        except Exception as e:
            InfoBar.error(
                title="追加粘贴失败", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=3000, parent=self
            )

    @staticmethod
    def _extract_urls(text: str) -> list:
        """从文本中提取多平台链接（支持回车 / 英文逗号 / 空格分隔）"""
        found = re.findall(r'https?://[^\s，,\n]+', text or '')
        urls = [u.strip("`\"'") for u in found if u.strip("`\"'")]
        # 去重并保持顺序
        seen = set()
        result = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                result.append(u)
        return result

    def _parse(self):
        """解析链接（防误触：下载中/解析中禁止重复触发）"""
        # 下载中禁止重新解析（防止销毁正在运行的下载线程）
        if self._downloading:
            InfoBar.warning(
                title="下载进行中", content="有文件正在下载，请等待下载完成后再解析",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
            return

        # 解析中禁止重复解析
        if self._parsing or self._queue_parsing:
            return

        text = self.urlEdit.toPlainText()
        urls = self._extract_urls(text)
        if not urls:
            InfoBar.warning(
                title="提示", content="请输入下载链接",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
            return

        self._parse_sessdata = self.sessdataEdit.text().strip() if self.platform == 'bilibili' else ''
        # 先清空旧结果（会同时清理旧的解析队列/活动线程）
        self._clear_results()
        # 初始化多链接解析队列
        self._parse_queue = list(urls)
        self._queue_parsing = True
        self._active_parsers = []
        self._parse_total = len(urls)
        self._parse_done = 0
        self._parse_failed = 0
        self._parse_retry_map = {}
        self._parse_fail_msgs = []
        self._parse_backup_done = set()

        # 锁定输入控件
        self.parseBtn.setEnabled(False)
        self.pasteBtn.setEnabled(False)
        self.appendBtn.setEnabled(False)
        self.urlEdit.setEnabled(False)
        if hasattr(self, 'sessdataEdit'):
            self.sessdataEdit.setEnabled(False)
        self.emptyLabel.setVisible(True)
        self.emptyLabel.setText(f"正在解析 {self._parse_done}/{self._parse_total} ...")
        self.resultsScroll.setVisible(True)

        # 启动解析（并发最多 _MAX_CONCURRENT 条，其余入队）
        for _ in range(min(self._MAX_CONCURRENT, len(self._parse_queue))):
            self._launch_next_parser()

    def _launch_next_parser(self):
        """从解析队列中取出下一条链接启动解析线程"""
        if not self._parse_queue:
            return
        url = self._parse_queue.pop(0)
        retry_count = self._parse_retry_map.get(url, 0)
        # 若该链接原解析重试已耗尽（已加入 _parse_backup_done），启用备用解析器
        use_backup_parser = url in getattr(self, '_parse_backup_done', set())

        thread = ParseThread(self.platform, url, self._parse_sessdata, self,
                             use_backup_parser=use_backup_parser)
        thread._parse_url = url
        thread._retry_count = retry_count
        # 将每条链接的结果绑定到对应回调
        thread.finished.connect(
            lambda items, u=url: self._on_parse_finished(items, u))
        thread.error.connect(
            lambda msg, u=url: self._on_parse_error(msg, u))
        self._active_parsers.append(thread)
        thread.start()

    def _on_parse_finished(self, items: list, url: str):
        """单条链接解析完成，追加卡片"""
        # 从活动列表移除该线程
        self._remove_parser_of(url)
        self._parse_retry_map.pop(url, None)
        self._parse_done += 1

        if items:
            # 暂停重绘以提升大量卡片创建时的流畅度
            self.resultsView.setUpdatesEnabled(False)
            base_row = self.resultsGrid.rowCount()
            for i, item in enumerate(items):
                card = MediaCard(item, self.platform, self.resultsView)
                row = base_row + i // 4
                col = i % 4
                self.resultsGrid.addWidget(card, row, col)
                self._cards.append(card)
            self.resultsView.setUpdatesEnabled(True)
            self.resultsView.update()
            self._items.extend(items)

        self._update_parse_progress(success=True)
        # 启动下一条（保持并发数）
        self._launch_next_parser()

    def _on_parse_error(self, message: str, url: str):
        """单条链接解析失败（自动重试最多 _parse_retry_max 次后跳过）"""
        # 从活动列表移除该线程
        self._remove_parser_of(url)

        retry_count = self._parse_retry_map.get(url, 0)
        if retry_count < self._parse_retry_max:
            # 加入重试队列末尾
            self._parse_retry_map[url] = retry_count + 1
            self._parse_queue.append(url)
            InfoBar.warning(
                title="解析失败，自动重试",
                content=f"第 {retry_count + 1}/{self._parse_retry_max} 次重试: {message}",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=2000, parent=self
            )
        else:
            # 重试耗尽：推特平台启用 gallery-dl 备用解析继续获取文件，
            # 备用解析也失败时才判定该条失败
            if self.platform == 'twitter' and url not in self._parse_backup_done:
                self._parse_backup_done.add(url)
                self._parse_queue.append(url)
                InfoBar.info(
                    title="原解析失败，启用备用解析",
                    content="已切换 gallery-dl 专用解析器，正在获取媒体文件...",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=3000, parent=self
                )
            else:
                # 备用解析仍失败（或非推特平台），判定该条失败
                self._parse_retry_map.pop(url, None)
                self._parse_done += 1
                self._parse_failed += 1
                self._parse_fail_msgs.append(f"{url}: {message}")
                self._update_parse_progress(success=False)

        # 无论重试还是失败，都启动下一条保持并发数（重试条目已重新入队，会被后续调度）
        self._launch_next_parser()

    def _update_parse_progress(self, success: bool):
        """所有活动解析结束后，统一更新解析进度"""
        # 若仍有活动线程，仅更新提示文字
        if self._active_parsers or self._parse_queue:
            self.emptyLabel.setText(
                f"正在解析 {self._parse_done}/{self._parse_total} ...")
            return

        # 全部解析完成
        self._queue_parsing = False
        self._parsing = False
        self.parseBtn.setEnabled(True)
        self.parseBtn.setText("解析")
        self.pasteBtn.setEnabled(not self._downloading)
        self.appendBtn.setEnabled(not self._downloading)
        self.urlEdit.setEnabled(not self._downloading)
        if hasattr(self, 'sessdataEdit'):
            self.sessdataEdit.setEnabled(not self._downloading)

        if self._cards:
            self.emptyLabel.setVisible(False)
            self.resultsScroll.setVisible(True)
        else:
            self.emptyLabel.setVisible(True)
            self.emptyLabel.setText("解析失败")
            self.resultsScroll.setVisible(False)

        # 汇总提示
        if self._parse_failed:
            msg = f"共 {self._parse_total} 条链接，成功 {self._parse_total - self._parse_failed} 条，失败 {self._parse_failed} 条"
            InfoBar.error(
                title="部分链接解析失败", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
            )
        else:
            total_media = len(self._items)
            InfoBar.success(
                title="解析完成", content=f"共 {self._parse_total} 条链接，找到 {total_media} 个媒体资源",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )

    def _remove_parser_of(self, url: str):
        """从活动线程列表中移除指定链接对应的解析线程并回收"""
        for t in list(self._active_parsers):
            if getattr(t, '_parse_url', None) == url:
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
        # 找不到：兼容通过对象身份查找
        for t in list(self._active_parsers):
            try:
                if not t.isRunning():
                    t.deleteLater()
                    self._active_parsers.remove(t)
            except (RuntimeError, Exception):
                try:
                    self._active_parsers.remove(t)
                except ValueError:
                    pass

    def _enqueue_download(self, card):
        """将卡片加入下载队列（按点击顺序依次下载）"""
        if card in self._download_queue or getattr(card, '_download_active', False):
            return
        # 标记排队中
        card.mark_queued()
        self._download_queue.append(card)
        # 若队列空闲，立即开始
        self._process_queue()

    def _process_queue(self):
        """处理下载队列：依次串行下载"""
        if self._queue_active:
            return
        if not self._download_queue:
            return
        # 取出队首并启动下载
        card = self._download_queue.pop(0)
        self._queue_active = True
        card.start_download()

    def _on_download_completed(self, card):
        """当前下载完成，调度下一个队列任务"""
        self._queue_active = False
        # 处理下一个
        self._process_queue()

    def _clear_results(self):
        """清空结果区域（安全回收正在运行的下载线程）"""
        # 清空下载队列
        self._download_queue = []
        self._queue_active = False
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
                t = getattr(card, '_dl_thread', None)
                if t is None:
                    continue
                if t.isRunning():
                    # 断开信号后等待线程结束，防止 QThread: Destroyed while thread is still running
                    try:
                        t.done.disconnect()
                        t.progress.disconnect()
                    except Exception:
                        pass
                    t.requestInterruption()
                    t.wait(3000)
                try:
                    t.deleteLater()
                except Exception:
                    pass
            except (RuntimeError, Exception):
                pass
            finally:
                try:
                    card._dl_thread = None
                    card._download_active = False
                except Exception:
                    pass

        while self.resultsGrid.count():
            item = self.resultsGrid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards = []
        self._items = []

    def _on_child_download_changed(self, downloading: bool):
        """子卡片下载状态变化

        下载中禁用解析/输入，但允许其他卡片继续点击入队
        """
        if downloading:
            self._downloading = True
            # 禁用解析、粘贴、追加粘贴、输入等控件
            self.parseBtn.setEnabled(False)
            self.pasteBtn.setEnabled(False)
            self.appendBtn.setEnabled(False)
            self.urlEdit.setEnabled(False)
            if hasattr(self, 'sessdataEdit'):
                self.sessdataEdit.setEnabled(False)
        else:
            # 检查是否还有卡片在下载或排队
            still_downloading = any(
                getattr(c, '_download_active', False) for c in self._cards)
            if not still_downloading:
                self._downloading = False
                # 恢复控件（若不在解析中：普通解析或队列解析）
                if not self._parsing and not self._queue_parsing:
                    self.parseBtn.setEnabled(True)
                    self.pasteBtn.setEnabled(True)
                    self.appendBtn.setEnabled(True)
                    self.urlEdit.setEnabled(True)
                    if hasattr(self, 'sessdataEdit'):
                        self.sessdataEdit.setEnabled(True)
                # 恢复所有卡片按钮
                for card in self._cards:
                    card.on_page_downloading_changed(False)


# ═══════════════════════════════════════════════════════════
#  视频主页面（六大平台入口卡片）
# ═══════════════════════════════════════════════════════════
class MultiPlatformVideoInterface(QScrollArea):
    """视频主页面：显示六个平台入口卡片，点击跳转到对应子模块"""

    # 平台配置: (key, 显示名, 图标路径)
    PLATFORMS = [
        ('douyin', '抖音', _ICON_DOUYIN),
        ('bilibili', '哔哩哔哩', _ICON_BILI),
        ('twitter', '推特(X)', _ICON_X),
        ('pixiv', 'Pixiv', _ICON_Pixiv),
        ('xvideo', 'Xvideo', _ICON_Xvideo),
        ('youtube', 'YouTube', _ICON_Youtube),
    ]

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("MultiPlatformVideoInterface")
        self._sub_interfaces = {}
        self._platform_cards = {}   # key -> 平台入口卡片

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.view = QWidget(self)
        self.layout = QVBoxLayout(self.view)
        self.layout.setSpacing(24)
        # 视口边距固定标题栏空间（不会随滚动移动）
        self.setViewportMargins(0, 64, 0, 0)
        self.layout.setContentsMargins(36, 0, 36, 36)
        self.setWidget(self.view)

        # 标题
        titleLabel = SubtitleLabel("多平台解析下载", self.view)
        titleLabel.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.layout.addWidget(titleLabel)

        descLabel = CaptionLabel("选择平台解析并下载视频 / 图片 / 音频，下载文件自动分类保存", self.view)
        descLabel.setStyleSheet("color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 13px;")
        self.layout.addWidget(descLabel)

        self.layout.addSpacing(16)

        # 平台入口卡片网格
        self.cardsGrid = QGridLayout()
        self.cardsGrid.setSpacing(16)
        self.cardsGrid.setAlignment(Qt.AlignTop)
        self.layout.addLayout(self.cardsGrid)

        # 创建平台入口卡片
        for i, (key, name, icon_path) in enumerate(self.PLATFORMS):
            card = self._create_platform_card(key, name, icon_path)
            self._platform_cards[key] = card
            row, col = divmod(i, 3)
            self.cardsGrid.addWidget(card, row, col)

        self.layout.addStretch()

        # 启动时自检下载目录
        try:
            ensure_download_dirs()
        except Exception:
            pass

    def setAllowedPlatforms(self, allowed_keys: set):
        """按权限过滤平台入口卡片（隐藏被禁用的平台）"""
        for key, card in self._platform_cards.items():
            card.setVisible(key in allowed_keys)

    def _create_platform_card(self, key: str, name: str, icon_path: str):
        """创建单个平台入口卡片，点击跳转到子模块"""
        card = CardWidget(self.view)
        card.setFixedSize(280, 160)
        card.setCursor(Qt.PointingHandCursor)

        cardLayout = QVBoxLayout(card)
        cardLayout.setSpacing(10)
        cardLayout.setAlignment(Qt.AlignCenter)

        # 图标
        iconWidget = QLabel(card)
        iconWidget.setAlignment(Qt.AlignCenter)
        iconWidget.setFixedSize(64, 64)
        if icon_path and os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            iconWidget.setPixmap(pix)
        else:
            # 使用 Fluent 图标
            icon_map = {
                'pixiv': FIF.PHOTO,
                'xvideo': FIF.VIDEO,
                'youtube': FIF.PLAY,
            }
            icon = icon_map.get(key, FIF.VIDEO)
            fl_icon = IconWidget(icon, card)
            fl_icon.setFixedSize(48, 48)
            fl_icon.setStyleSheet("color: #28afe9; background: transparent;")
            cardLayout.addWidget(fl_icon, 0, Qt.AlignCenter)
            cardLayout.addWidget(BodyLabel(name, card), 0, Qt.AlignCenter)
            card.clicked = lambda: self._navigate(key)
            card.mouseReleaseEvent = lambda e: self._navigate(key)
            return card

        cardLayout.addWidget(iconWidget, 0, Qt.AlignCenter)
        cardLayout.addWidget(BodyLabel(name, card), 0, Qt.AlignCenter)
        card.clicked = lambda: self._navigate(key)
        card.mouseReleaseEvent = lambda e: self._navigate(key)
        return card

    def setSubInterfaces(self, subs: dict):
        """由 Window 设置六个子页面引用 {key: page}"""
        self._sub_interfaces = subs

    def _navigate(self, key: str):
        """跳转到对应平台子页面"""
        sub = self._sub_interfaces.get(key)
        win = self.window()
        if win and sub:
            win.switchTo(sub)

    # ── 主题切换自动刷新 ──
    def _apply_theme_style(self):
        """主题切换时刷新标题/描述文字颜色"""
        subLabel = self.layout.itemAt(1).widget()
        if subLabel is not None:
            subLabel.setStyleSheet(
                "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 13px;")
        # 刷新所有卡片
        for card in self._platform_cards.values():
            card.update()


# =======================  独立测试  =======================
if __name__ == '__main__':
    from PyQt5.QtWidgets import QApplication
    from qfluentwidgets import setTheme, Theme

    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    w = MultiPlatformVideoInterface()
    w.resize(1080, 780)
    w.show()
    sys.exit(app.exec_())