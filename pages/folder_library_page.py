# -*- coding: utf-8 -*-
"""
Folder library（下载文件库）页面
================================
- 浏览配置的下载根目录（video_download_root）
- 跨平台文件检索与展示（目录/图片/视频/音频/压缩包/文本）
- 封面异步加载、文本阅读、视频/音乐播放、图片/漫画浏览
- 目录扫描异步化，避免打开大文件夹时界面卡顿
- 下载目录变更后自动切换
"""
import os

from PyQt5.QtCore import Qt, QUrl, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap, QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame,
    QDialog, QListWidget, QListWidgetItem, QSlider, QTextEdit,
)

try:
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    from PyQt5.QtMultimediaWidgets import QVideoWidget
    _HAS_MULTIMEDIA = True
except Exception:
    _HAS_MULTIMEDIA = False

from qfluentwidgets import (
    CardWidget, FluentIcon as FIF, PushButton,
    CaptionLabel, SubtitleLabel, BodyLabel, InfoBar, InfoBarPosition,
    ToolButton, isDarkTheme, FlowLayout, IndeterminateProgressBar,
    ComboBox as FluentComboBox,
)

from services import file_library as FL
from ui.widgets.theme import theme_color
from ui.widgets.ui_utils import install_hover_tip


RESOLUTION_PRESETS = [
    ('1920×1080', 1920, 1080),
    ('2560×1440', 2560, 1440),
    ('1600×1200', 1600, 1200),
    ('1280×720', 1280, 720),
    ('1024×768', 1024, 768),
    ('800×600', 800, 600),
    ('640×480', 640, 480),
]


def add_resolution_selector(dialog, layout, default_w: int, default_h: int) -> FluentComboBox:
    """在对话框顶部添加分辨率选择器，选中后调整窗口大小"""
    row = QHBoxLayout()
    row.setSpacing(8)

    label = CaptionLabel("页面大小", dialog)
    label.setStyleSheet("font-size: 12px; color: " + theme_color('#909399', '#8A8A8A') + ";")
    row.addWidget(label)

    combo = FluentComboBox(dialog)
    combo.setFixedWidth(150)
    combo.setFixedHeight(30)
    for text, w, h in RESOLUTION_PRESETS:
        combo.addItem(text, None, (w, h))

    best_idx = 0
    best_diff = None
    for i, (text, w, h) in enumerate(RESOLUTION_PRESETS):
        diff = abs(w - default_w) + abs(h - default_h)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_idx = i
    combo.setCurrentIndex(best_idx)

    def _on_changed(idx):
        data = combo.itemData(idx)
        if data:
            w, h = data
            dialog.resize(w, h)

    combo.currentIndexChanged.connect(_on_changed)
    row.addWidget(combo)
    row.addStretch(1)

    layout.insertLayout(0, row)
    return combo


