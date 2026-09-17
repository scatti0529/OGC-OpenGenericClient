"""
音乐播放引擎 - 基于 QMediaPlayer
功能：播放、暂停、切换、播放模式、播放列表管理及JSON持久化
"""
import os
import json
import random
from pathlib import Path
from enum import Enum
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal, QUrl, QTimer
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent, QMediaMetaData

from ui.widgets.common import CFG, log_manager

# ── 播放模式 ─────────────────────────────────────────────
class PlayMode(Enum):
    ORDER = "order"        # 顺序播放
    REPEAT_ONE = "repeat_one"  # 单曲循环
    REPEAT_ALL = "repeat_all"  # 列表循环
    SHUFFLE = "shuffle"    # 随机播放


# ── 播放状态 ─────────────────────────────────────────────
class PlayState(Enum):
    STOPPED = 0
    PLAYING = 1
    PAUSED = 2


# ── 播放列表条目 ─────────────────────────────────────────
class PlaylistItem:
    """播放列表中的单曲"""
    def __init__(self, song_name="", singers="", album="", duration="",
                 download_url="", quality="", identifier="", cover_url="",
                 local_path="", file_size="", lyric=""):
        self.song_name = song_name
        self.singers = singers
        self.album = album
        self.duration = duration
        self.download_url = download_url
        self.quality = quality
        self.identifier = identifier
        self.cover_url = cover_url
        self.local_path = local_path
        self.file_size = file_size
        self.lyric = lyric

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d.get(k, "") for k in [
            'song_name', 'singers', 'album', 'duration', 'download_url',
            'quality', 'identifier', 'cover_url', 'local_path', 'file_size', 'lyric'
        ]})

    @classmethod
    def from_song_info(cls, info):
        """从 SongInfo 创建"""
        return cls(
            song_name=info.song_name or "",
            singers=info.singers or "",
            album=info.album or "",
            duration=info.duration or "",
            download_url=info.download_url if isinstance(info.download_url, str) else "",
            quality=info.quality or "",
            identifier=info.identifier or "",
            cover_url=info.cover_url or "",
            file_size=info.file_size or "",
            lyric=info.lyric or "",
        )


