# -*- coding: utf-8 -*-
"""
视频平台离线/在线媒体查看器（OGC 集成版）
==========================================
供 Xvideo / 推特 / 抖音 / 哔哩哔哩 / Pixiv 等平台复用。

功能：
1. **离线查看**：左侧边栏列出 {下载根}/{platform}-download 下的所有
   图片/视频文件（按类型分组），点击后在右侧查看图片或播放视频；
   支持按名称 / 下载时间排序，可删除选中的本地文件。
2. **在线阅读**：粘贴链接 → 解析（get_parser）→ 直接播放 / 查看，
   无需先下载；图片走 requests 后台线程加载，视频走 QMediaPlayer。

说明：
- 视频播放依赖 QtMultimedia（QMediaPlayer + QVideoWidget）。
- 图片与视频分开：边栏以「图片」「视频」两个分组展示，右侧按类型切换
  图片查看器 / 视频播放器。
"""
from __future__ import annotations

import os
import threading
from typing import List, Optional

from PyQt5.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    Dialog,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from services import download_manager as _dlm
from services.platform_parsers import get_parser
from ui.widgets.theme import text_primary, text_secondary, text_tertiary

try:
    from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
    from PyQt5.QtMultimediaWidgets import QVideoWidget
    QT_MULTIMEDIA_AVAILABLE = True
except ImportError:
    QT_MULTIMEDIA_AVAILABLE = False

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')
VIDEO_EXTS = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.m4v', '.ts')

# 文件列表通用样式：选中项文字用暗红色（#8B0000 = darkred）
_LIST_QSS = (
    "QListWidget { border: 1px solid rgba(128,128,128,0.2); border-radius: 8px;"
    " background: rgba(128,128,128,0.06); }"
    " QListWidget::item:selected { color: #8B0000; }"
)


def _kind_of(name: str) -> str:
    low = name.lower()
    if low.endswith(IMAGE_EXTS):
        return 'image'
    if low.endswith(VIDEO_EXTS):
        return 'video'
    return ''


# ═══════════════════════════════════════════
#  远程图片后台加载线程（requests，规避 Qt TLS 问题）
# ═══════════════════════════════════════════
class RemoteImageThread(QThread):
    loaded = pyqtSignal(bytes)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            import requests
            resp = requests.get(self.url, timeout=20)
            if resp.status_code == 200 and resp.content:
                self.loaded.emit(resp.content)
        except Exception:
            pass