# ═══════════════════════════════════════════════════════════
#  后台线程
# ═══════════════════════════════════════════════════════════
class DirectoryScanWorker(QThread):
    """后台扫描目录，避免大文件夹阻塞 UI"""
    done = pyqtSignal(int, dict)   # (generation, data)
    failed = pyqtSignal(int, str)

    def __init__(self, generation: int, path: str, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.path = path

    def run(self):
        try:
            data = FL.list_directory_cached(self.path)
            self.done.emit(self.generation, data)
        except Exception as e:
            self.failed.emit(self.generation, str(e))


class BatchThumbnailWorker(QThread):
    """主动遍历目录（含子目录）批量生成缩略图，已有缩略图自动跳过"""
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal()

    def __init__(self, root: str, max_files: int = 2000, parent=None):
        super().__init__(parent)
        self.root = root
        self.max_files = max_files
        self._stop = False

    def stop(self):
        """请求停止（协作式：循环中检查，尽快退出）。"""
        self._stop = True

    def _collect_media(self):
        items = []
        try:
            for dirpath, dirnames, filenames in os.walk(self.root):
                # 排除所有缓存目录：旧命名 thumb_cache/dir_cache + 新命名 .cache/.thumbs。
                # 缓存现在位于下载根目录下，必须在这里挡掉，否则会被当成用户内容批量生成缩略图。
                dirnames[:] = [d for d in dirnames
                               if d not in ('thumb_cache', 'dir_cache', '.cache', '.thumbs')]
                for name in filenames:
                    ext = os.path.splitext(name)[1].lower()
                    if FL.classify_ext(ext) in ('image', 'video', 'audio'):
                        items.append(os.path.join(dirpath, name))
                        if len(items) >= self.max_files:
                            return items
        except Exception:
            pass
        return items

    def run(self):
        try:
            self.setPriority(QThread.LowPriority)
        except Exception:
            pass
        items = self._collect_media()
        total = len(items)
        done = 0
        for p in items:
            if self._stop:
                break
            try:
                if FL.get_cached_thumb(p):
                    done += 1
                    self.progress.emit(done, total, f"跳过 {os.path.basename(p)}")
                    continue
                kind = FL.classify_ext(os.path.splitext(p)[1].lower())
                if kind == 'image':
                    FL.get_image_thumbnail(p)
                elif kind == 'video':
                    if FL.VIDEO_COVER_SEM.acquire(timeout=5):
                        try:
                            FL.get_video_thumbnail(p)
                        finally:
                            FL.VIDEO_COVER_SEM.release()
                elif kind == 'audio':
                    cover = FL.find_audio_cover_in_dir(os.path.dirname(p))
                    if cover:
                        FL.get_image_thumbnail(cover)
                done += 1
                self.progress.emit(done, total, f"生成 {os.path.basename(p)}")
            except Exception:
                done += 1
                self.progress.emit(done, total, f"失败 {os.path.basename(p)}")
        self.finished.emit()


class CoverLoadWorker(QThread):
    """后台仅查找/提取封面路径，不加载图像（避免跨线程创建 QPixmap）"""
    found = pyqtSignal(int, str, str)  # (card_id, cover_path, kind)
    done = pyqtSignal(int)             # (card_id) 无论成功失败都会发出

    def __init__(self, card_id: int, path: str, kind: str, parent=None):
        super().__init__(parent)
        self.card_id = card_id
        self.path = path
        self.kind = kind

    def run(self):
        try:
            self.setPriority(QThread.LowPriority)
        except Exception:
            pass
        cover = ''
        try:
            # 先查索引缓存，已有则直接返回；无则生成并注册
            cover = FL.get_cached_thumb(self.path)
            if not cover:
                if FL.COVER_LOAD_SEM.acquire(timeout=8):
                    try:
                        cover = FL.get_cover_thumbnail(self.path, self.kind)
                    finally:
                        FL.COVER_LOAD_SEM.release()
        except Exception:
            cover = ''
        try:
            if cover:
                self.found.emit(self.card_id, cover, self.kind)
        finally:
            self.done.emit(self.card_id)


# ═══════════════════════════════════════════════════════════
#  媒体播放对话框
# ═══════════════════════════════════════════════════════════
class MediaPlayerDialog(QDialog):
    """视频/音乐播放对话框（支持进度条拖动 + 上一个/下一个视频）"""

    def __init__(self, path: str, title: str, kind: str, parent=None,
                 video_list=None, index=0):
        super().__init__(parent)
        self.path = path
        self.kind = kind
        self._closing = False
        self.video_list = video_list or [path]
        self.index = max(0, min(index, len(self.video_list) - 1))
        self._slider_dragging = False

        self.setWindowTitle(title)
        self.setMinimumSize(760, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 分辨率选择器（视频 16:9，音乐 4:3）
        if kind == 'video':
            add_resolution_selector(self, layout, 1280, 720)
        else:
            add_resolution_selector(self, layout, 800, 600)

        if kind == 'video' and _HAS_MULTIMEDIA:
            self.video_widget = QVideoWidget(self)
            self.video_widget.setMinimumSize(720, 400)
            layout.addWidget(self.video_widget, 1)
            self.player = QMediaPlayer(self, QMediaPlayer.VideoSurface)
            self.player.setVideoOutput(self.video_widget)
        elif _HAS_MULTIMEDIA:
            self.player = QMediaPlayer(self)
            layout.addSpacing(20)
            self.hint_label = SubtitleLabel(f"♪ {os.path.basename(title)}", self)
            self.hint_label.setStyleSheet("font-size: 18px; font-weight: bold;")
            self.hint_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.hint_label)
            layout.addStretch(1)
        else:
            layout.addStretch(1)
            lbl = BodyLabel("当前环境缺少多媒体组件，无法播放。", self)
            lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(lbl)
            layout.addStretch(1)

        if _HAS_MULTIMEDIA:
            ctrl = QHBoxLayout()
            ctrl.setSpacing(8)

            # 视频同目录上一个/下一个切换
            if kind == 'video' and len(self.video_list) > 1:
                self.prev_btn = PushButton(FIF.LEFT_ARROW, " 上一个", self)
                self.prev_btn.clicked.connect(self._prev_video)
                self.prev_btn.setEnabled(self.index > 0)
                ctrl.addWidget(self.prev_btn)

                self.next_btn = PushButton(FIF.RIGHT_ARROW, " 下一个", self)
                self.next_btn.clicked.connect(self._next_video)
                self.next_btn.setEnabled(self.index < len(self.video_list) - 1)
                ctrl.addWidget(self.next_btn)

            self.play_btn = PushButton(FIF.PLAY, " 播放/暂停", self)
            self.play_btn.clicked.connect(self._toggle_play)
            ctrl.addWidget(self.play_btn)

            self.stop_btn = PushButton(FIF.CANCEL, " 停止", self)
            self.stop_btn.clicked.connect(self._stop)
            ctrl.addWidget(self.stop_btn)

            self.position_slider = QSlider(Qt.Horizontal, self)
            self.position_slider.setRange(0, 1000)
            self.position_slider.sliderPressed.connect(self._on_slider_pressed)
            self.position_slider.sliderReleased.connect(self._on_slider_released)
            self.position_slider.sliderMoved.connect(self._seek)
            ctrl.addWidget(self.position_slider, 1)

            self.time_label = BodyLabel("00:00 / 00:00", self)
            self.time_label.setStyleSheet(
                "font-size: 11px; color: " + theme_color('#909399', '#8A8A8A') + ";")
            ctrl.addWidget(self.time_label)

            ctrl.addStretch()
            layout.addLayout(ctrl)

            self.player.positionChanged.connect(self._on_position)
            self.player.durationChanged.connect(self._on_duration)
            self._load_path(self.video_list[self.index])
        else:
            bottom = QHBoxLayout()
            bottom.addStretch()
            close_btn = PushButton(FIF.CLOSE, " 关闭", self)
            close_btn.clicked.connect(self.close)
            bottom.addWidget(close_btn)
            layout.addLayout(bottom)

    def _load_path(self, path: str):
        """加载指定媒体文件并播放"""
        self.path = path
        self.setWindowTitle(os.path.basename(path))
        if hasattr(self, 'hint_label'):
            self.hint_label.setText(f"♪ {os.path.basename(path)}")
        self.player.setMedia(
            QMediaContent(QUrl.fromLocalFile(os.path.abspath(path))))
        self.player.play()

    def _prev_video(self):
        if self.index > 0:
            self.index -= 1
            self._load_path(self.video_list[self.index])
            self.prev_btn.setEnabled(self.index > 0)
            self.next_btn.setEnabled(True)

    def _next_video(self):
        if self.index < len(self.video_list) - 1:
            self.index += 1
            self._load_path(self.video_list[self.index])
            self.next_btn.setEnabled(self.index < len(self.video_list) - 1)
            self.prev_btn.setEnabled(True)

    def _toggle_play(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _stop(self):
        self.player.stop()

    def _on_slider_pressed(self):
        self._slider_dragging = True

    def _on_slider_released(self):
        self._slider_dragging = False
        self._seek(self.position_slider.value())

    def _seek(self, value: int):
        if self.player.duration() > 0:
            self.player.setPosition(int(self.player.duration() * value / 1000))

    @staticmethod
    def _fmt_time(ms: int) -> str:
        s = max(0, ms // 1000)
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"

    def _on_position(self, pos: int):
        if self.player.duration() > 0 and not self._closing:
            if not self._slider_dragging:
                try:
                    self.position_slider.blockSignals(True)
                    self.position_slider.setValue(int(pos * 1000 / self.player.duration()))
                    self.position_slider.blockSignals(False)
                except Exception:
                    pass
            self.time_label.setText(
                f"{self._fmt_time(pos)} / {self._fmt_time(self.player.duration())}")

    def _on_duration(self, dur: int):
        pass

    def closeEvent(self, event):
        self._closing = True
        # 精确回收模块持有的后台线程（协作式 stop + wait）
        for attr in ('_batch_worker', '_cover_worker', '_scan_worker', '_worker', '_cover_load_worker'):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    if getattr(w, 'stop', None):
                        w.stop()
                    if w.isRunning():
                        w.wait(2000)
                except Exception:
                    pass
        if _HAS_MULTIMEDIA and hasattr(self, 'player'):
            try:
                self.player.stop()
                self.player.setMedia(QMediaContent())
            except Exception:
                pass
        super().closeEvent(event)


class ImageGalleryDialog(QDialog):
    """图片 / 漫画图集浏览对话框"""

    def __init__(self, images: list, start_index: int = 0, title: str = '', parent=None):
        super().__init__(parent)
        self.images = list(images)
        self.index = max(0, min(start_index, len(self.images) - 1)) if self.images else -1
        self._pix = None
        self._zoom = 1.0

        self.setWindowTitle(title or '图片浏览')
        self.resize(900, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 分辨率选择器（图片默认 1024×768）
        add_resolution_selector(self, layout, 1024, 768)

        self.info_label = CaptionLabel("", self)
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.info_label)

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(400)
        self.image_label.setStyleSheet(
            "background-color: rgba(0,0,0,0.35); border-radius: 8px; color: #CCCCCC;")
        layout.addWidget(self.image_label, 1)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.prev_btn = PushButton(FIF.LEFT_ARROW, " 上一张", self)
        self.prev_btn.clicked.connect(self.prev)
        ctrl.addWidget(self.prev_btn)
        self.next_btn = PushButton(FIF.RIGHT_ARROW, " 下一张", self)
        self.next_btn.clicked.connect(self.next)
        ctrl.addWidget(self.next_btn)
        ctrl.addStretch()
        self.zoom_out_btn = PushButton(FIF.ZOOM_OUT, " 缩小", self)
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        ctrl.addWidget(self.zoom_out_btn)
        self.zoom_in_btn = PushButton(FIF.ZOOM_IN, " 放大", self)
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        ctrl.addWidget(self.zoom_in_btn)
        self.open_folder_btn = PushButton(FIF.FOLDER, " 所在目录", self)
        self.open_folder_btn.clicked.connect(self._open_folder)
        ctrl.addWidget(self.open_folder_btn)
        self.close_btn = PushButton(FIF.CLOSE, " 关闭", self)
        self.close_btn.clicked.connect(self.close)
        ctrl.addWidget(self.close_btn)
        layout.addLayout(ctrl)

        self._show_current()

    def _show_current(self):
        if self.index < 0 or self.index >= len(self.images):
            self.image_label.setText("无图片")
            self.info_label.setText("")
            return
        path = self.images[self.index]
        self.info_label.setText(f"{self.index + 1} / {len(self.images)}  ·  {os.path.basename(path)}")
        pix = QPixmap(path)
        if pix.isNull():
            self.image_label.setText("无法加载图片")
            self._pix = None
            return
        self._pix = pix
        self._zoom = 1.0
        self._apply_scale()
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.images) - 1)

    def _apply_scale(self):
        if self._pix is None:
            return
        tw = int(self.image_label.width() * self._zoom)
        th = int(self.image_label.height() * self._zoom)
        if tw <= 0 or th <= 0:
            return
        scaled = self._pix.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_scale()

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.prev()
        else:
            self.next()

    def _zoom_in(self):
        self._zoom = min(5.0, self._zoom * 1.25)
        self._apply_scale()

    def _zoom_out(self):
        self._zoom = max(0.2, self._zoom / 1.25)
        self._apply_scale()

    def prev(self):
        if self.index > 0:
            self.index -= 1
            self._show_current()

    def next(self):
        if self.index < len(self.images) - 1:
            self.index += 1
            self._show_current()

    def _open_folder(self):
        if self.index >= 0 and self.index < len(self.images):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.images[self.index])))


