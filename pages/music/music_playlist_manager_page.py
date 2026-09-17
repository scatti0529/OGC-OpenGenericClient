"""
播放列表管理器 - TreeView 显示所有播放列表及其歌曲
双击播放列表或歌曲切换当前播放列表并开始播放
"""
from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox, QInputDialog

from qfluentwidgets import BodyLabel, CaptionLabel, StrongBodyLabel, PushButton, PrimaryPushButton
from qfluentwidgets import FluentIcon, InfoBar, TransparentToolButton

from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem

from core.database import (get_all_playlists_with_song_count, get_songs_by_playlist,
                    create_playlist, delete_playlist,
                    add_song_to_db, clear_playlist_songs)
from pages.music.music_player_engine import PlaylistItem
from ui.widgets.ui_utils import install_hover_tip


class PlaylistManagerPage(QWidget):
    """播放列表管理页面"""
    # signals
    playPlaylistRequested = pyqtSignal(int, int)  # playlist_id, start_song_index
    saveCurrentRequested = pyqtSignal(int)  # playlist_id

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setObjectName('playlistManagerPage')
        self._setup_ui()
        # 延迟加载：首次显示时才查询数据库刷新播放列表（避开启动阶段查询）
        self._lazy_refreshed = False

    def showEvent(self, event):
        """首次显示时刷新播放列表（延迟加载）。"""
        super().showEvent(event)
        if not getattr(self, '_lazy_refreshed', False):
            self._lazy_refreshed = True
            try:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, self._refresh)
            except Exception:
                pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(12)

        # 标题栏
        header = QHBoxLayout()
        title = StrongBodyLabel('📂 播放列表管理', self)
        header.addWidget(title)
        header.addStretch()
        self.refresh_btn = PushButton(FluentIcon.SYNC, '刷新')
        self.refresh_btn.clicked.connect(self._refresh)
        header.addWidget(self.refresh_btn)
        self.new_btn = PrimaryPushButton(FluentIcon.ADD, '新建列表')
        self.new_btn.clicked.connect(self._new_playlist)
        header.addWidget(self.new_btn)
        layout.addLayout(header)

        # QTreeWidget
        self.tree = QTreeWidget(self)
        self.tree.setStyleSheet("QTreeWidget{border:1px solid rgba(128,128,128,0.3);border-radius:8px;}")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(['名称', '信息', ''])
        self.tree.setColumnWidth(0, 350)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 60)
        self.tree.setEditTriggers(self.tree.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree, 1)

        # 底部操作
        btn_row = QHBoxLayout()
        self.save_btn = PushButton(FluentIcon.SAVE, '保存当前列表')
        self.save_btn.clicked.connect(self._save_current)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch()
        self.delete_playlist_btn = PushButton(FluentIcon.DELETE, '删除选中列表')
        self.delete_playlist_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.delete_playlist_btn)
        layout.addLayout(btn_row)

        # ── 悬停功能简介 ──
        install_hover_tip(self.refresh_btn, '刷新', '重新加载所有播放列表及其歌曲')
        install_hover_tip(self.new_btn, '新建列表', '创建一个新的空播放列表')
        install_hover_tip(self.tree, '播放列表树', '双击播放列表或歌曲进行播放')
        install_hover_tip(self.save_btn, '保存当前列表', '将当前正在播放的列表保存到数据库')
        install_hover_tip(self.delete_playlist_btn, '删除选中列表', '删除选中的播放列表及其歌曲')

    def _refresh(self):
        """刷新 QTreeWidget"""
        self.tree.clear()
        playlists = get_all_playlists_with_song_count()
        for pl in playlists:
            pid = pl['id']
            pl_item = QTreeWidgetItem(
                [f'📁 {pl["name"]}', f'{pl["song_count"]} 首', ''],
                type=0
            )
            pl_item.setData(0, Qt.UserRole, pid)  # playlist_id
            pl_item.setData(2, Qt.UserRole, 'playlist')

            # 加载歌曲子项
            songs = get_songs_by_playlist(pid)
            for song in songs:
                s_text = f'🎵 {song["song_name"]}'
                if song.get('singers'):
                    s_text += f'  -  {song["singers"]}'
                s_item = QTreeWidgetItem(
                    [s_text, song.get('duration', ''), ''],
                    type=0
                )
                s_item.setData(0, Qt.UserRole, song['id'])  # song_id
                s_item.setData(2, Qt.UserRole, 'song')
                pl_item.addChild(s_item)
            self.tree.addTopLevelItem(pl_item)
            pl_item.setExpanded(True)

    def _on_item_double_clicked(self, item, column):
        """双击播放列表或歌曲"""
        if not isinstance(item, QTreeWidgetItem):
            return
        data_type = item.data(2, Qt.UserRole)
        if data_type == 'playlist':
            pid = item.data(0, Qt.UserRole)
            self._load_and_play(pid, 0)
        elif data_type == 'song':
            parent_item = item.parent()
            if parent_item:
                pid = parent_item.data(0, Qt.UserRole)
                song_id = item.data(0, Qt.UserRole)
                songs = get_songs_by_playlist(pid)
                start_idx = 0
                for i, s in enumerate(songs):
                    if s['id'] == song_id:
                        start_idx = i
                        break
                self._load_and_play(pid, start_idx)

    def _load_and_play(self, playlist_id: int, start_idx: int = 0):
        """加载播放列表并播放"""
        songs = get_songs_by_playlist(playlist_id)
        if not songs:
            return
        items = []
        for s in songs:
            items.append(PlaylistItem(
                song_name=s.get('song_name',''),
                singers=s.get('singers',''),
                album=s.get('album',''),
                duration=s.get('duration',''),
                download_url=s.get('download_url',''),
                quality=s.get('quality',''),
                identifier=s.get('identifier',''),
                cover_url=s.get('cover_url',''),
                local_path=s.get('local_path',''),
                file_size=s.get('file_size',''),
                lyric=s.get('lyric',''),
            ))
        self.engine.clear_playlist()
        self.engine.add_songs(items)
        if 0 <= start_idx < len(items):
            self.engine.play_index(start_idx)
        elif items:
            self.engine.play_index(0)
        self.playPlaylistRequested.emit(playlist_id, start_idx)

    def _save_current(self):
        """保存当前引擎播放列表到数据库"""
        pl = self.engine.playlist
        if not pl:
            InfoBar.warning('提示', '当前播放列表为空', parent=self)
            return
        # 询问播放列表名称
        name, ok = QInputDialog.getText(self, '保存播放列表', '请输入播放列表名称:')
        if not ok or not name.strip():
            return
        pid = create_playlist(name.strip())
        # 清空旧歌曲
        clear_playlist_songs(pid)
        for item in pl:
            d = item.to_dict()
            add_song_to_db(pid, d)
        InfoBar.success('保存成功', f'已保存 {len(pl)} 首歌曲到 "{name}"', parent=self)
        self._refresh()

    def _new_playlist(self):
        """新建空播放列表"""
        name, ok = QInputDialog.getText(self, '新建播放列表', '名称:')
        if not ok or not name.strip():
            return
        create_playlist(name.strip())
        InfoBar.success('成功', f'已创建播放列表 "{name}"', parent=self)
        self._refresh()

    def _delete_selected(self):
        """删除选中的播放列表"""
        items = self.tree.selectedItems()
        if not items:
            InfoBar.warning('提示', '请先选择一个播放列表', parent=self)
            return
        item = items[0]
        # 向上找到播放列表级
        while item.parent():
            item = item.parent()
        pid = item.data(0, Qt.UserRole)
        name = item.text(0)
        reply = QMessageBox.question(self, '确认删除', f'确定删除播放列表 "{name}" 吗？')
        if reply == QMessageBox.Yes:
            delete_playlist(pid)
            self._refresh()