# ═══════════════════════════════════════════
#  媒体查看器
# ═══════════════════════════════════════════
class MediaOfflineViewer(QWidget):
    """平台离线/在线媒体查看器。"""

    back_requested = pyqtSignal()
    bar = pyqtSignal(str, str)      # (level, message) 跨线程提示

    def __init__(self, platform: str, display_name: str, parent=None):
        super().__init__(parent)
        self.platform = platform
        self.display_name = display_name
        self._offline_entries: List[dict] = []   # {label, source, kind, is_local}
        self._online_entries: List[dict] = []
        self._current: Optional[dict] = None
        self._sort_key = 'name'                  # 'name' | 'time_desc'
        self._image_thread: Optional[RemoteImageThread] = None
        self._image_threads: List[RemoteImageThread] = []  # 存活引用，避免运行中被 GC
        self._player: Optional[QMediaPlayer] = None
        self.bar.connect(self._on_bar)
        self._build_ui()
        # 延迟加载：首次显示时才扫描本地下载目录（避开启动阶段的目录遍历）
        self._lazy_scanned = False

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def showEvent(self, event):
        """首次显示时扫描本地下载目录（延迟加载）。"""
        super().showEvent(event)
        if not getattr(self, '_lazy_scanned', False):
            self._lazy_scanned = True
            try:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, self.refresh_offline)
            except Exception:
                pass

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(10)

        # ---- 顶部栏 ----
        top = QHBoxLayout()
        top.setSpacing(10)
        self.back_btn = PushButton("← 返回", self)
        self.back_btn.clicked.connect(self.back_requested.emit)
        top.addWidget(self.back_btn)

        self.title_label = StrongBodyLabel(f"{self.display_name} · 媒体查看", self)
        self.title_label.setStyleSheet(f"color: {text_primary()}; font-size: 15px;")
        top.addWidget(self.title_label)
        top.addStretch(1)

        # 排序
        self.sort_combo = ComboBox(self)
        self.sort_combo.addItems(['名称排序', '下载时间（新→旧）'])
        self.sort_combo.setFixedWidth(150)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        top.addWidget(self.sort_combo)

        self.refresh_btn = PushButton(FluentIcon.SYNC, "刷新", self)
        self.refresh_btn.clicked.connect(self.refresh_offline)
        top.addWidget(self.refresh_btn)

        self.delete_btn = PushButton(FluentIcon.DELETE, "删除选中", self)
        self.delete_btn.clicked.connect(self._delete_current)
        top.addWidget(self.delete_btn)
        root.addLayout(top)

        # ---- 在线阅读输入行 ----
        online_row = QHBoxLayout()
        online_row.setSpacing(10)
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText(
            f'粘贴 {self.display_name} 链接，直接解析并播放 / 查看（无需下载）')
        self.url_edit.returnPressed.connect(self._parse_online)
        online_row.addWidget(self.url_edit, 1)
        self.parse_btn = PrimaryPushButton(FluentIcon.SYNC, "在线阅读", self)
        self.parse_btn.clicked.connect(self._parse_online)
        online_row.addWidget(self.parse_btn)
        root.addLayout(online_row)

        # ---- 主体：左侧文件列表 + 右侧查看区 ----
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        # 左侧边栏（图片 / 视频 两个独立列表，不再混在一个列表里）
        left_panel = QWidget(splitter)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        img_title = CaptionLabel("🖼 图片", left_panel)
        img_title.setStyleSheet(f"color: {text_tertiary()};")
        left_layout.addWidget(img_title)
        self.image_list = QListWidget(left_panel)
        self.image_list.setMinimumWidth(240)
        self.image_list.setMinimumHeight(120)
        self.image_list.itemClicked.connect(self._on_item_clicked)
        self.image_list.setStyleSheet(_LIST_QSS)
        left_layout.addWidget(self.image_list, 1)

        vid_title = CaptionLabel("🎬 视频", left_panel)
        vid_title.setStyleSheet(f"color: {text_tertiary()};")
        left_layout.addWidget(vid_title)
        self.video_list = QListWidget(left_panel)
        self.video_list.setMinimumWidth(240)
        self.video_list.setMinimumHeight(120)
        self.video_list.itemClicked.connect(self._on_item_clicked)
        self.video_list.setStyleSheet(_LIST_QSS)
        left_layout.addWidget(self.video_list, 1)

        splitter.addWidget(left_panel)

        # 右侧查看区
        self.view_stack = QStackedWidget(splitter)
        self.empty_label = QLabel("请选择左侧文件，或粘贴链接在线阅读。", self)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {text_secondary()};")
        self.view_stack.addWidget(self.empty_label)          # index 0

        # 图片查看器
        img_scroll = QScrollArea(self)
        img_scroll.setWidgetResizable(True)
        img_scroll.setFrameShape(img_scroll.NoFrame)
        img_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.image_label = QLabel("", self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background: transparent;")
        img_scroll.setWidget(self.image_label)
        self.view_stack.addWidget(img_scroll)                # index 1

        # 视频播放器（延迟初始化）
        # QVideoWidget / QMediaPlayer 是原生控件。主窗口为"透明无边框 + 磨砂"，
        # 若在启动时就为 6 个平台页各自创建一份原生视频控件，会干扰 Windows DWM
        # 合成，导致首页整体出现"重影/双份渲染"。因此改为首次真正播放视频时才创建。
        video_panel = QWidget(self)
        video_layout = QVBoxLayout(video_panel)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(8)
        self.video_surface = None
        self._video_panel = video_panel
        self._video_layout = video_layout
        self._video_placeholder = QLabel(
            "选择左侧视频，或粘贴链接后点击「播放」。", video_panel)
        self._video_placeholder.setAlignment(Qt.AlignCenter)
        self._video_placeholder.setStyleSheet(f"color: {text_secondary()};")
        video_layout.addWidget(self._video_placeholder, 1)

        # 播放控制条
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.play_btn = PushButton(FluentIcon.PLAY, "播放", video_panel)
        self.play_btn.clicked.connect(self._toggle_play)
        ctrl.addWidget(self.play_btn)
        self.stop_btn = PushButton(FluentIcon.CANCEL, "停止", video_panel)
        self.stop_btn.clicked.connect(self._stop_video)
        ctrl.addWidget(self.stop_btn)
        self.pos_slider = QSlider(Qt.Horizontal, video_panel)
        self.pos_slider.setRange(0, 1000)
        self.pos_slider.sliderMoved.connect(self._seek_video)
        ctrl.addWidget(self.pos_slider, 1)
        self.time_label = CaptionLabel("00:00 / 00:00", video_panel)
        self.time_label.setStyleSheet(f"color: {text_tertiary()};")
        ctrl.addWidget(self.time_label)
        video_layout.addLayout(ctrl)
        self.view_stack.addWidget(video_panel)               # index 2

        splitter.addWidget(self.view_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 760])
        root.addWidget(splitter, 1)

        # 播放器延迟初始化：_ensure_video_surface() 在首次播放时才创建。
        self._player = None

    # ------------------------------------------------------------------
    # 离线扫描
    # ------------------------------------------------------------------
    def _platform_root(self) -> str:
        try:
            return os.path.join(_dlm.get_download_root(), f'{self.platform}-download')
        except Exception:
            return os.path.join('data', f'{self.platform}-download')

    def refresh_offline(self):
        """重新扫描本地下载目录。"""
        self._offline_entries = self._scan_offline()
        self._rebuild_list()

    def _scan_offline(self) -> List[dict]:
        entries: List[dict] = []
        root = self._platform_root()
        if not os.path.isdir(root):
            return entries
        try:
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    if name.startswith('.') or name.endswith('.part'):
                        continue
                    full = os.path.join(dirpath, name)
                    kind = _kind_of(name)
                    if not kind:
                        continue
                    rel = os.path.relpath(full, root)
                    entries.append({
                        'label': rel.replace('\\', '/'),
                        'source': full,
                        'kind': kind,
                        'is_local': True,
                        'mtime': os.path.getmtime(full),
                    })
        except Exception:
            pass
        return entries

    # ------------------------------------------------------------------
    # 在线阅读解析
    # ------------------------------------------------------------------
    def _parse_online(self):
        url = self.url_edit.text().strip()
        if not url:
            InfoBar.warning(
                title="提示", content="请输入链接",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=2000, parent=self,
            )
            return
        self.parse_btn.setEnabled(False)
        self.parse_btn.setText("解析中…")
        threading.Thread(target=self._parse_online_worker, args=(url,), daemon=True).start()

    def _parse_online_worker(self, url: str):
        try:
            parser = get_parser(self.platform)
            if parser is None:
                raise RuntimeError(f"不支持的平台：{self.platform}")
            items = parser.parse(url)
            entries = []
            for item in items or []:
                kind = _dlm.infer_file_type(
                    getattr(item, 'url', ''),
                    getattr(item, 'media_type', ''),
                    getattr(item, 'title', ''),
                )
                if kind not in ('image', 'video'):
                    kind = _kind_of(getattr(item, 'url', '')) or 'video'
                title = getattr(item, 'title', '') or getattr(item, 'url', '')
                entries.append({
                    'label': title[:60],
                    'source': getattr(item, 'url', ''),
                    'kind': kind,
                    'is_local': False,
                    'mtime': 0,
                })
            self._online_entries = entries
            self._rebuild_list()
            msg = f"解析到 {len(entries)} 个媒体" if entries else "未解析到媒体"
            self.bar.emit('success' if entries else 'warning', msg)
        except Exception as e:
            self.bar.emit('error', f"解析失败：{e}")
        finally:
            self.parse_btn.setEnabled(True)
            self.parse_btn.setText("在线阅读")

    def _on_bar(self, level: str, msg: str):
        """跨线程提示（bar 信号在主线程槽中执行）。"""
        kw = dict(
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=3000, parent=self,
        )
        if level == 'success':
            InfoBar.success(title="完成", content=msg, **kw)
        elif level == 'error':
            InfoBar.error(title="错误", content=msg, **kw)
        else:
            InfoBar.warning(title="提示", content=msg, **kw)

    # ------------------------------------------------------------------
    # 列表构建
    # ------------------------------------------------------------------
    def _on_sort_changed(self, index: int):
        """切换排序方式（名称 / 下载时间）。"""
        self._sort_key = 'time_desc' if index == 1 else 'name'
        self._rebuild_list()

    def _rebuild_list(self):
        entries = list(self._offline_entries) + list(self._online_entries)
        if self._sort_key == 'time_desc':
            entries.sort(key=lambda e: e.get('mtime', 0), reverse=True)
        else:
            entries.sort(key=lambda e: e['label'].lower())

        for lst in (self.image_list, self.video_list):
            lst.blockSignals(True)
            lst.clear()
            lst.blockSignals(False)

        for e in entries:
            if e['kind'] == 'image':
                self._add_entry_item(self.image_list, e)
            else:
                # 视频/其他 统一进视频列表（本查看器仅支持图片与视频浏览）
                self._add_entry_item(self.video_list, e)

    def _add_entry_item(self, lst: QListWidget, entry: dict):
        item = QListWidgetItem(entry['label'])
        item.setData(Qt.UserRole, entry)
        if not entry['is_local']:
            item.setToolTip("在线媒体（点击直接播放/查看）")
        lst.addItem(item)

    # ------------------------------------------------------------------
    # 选择与查看
    # ------------------------------------------------------------------
    def _on_item_clicked(self, item: QListWidgetItem):
        entry = item.data(Qt.UserRole)
        if not entry:
            return
        self._current = entry
        self._stop_video()
        if entry['kind'] == 'image':
            self.view_stack.setCurrentIndex(1)
            self._load_image(entry)
        elif entry['kind'] == 'video':
            self.view_stack.setCurrentIndex(2)
            self._load_video(entry)
        else:
            self.view_stack.setCurrentIndex(0)

    def _load_image(self, entry: dict):
        self.image_label.setText("加载中…")
        self.image_label.setPixmap(QPixmap())
        if entry['is_local']:
            self._show_local_image(entry['source'])
        else:
            thread = RemoteImageThread(entry['source'], self)
            self._image_threads.append(thread)   # 保持引用，防止运行中被 GC
            thread.loaded.connect(lambda data, src=entry['source']: self._on_remote_image(data, src))
            thread.finished.connect(lambda t=thread: self._thread_done(t))
            thread.start()

    def _thread_done(self, thread: RemoteImageThread):
        """线程结束后移除引用并销毁（避免 QThread: Destroyed while running）。"""
        try:
            if thread in self._image_threads:
                self._image_threads.remove(thread)
            thread.deleteLater()
        except Exception:
            pass

    def _show_local_image(self, path: str):
        pix = QPixmap(path)
        if pix.isNull():
            self.image_label.setText("图片加载失败")
            return
        self._fit_image(pix)

    def _on_remote_image(self, data: bytes, src: str = ''):
        # 忽略过期请求的结果（用户已切换其他条目）
        cur = self._current or {}
        if src and cur.get('source') and src != cur.get('source'):
            return
        pix = QPixmap()
        if not pix.loadFromData(data):
            self.image_label.setText("图片加载失败")
            return
        self._fit_image(pix)

    def _fit_image(self, pix: QPixmap):
        try:
            area = self.image_label.size()
            scaled = pix.scaled(
                area.width() or 800, area.height() or 600,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled)
        except Exception:
            self.image_label.setPixmap(pix)

    def _ensure_video_surface(self):
        """首次播放视频时才创建原生播放控件，避免启动即建造成重影。"""
        if self._player is not None or not QT_MULTIMEDIA_AVAILABLE:
            return
        try:
            self.video_surface = QVideoWidget(self._video_panel)
            self.video_surface.setStyleSheet("background: black;")
            self.video_surface.setMinimumHeight(320)
            idx = self._video_layout.indexOf(self._video_placeholder)
            if idx >= 0:
                self._video_layout.removeWidget(self._video_placeholder)
                self._video_placeholder.deleteLater()
                self._video_placeholder = None
            self._video_layout.insertWidget(0, self.video_surface, 1)
            self._player = QMediaPlayer(self)
            self._player.setVideoOutput(self.video_surface)
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)
            self._player.stateChanged.connect(self._on_state_changed)
            self._player.mediaStatusChanged.connect(self._on_media_status)
        except Exception:
            self._player = None
            self.video_surface = None

    def _load_video(self, entry: dict):
        if not QT_MULTIMEDIA_AVAILABLE:
            return
        self._ensure_video_surface()
        if self._player is None:
            return
        if entry['is_local']:
            media = QMediaContent(QUrl.fromLocalFile(entry['source']))
        else:
            media = QMediaContent(QUrl(entry['source']))
        self._player.setMedia(media)
        self._player.play()
        self._sync_play_btn()

    def _toggle_play(self):
        if self._player is None:
            return
        if self._player.state() == QMediaPlayer.State.PlayingState:
            self._player.pause()
        else:
            self._player.play()
        self._sync_play_btn()

    def _stop_video(self):
        if self._player is not None:
            self._player.stop()
            # 释放当前媒体源，否则 DirectShow/QMediaPlayer 会一直占用文件句柄，
            # 导致「删除本地视频」报 PermissionError: WinError 32。
            try:
                self._player.setMedia(QMediaContent())
            except Exception:
                pass
            self.pos_slider.setValue(0)
            self.time_label.setText("00:00 / 00:00")
        self._sync_play_btn()

    def _sync_play_btn(self):
        if self._player is None:
            return
        playing = self._player.state() == QMediaPlayer.State.PlayingState
        self.play_btn.setText("暂停" if playing else "播放")
        self.play_btn.setIcon(FluentIcon.PAUSE if playing else FluentIcon.PLAY)

    def _on_position_changed(self, pos: int):
        dur = self._player.duration() if self._player else 0
        if dur > 0:
            self.pos_slider.setValue(int(pos * 1000 / dur))
        self.time_label.setText(f"{_fmt_ms(pos)} / {_fmt_ms(dur)}")

    def _on_duration_changed(self, dur: int):
        self.time_label.setText(f"00:00 / {_fmt_ms(dur)}")

    def _on_state_changed(self, state):
        self._sync_play_btn()

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._sync_play_btn()

    def _seek_video(self, value: int):
        if self._player is None:
            return
        dur = self._player.duration()
        if dur > 0:
            self._player.setPosition(int(value * dur / 1000))

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------
    def pause(self):
        """离开播放页面时暂停视频（不销毁播放器，回到页面可继续）。"""
        self._stop_video()

    def shutdown(self):
        """安全回收：停止视频播放、清理图片线程（运行中的等其结束再销毁）。"""
        self._stop_video()
        for t in list(self._image_threads):
            try:
                if t.isRunning():
                    t.requestInterruption()
                    # 结束时再销毁，避免 QThread: Destroyed while running
                    t.finished.connect(lambda th=t: th.deleteLater())
                else:
                    t.deleteLater()
            except Exception:
                pass
        self._image_threads.clear()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _delete_current(self):
        entry = self._current
        if entry is None or not entry['is_local']:
            InfoBar.warning(
                title="提示", content="请先在左侧选中一个本地文件",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=2500, parent=self,
            )
            return
        w = Dialog(
            '确认删除',
            f'确定要删除「{entry["label"]}」吗？\n路径：{entry["source"]}\n此操作不可恢复！',
            self.window(),
        )
        w.yesButton.setText('确认删除')
        w.cancelButton.setText('取消')
        if not w.exec():
            return
        # 先停止播放并释放媒体源，否则 QMediaPlayer 占用文件句柄导致删除失败
        self._stop_video()
        try:
            if os.path.isfile(entry['source']):
                os.remove(entry['source'])
        except Exception as e:
            InfoBar.error(
                title="删除失败", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT, duration=4000, parent=self,
            )
            return
        self._current = None
        self.view_stack.setCurrentIndex(0)
        self.refresh_offline()
        InfoBar.success(
            title="已删除", content=f"「{entry['label']}」已删除",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2000, parent=self,
        )


def _fmt_ms(ms: int) -> str:
    try:
        ms = int(ms or 0)
        s = ms // 1000
        return f"{s // 60:02d}:{s % 60:02d}"
    except Exception:
        return "00:00"