class ExtractWorker(QThread):
    """后台解压线程"""
    done = pyqtSignal(bool, str)

    def __init__(self, archive_path: str, dest: str, parent=None):
        super().__init__(parent)
        self.archive_path = archive_path
        self.dest = dest

    def run(self):
        try:
            success, msg = FL.extract_archive(self.archive_path, self.dest)
            self.done.emit(success, msg)
        except Exception as e:
            self.done.emit(False, str(e))


class ExtractDialog(QDialog):
    """压缩包解压对话框（Bandizip 风格）"""

    def __init__(self, archive_path: str, parent=None):
        super().__init__(parent)
        self.archive_path = archive_path
        self.setWindowTitle(f"解压 - {os.path.basename(archive_path)}")
        self.setMinimumSize(520, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = SubtitleLabel(f"📦 {os.path.basename(archive_path)}", self)
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        info_row = QHBoxLayout()
        info_label = CaptionLabel("目标目录：", self)
        info_label.setStyleSheet("font-size: 13px;")
        info_row.addWidget(info_label)
        self.dest_label = CaptionLabel("", self)
        self.dest_label.setStyleSheet(
            "font-size: 12px; color: " + theme_color('#909399', '#8A8A8A') + ";")
        self.dest_label.setWordWrap(True)
        info_row.addWidget(self.dest_label, 1)
        layout.addLayout(info_row)

        # 默认解压到同目录同名文件夹
        default_dest = os.path.join(
            os.path.dirname(archive_path),
            os.path.splitext(os.path.basename(archive_path))[0])
        self.dest_label.setText(default_dest)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.extract_btn = PrimaryPushButton(FIF.DOWNLOAD, " 立即解压", self)
        self.extract_btn.clicked.connect(self._extract)
        btn_row.addWidget(self.extract_btn)

        self.open_folder_btn = PushButton(FIF.FOLDER, " 打开解压目录", self)
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._open_dest)
        btn_row.addWidget(self.open_folder_btn)

        self.cancel_btn = PushButton(FIF.CLOSE, " 关闭", self)
        self.cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.progress = IndeterminateProgressBar(self)
        self.progress.setFixedHeight(6)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_label = CaptionLabel("", self)
        self.status_label.setStyleSheet(
            "font-size: 11px; color: " + theme_color('#909399', '#8A8A8A') + ";")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.list_label = CaptionLabel("", self)
        self.list_label.setStyleSheet(
            "font-size: 11px; color: " + theme_color('#909399', '#8A8A8A') + ";")
        self.list_label.setWordWrap(True)
        self.list_label.setVisible(False)
        layout.addWidget(self.list_label)

        layout.addStretch()

        self._load_preview()
        self._worker = None

    def _load_preview(self):
        entries = FL.list_archive(self.archive_path)
        if entries:
            shown = entries[:100]
            self.list_label.setText("包含文件：\n" + "\n".join(shown))
            self.list_label.setVisible(True)

    def _extract(self):
        dest = self.dest_label.text()
        self.extract_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.start()
        self.status_label.setText("正在解压...")

        self._worker = ExtractWorker(self.archive_path, dest, self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, success: bool, msg: str):
        self.progress.setVisible(False)
        self.progress.stop()
        self.extract_btn.setEnabled(True)
        self.status_label.setText(msg)
        self._worker = None
        if success:
            self.open_folder_btn.setEnabled(True)
            InfoBar.success("解压完成", msg, parent=self.window())
        else:
            InfoBar.error("解压失败", msg, parent=self.window())

    def _open_dest(self):
        dest = self.dest_label.text()
        if os.path.isdir(dest):
            QDesktopServices.openUrl(QUrl.fromLocalFile(dest))

    def closeEvent(self, event):
        w = self._worker
        if w is not None and w.isRunning():
            try:
                w.requestInterruption()
                w.wait(3000)
            except (RuntimeError, Exception):
                pass
        super().closeEvent(event)


