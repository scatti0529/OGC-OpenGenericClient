# -*- coding: utf-8 -*-
"""
全局配置管理
============
统一管理系统路径与用户配置，替代原 ilbs.common 中的 Config_info。

用法::

    from core.config import config as CFG

    CFG['video_save_path']           # 读取配置
    CFG['xc'] = 10                   # 修改并自动保存
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path


class ConfigManager:
    """JSON 配置管理器（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        # 配置会被多个线程写（UI 设置页、下载线程保存账号、网络线程刷新 cookie），
        # 用可重入锁串行化"改值 + 落盘"，避免并发写坏文件。
        self._lock = threading.RLock()

        self.root = Path(sys.argv[0]).parent
        self.data = self.root / 'data'
        # self.videos = self.data / 'videos'
        # self.musics = self.data / 'musics'
        # self.temp_videos = self.data / 'temp_videos'
        self.music_dir = self.root / 'music'
        self.logs_dir = self.root / 'logs'
        self.cfg_file = self.data / 'config.json'

        # 创建必要的目录
        for d in (self.data, self.logs_dir, self.music_dir):
            d.mkdir(parents=True, exist_ok=True)

        # 默认配置
        self.default = {
            'HEADERS': {},
            'COOKIES': '',
            'bili_key': '',
            'URL_COM': '',
            'douyin_headers': {},
            'douyin_params': {},
            'cursor': [],
            'delay': [50, 150],
            'save_path': str(self.data),
            'save_mode': 1,
            'xc': 5,
            'auto_backup': True,
            'version': '1.0.0',
            # 日志路径配置
            'operation_log_path': str(self.logs_dir / 'operation.log'),
            'error_log_path': str(self.logs_dir / 'error.log'),
            # 视频/多媒体下载根目录（默认 data 文件夹，可在设置中修改）
            'video_download_root': str(self.data),
            # 兼容旧配置键（旧代码 video_page/settings_page 仍会引用，保持向后兼容）
            'video_save_path': str(self.data / 'videos'),
            'temp_video_save_path': str(self.data / 'temp_videos'),
            'music_cache_path': str(self.music_dir),
            'music_download_path': str(self.music_dir),
            # 下载优化配置
            'download_max_threads': 8,           # 并发分块下载线程数
            'download_parallel_threshold': 20,   # 大文件并发分块阈值 (MB)
            'download_retry_times': 3,           # 单模式内部重试次数
            'download_mode': 'auto',             # 下载模式: auto/parallel/stream/hls
            # 自动登录（本机多账号）
            'auto_login_enabled': False,
            'auto_login_selected': '',
            'auto_login_accounts': [],
        }

        # 加载配置（兼容旧路径缺失的默认值补全）
        self.cfg = {}
        if self.cfg_file.exists():
            try:
                self.cfg = json.loads(self.cfg_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                self.cfg = {}
        for k, v in self.default.items():
            self.cfg.setdefault(k, v)

    # ---------- 字典式访问 ----------
    def save(self):
        """保存配置到文件：加锁串行化 + 临时文件原子替换。

        原实现直接 ``write_text`` 覆盖同一个 config.json。而本项目有多个线程会写它
        （设置页保存、jmcomic 保存账号、douyin 保存 cookie、pixiv 保存抓取选项），
        并发覆盖会产生"截断/交错"的半截 JSON，下次启动即 ``JSONDecodeError``，
        被吞掉后回退成默认配置 —— 用户看到的现象是"设置莫名其妙全丢了"。
        改为先写同目录临时文件再 ``os.replace`` 原子替换：任何时刻磁盘上的
        config.json 要么是旧内容、要么是完整新内容，不会出现半截。
        """
        with self._lock:
            # 持锁快照，避免 json.dumps 期间别的线程改字典导致
            # "dictionary changed size during iteration"
            data = json.dumps(dict(self.cfg), ensure_ascii=False, indent=2)
            self.cfg_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = None
            try:
                fd, tmp_path = tempfile.mkstemp(
                    dir=str(self.cfg_file.parent),
                    prefix=self.cfg_file.name + '.', suffix='.tmp')
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.cfg_file)
                tmp_path = None
            finally:
                # 替换成功则临时文件已不存在；失败时清理残留，避免堆积 .tmp
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

    def __getitem__(self, key):
        return self.cfg[key]

    def __setitem__(self, key, value):
        with self._lock:
            self.cfg[key] = value
            self.save()

    def __contains__(self, key):
        return key in self.cfg

    def get(self, key, default=None):
        """安全获取配置项"""
        return self.cfg.get(key, default)


# 全局配置单例
config = ConfigManager()