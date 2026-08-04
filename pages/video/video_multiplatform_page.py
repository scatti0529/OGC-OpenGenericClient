# coding:utf-8
"""
多平台视频解析页面
===================
视频主页显示六大平台入口，每个平台是子模块页面，
可通过导航栏子项或主页图标按钮跳转。
"""
import os
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
    SegmentedWidget, LineEdit, PrimaryPushButton, PushButton,
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

    def __init__(self, platform: str, url: str, sessdata: str = '', parent=None):
        super().__init__(parent)
        self.platform = platform
        self.url = url
        self.sessdata = sessdata

    def run(self):
        try:
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
        self.urlEdit = LineEdit(inputCard)
        self.urlEdit.setPlaceholderText(f"请输入{display_name}分享链接...")
        self.urlEdit.setClearButtonEnabled(True)
        urlRow.addWidget(self.urlEdit, 1)

        # 粘贴按钮：清空输入框并填入刚刚复制的内容
        self.pasteBtn = PushButton(FIF.PASTE, "粘贴", inputCard)
        self.pasteBtn.setFixedWidth(80)
        self.pasteBtn.setToolTip("清空输入框并粘贴剪贴板内容")
        self.pasteBtn.clicked.connect(self._paste_from_clipboard)
        urlRow.addWidget(self.pasteBtn)

        self.parseBtn = PrimaryPushButton(FIF.SYNC, "解析", inputCard)
        self.parseBtn.clicked.connect(self._parse)
        urlRow.addWidget(self.parseBtn)
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

    def _paste_from_clipboard(self):
        """清空输入框并填入刚刚复制的内容"""
        try:
            from PyQt5.QtWidgets import QApplication
            text = QApplication.clipboard().text().strip()
            if text:
                self.urlEdit.clear()
                self.urlEdit.setText(text)
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
        if self._parsing:
            return

        url = self.urlEdit.text().strip()
        if not url:
            InfoBar.warning(
                title="提示", content="请输入下载链接",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
            return

        # 保存本次解析参数并重置重试计数
        self._parse_url = url
        self._parse_sessdata = self.sessdataEdit.text().strip() if self.platform == 'bilibili' else ''
        self._parse_retry_count = 0

        # 开始解析
        self._start_parse(retrying=False)

    def _start_parse(self, retrying: bool = False):
        """启动解析（支持重试）

        Args:
            retrying: 是否为自动重试
        """
        # 锁定输入控件，防止解析中再次点击
        self._parsing = True
        self.parseBtn.setEnabled(False)
        if retrying:
            self.parseBtn.setText(f"重试 {self._parse_retry_count}/{self._parse_retry_max}...")
            self.emptyLabel.setText(f"解析失败，正在自动重试 ({self._parse_retry_count}/{self._parse_retry_max})...")
        else:
            self.parseBtn.setText("解析中...")
            self.emptyLabel.setText("正在解析...")
        self.pasteBtn.setEnabled(False)
        self.urlEdit.setEnabled(False)
        if hasattr(self, 'sessdataEdit'):
            self.sessdataEdit.setEnabled(False)

        # 清空现有结果（首次解析时）
        if not retrying:
            self._clear_results()

        # 安全回收旧解析线程（防止访问已删除的 C++ 对象）
        old_thread = self._parse_thread
        self._parse_thread = None
        if old_thread is not None:
            try:
                if old_thread.isRunning():
                    old_thread.wait(1000)
                old_thread.deleteLater()
            except (RuntimeError, Exception):
                pass

        self._parse_thread = ParseThread(
            self.platform, self._parse_url, self._parse_sessdata)
        self._parse_thread.finished.connect(self._on_parse_finished)
        self._parse_thread.error.connect(self._on_parse_error)
        self._parse_thread.start()

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
            # 禁用解析、粘贴、输入等控件
            self.parseBtn.setEnabled(False)
            self.pasteBtn.setEnabled(False)
            self.urlEdit.setEnabled(False)
            if hasattr(self, 'sessdataEdit'):
                self.sessdataEdit.setEnabled(False)
        else:
            # 检查是否还有卡片在下载或排队
            still_downloading = any(
                getattr(c, '_download_active', False) for c in self._cards)
            if not still_downloading:
                self._downloading = False
                # 恢复控件（若不在解析中）
                if not self._parsing:
                    self.parseBtn.setEnabled(True)
                    self.pasteBtn.setEnabled(True)
                    self.urlEdit.setEnabled(True)
                    if hasattr(self, 'sessdataEdit'):
                        self.sessdataEdit.setEnabled(True)
                # 恢复所有卡片按钮
                for card in self._cards:
                    card.on_page_downloading_changed(False)

    def _on_parse_finished(self, items: list):
        """解析完成"""
        self._parsing = False
        self.parseBtn.setEnabled(True)
        self.parseBtn.setText("解析")
        self.pasteBtn.setEnabled(not self._downloading)
        self.urlEdit.setEnabled(not self._downloading)
        if hasattr(self, 'sessdataEdit'):
            self.sessdataEdit.setEnabled(not self._downloading)
        # 安全回收解析线程
        old_thread = self._parse_thread
        self._parse_thread = None
        if old_thread is not None:
            try:
                if old_thread.isRunning():
                    old_thread.wait(500)
                old_thread.deleteLater()
            except (RuntimeError, Exception):
                pass

        self._items = items
        self.emptyLabel.setVisible(False)
        self.resultsScroll.setVisible(True)

        for i, item in enumerate(items):
            card = MediaCard(item, self.platform, self.resultsView)
            row = i // 4
            col = i % 4
            self.resultsGrid.addWidget(card, row, col)
            self._cards.append(card)

        InfoBar.success(
            title="解析完成", content=f"找到 {len(items)} 个媒体资源",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=3000, parent=self
        )

    def _on_parse_error(self, message: str):
        """解析失败（自动重试最多 3 次）"""
        # 安全回收解析线程
        old_thread = self._parse_thread
        self._parse_thread = None
        if old_thread is not None:
            try:
                if old_thread.isRunning():
                    old_thread.wait(500)
                old_thread.deleteLater()
            except (RuntimeError, Exception):
                pass

        # 自动重试
        if self._parse_retry_count < self._parse_retry_max:
            self._parse_retry_count += 1
            InfoBar.warning(
                title="解析失败，自动重试",
                content=f"第 {self._parse_retry_count}/{self._parse_retry_max} 次重试: {message}",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
            self._start_parse(retrying=True)
            return

        # 重试耗尽，最终失败
        self._parsing = False
        self.parseBtn.setEnabled(True)
        self.parseBtn.setText("解析")
        self.pasteBtn.setEnabled(not self._downloading)
        self.urlEdit.setEnabled(not self._downloading)
        if hasattr(self, 'sessdataEdit'):
            self.sessdataEdit.setEnabled(not self._downloading)
        # 重置重试计数
        self._parse_retry_count = 0

        self.emptyLabel.setVisible(True)
        self.emptyLabel.setText("解析失败")
        self.resultsScroll.setVisible(False)
        InfoBar.error(
            title="解析失败", content=message,
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT, duration=5000, parent=self
        )


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