class TextReaderDialog(QDialog):
    """文本文件阅读对话框"""

    def __init__(self, path: str, title: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle(title or os.path.basename(path))
        self.resize(760, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 分辨率选择器（文本默认 800×600）
        add_resolution_selector(self, layout, 800, 600)

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            "QTextEdit { background-color: " + theme_color('#FAFAFA', '#1E1E1E') +
            "; border: none; border-radius: 6px; font-size: 13px; }")
        layout.addWidget(self.text_edit, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = PushButton(FIF.CLOSE, " 关闭", self)
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        try:
            content = FL.read_text_file(path)
            self.text_edit.setPlainText(content)
        except Exception:
            self.text_edit.setPlainText("无法读取该文本文件")


# ═══════════════════════════════════════════════════════════
#  文件卡片
# ═══════════════════════════════════════════════════════════
class FileCard(CardWidget):
    """文件/目录条目卡片（支持封面异步加载）"""

    def __init__(self, entry: dict, page, parent=None):
        super().__init__(parent=parent)
        self.entry = entry
        self.page = page
        self.card_id = id(self)
        self._cover_worker = None

        self.setFixedSize(180, 140)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # 封面预览区
        self.cover_label = QLabel(self)
        self.cover_label.setFixedSize(160, 88)
        self.cover_label.setAlignment(Qt.AlignCenter)
        kind = entry.get('kind', '')
        if kind == 'dir':
            self.cover_label.setStyleSheet(
                "background-color: " + theme_color('rgba(5,167,220,0.10)', 'rgba(5,167,220,0.14)') +
                "; border: 1px solid " + theme_color('rgba(5,167,220,0.35)', 'rgba(5,167,220,0.4)') +
                "; border-radius: 2px; font-size: 34px; color: " +
                theme_color('#4A90D9', '#7EB8F0') + ";")
        else:
            self.cover_label.setStyleSheet(
                "background-color: " + theme_color('rgba(0,0,0,0.05)', 'rgba(255,255,255,0.06)') +
                "; border-radius: 6px; font-size: 34px; color: " +
                theme_color('#909399', '#8A8A8A') + ";")
        icon_map = {'dir': '📁', 'video': '🎬', 'audio': '🎵', 'image': '🖼',
                    'txt': '📝', 'archive': '📦'}
        self.cover_label.setText(icon_map.get(kind, '📄'))
        layout.addWidget(self.cover_label)

        # 名称
        name = entry.get('name', '')
        if len(name) > 18:
            name = name[:18] + '...'
        self.name_label = BodyLabel(name, self)
        self.name_label.setStyleSheet(
            "font-size: 12px; color: " + theme_color('#555555', '#CCCCCC') + ";")
        self.name_label.setToolTip(entry.get('name', ''))
        self.name_label.setWordWrap(False)
        layout.addWidget(self.name_label)

        # 大小
        if not entry.get('is_dir') and entry.get('size'):
            self.size_label = CaptionLabel(FL.format_size(entry['size']), self)
            self.size_label.setStyleSheet(
                "font-size: 10px; color: " + theme_color('#909399', '#8A8A8A') + ";")
            layout.addWidget(self.size_label)

        # 同步加载已有缓存封面（立即显示，不依赖异步信号）
        if kind in ('dir', 'image', 'audio', 'video'):
            cached = FL.get_cached_thumb(entry['path'])
            if cached:
                self._set_cover_pixmap(cached, kind)

        # 触发异步封面加载（生成缺失缩略图）
        if kind in ('dir', 'image', 'audio', 'video'):
            self._start_cover_load(entry['path'], kind)

    def _set_cover_pixmap(self, cover_path: str, kind: str = ''):
        """加载封面缩略图并设置到标签"""
        try:
            pix = QPixmap(cover_path)
            if pix.isNull():
                return
            pix = pix.scaled(
                160, 88, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            w, h = pix.width(), pix.height()
            x = max(0, (w - 160) // 2)
            y = max(0, (h - 88) // 2)
            cropped = pix.copy(x, y, 160, 88)
            self.cover_label.setPixmap(cropped)
            if kind == 'dir':
                self.cover_label.setStyleSheet(
                    "border: 1px solid " + theme_color('rgba(5,167,220,0.35)', 'rgba(5,167,220,0.4)') +
                    "; border-radius: 2px;")
        except Exception:
            pass

    def _start_cover_load(self, path: str, kind: str):
        self._cover_worker = CoverLoadWorker(self.card_id, path, kind, self)
        self._cover_worker.found.connect(self._on_cover_found)
        self._cover_worker.done.connect(self._on_cover_done)
        self._cover_worker.start()

    def _on_cover_found(self, card_id: int, cover_path: str, kind: str = ''):
        if card_id != self.card_id:
            return
        self._set_cover_pixmap(cover_path, kind)

    def _on_cover_done(self, card_id: int):
        """封面线程结束（成功或失败），更新进度计数"""
        if card_id != self.card_id:
            return
        self._cover_worker = None
        if self.page is not None and hasattr(self.page, '_on_thumb_done'):
            self.page._on_thumb_done()

    def stop_worker(self):
        """安全停止封面线程，避免 QThread destroyed while running"""
        w = self._cover_worker
        self._cover_worker = None
        if w is None:
            return
        try:
            w.found.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            w.done.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            if w.isRunning():
                w.requestInterruption()
                w.wait(3000)
            w.deleteLater()
        except (RuntimeError, Exception):
            pass

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.page.on_entry_clicked(self.entry)
        super().mouseReleaseEvent(e)


# ═══════════════════════════════════════════════════════════
#  Folder library 页面主体
# ═══════════════════════════════════════════════════════════
class FolderLibraryPage(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("FolderLibraryPage")

        self._current_path = ''
        self._history = []
        self._root_watch_timer = None
        self._last_root = ''
        self._scan_worker = None
        self._scan_generation = 0
        self._batch_worker = None

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        outer = QWidget(self)
        outer.setStyleSheet("background: transparent;")
        self.setWidget(outer)
        main_layout = QVBoxLayout(outer)
        main_layout.setContentsMargins(20, 36, 20, 16)
        main_layout.setSpacing(12)

        # 顶部标题栏
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = SubtitleLabel("📂 下载文件库", outer)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_row.addWidget(title)

        self.dir_label = CaptionLabel("", outer)
        self.dir_label.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 11px;")
        self.dir_label.setWordWrap(True)
        title_row.addWidget(self.dir_label, 1)

        self.open_root_btn = PushButton(FIF.FOLDER, " 打开根目录", outer)
        self.open_root_btn.setFixedHeight(28)
        self.open_root_btn.clicked.connect(self._open_root_folder)
        title_row.addWidget(self.open_root_btn)

        self.refresh_btn = PushButton(FIF.SYNC, " 刷新", outer)
        self.refresh_btn.setFixedHeight(28)
        self.refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self.refresh_btn)

        self.preview_btn = PushButton(FIF.PHOTO, " 预览画册", outer)
        self.preview_btn.setFixedHeight(28)
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self._preview_current_album)
        title_row.addWidget(self.preview_btn)

        main_layout.addLayout(title_row)

        # 面包屑导航
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self.back_btn = ToolButton(FIF.LEFT_ARROW, outer)
        self.back_btn.setFixedSize(28, 28)
        self.back_btn.clicked.connect(self.go_back)
        nav_row.addWidget(self.back_btn)
        self.up_btn = ToolButton(FIF.UP, outer)
        self.up_btn.setFixedSize(28, 28)
        self.up_btn.clicked.connect(self.go_up)
        nav_row.addWidget(self.up_btn)
        self.path_label = BodyLabel("", outer)
        self.path_label.setStyleSheet(
            "font-size: 12px; color: " + theme_color('#606060', '#AAAAAA') + ";")
        self.path_label.setWordWrap(True)
        nav_row.addWidget(self.path_label, 1)
        main_layout.addLayout(nav_row)

        # 主体
        body = QHBoxLayout()
        body.setSpacing(12)

        self.sidebar = QFrame(outer)
        self.sidebar.setFixedWidth(220)
        self.sidebar.setStyleSheet(
            "QFrame { background-color: " + theme_color('rgba(255,255,255,0.65)', 'rgba(255,255,255,0.06)') + ";"
            " border: 1px solid " + theme_color('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.08)') + ";"
            " border-radius: 8px; }")
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(10, 10, 10, 10)
        side_layout.setSpacing(6)
        side_title = CaptionLabel("平台 / 分类", self.sidebar)
        side_title.setStyleSheet("font-size: 12px; font-weight: bold;")
        side_layout.addWidget(side_title)
        self.side_list = QListWidget(self.sidebar)
        self.side_list.setFrameShape(QFrame.NoFrame)
        self.side_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
            "QListWidget::item { padding: 8px 6px; border-radius: 6px; font-size: 13px; }"
            "QListWidget::item:hover { background: rgba(5,167,220,0.15); }"
            "QListWidget::item:selected { background: rgba(5,167,220,0.25); }")
        self.side_list.itemClicked.connect(self._on_sidebar_clicked)
        side_layout.addWidget(self.side_list, 1)
        self._add_sidebar_root()
        body.addWidget(self.sidebar)

        self.content_scroll = QScrollArea(outer)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.NoFrame)
        self.content_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.content_view = QWidget()
        self.content_view.setStyleSheet("background: transparent;")
        self.content_scroll.setWidget(self.content_view)
        body.addWidget(self.content_scroll, 1)
        main_layout.addLayout(body, 1)

        self.content_layout = QVBoxLayout(self.content_view)
        self.content_layout.setContentsMargins(4, 4, 4, 4)
        self.content_layout.setSpacing(0)

        self.loading_bar = IndeterminateProgressBar(outer)
        self.loading_bar.setFixedHeight(4)
        self.loading_bar.setVisible(False)
        main_layout.addWidget(self.loading_bar)

        # 缩略图进度标签
        self.thumb_progress_label = CaptionLabel("", outer)
        self.thumb_progress_label.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 11px;")
        self.thumb_progress_label.setVisible(False)
        main_layout.addWidget(self.thumb_progress_label)

        self._setup_root_watcher()
        self.goto_root()

    # ── 清理与重建 ──
    def _clear_content_layout(self):
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            if item is None:
                continue
            sub = item.layout()
            if sub is not None and hasattr(sub, 'removeAllWidgets'):
                try:
                    sub.removeAllWidgets()
                except (RuntimeError, Exception):
                    pass
        for child in list(self.content_view.findChildren(QWidget)):
            if child is self.content_view:
                continue
            if isinstance(child, FileCard):
                try:
                    child.stop_worker()
                except (RuntimeError, Exception):
                    pass
            try:
                child.setParent(None)
                child.deleteLater()
            except (RuntimeError, Exception):
                pass
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                sub.deleteLater()

    def _rebuild_content(self, data: dict):
        self._clear_content_layout()
        dirs = data.get('dirs', [])
        files = data.get('files', [])

        # 停止旧的分批渲染定时器
        if hasattr(self, '_render_timer') and self._render_timer is not None:
            self._render_timer.stop()
            self._render_timer.deleteLater()
            self._render_timer = None

        # 记录待加载缩略图总数，用于进度显示
        self._thumb_total = 0
        self._thumb_done_count = 0
        for d in dirs:
            if d['kind'] in ('dir', 'image', 'audio', 'video'):
                self._thumb_total += 1
        for f in files:
            if f['kind'] in ('image', 'audio', 'video'):
                self._thumb_total += 1
        self._update_thumb_progress()

        if not dirs and not files:
            empty = CaptionLabel("📭 空目录", self.content_view)
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                "color: " + theme_color('#AAAAAA', '#666666') + "; font-size: 14px; padding: 60px 0;")
            self.content_layout.addWidget(empty)
            self.content_layout.addStretch(1)
            return

        # 构建条目流与 FlowLayout
        if dirs:
            header = CaptionLabel(f"📁 文件夹（{len(dirs)}）", self.content_view)
            header.setStyleSheet("font-size: 12px; font-weight: bold; margin: 4px 0;")
            self.content_layout.addWidget(header)
            self._folder_flow = FlowLayout()
            self._folder_flow.setHorizontalSpacing(10)
            self._folder_flow.setVerticalSpacing(10)
            self.content_layout.addLayout(self._folder_flow)
        else:
            self._folder_flow = None

        if files:
            header = CaptionLabel(f"🗂 文件（{len(files)}）", self.content_view)
            header.setStyleSheet("font-size: 12px; font-weight: bold; margin: 8px 0 4px 0;")
            self.content_layout.addWidget(header)
            self._file_flow = FlowLayout()
            self._file_flow.setHorizontalSpacing(10)
            self._file_flow.setVerticalSpacing(10)
            self.content_layout.addLayout(self._file_flow)
        else:
            self._file_flow = None

        self.content_layout.addStretch(1)

        # 分批渲染条目，每批 24 个卡片
        self._render_queue = list(dirs) + list(files)
        self._render_index = 0
        self._render_batch_size = 24
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(0)
        self._render_timer.timeout.connect(self._render_next_batch)
        self._render_timer.start()
        self._render_next_batch()

    def _on_thumb_done(self):
        """封面加载完成进度回调"""
        self._thumb_done_count = getattr(self, '_thumb_done_count', 0) + 1
        self._update_thumb_progress()

    def _update_thumb_progress(self):
        total = getattr(self, '_thumb_total', 0)
        done = getattr(self, '_thumb_done_count', 0)
        lbl = getattr(self, 'thumb_progress_label', None)
        if total <= 0 or done >= total:
            if lbl is not None:
                lbl.setVisible(False)
        else:
            if lbl is not None:
                lbl.setText(f"🖼 缩略图加载中 {done}/{total} ...")
                lbl.setVisible(True)

    def _render_next_batch(self):
        """分批渲染卡片，避免一次性创建大量控件卡 UI"""
        if not hasattr(self, '_render_queue') or self._render_index >= len(self._render_queue):
            if hasattr(self, '_render_timer') and self._render_timer is not None:
                self._render_timer.stop()
                self._render_timer.deleteLater()
                self._render_timer = None
            return

        from PyQt5.QtWidgets import QApplication
        end = min(self._render_index + self._render_batch_size, len(self._render_queue))
        for i in range(self._render_index, end):
            entry = self._render_queue[i]
            if entry.get('is_dir'):
                flow = self._folder_flow
            else:
                flow = self._file_flow
            if flow is not None:
                flow.addWidget(FileCard(entry, self, self.content_view))
        self._render_index = end
        QApplication.processEvents()

    # ── 侧边栏 ──
    def _add_sidebar_root(self):
        item = QListWidgetItem("📂 下载根目录")
        item.setData(Qt.UserRole, FL.get_download_root())
        self.side_list.addItem(item)

    def _refresh_sidebar(self):
        self.side_list.blockSignals(True)
        self.side_list.clear()
        self._add_sidebar_root()
        for plat in FL.list_platforms():
            item = QListWidgetItem(f"📁 {plat['name']}")
            item.setData(Qt.UserRole, plat['path'])
            self.side_list.addItem(item)
        self.side_list.blockSignals(False)

    def _on_sidebar_clicked(self, item):
        path = item.data(Qt.UserRole)
        if path:
            self.goto_path(path)

    # ── 导航（异步扫描） ──
    def goto_root(self):
        self._refresh_sidebar()
        self.goto_path(FL.get_download_root())

    def goto_path(self, path: str):
        if not path or not os.path.isdir(path):
            InfoBar.warning("提示", "目录不存在", parent=self)
            return
        self._current_path = os.path.abspath(path)
        if not self._history or self._history[-1] != self._current_path:
            self._history.append(self._current_path)
            if len(self._history) > 100:
                self._history = self._history[-100:]

        self.dir_label.setText(self._current_path)
        self.path_label.setText(self._current_path)
        self.back_btn.setEnabled(len(self._history) > 1)
        root = FL.get_download_root()
        self.up_btn.setEnabled(os.path.abspath(self._current_path) != os.path.abspath(root))

        # 异步扫描目录（避免大文件夹卡 UI）
        self._scan_generation += 1
        gen = self._scan_generation
        self.loading_bar.setVisible(True)
        self.loading_bar.start()

        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.done.disconnect()
            self._scan_worker.failed.disconnect()
            try:
                self._scan_worker.wait(100)
            except Exception:
                pass

        self._scan_worker = DirectoryScanWorker(gen, self._current_path, self)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def _on_scan_done(self, gen: int, data: dict):
        if gen != self._scan_generation:
            return
        self.loading_bar.setVisible(False)
        self.loading_bar.stop()
        # 判断画册状态
        have_images = bool(data.get('files') and any(f['kind'] == 'image' for f in data['files']))
        self._is_album = have_images or FL.has_image_subdirs(self._current_path)
        self.preview_btn.setEnabled(self._is_album)
        self._rebuild_content(data)

        # 主动遍历当前目录，后台批量生成缺失缩略图（已有跳过）
        self._start_batch_thumbnail(self._current_path)

    def _start_batch_thumbnail(self, root: str):
        """启动批量缩略图后台任务"""
        if not root or not os.path.isdir(root):
            return
        if self._batch_worker is not None and self._batch_worker.isRunning():
            try:
                self._batch_worker.progress.disconnect()
                self._batch_worker.finished.disconnect()
                self._batch_worker.requestInterruption()
                self._batch_worker.wait(500)
            except (RuntimeError, Exception):
                pass
        self._batch_worker = BatchThumbnailWorker(root, max_files=500, parent=self)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished.connect(self._on_batch_finished)
        self._batch_worker.start()

    def _on_batch_progress(self, done: int, total: int, msg: str):
        self.thumb_progress_label.setText(f"🖼 缩略图 {done}/{total} - {msg}")
        self.thumb_progress_label.setVisible(True)

    def _on_batch_finished(self):
        self._batch_worker = None
        self.thumb_progress_label.setVisible(False)

    def _on_scan_failed(self, gen: int, msg: str):
        if gen != self._scan_generation:
            return
        self.loading_bar.setVisible(False)
        self.loading_bar.stop()
        InfoBar.error("扫描失败", msg, parent=self)

    def refresh(self):
        if self._current_path:
            self.goto_path(self._current_path)
        else:
            self.goto_root()

    def go_up(self):
        if not self._current_path:
            return
        parent = os.path.dirname(os.path.abspath(self._current_path))
        if parent and parent != self._current_path:
            self.goto_path(parent)

    def go_back(self):
        if len(self._history) <= 1:
            return
        self._history.pop()
        prev = self._history[-1]
        self._history.pop()
        self.goto_path(prev)

    # ── 条目点击 ──
    def on_entry_clicked(self, entry: dict):
        if entry.get('is_dir'):
            self.goto_path(entry['path'])
            return
        kind = entry.get('kind', 'other')
        path = entry['path']
        if kind == 'video':
            # 收集同目录所有视频，支持上一个/下一个切换
            video_list = []
            for f in FL.list_directory(os.path.dirname(path)).get('files', []):
                if f['kind'] == 'video':
                    video_list.append(f['path'])
            if path not in video_list:
                video_list = [path]
            index = video_list.index(path)
            self._play_media(path, entry['name'], 'video',
                             video_list=video_list, index=index)
        elif kind == 'audio':
            self._play_media(path, entry['name'], 'audio')
        elif kind == 'image':
            try:
                siblings = FL.list_images_in_dir(os.path.dirname(path))
                idx = siblings.index(path) if path in siblings else 0
                ImageGalleryDialog(siblings, idx, entry['name'], self).exec_()
            except Exception:
                InfoBar.error("打开失败", "无法浏览图片", parent=self)
        elif kind == 'txt':
            try:
                TextReaderDialog(path, entry['name'], self).exec_()
            except Exception:
                InfoBar.error("打开失败", "无法读取该文本文件", parent=self)
        elif kind == 'archive':
            try:
                ExtractDialog(path, self).exec_()
            except Exception:
                InfoBar.error("打开失败", "无法打开解压窗口", parent=self)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _play_media(self, path: str, title: str, kind: str, video_list=None, index=0):
        if not _HAS_MULTIMEDIA:
            InfoBar.error("无法播放", "当前环境缺少多媒体组件", parent=self)
            return
        try:
            MediaPlayerDialog(path, title, kind, parent=self,
                              video_list=video_list, index=index).exec_()
        except Exception as e:
            InfoBar.error("播放失败", str(e), parent=self)

    def _preview_current_album(self):
        if not self._current_path:
            return
        try:
            recursive = FL.has_image_subdirs(self._current_path)
            images = FL.list_images_in_dir(self._current_path, recursive=recursive)
            if not images:
                InfoBar.warning("提示", "当前目录没有可预览的图片", parent=self)
                return
            ImageGalleryDialog(images, 0, os.path.basename(self._current_path), self).exec_()
        except Exception:
            InfoBar.error("预览失败", "无法加载画册", parent=self)

    # ── 下载目录轮询 ──
    def _setup_root_watcher(self):
        self._last_root = FL.get_download_root()
        self._root_watch_timer = QTimer(self)
        self._root_watch_timer.setInterval(2000)
        self._root_watch_timer.timeout.connect(self._check_root_changed)
        self._root_watch_timer.start()

    def _check_root_changed(self):
        current = FL.get_download_root()
        if current != self._last_root:
            self._last_root = current
            self.goto_root()
            InfoBar.info("下载目录已切换", current, orient=Qt.Horizontal,
                         isClosable=True, position=InfoBarPosition.TOP,
                         duration=3000, parent=self)

    def _open_root_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(FL.get_download_root()))