# ── 播放引擎 ─────────────────────────────────────────────
class MusicPlayerEngine(QObject):
    """音乐播放引擎 - 核心播放逻辑"""

    # 信号
    positionChanged = pyqtSignal(int, int)   # 当前进度ms, 总时长ms
    stateChanged = pyqtSignal(PlayState)      # 播放状态变化
    songChanged = pyqtSignal(PlaylistItem)    # 切歌
    modeChanged = pyqtSignal(PlayMode)        # 播放模式变化
    playlistChanged = pyqtSignal()            # 播放列表变化
    metaDataChanged = pyqtSignal(dict)        # 元数据变化
    volumeChanged = pyqtSignal(int)           # 音量变化(0-100)
    finished = pyqtSignal()                   # 列表播放完毕

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._playlist = []           # List[PlaylistItem]
        self._current_index = -1
        self._mode = PlayMode.ORDER
        self._state = PlayState.STOPPED
        self._playlist_path = self._get_playlist_path()
        self._volume = 80
        self._is_seeking = False

        # 信号连接
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.stateChanged.connect(self._on_player_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.metaDataChanged.connect(self._on_meta_data_changed)
        self._player.mediaChanged.connect(self._on_media_changed)
        # 兼容 PyQt5/Qt5 不同版本的 error 信号
        if hasattr(self._player, 'errorOccurred'):
            self._player.errorOccurred.connect(self._on_error)
        else:
            self._player.error.connect(self._on_error)

        # 加载播放列表
        self._load_playlist()

    # ── 属性 ─────────────────────────────────────────────
    @property
    def playlist(self) -> list:
        return self._playlist

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def current_item(self) -> Optional[PlaylistItem]:
        if 0 <= self._current_index < len(self._playlist):
            return self._playlist[self._current_index]
        return None

    @property
    def play_mode(self) -> PlayMode:
        return self._mode

    @property
    def play_state(self) -> PlayState:
        return self._state

    @property
    def volume(self) -> int:
        return self._volume

    # ── 播放控制 ─────────────────────────────────────────
    def play(self):
        """播放/继续"""
        if self._state == PlayState.PAUSED:
            self._player.play()
        elif self._current_index >= 0:
            self._player.play()

    def pause(self):
        """暂停"""
        self._player.pause()

    def stop(self):
        """停止"""
        self._player.stop()
        self._state = PlayState.STOPPED
        self.stateChanged.emit(self._state)

    def play_pause_toggle(self):
        """播放/暂停切换"""
        if self._state == PlayState.PLAYING:
            self.pause()
        else:
            self.play()

    def set_position(self, position_ms: int):
        """设置播放位置(ms)"""
        self._player.setPosition(position_ms)

    def set_volume(self, vol: int):
        """设置音量 0-100"""
        vol = max(0, min(100, vol))
        self._volume = vol
        self._player.setVolume(vol)
        self.volumeChanged.emit(vol)

    def toggle_mute(self):
        """切换静音"""
        self._player.setMuted(not self._player.isMuted())

    # ── 切歌 ─────────────────────────────────────────────
    def play_index(self, index: int):
        """播放指定索引"""
        if not self._playlist or index < 0 or index >= len(self._playlist):
            return
        self._current_index = index
        item = self._playlist[index]
        url = item.local_path if (item.local_path and os.path.exists(item.local_path)) else item.download_url
        if not url:
            log_manager.warning(
                f"无可用播放地址: {item.song_name} | 歌手: {item.singers} | "
                f"local_path: {item.local_path!r} | download_url: {item.download_url!r}")
            return
        content = QMediaContent(QUrl(url))
        self._player.setMedia(content)
        self._player.setVolume(self._volume)
        self._player.play()
        self.songChanged.emit(item)
        log_manager.info(f"播放: {item.song_name} - {item.singers}")

    def play_next(self):
        """下一首"""
        idx = self._get_next_index()
        if idx >= 0:
            self.play_index(idx)
        else:
            self.stop()
            self.finished.emit()

    def play_prev(self):
        """上一首"""
        idx = self._get_prev_index()
        if idx >= 0:
            self.play_index(idx)
        else:
            self.stop()

    def _get_next_index(self) -> int:
        """计算下一首索引"""
        n = len(self._playlist)
        if n == 0:
            return -1
        if self._mode == PlayMode.SHUFFLE:
            candidates = [i for i in range(n) if i != self._current_index]
            return random.choice(candidates) if candidates else self._current_index
        idx = self._current_index + 1
        if idx >= n:
            return 0 if self._mode == PlayMode.REPEAT_ALL else -1
        return idx

    def _get_prev_index(self) -> int:
        """计算上一首索引"""
        n = len(self._playlist)
        if n == 0:
            return -1
        if self._mode == PlayMode.SHUFFLE:
            candidates = [i for i in range(n) if i != self._current_index]
            return random.choice(candidates) if candidates else self._current_index
        idx = self._current_index - 1
        if idx < 0:
            return n - 1 if self._mode == PlayMode.REPEAT_ALL else -1
        return idx

    # ── 播放模式 ─────────────────────────────────────────
    def set_play_mode(self, mode: PlayMode):
        """设置播放模式"""
        self._mode = mode
        self.modeChanged.emit(mode)
        log_manager.info(f"播放模式: {mode.value}")

    def cycle_play_mode(self):
        """循环切换播放模式"""
        modes = [PlayMode.ORDER, PlayMode.REPEAT_ALL, PlayMode.REPEAT_ONE, PlayMode.SHUFFLE]
        idx = modes.index(self._mode)
        self.set_play_mode(modes[(idx + 1) % len(modes)])

    # ── 播放列表管理 ─────────────────────────────────────
    def add_song(self, item: PlaylistItem):
        """添加单曲到列表"""
        self._playlist.append(item)
        if self._current_index < 0 and len(self._playlist) == 1:
            self._current_index = 0
        self.playlistChanged.emit()
        self._save_playlist()

    def add_songs(self, items: list):
        """批量添加"""
        if not items:
            return
        self._playlist.extend(items)
        if self._current_index < 0:
            self._current_index = 0
        self.playlistChanged.emit()
        self._save_playlist()

    def remove_song(self, index: int):
        """删除指定歌曲"""
        if index < 0 or index >= len(self._playlist):
            return
        if index == self._current_index:
            self.stop()
        self._playlist.pop(index)
        if index <= self._current_index:
            self._current_index = max(-1, self._current_index - 1)
        self.playlistChanged.emit()
        self._save_playlist()

    def clear_playlist(self):
        """清空播放列表"""
        self.stop()
        self._playlist.clear()
        self._current_index = -1
        self.playlistChanged.emit()
        self._save_playlist()

    def move_song(self, from_idx: int, to_idx: int):
        """调整顺序"""
        if from_idx < 0 or from_idx >= len(self._playlist) or to_idx < 0 or to_idx >= len(self._playlist):
            return
        item = self._playlist.pop(from_idx)
        self._playlist.insert(to_idx, item)
        if self._current_index == from_idx:
            self._current_index = to_idx
        elif from_idx < self._current_index <= to_idx:
            self._current_index -= 1
        elif to_idx <= self._current_index < from_idx:
            self._current_index += 1
        self.playlistChanged.emit()
        self._save_playlist()

    def get_playlist(self) -> list:
        return self._playlist

    # ── 播放列表持久化 ───────────────────────────────────
    def _get_playlist_path(self) -> str:
        # 使用主程序目录，而不是CFG（可能有误）
        import sys
        base = Path(sys.argv[0]).parent
        music_dir = base / 'data'
        music_dir.mkdir(parents=True, exist_ok=True)
        return str(music_dir / 'playlist.json')

    def _save_playlist(self):
        """保存播放列表到JSON"""
        try:
            data = {
                'current_index': self._current_index,
                'play_mode': self._mode.value,
                'songs': [item.to_dict() for item in self._playlist]
            }
            Path(self._playlist_path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except Exception as e:
            log_manager.error(f"保存播放列表失败: {e}")

    def _load_playlist(self):
        """从JSON加载播放列表"""
        try:
            p = Path(self._playlist_path)
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding='utf-8'))
            self._playlist = [PlaylistItem.from_dict(s) for s in data.get('songs', [])]
            self._current_index = data.get('current_index', -1)
            if self._current_index >= len(self._playlist):
                self._current_index = -1
            mode_str = data.get('play_mode', 'order')
            for m in PlayMode:
                if m.value == mode_str:
                    self._mode = m
                    break
            log_manager.info(f"加载播放列表: {len(self._playlist)} 首")
        except Exception as e:
            log_manager.error(f"加载播放列表失败: {e}")
            self._playlist = []
            self._current_index = -1

    # ── 内部回调 ─────────────────────────────────────────
    def _on_position_changed(self, pos_ms: int):
        dur = self._player.duration()
        self.positionChanged.emit(pos_ms, dur)

    def _on_duration_changed(self, dur_ms: int):
        pos = self._player.position()
        self.positionChanged.emit(pos, dur_ms)

    def _on_player_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self._state = PlayState.PLAYING
        elif state == QMediaPlayer.PausedState:
            self._state = PlayState.PAUSED
        else:
            self._state = PlayState.STOPPED
        self.stateChanged.emit(self._state)

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.EndOfMedia:
            if self._mode == PlayMode.REPEAT_ONE:
                # 单曲循环 - 重新播放
                self._player.setPosition(0)
                self._player.play()
            else:
                self.play_next()

    def _on_meta_data_changed(self):
        """元数据变化"""
        meta = {}
        try:
            # 通过已知的 Key 枚举来获取元数据
            meta_keys = [
                'Title', 'Author', 'AlbumTitle', 'Genre', 'Year',
                'TrackNumber', 'Duration', 'AudioBitRate', 'AudioCodec'
            ]
            for name in meta_keys:
                key = getattr(QMediaMetaData, name, None)
                if key is not None:
                    val = self._player.metaData(key)
                    if val:
                        meta[name] = str(val)
        except Exception:
            pass
        self.metaDataChanged.emit(meta)

    def _on_media_changed(self, content):
        pass

    def _on_error(self, *args):
        """播放器错误回调（兼容新旧版信号参数数量）

        - Qt5 旧版 error(QMediaPlayer::Error)      -> 1 个参数
        - Qt5/Qt6 新版 errorOccurred(Error, str)    -> 2 个参数
        """
        try:
            if len(args) >= 2:
                error, error_str = args[0], args[1]
                log_manager.error(f"播放器错误 [{error}]: {error_str}")
            else:
                error = args[0] if args else 'unknown'
                log_manager.error(f"播放器错误 [{error}]")
        except Exception as e:
            log_manager.error(f"播放器错误回调异常: {e}")

    # ── 工具 ─────────────────────────────────────────────
    def format_time(self, ms: int) -> str:
        """毫秒转时间字符串 mm:ss"""
        if ms < 0:
            return "00:00"
        s = ms // 1000
        m = s // 60
        s = s % 60
        return f"{m:02d}:{s:02d}"

    def get_music_cache_dir(self) -> str:
        """获取音乐缓存目录"""
        return CFG.cfg.get('music_cache_path', str(Path(CFG['save_path']) / 'music'))

    def get_music_download_dir(self) -> str:
        """获取音乐下载目录"""
        return CFG.cfg.get('music_download_path', str(Path(CFG['save_path']) / 'music'))
