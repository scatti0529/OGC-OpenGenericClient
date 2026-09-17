"""
音乐播放器 UI - 底部播放栏 + 播放页面 + 播放列表面板
仿网易云音乐风格
"""
import os
import re
import requests
from pathlib import Path
from io import BytesIO

from PyQt5.QtCore import Qt, QUrl, QSize, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap, QIcon, QFont, QPainter, QColor, QLinearGradient, QBrush, QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QFrame, QApplication, QListWidget, QListWidgetItem, QAbstractItemView,
    QMenu, QAction, QStackedWidget, QSizePolicy, QSplitter, QTextEdit,
    QScrollArea, QToolButton
)

from qfluentwidgets import (
    FluentIcon, PushButton, ToolButton, TransparentToolButton,
    BodyLabel, CaptionLabel, StrongBodyLabel, TitleLabel,
    Slider, ProgressBar, InfoBar,
    SimpleCardWidget, ScrollArea, PrimaryPushButton,
    HorizontalFlipView, ImageLabel,
    isDarkTheme
)
from ui.widgets.common import log_manager, CFG
from pages.music.music_player_engine import MusicPlayerEngine, PlayMode, PlayState, PlaylistItem
from ui.widgets.ui_utils import install_hover_tip


# ============================================================
# 工具函数
# ============================================================
def load_image_from_url(url: str, size=(60, 60)) -> QPixmap:
    """从URL加载图片"""
    pix = QPixmap()
    if not url:
        return pix
    try:
        if url.startswith('http'):
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                pix.loadFromData(resp.content)
        elif os.path.exists(url):
            pix.load(url)
        if not pix.isNull():
            pix = pix.scaled(size[0], size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        pass
    return pix


class CoverLoader:
    """封面图片加载缓存"""
    _cache = {}

    @classmethod
    def get(cls, url: str, size=(60, 60)) -> QPixmap:
        if url in cls._cache:
            return cls._cache[url]
        pix = load_image_from_url(url, size)
        if not pix.isNull():
            cls._cache[url] = pix
        return pix


# ============================================================
# 播放列表面板（向上弹、限高、每行有删除按钮）
# ============================================================
class PlaylistPanel(QWidget):
    """播放列表面板"""
    playRequested = pyqtSignal(int)
    removeRequested = pyqtSignal(int)
    moveRequested = pyqtSignal(int, int)
    clearRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('playlistPanel')
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setFixedSize(440, 320)
        self._setup_ui()

    def _setup_ui(self):
        # 背景图路径（统一资源路径管理）
        from core.resource_paths import MUSIC_PLAYER_BG
        bg_path = MUSIC_PLAYER_BG
        bg_style = ""
        if os.path.exists(bg_path):
            bg_style = f"border-image: url({bg_path.replace(chr(92), '/')});"
        self.setStyleSheet(f"""
            PlaylistPanel {{
                {bg_style}
                border-radius: 12px;
                border: 1px solid rgba(128,128,128,0.2);
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 标题栏
        header = QHBoxLayout()
        title = StrongBodyLabel('播放列表', self)
        header.addWidget(title)
        header.addStretch()
        self.count_label = CaptionLabel('0 首', self)
        header.addWidget(self.count_label)
        layout.addLayout(header)

        # 列表（滚动区域限定显示5首）
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(240)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.MoveAction)
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setStyleSheet("""
            QListWidget{background:transparent;border:none;font-size:13px;}
            QListWidget::item{padding:4px 6px;border-radius:4px;min-height:36px;}
            QListWidget::item:hover{background:rgba(128,128,128,0.1);}
            QListWidget::item:selected{background:rgba(0,120,215,0.3);}
        """)
        scroll.setWidget(self.list_widget)
        layout.addWidget(scroll)

        # 底部按钮
        btn_layout = QHBoxLayout()
        self.clear_btn = ToolButton(FluentIcon.DELETE, self)
        self.clear_btn.setToolTip('清空列表')
        self.clear_btn.clicked.connect(self.clearRequested.emit)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def update_list(self, items: list, current_idx: int):
        """更新播放列表"""
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for i, item in enumerate(items):
            # 行容器
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(6)

            # 序号+歌名
            text = f"{i+1}. {item.song_name}"
            if item.singers:
                text += f"  -  {item.singers}"
            label = QLabel(text)
            label.setStyleSheet("background:transparent;")
            if i == current_idx:
                label.setStyleSheet("color:#28afe9;font-weight:bold;background:transparent;")
            row_layout.addWidget(label, 1)

            # 删除按钮
            del_btn = QToolButton()
            del_btn.setText("✕")
            del_btn.setFixedSize(22, 22)
            del_btn.setStyleSheet("""
                QToolButton{background:transparent;border:none;color:#999;font-size:13px;}
                QToolButton:hover{color:red;}
            """)
            row_idx = i
            del_btn.clicked.connect(lambda checked, idx=row_idx: self.removeRequested.emit(idx))
            row_layout.addWidget(del_btn)

            list_item = QListWidgetItem()
            list_item.setSizeHint(row_widget.sizeHint())
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, row_widget)

        self.list_widget.blockSignals(False)
        self.count_label.setText(f'{len(items)} 首')

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        row = self.list_widget.row(item)
        menu = QMenu(self)
        play_action = menu.addAction('▶ 播放')
        delete_action = menu.addAction('✕ 删除')
        menu.addSeparator()
        clear_action = menu.addAction('清空列表')
        action = menu.exec_(self.list_widget.mapToGlobal(pos))
        if action == play_action:
            self.playRequested.emit(row)
        elif action == delete_action:
            self.removeRequested.emit(row)
        elif action == clear_action:
            self.clearRequested.emit()

    def _on_rows_moved(self, *args):
        parent, start, end, dest, row = args
        self.moveRequested.emit(start, row)

    def _on_item_double_clicked(self, item):
        row = self.list_widget.row(item)
        self.playRequested.emit(row)


# ============================================================
# 底部播放栏（跟随主题）
# ============================================================
class BottomPlayBar(QFrame):
    """底部迷你播放栏"""
    showPlaylistRequested = pyqtSignal()
    showPlayerPageRequested = pyqtSignal()

    def __init__(self, engine: MusicPlayerEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setObjectName('bottomPlayBar')
        self.setFixedHeight(68)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(12)

        # 左侧：封面
        self.cover_label = QLabel(self)
        self.cover_label.setFixedSize(52, 52)
        self.cover_label.setStyleSheet("border-radius:4px;")
        pix = QPixmap(52, 52)
        pix.fill(QColor(60, 60, 60))
        self.cover_label.setPixmap(pix)
        layout.addWidget(self.cover_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        self.song_name_label = StrongBodyLabel('未在播放', self)
        self.artist_label = CaptionLabel('', self)
        info_layout.addWidget(self.song_name_label)
        info_layout.addWidget(self.artist_label)
        layout.addLayout(info_layout)
        layout.addStretch(1)

        # 控制按钮
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)

        self.prev_btn = TransparentToolButton(FluentIcon.LEFT_ARROW, self)
        self.prev_btn.setIconSize(QSize(20, 20))
        self.prev_btn.setFixedSize(32, 32)
        self.prev_btn.clicked.connect(self.engine.play_prev)
        ctrl_layout.addWidget(self.prev_btn)

        self.play_btn = TransparentToolButton(FluentIcon.PLAY, self)
        self.play_btn.setIconSize(QSize(28, 28))
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.clicked.connect(self.engine.play_pause_toggle)
        ctrl_layout.addWidget(self.play_btn)

        self.next_btn = TransparentToolButton(FluentIcon.RIGHT_ARROW, self)
        self.next_btn.setIconSize(QSize(20, 20))
        self.next_btn.setFixedSize(32, 32)
        self.next_btn.clicked.connect(self.engine.play_next)
        ctrl_layout.addWidget(self.next_btn)
        layout.addLayout(ctrl_layout)
        layout.addStretch(1)

        # 进度
        self.time_label = CaptionLabel('00:00', self)
        layout.addWidget(self.time_label)
        self.progress_slider = Slider(Qt.Horizontal, self)
        self.progress_slider.setFixedWidth(180)
        self.progress_slider.setRange(0, 100)
        self.progress_slider.sliderMoved.connect(self._on_slider_moved)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)
        layout.addWidget(self.progress_slider)
        self.duration_label = CaptionLabel('00:00', self)
        layout.addWidget(self.duration_label)

        # 模式+播放列表按钮
        self.mode_btn = TransparentToolButton(FluentIcon.SYNC, self)
        self.mode_btn.setIconSize(QSize(18, 18))
        self.mode_btn.setFixedSize(32, 32)
        self.mode_btn.clicked.connect(self.engine.cycle_play_mode)
        layout.addWidget(self.mode_btn)

        self.playlist_btn = TransparentToolButton(FluentIcon.MENU, self)
        self.playlist_btn.setIconSize(QSize(18, 18))
        self.playlist_btn.setFixedSize(32, 32)
        self.playlist_btn.clicked.connect(self.showPlaylistRequested.emit)
        layout.addWidget(self.playlist_btn)

        # 引擎信号
        self.engine.positionChanged.connect(self._on_position_changed)
        self.engine.stateChanged.connect(self._on_state_changed)
        self.engine.songChanged.connect(self._on_song_changed)
        self.engine.modeChanged.connect(self._on_mode_changed)

        # 播放条按钮悬停提示
        install_hover_tip(self.prev_btn, '上一首', '播放列表中的上一首歌曲')
        install_hover_tip(self.play_btn, '播放/暂停', '播放或暂停当前歌曲')
        install_hover_tip(self.next_btn, '下一首', '播放列表中的下一首歌曲')
        install_hover_tip(self.mode_btn, '播放模式', '切换顺序/单曲循环/列表循环/随机')
        install_hover_tip(self.playlist_btn, '播放列表', '展开/收起播放列表面板')
        install_hover_tip(self.progress_slider, '播放进度', '拖动跳转到歌曲任意位置')

        self._is_dragging = False

        # 最后设置主题样式（所有控件必须在之前创建好）
        self._update_theme_style()

    def _update_theme_style(self):
        """根据深浅主题更新样式"""
        dark = isDarkTheme()
        if dark:
            self.setStyleSheet("""
                BottomPlayBar{background:rgba(40,40,40,0.95);border-top:1px solid rgba(255,255,255,0.08);}
            """)
            self.song_name_label.setStyleSheet("color:white;font-size:13px;")
            self.artist_label.setStyleSheet("color:#aaa;font-size:11px;")
            self.time_label.setStyleSheet("color:#aaa;font-size:11px;")
            self.duration_label.setStyleSheet("color:#aaa;font-size:11px;")
        else:
            self.setStyleSheet("""
                BottomPlayBar{background:rgba(245,245,245,0.95);border-top:1px solid rgba(0,0,0,0.1);}
            """)
            self.song_name_label.setStyleSheet("color:#333;font-size:13px;")
            self.artist_label.setStyleSheet("color:#888;font-size:11px;")
            self.time_label.setStyleSheet("color:#888;font-size:11px;")
            self.duration_label.setStyleSheet("color:#888;font-size:11px;")

    def _on_position_changed(self, pos_ms: int, dur_ms: int):
        if self._is_dragging:
            return
        if dur_ms > 0:
            self.progress_slider.setValue(int(pos_ms * 100 / dur_ms))
            self.time_label.setText(self.engine.format_time(pos_ms))
            self.duration_label.setText(self.engine.format_time(dur_ms))

    def _on_state_changed(self, state: PlayState):
        if state == PlayState.PLAYING:
            self.play_btn.setIcon(FluentIcon.PAUSE)
        else:
            self.play_btn.setIcon(FluentIcon.PLAY)

    def _on_song_changed(self, item: PlaylistItem):
        self.song_name_label.setText(item.song_name or '未知歌曲')
        self.artist_label.setText(item.singers or '')
        if item.cover_url:
            pix = CoverLoader.get(item.cover_url, (52, 52))
            if not pix.isNull():
                self.cover_label.setPixmap(pix)

    def _on_mode_changed(self, mode: PlayMode):
        icons = {PlayMode.ORDER: FluentIcon.SYNC, PlayMode.REPEAT_ONE: FluentIcon.RETURN,
                 PlayMode.REPEAT_ALL: FluentIcon.SYNC, PlayMode.SHUFFLE: FluentIcon.UPDATE}
        self.mode_btn.setIcon(icons.get(mode, FluentIcon.SYNC))

    def _on_slider_moved(self, value: int):
        self._is_dragging = True
        dur = self.engine._player.duration() if hasattr(self.engine, '_player') else 0
        self.time_label.setText(self.engine.format_time(int(dur * value / 100)))

    def _on_slider_released(self):
        self._is_dragging = False
        dur = self.engine._player.duration() if hasattr(self.engine, '_player') else 0
        self.engine.set_position(int(dur * self.progress_slider.value() / 100))


# ============================================================
# 播放页面（封面+歌词+完整控制）
# ============================================================
class PlayerPage(QWidget):
    """全屏播放页面，仿网易云音乐播放界面"""
    closeRequested = pyqtSignal()

    def __init__(self, engine: MusicPlayerEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setObjectName('playerPage')
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setStyleSheet("""
            PlayerPage{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1a1a2e,stop:0.5 #16213e,stop:1 #0f3460);}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(16, 12, 16, 12)
        self.back_btn = TransparentToolButton(FluentIcon.CHEVRON_DOWN_MED, self)
        self.back_btn.setFixedSize(40, 40)
        self.back_btn.clicked.connect(self.closeRequested.emit)
        toolbar.addWidget(self.back_btn)
        toolbar.addStretch()
        self.page_title = StrongBodyLabel('正在播放', self)
        self.page_title.setStyleSheet("color:white;font-size:16px;")
        toolbar.addWidget(self.page_title)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        center_layout = QHBoxLayout()
        center_layout.setContentsMargins(40, 10, 40, 10)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setAlignment(Qt.AlignCenter)
        self.big_cover = QLabel(self)
        self.big_cover.setFixedSize(320, 320)
        self.big_cover.setAlignment(Qt.AlignCenter)
        self.big_cover.setStyleSheet("border-radius:16px;background:rgba(255,255,255,0.05);")
        pix = QPixmap(320, 320)
        pix.fill(QColor(50, 50, 80))
        self.big_cover.setPixmap(pix)
        left_layout.addWidget(self.big_cover, 0, Qt.AlignCenter)
        self.page_song_name = TitleLabel('未在播放', left_widget)
        self.page_song_name.setStyleSheet("color:white;font-size:22px;")
        self.page_song_name.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.page_song_name)
        self.page_artist = BodyLabel('', left_widget)
        self.page_artist.setStyleSheet("color:#aaa;font-size:14px;")
        self.page_artist.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.page_artist)
        center_layout.addWidget(left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(20, 0, 0, 0)
        lyric_title = StrongBodyLabel('歌词', right_widget)
        lyric_title.setStyleSheet("color:#ddd;font-size:15px;")
        right_layout.addWidget(lyric_title)
        self.lyric_text = QTextEdit(right_widget)
        self.lyric_text.setReadOnly(True)
        self.lyric_text.setStyleSheet("QTextEdit{background:transparent;color:#bbb;font-size:14px;border:none;padding:10px;}")
        self.lyric_text.setPlaceholderText('暂无歌词')
        right_layout.addWidget(self.lyric_text)
        center_layout.addWidget(right_widget, 1)
        layout.addLayout(center_layout, 1)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(40, 8, 40, 16)

        progress_row = QHBoxLayout()
        self.page_time_label = CaptionLabel('00:00', bottom_widget)
        progress_row.addWidget(self.page_time_label)
        self.page_progress = Slider(Qt.Horizontal, bottom_widget)
        self.page_progress.setRange(0, 100)
        self.page_progress.sliderMoved.connect(self._on_page_slider_moved)
        self.page_progress.sliderReleased.connect(self._on_page_slider_released)
        progress_row.addWidget(self.page_progress)
        self.page_duration_label = CaptionLabel('00:00', bottom_widget)
        progress_row.addWidget(self.page_duration_label)
        bottom_layout.addLayout(progress_row)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(20)
        ctrl_row.setAlignment(Qt.AlignCenter)
        self.page_mode_btn = TransparentToolButton(FluentIcon.SYNC, bottom_widget)
        self.page_mode_btn.setIconSize(QSize(24, 24))
        self.page_mode_btn.setFixedSize(44, 44)
        self.page_mode_btn.clicked.connect(self.engine.cycle_play_mode)
        ctrl_row.addWidget(self.page_mode_btn)

        self.page_prev_btn = TransparentToolButton(FluentIcon.LEFT_ARROW, bottom_widget)
        self.page_prev_btn.setIconSize(QSize(28, 28))
        self.page_prev_btn.setFixedSize(48, 48)
        self.page_prev_btn.clicked.connect(self.engine.play_prev)
        ctrl_row.addWidget(self.page_prev_btn)

        self.page_play_btn = TransparentToolButton(FluentIcon.PLAY, bottom_widget)
        self.page_play_btn.setIconSize(QSize(36, 36))
        self.page_play_btn.setFixedSize(60, 60)
        self.page_play_btn.setStyleSheet("background:rgba(255,255,255,0.1);border-radius:30px;")
        self.page_play_btn.clicked.connect(self.engine.play_pause_toggle)
        ctrl_row.addWidget(self.page_play_btn)

        self.page_next_btn = TransparentToolButton(FluentIcon.RIGHT_ARROW, bottom_widget)
        self.page_next_btn.setIconSize(QSize(28, 28))
        self.page_next_btn.setFixedSize(48, 48)
        self.page_next_btn.clicked.connect(self.engine.play_next)
        ctrl_row.addWidget(self.page_next_btn)

        self.page_playlist_btn = TransparentToolButton(FluentIcon.MENU, bottom_widget)
        self.page_playlist_btn.setIconSize(QSize(24, 24))
        self.page_playlist_btn.setFixedSize(44, 44)
        self.page_playlist_btn.clicked.connect(self._show_playlist)
        ctrl_row.addWidget(self.page_playlist_btn)

        bottom_layout.addLayout(ctrl_row)
        layout.addWidget(bottom_widget)

    def _connect_signals(self):
        self.engine.positionChanged.connect(self._on_position_changed)
        self.engine.stateChanged.connect(self._on_state_changed)
        self.engine.songChanged.connect(self._on_song_changed)
        self.engine.modeChanged.connect(self._on_mode_changed)
        install_hover_tip(self.back_btn, '收起播放页', '返回音乐主界面')
        install_hover_tip(self.page_mode_btn, '播放模式', '切换顺序/单曲循环/列表循环/随机')
        install_hover_tip(self.page_prev_btn, '上一首', '播放上一首歌曲')
        install_hover_tip(self.page_play_btn, '播放/暂停', '播放或暂停当前歌曲')
        install_hover_tip(self.page_next_btn, '下一首', '播放下一首歌曲')
        install_hover_tip(self.page_playlist_btn, '播放列表', '查看当前播放列表')
        install_hover_tip(self.page_progress, '播放进度', '拖动跳转到歌曲任意位置')

    def _on_position_changed(self, pos_ms, dur_ms):
        if dur_ms > 0:
            self.page_progress.setValue(int(pos_ms * 100 / dur_ms))
            self.page_time_label.setText(self.engine.format_time(pos_ms))
            self.page_duration_label.setText(self.engine.format_time(dur_ms))

    def _on_state_changed(self, state):
        if state == PlayState.PLAYING:
            self.page_play_btn.setIcon(FluentIcon.PAUSE)
        else:
            self.page_play_btn.setIcon(FluentIcon.PLAY)

    def _on_song_changed(self, item):
        self.page_song_name.setText(item.song_name or '未知歌曲')
        self.page_artist.setText(item.singers or '')
        if item.cover_url:
            pix = CoverLoader.get(item.cover_url, (320, 320))
            if not pix.isNull():
                self.big_cover.setPixmap(pix)
        if item.lyric and item.lyric.strip():
            self.lyric_text.setText(item.lyric)
        else:
            self.lyric_text.setText('暂无歌词')

    def _on_mode_changed(self, mode):
        icons = {PlayMode.ORDER: FluentIcon.SYNC, PlayMode.REPEAT_ONE: FluentIcon.RETURN,
                 PlayMode.REPEAT_ALL: FluentIcon.SYNC, PlayMode.SHUFFLE: FluentIcon.UPDATE}
        self.page_mode_btn.setIcon(icons.get(mode, FluentIcon.SYNC))

    def _on_page_slider_moved(self, value):
        dur = self.engine._player.duration() if hasattr(self.engine, '_player') else 0
        self.page_time_label.setText(self.engine.format_time(int(dur * value / 100)))

    def _on_page_slider_released(self):
        dur = self.engine._player.duration() if hasattr(self.engine, '_player') else 0
        self.engine.set_position(int(dur * self.page_progress.value() / 100))

    def _show_playlist(self):
        InfoBar.info('提示', '点击底部播放栏的按钮查看', parent=self, duration=2000)
