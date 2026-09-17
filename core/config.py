# -*- coding: utf-8 -*-
"""
全局配置管理
============
统一管理系统路径与用户配置，替代原 ilbs.common 中的 Config_info。

目录职责划分（重要 —— 改路径前先读这段）
----------------------------------------
本程序把"数据"刻意分成两类，避免项目目录被几百 MB 缓存撑大：

* ``data/``                     **小体积、不可再生** —— 索引 JSON、配置、数据库、
                               7Z 解压器、用户头像。必须随程序保留，删了就丢信息。
* ``{下载根目录}/.cache/``      **大体积、可再生** —— 缩略图缓存、画廊图片缓存、
                               预览图、阅读临时缓存。放在下载根目录（用户自己的大容量
                               空间，可在设置里换盘），不占项目体积。
* ``{下载根目录}/`` 下的平台目录  用户下载的实际媒体内容。

所以：索引一律留 ``data/``（``thumb_index.json`` / ``dir_cache/`` /
``offline_index/*.json``），缓存一律去下载根目录。

用法::

    from core.config import config as CFG

    CFG['video_save_path']               # 读取配置
    CFG['xc'] = 10                       # 修改并自动保存
    CFG.download_root                    # 下载根目录（权威解析，别自己再实现一份）
    CFG.cache_path('ehentai', 'cache')   # 缓存目录（自动创建）
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

# 下载根目录下存放各类缓存的子目录名。
# 用点号前缀：文件库扫描会跳过隐藏项，缓存不会混进"本地文件"列表。
CACHE_DIR_NAME = '.cache'

# 离线索引（漫画/画廊扫描结果 JSON）在 data/ 下的子目录名
INDEX_DIR_NAME = 'offline_index'


def _reload_from_disk(mgr) -> None:
    """按 mgr.cfg_file 重新读取配置（保留默认值补全）。

    换根目录（set_root）后必须重新加载：否则程序会用 A 目录的配置
    去读写 B 目录的数据，表现为"设置刚改完就丢"。
    """
    cfg = {}
    try:
        if mgr.cfg_file.exists():
            cfg = json.loads(mgr.cfg_file.read_text(encoding='utf-8'))
            if not isinstance(cfg, dict):
                cfg = {}
    except (json.JSONDecodeError, OSError):
        cfg = {}
    for k, v in mgr.default.items():
        cfg.setdefault(k, v)
    mgr.cfg = cfg


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
        self.music_dir = self.root / 'music'
        self.logs_dir = self.root / 'logs'
        self.cfg_file = self.data / 'config.json'

        # download_root 的解析结果缓存（配置变更时失效，见 __setitem__）
        self._download_root_cache = None

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
            if key == 'video_download_root':
                # 下载根目录变了，缓存/索引的解析结果必须重算
                self._download_root_cache = None
            self.save()

    def __contains__(self, key):
        return key in self.cfg

    def get(self, key, default=None):
        """安全获取配置项"""
        return self.cfg.get(key, default)

    def set_root(self, root) -> None:
        """显式指定程序根目录（进而决定 data/ 与 logs/ 的位置）。

        为什么需要它：默认 root 取自 ``sys.argv[0]`` 的父目录 ——
        ``python main.py``（在项目根运行）解析为当前目录，是正确的；但
        ``python scripts/xxx.py`` 会解析成 **scripts/**，于是 data/ 变成
        ``scripts/data``。这对冒烟测试反而是好事（测试数据与真实数据隔离），
        可一旦某个**维护脚本**需要操作真实的 data/（如存储迁移工具），
        就会默默改到 scripts/data 上去。

        因此需要真实根目录的脚本必须显式调用本方法::

            from core.config import config as CFG
            CFG.set_root(r'<项目根>')
        """
        self.root = Path(root)
        self.data = self.root / 'data'
        self.music_dir = self.root / 'music'
        self.logs_dir = self.root / 'logs'
        self.cfg_file = self.data / 'config.json'
        self._download_root_cache = None
        for d in (self.data, self.logs_dir, self.music_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        _reload_from_disk(self)

    # ---------- 路径解析（全项目唯一权威实现） ----------
    @property
    def download_root(self) -> str:
        """下载根目录（绝对路径，保证存在）。

        与旧实现的关键区别：**配置了就以实现为准并确保目录存在**。
        旧逻辑是「配置路径不存在 → 静默回退 data/」，后果是：用户明明在设置里
        把下载根目录指到了别的盘（如 ``E:/.../测试下载``），只要那个目录还没
        被创建，所有下载与缓存就悄悄落回项目内的 ``data/`` —— 项目体积暴涨，
        而用户完全看不出原因（设置页显示的还是他填的路径）。

        只有配置的路径**真的建不出来**（盘符不存在 / 无权限）才回退 data/。
        """
        if self._download_root_cache:
            return self._download_root_cache
        with self._lock:
            if self._download_root_cache:
                return self._download_root_cache
            custom = str(self.cfg.get('video_download_root', '') or '').strip()
            path = custom or str(self.data)
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                # 配置不可用（离线盘/只读）才降级，避免整个程序起不来
                path = str(self.data)
                try:
                    os.makedirs(path, exist_ok=True)
                except OSError:
                    pass
            self._download_root_cache = os.path.abspath(path)
            return self._download_root_cache

    @property
    def cache_dir(self) -> str:
        """大体积可再生产物（缩略图 / 图片缓存 / 预览）的根目录。

        刻意放在**下载根目录**下而非 data/：这类缓存动辄几百 MB，放 data/
        会让程序目录越来越臃肿；下载根目录本就是用户的大容量空间，还能换盘。
        """
        d = os.path.join(self.download_root, CACHE_DIR_NAME)
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d

    def cache_path(self, *parts) -> str:
        """拼接并创建缓存子目录，如 ``cache_path('ehentai', 'cache')``"""
        p = os.path.join(self.cache_dir, *parts)
        try:
            os.makedirs(p, exist_ok=True)
        except OSError:
            pass
        return p

    def offline_index_path(self, platform: str) -> str:
        """漫画/画廊离线索引 JSON 的路径（**在 data/ 内**）。

        历史：这些索引曾写在 ``{下载根}/.{platform}_offline_index.json``，
        与用户的下载内容混在一起；现在统一收进 ``data/offline_index/``，
        索引与内容分离，换下载盘也不会丢索引。
        """
        d = os.path.join(str(self.data), INDEX_DIR_NAME)
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return os.path.join(d, f'{platform}_offline_index.json')


# 全局配置单例
config = ConfigManager()