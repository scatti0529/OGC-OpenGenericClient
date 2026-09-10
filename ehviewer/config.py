# -*- coding: utf-8 -*-
"""全局配置（JSON 持久化），对应 Android 版 Settings.java 的核心项"""
import json
import os
import threading

from .constants import SITE_E, IMAGE_SIZE_AUTO

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ehentai")
CONFIG_PATH = os.path.join(CONFIG_DIR, "ehviewer_config.json")

DEFAULTS = {
    # 站点与账户
    "site": SITE_E,                       # 0=表站 1=里站
    "cookies": {},                        # 登录 Cookie：ipb_member_id / ipb_pass_hash / igneous 等
    "display_name": "",
    "avatar_path": "",
    # 显示
    "show_jpn_title": False,              # 优先显示日文标题
    "show_gallery_pages": True,           # 列表显示页数
    "list_layout": "l",                   # 列表布局：l=列表 t=缩略图
    "thumb_resolution": 1,                # 0=原始 1=250 2=300
    # 阅读
    "image_size": IMAGE_SIZE_AUTO,        # 图片分辨率 a/780/980/1280/1600/2400
    "read_style": "page",                 # 阅读模式：page=翻页 scroll=滚动
    "reader_fit": "width",                # 适配方式：width=宽度适配 whole=整图适配
    "preload_pages": 2,                   # 预加载页数
    "double_click_zoom": True,
    # 下载
    "download_dir": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ehentai", "ehviewer_downloads"),
    "download_concurrency": 4,            # 同时下载的画廊数
    "download_speed_limit": 0,            # 0 不限速，KB/s
    "download_original": False,           # 下载原图（默认压缩图）
    "sync_download_on_read": False,       # 阅读时同步下载
    "auto_retry_failed": False,
    # 网络
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "timeout": 20,                        # 请求超时秒数
    "retry_count": 3,
    "proxy": "",                          # 代理地址，如 http://127.0.0.1:7890
    # 其他
    "quick_searches": [],                 # 快速搜索列表
    "filters": [],                        # 过滤器列表 [{mode, text}]
    "favorite_cat_names": [],             # 收藏夹自定义名称（10 个）
    "auto_sync_favorites": True,
    "check_update": True,
}

_lock = threading.Lock()
_data = None


def _load():
    global _data
    _data = dict(DEFAULTS)
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k, v in saved.items():
                    _data[k] = v
    except Exception:
        pass


def _save():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        pass


def get(key, default=None):
    if _data is None:
        _load()
    return _data.get(key, default)


def set(key, value, persist=True):
    with _lock:
        if _data is None:
            _load()
        _data[key] = value
        if persist:
            _save()


def update(d, persist=True):
    with _lock:
        if _data is None:
            _load()
        _data.update(d)
        if persist:
            _save()


def is_login():
    cookies = get("cookies", {}) or {}
    return bool(cookies.get("ipb_member_id") and cookies.get("ipb_pass_hash"))


def get_cookie(name):
    return (get("cookies", {}) or {}).get(name)


def set_cookies(cookies_dict):
    cur = dict(get("cookies", {}) or {})
    cur.update({k: v for k, v in cookies_dict.items() if v is not None})
    set("cookies", cur)


def clear_cookies():
    set("cookies", {})


# 供 ui 使用的一个全局信号桥（由 main 模块注入）
class ConfigSignals(object):
    """配置变更通知（避免循环 import，由应用启动时实例化）"""
    def __init__(self):
        self._handlers = []

    def connect(self, fn):
        self._handlers.append(fn)

    def emit(self, key=None):
        for fn in list(self._handlers):
            try:
                fn(key)
            except Exception:
                pass


signals = ConfigSignals()

CFG = None  # 由 config 模块自身暴露一个便捷别名


class _CFGProxy(object):
    """dict 风格只读访问代理：CFG['site']"""
    def __getitem__(self, key):
        return get(key)

    def get(self, key, default=None):
        return get(key, default)

    def __contains__(self, key):
        return key in (_data or DEFAULTS)


CFG = _CFGProxy()
