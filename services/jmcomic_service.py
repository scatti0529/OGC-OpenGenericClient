# -*- coding: utf-8 -*-
"""
JMComic 下载服务模块
====================
整合 OGC-jmcomic 的核心功能：
- 搜索 / 详情 / 排行榜 / 分类浏览
- 本子 / 章节下载（QThread 异步执行）
- JM 账号登录 / 登出 / 会话持久化
- ZIP / PDF / 长图打包（支持加密）
- 配额管理 & 订阅管理（合并到主程序数据库）
- 核心功能基于 jmcomic 库（惰性加载）
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import sqlite3
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import QObject, QThread, pyqtSignal

# 使用主程序日志系统
from core.logger import logger

# 主程序数据库
from core.database import DB_PATH as MAIN_DB_PATH, get_db_connection

if TYPE_CHECKING:
    from jmcomic import JmOption

# ═══════════════════════════════════════════════════════════
#  jmcomic 惰性加载
# ═══════════════════════════════════════════════════════════

def is_jmcomic_available() -> bool:
    """检查 jmcomic 库是否可被发现（不实际导入）"""
    try:
        return importlib.util.find_spec("jmcomic") is not None
    except (ImportError, ValueError):
        return False


def import_jmcomic() -> Any | None:
    """惰性导入 jmcomic 库"""
    try:
        import jmcomic
    except ImportError:
        return None
    return jmcomic


def can_import_jmcomic() -> bool:
    """检查 jmcomic 库是否可实际导入"""
    return import_jmcomic() is not None


JMCOMIC_AVAILABLE = is_jmcomic_available()

# ═══════════════════════════════════════════════════════════
#  常量定义（来自 OGC-jmcomic/core/constants.py）
# ═══════════════════════════════════════════════════════════

# 分类映射：用户输入 -> API 参数
CATEGORY_MAP = {
    "all": "0",
    "doujin": "doujin",
    "single": "single",
    "short": "short",
    "hanman": "hanman",
    "meiman": "meiman",
    "3d": "3D",
    "cosplay": "doujin_cosplay",
    "another": "another",
}

# 排序映射：用户输入 -> API 参数
ORDER_MAP = {
    "new": "mr",   # 最新
    "hot": "mv",   # 最热（观看数）
    "pic": "mp",   # 图片多
    "like": "tf",  # 点赞多
}

# 时间映射：用户输入 -> API 参数
TIME_MAP = {
    "day": "t",    # 今日
    "week": "w",   # 本周
    "month": "m",  # 本月
    "all": "a",    # 全部时间
}

# 分类显示名称
CATEGORY_NAMES = {
    "all": "全部", "0": "全部",
    "doujin": "同人", "single": "单本", "short": "短篇",
    "hanman": "韩漫", "meiman": "美漫",
    "3d": "3D", "3D": "3D",
    "cosplay": "Cosplay", "doujin_cosplay": "Cosplay",
    "another": "其他",
}

# 排序显示名称
ORDER_NAMES = {
    "new": "最新", "mr": "最新",
    "hot": "热门", "mv": "热门",
    "pic": "图多", "mp": "图多",
    "like": "点赞", "tf": "点赞",
}

# 时间显示名称
TIME_NAMES = {
    "day": "今日", "t": "今日",
    "week": "本周", "w": "本周",
    "month": "本月", "m": "本月",
    "all": "全部时间", "a": "全部时间",
}

# 搜索模式
SEARCH_MODES = [
    ("site", "综合"),
    ("tag", "标签"),
    ("author", "作者"),
    ("actor", "角色"),
    ("work", "作品"),
]

# 选择器（用于 UI 显示）
RANK_TYPES = [
    ("week", "周榜"),
    ("day", "日榜"),
    ("month", "月榜"),
]

CATEGORY_LIST = [
    ("all", "全部"),
    ("doujin", "同人"),
    ("single", "单本"),
    ("short", "短篇"),
    ("hanman", "韩漫"),
    ("meiman", "美漫"),
    ("3d", "3D"),
    ("cosplay", "Cosplay"),
    ("another", "其他"),
]

ORDER_LIST = [
    ("hot", "热门"),
    ("new", "最新"),
    ("pic", "图多"),
    ("like", "点赞"),
]

TIME_LIST = [
    ("week", "本周"),
    ("day", "今日"),
    ("month", "本月"),
    ("all", "全部"),
]

PACK_FORMATS = [
    ("zip", "ZIP 压缩包"),
    ("pdf", "PDF 文档"),
    ("long_img", "长图"),
    ("none", "不打包"),
]

# ═══════════════════════════════════════════════════════════
#  异常分类
# ═══════════════════════════════════════════════════════════

_NETWORK_KEYWORDS = ("timeout", "connect", "network", "ssl", "proxy", "max retries")


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """将异常映射为 (error_type, 用户提示)"""
    jmcomic = import_jmcomic()
    if jmcomic is not None:
        missing = getattr(jmcomic, "MissingAlbumPhotoException", None)
        retry_fail = getattr(jmcomic, "RequestRetryAllFailException", None)
        partial = getattr(jmcomic, "PartialDownloadFailedException", None)

        if missing is not None and isinstance(exc, missing):
            return "not_found", "未找到该本子或章节，请检查ID是否正确"
        if retry_fail is not None and isinstance(exc, retry_fail):
            return (
                "network",
                "请求多次重试均失败，可能是域名被墙或网络问题，"
                "可尝试配置代理或自定义域名",
            )
        if partial is not None and isinstance(exc, partial):
            return "download_failed", "部分图片下载失败"

    msg = str(exc) or exc.__class__.__name__
    if any(keyword in msg.lower() for keyword in _NETWORK_KEYWORDS):
        return "network", "网络连接失败，请稍后重试"
    return "download_failed", msg


# ═══════════════════════════════════════════════════════════
#  默认配置
# ═══════════════════════════════════════════════════════════

JM_DEFAULTS = {
    "download_dir": "./jmcomic-download",
    "image_suffix": ".jpg",
    "client_type": "api",
    "client_domain": "",
    "retry_times": 0,
    "use_proxy": False,
    "proxy_url": "",
    "max_concurrent_photos": 3,
    "max_concurrent_images": 5,
    "pack_format": "zip",
    "pack_password": "",
    "filename_show_password": False,
    "auto_delete_after_send": True,
    "jm_username": "",
    "jm_password": "",
    "search_page_size": 5,
    "daily_download_limit": 0,
    "subscribe_check_interval": 3600,
    "debug_mode": False,
}


# ═══════════════════════════════════════════════════════════
#  配置管理器（适配主程序 data 目录）
# ═══════════════════════════════════════════════════════════

class JMConfigManager:
    """JMComic 配置管理器"""

    def __init__(self, plugin_config: dict, data_dir: Path | str):
        self.plugin_config = dict(plugin_config)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._option = None

    # ---- 属性 ----
    @property
    def download_dir(self) -> Path:
        dir_path = self.plugin_config.get("download_dir", "./jmcomic-download")
        p = Path(dir_path)
        if not p.is_absolute():
            p = self.data_dir / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def image_suffix(self) -> str:
        return self.plugin_config.get("image_suffix", ".jpg")

    @property
    def client_type(self) -> str:
        return self.plugin_config.get("client_type", "api")

    @property
    def client_domain(self) -> list[str]:
        domain_str = self.plugin_config.get("client_domain", "")
        return [d.strip() for d in domain_str.split(",") if d.strip()]

    @property
    def retry_times(self) -> int:
        return self.plugin_config.get("retry_times", 0)

    @property
    def use_proxy(self) -> bool:
        return self.plugin_config.get("use_proxy", False)

    @property
    def proxy_url(self) -> str:
        return self.plugin_config.get("proxy_url", "")

    @property
    def max_concurrent_photos(self) -> int:
        return self.plugin_config.get("max_concurrent_photos", 3)

    @property
    def max_concurrent_images(self) -> int:
        return self.plugin_config.get("max_concurrent_images", 5)

    @property
    def pack_format(self) -> str:
        return self.plugin_config.get("pack_format", "zip")

    @property
    def pack_password(self) -> str:
        return self.plugin_config.get("pack_password", "")

    @property
    def filename_show_password(self) -> bool:
        return self.plugin_config.get("filename_show_password", False)

    @property
    def auto_delete_after_send(self) -> bool:
        return self.plugin_config.get("auto_delete_after_send", True)

    @property
    def daily_download_limit(self) -> int:
        return self.plugin_config.get("daily_download_limit", 0)

    @property
    def jm_username(self) -> str:
        return self.plugin_config.get("jm_username", "")

    @property
    def jm_password(self) -> str:
        return self.plugin_config.get("jm_password", "")

    @property
    def debug_mode(self) -> bool:
        return self.plugin_config.get("debug_mode", False)

    @property
    def cookies_file(self) -> Path:
        return self.data_dir / "jm_cookies.json"

    # ---- 方法 ----
    def has_credentials(self) -> bool:
        return bool(self.jm_username and self.jm_password)

    def create_jm_option(self):
        """创建 JmOption 配置对象"""
        jmcomic = import_jmcomic()
        if jmcomic is None:
            return None

        if self._option is not None:
            return self._option

        option_dict = {
            "dir_rule": {"base_dir": str(self.download_dir), "rule": "Bd/Aid/Pindex"},
            "download": {
                "image": {"suffix": self.image_suffix},
                "threading": {
                    "photo": self.max_concurrent_photos,
                    "image": self.max_concurrent_images,
                },
            },
            "client": {"impl": self.client_type},
        }

        if self.client_domain:
            option_dict["client"]["domain"] = self.client_domain
        if self.retry_times > 0:
            option_dict["client"]["retry_times"] = self.retry_times

        if self.use_proxy and self.proxy_url:
            option_dict["client"]["postman"] = {
                "meta_data": {"proxies": self.proxy_url}
            }
        else:
            option_dict["client"]["postman"] = {"meta_data": {"proxies": {}}}

        try:
            self._option = jmcomic.JmModuleConfig.option_class().construct(option_dict)
        except Exception:
            logger.error("创建 JmOption 失败", exc_info=True)
            self._option = None
        return self._option

    def get_option(self):
        if self._option is None:
            self._option = self.create_jm_option()
        return self._option


# ═══════════════════════════════════════════════════════════
#  客户端混入（提供异步执行）
# ═══════════════════════════════════════════════════════════

class JMClientMixin:
    """JMComic 客户端混入类"""

    config: JMConfigManager

    def _get_option(self):
        return self.config.get_option()

    def _build_client(self, option=None):
        if option is None:
            option = self._get_option()
        if option is None:
            return None
        return option.new_jm_client()

    async def _run_sync(self, func: Callable[..., T], *args, **kwargs) -> T:
        return await asyncio.to_thread(func, *args, **kwargs)

    @staticmethod
    def is_available() -> bool:
        return can_import_jmcomic()


T = Any


# ═══════════════════════════════════════════════════════════
#  浏览查询模块（搜索 / 详情 / 榜单 / 分类）
# ═══════════════════════════════════════════════════════════

class JMBrowser(JMClientMixin):
    """JMComic 浏览查询器"""

    def __init__(self, config_manager: JMConfigManager):
        self.config = config_manager

    # ---------------- 搜索 ----------------
    async def search_albums(self, keyword: str, page: int = 1, mode: str = "site") -> list:
        if not self.is_available():
            return []
        option = self._get_option()
        if option is None:
            return []
        return await self._run_sync(self._search_albums_sync, keyword, page, mode, option)

    def _search_albums_sync(self, keyword, page, mode, option) -> list:
        client = option.new_jm_client()
        search_method = {
            "site": client.search_site,
            "tag": client.search_tag,
            "author": client.search_author,
            "actor": client.search_actor,
            "work": client.search_work,
        }.get(mode, client.search_site)
        search_page = search_method(keyword, page)
        results = []
        for album_id, title, tags in search_page.iter_id_title_tag():
            results.append({
                "id": album_id, "title": title, "author": "",
                "tags": tags, "category": "",
            })
        return results

    # ---------------- 详情 ----------------
    async def get_album_detail(self, album_id: str) -> dict | None:
        if not self.is_available():
            return None
        option = self._get_option()
        if option is None:
            return None
        return await self._run_sync(self._get_album_detail_sync, album_id, option)

    def _get_album_detail_sync(self, album_id, option) -> dict | None:
        jmcomic = import_jmcomic()
        if jmcomic is None:
            return None
        client = option.new_jm_client()
        parsed_id = jmcomic.JmcomicText.parse_to_jm_id(album_id)
        album = client.get_album_detail(parsed_id)
        return {
            "id": album.id,
            "title": album.title,
            "author": album.author,
            "tags": album.tags if hasattr(album, "tags") else [],
            "photo_count": len(album),
            "pub_date": str(album.pub_date) if hasattr(album, "pub_date") else "",
            "update_date": str(album.update_date) if hasattr(album, "update_date") else "",
            "description": album.description if hasattr(album, "description") else "",
            "likes": album.likes if hasattr(album, "likes") else 0,
            "views": album.views if hasattr(album, "views") else 0,
        }

    async def get_photo_id_by_index(self, album_id: str, chapter_index: int):
        if not self.is_available():
            return None
        option = self._get_option()
        if option is None:
            return None
        return await self._run_sync(
            self._get_photo_id_by_index_sync, album_id, chapter_index, option
        )

    def _get_photo_id_by_index_sync(self, album_id, chapter_index, option):
        jmcomic = import_jmcomic()
        if jmcomic is None:
            return None
        client = option.new_jm_client()
        parsed_id = jmcomic.JmcomicText.parse_to_jm_id(album_id)
        album = client.get_album_detail(parsed_id)
        total_chapters = len(album.episode_list)
        if chapter_index < 1 or chapter_index > total_chapters:
            return None
        photo_id, _, photo_title = album.episode_list[chapter_index - 1]
        return (photo_id, photo_title, total_chapters)

    async def get_album_cover(self, album_id: str, save_dir: Path) -> Path | None:
        if not self.is_available():
            return None
        try:
            option = self._get_option()
            if option is None:
                return None
            save_dir.mkdir(parents=True, exist_ok=True)
            return await self._run_sync(self._get_album_cover_sync, album_id, save_dir, option)
        except Exception:
            return None

    def _get_album_cover_sync(self, album_id, save_dir, option) -> Path | None:
        try:
            jmcomic = import_jmcomic()
            if jmcomic is None:
                return None
            client = option.new_jm_client()
            parsed_id = jmcomic.JmcomicText.parse_to_jm_id(album_id)
            cover_path = save_dir / f"{parsed_id}.jpg"
            if cover_path.exists():
                return cover_path
            client.download_album_cover(parsed_id, str(cover_path))
            return cover_path if cover_path.exists() else None
        except Exception:
            return None

    # ---------------- 排行榜 ----------------
    async def get_week_ranking(self, page=1, category="all"):
        return await self._get_ranking("week", page, category)

    async def get_month_ranking(self, page=1, category="all"):
        return await self._get_ranking("month", page, category)

    async def get_day_ranking(self, page=1, category="all"):
        return await self._get_ranking("day", page, category)

    async def _get_ranking(self, ranking_type, page, category):
        if not self.is_available():
            return []
        option = self._get_option()
        if option is None:
            return []
        cat = CATEGORY_MAP.get(category.lower(), "0")
        method_name = f"{ranking_type}_ranking"
        return await self._run_sync(self._get_ranking_sync, method_name, page, cat, option)

    def _get_ranking_sync(self, method_name, page, category, option) -> list:
        client = option.new_jm_client()
        ranking_page = getattr(client, method_name)(page, category)
        results = []
        for album_id, title in ranking_page.iter_id_title():
            results.append({
                "id": album_id, "title": title, "author": "",
                "tags": [], "category": category,
            })
        return results

    # ---------------- 分类浏览 ----------------
    async def get_category_albums(self, category="all", order_by="hot", time_range="week", page=1):
        if not self.is_available():
            return []
        option = self._get_option()
        if option is None:
            return []
        cat = CATEGORY_MAP.get(category.lower(), "0")
        order = ORDER_MAP.get(order_by.lower(), "mv")
        time = TIME_MAP.get(time_range.lower(), "w")
        return await self._run_sync(self._get_category_albums_sync, page, time, cat, order, option)

    def _get_category_albums_sync(self, page, time, category, order_by, option) -> list:
        client = option.new_jm_client()
        category_page = client.categories_filter(page=page, time=time, category=category, order_by=order_by)
        results = []
        for album_id, title in category_page.iter_id_title():
            results.append({
                "id": album_id, "title": title, "author": "",
                "tags": [], "category": category,
            })
        return results

    # ---------------- 收藏 ----------------
    async def get_favorites(self, client, page=1, folder_id="0", username=""):
        if not self.is_available():
            return [], []
        return await self._run_sync(self._get_favorites_sync, client, page, folder_id, username)

    def _get_favorites_sync(self, client, page, folder_id, username=""):
        fav_page = client.favorite_folder(page=page, folder_id=folder_id, username=username)
        albums = [{"id": aid, "title": title} for aid, title in fav_page.iter_id_title()]
        folders = [{"id": fid, "name": name} for fid, name in fav_page.iter_folder_id_name()]
        return albums, folders

    async def add_favorite(self, client, album_id, folder_id="0"):
        if not self.is_available():
            return False, "jmcomic 库未安装"
        try:
            return await self._run_sync(self._set_favorite_sync, client, album_id, folder_id, True)
        except Exception as e:
            return False, str(e) or type(e).__name__

    async def remove_favorite(self, client, album_id, folder_id="0"):
        if not self.is_available():
            return False, "jmcomic 库未安装"
        try:
            return await self._run_sync(self._set_favorite_sync, client, album_id, folder_id, False)
        except Exception as e:
            return False, str(e) or type(e).__name__

    def _set_favorite_sync(self, client, album_id, folder_id, want_favorite):
        try:
            jmcomic = import_jmcomic()
            if jmcomic is None:
                return False, "jmcomic 库未安装"
            if client is None:
                option = self._get_option()
                if option is None:
                    return False, "无法创建下载配置"
                client = option.new_jm_client()
            parsed_id = jmcomic.JmcomicText.parse_to_jm_id(album_id)
            client_key = getattr(type(client), "client_key", "api")

            if client_key == "html":
                client.add_favorite_album(parsed_id, folder_id)
                if want_favorite:
                    return True, f"收藏成功（本子 {album_id}）"
                return True, f"已切换收藏状态（本子 {album_id}）"

            current = self._is_favorite_api(client, parsed_id)
            if current is True and want_favorite:
                return True, f"本子 {album_id} 已在收藏夹中，无需重复添加"
            if current is False and not want_favorite:
                return True, f"本子 {album_id} 不在收藏夹中，无需取消"

            resp = client.req_api("/favorite", False, data={"aid": parsed_id})
            data = resp.model_data
            src = data.src_dict if hasattr(data, "src_dict") else (data if isinstance(data, dict) else {})
            status = src.get("status")
            server_msg = (src.get("msg") or "").strip()
            if status == "ok":
                default = f"收藏成功（本子 {album_id}）" if want_favorite else f"已取消收藏（本子 {album_id}）"
                return True, server_msg or default
            action = "收藏" if want_favorite else "取消收藏"
            return False, server_msg or f"{action}失败（status={status}）"
        except Exception as e:
            return False, str(e) or type(e).__name__

    @staticmethod
    def _is_favorite_api(client, parsed_id):
        try:
            resp = client.req_api("/album", params={"id": parsed_id})
            data = resp.model_data
            src = data.src_dict if hasattr(data, "src_dict") else (data if isinstance(data, dict) else {})
            return bool(src.get("is_favorite"))
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════
#  下载管理模块
# ═══════════════════════════════════════════════════════════

@dataclass
class DownloadResult:
    """下载结果"""
    success: bool
    album_id: str
    title: str
    author: str
    photo_count: int
    image_count: int
    save_path: Path
    cover_path: Path | None = None
    error_message: str | None = None
    all_success: bool = True
    failed_images: int = 0


_PROGRESS_DOWNLOADER_CLASS = None


def _get_progress_downloader_class(jmcomic):
    """惰性构建带进度计数的 JmDownloader 子类"""
    global _PROGRESS_DOWNLOADER_CLASS
    if _PROGRESS_DOWNLOADER_CLASS is not None:
        return _PROGRESS_DOWNLOADER_CLASS

    class _ProgressDownloader(jmcomic.JmDownloader):
        def __init__(self, option):
            super().__init__(option)
            self.total_images = 0
            self.downloaded_images = 0
            self.total_photos = 0
            self.downloaded_photos = 0
            self.skip_photos = 0

        def create_client(self):
            return self.option.new_jm_client()

        def do_filter(self, detail):
            if self.skip_photos and detail.is_album():
                return list(detail)[self.skip_photos:]
            return detail

        def before_album(self, album):
            super().before_album(album)
            try:
                self.total_photos = max(0, len(album) - self.skip_photos)
            except Exception:
                self.total_photos = 0

        def before_photo(self, photo):
            super().before_photo(photo)
            if self.total_photos <= 1 and not self.total_images:
                try:
                    self.total_images = len(photo)
                except Exception:
                    pass

        def after_photo(self, photo):
            super().after_photo(photo)
            self.downloaded_photos += 1

        def after_image(self, image, img_save_path):
            super().after_image(image, img_save_path)
            self.downloaded_images += 1

        def progress_view(self):
            if self.total_photos > 1:
                return self.downloaded_photos, self.total_photos, "章节"
            return self.downloaded_images, self.total_images, "图片"

    _PROGRESS_DOWNLOADER_CLASS = _ProgressDownloader
    return _PROGRESS_DOWNLOADER_CLASS


def _resolve_all_success(downloader, skip_photos: int) -> bool:
    if skip_photos:
        return not bool(getattr(downloader, "has_download_failures", False))
    return bool(getattr(downloader, "all_success", True))


class JMDownloadManager(JMClientMixin):
    """JMComic 下载管理器"""

    def __init__(self, config_manager: JMConfigManager):
        self.config = config_manager

    async def download_album(self, album_id, progress_callback=None, skip_photos: int = 0) -> DownloadResult:
        if not self.is_available():
            return DownloadResult(False, album_id, "", "", 0, 0, Path(), error_message="jmcomic 库未安装")
        try:
            option = self._get_option()
            if option is None:
                return DownloadResult(False, album_id, "", "", 0, 0, Path(), error_message="无法创建下载配置")
            return await self._run_with_progress(
                self._download_album_sync, (album_id, option, skip_photos), progress_callback
            )
        except Exception as e:
            _, friendly = classify_exception(e)
            return DownloadResult(False, album_id, "", "", 0, 0, Path(), error_message=friendly)

    def _download_album_sync(self, album_id, option, skip_photos=0, progress_holder=None) -> DownloadResult:
        try:
            jmcomic = import_jmcomic()
            if jmcomic is None:
                return DownloadResult(False, album_id, "", "", 0, 0, Path(), error_message="jmcomic 库未安装")
            parsed_id = jmcomic.JmcomicText.parse_to_jm_id(album_id)
            downloader_cls = _get_progress_downloader_class(jmcomic)
            downloader = downloader_cls(option)
            downloader.skip_photos = max(0, int(skip_photos))
            if progress_holder is not None:
                progress_holder["downloader"] = downloader

            with downloader:
                album = downloader.download_album(parsed_id)

            save_path = Path(option.dir_rule.decide_album_root_dir(album))
            failed_images = len(getattr(downloader, "download_failed_image", []))
            failed_images += len(getattr(downloader, "download_failed_photo", []))
            all_success = _resolve_all_success(downloader, skip_photos)
            image_count = getattr(downloader, "downloaded_images", 0) or album.page_count

            return DownloadResult(
                success=True, album_id=str(album.id), title=album.title,
                author=album.author, photo_count=len(album), image_count=image_count,
                save_path=save_path, all_success=all_success, failed_images=failed_images,
            )
        except Exception as e:
            _, friendly = classify_exception(e)
            return DownloadResult(False, album_id, "", "", 0, 0, Path(), error_message=friendly)

    async def download_photo(self, photo_id, progress_callback=None) -> DownloadResult:
        if not self.is_available():
            return DownloadResult(False, photo_id, "", "", 0, 0, Path(), error_message="jmcomic 库未安装")
        try:
            option = self._get_option()
            if option is None:
                return DownloadResult(False, photo_id, "", "", 0, 0, Path(), error_message="无法创建下载配置")
            return await self._run_with_progress(
                self._download_photo_sync, (photo_id, option), progress_callback
            )
        except Exception as e:
            _, friendly = classify_exception(e)
            return DownloadResult(False, photo_id, "", "", 0, 0, Path(), error_message=friendly)

    def _download_photo_sync(self, photo_id, option, progress_holder=None) -> DownloadResult:
        try:
            jmcomic = import_jmcomic()
            if jmcomic is None:
                return DownloadResult(False, photo_id, "", "", 0, 0, Path(), error_message="jmcomic 库未安装")
            parsed_id = jmcomic.JmcomicText.parse_to_jm_id(photo_id)
            downloader_cls = _get_progress_downloader_class(jmcomic)
            downloader = downloader_cls(option)
            if progress_holder is not None:
                progress_holder["downloader"] = downloader

            with downloader:
                photo = downloader.download_photo(parsed_id)

            save_path = Path(option.decide_image_save_dir(photo))
            image_count = len(photo.images) if hasattr(photo, "images") else 0
            failed_images = len(getattr(downloader, "download_failed_image", []))
            failed_images += len(getattr(downloader, "download_failed_photo", []))
            all_success = bool(getattr(downloader, "all_success", True))

            return DownloadResult(
                success=True, album_id=str(photo.album_id) if hasattr(photo, "album_id") else photo_id,
                title=photo.title if hasattr(photo, "title") else "", author="",
                photo_count=1, image_count=image_count, save_path=save_path,
                all_success=all_success, failed_images=failed_images,
            )
        except Exception as e:
            _, friendly = classify_exception(e)
            return DownloadResult(False, photo_id, "", "", 0, 0, Path(), error_message=friendly)

    async def _run_with_progress(self, sync_func, args, progress_callback) -> DownloadResult:
        progress_holder: dict = {}
        task = asyncio.create_task(self._run_sync(sync_func, *args, progress_holder))
        if progress_callback is not None:
            await self._poll_progress(task, progress_holder, progress_callback)
        return await task

    @staticmethod
    async def _poll_progress(task, progress_holder, progress_callback, interval: float = 2.0):
        last_bucket = -1
        while not task.done():
            await asyncio.sleep(interval)
            downloader = progress_holder.get("downloader")
            view = getattr(downloader, "progress_view", None)
            if view is None:
                continue
            done, total, unit = view()
            if total <= 0 or done <= 0 or done >= total:
                continue
            bucket = int(done * 10 / total)
            if bucket != last_bucket:
                last_bucket = bucket
                try:
                    await progress_callback(done, total, unit)
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════
#  认证管理模块
# ═══════════════════════════════════════════════════════════

class JMAuthManager(JMClientMixin):
    """JMComic 认证管理器"""

    def __init__(self, config_manager: JMConfigManager):
        self.config = config_manager
        self._logged_in = False
        self._username: str | None = None
        self._try_restore_session()

    def _try_restore_session(self):
        cookies_file = self.config.cookies_file
        if not cookies_file.exists():
            return
        try:
            with open(cookies_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        username = data.get("username")
        cookies = data.get("cookies")
        if username and cookies:
            try:
                option = self._get_option()
                if option is not None:
                    option.update_cookies(cookies)
                    self._username = username
                    self._logged_in = True
                    logger.info(f"已从本地恢复 JM 登录会话: {username}")
                    return
            except Exception:
                pass
        if username:
            self._username = username
            logger.info(f"发现已保存的 JM 登录用户名: {username}（需要重新登录）")

    async def validate_session(self) -> bool:
        """异步验证当前会话是否有效。

        采用 fail-open 策略：只要本地保存了 cookies 且 _logged_in 为 True，
        就视为会话有效。真正的会话过期会在实际 API 调用时抛出异常，
        无需主动探测（探测端点不可靠且会触发不必要的重登）。
        """
        if not self._logged_in:
            return False
        # 检查 cookies 文件是否存在且有效
        cookies_file = self.config.cookies_file
        try:
            if not cookies_file.exists():
                return False
            with open(cookies_file, encoding="utf-8") as f:
                data = json.load(f)
            # cookies 中存在实质内容（非空）
            return bool(data.get("cookies"))
        except Exception:
            # 读取失败也视为有效（fail-open），交给实际 API 调用判断
            return True

    async def ensure_valid_session(self):
        """确保会话有效，无效则尝试自动重新登录。

        Returns:
            (bool, str): (是否成功, 消息)
        """
        if self._logged_in:
            valid = await self.validate_session()
            if valid:
                return True, f"已登录: {self._username}"

            # 会话已过期，清除登录状态
            logger.warning(f"JM 会话已过期，尝试自动重新登录: {self._username}")
            self._logged_in = False

        # 尝试使用配置的凭据自动登录
        if self.config.has_credentials():
            return await self.auto_login()

        return False, "未登录或会话已过期，请重新登录"

    def _save_session(self, cookies=None):
        if not self._logged_in or not self._username:
            return
        cookies_file = self.config.cookies_file
        try:
            data = {"username": self._username, "logged_in": True}
            if cookies:
                data["cookies"] = cookies
            with open(cookies_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存 JM 登录信息失败: {e}")

    def _clear_session(self):
        cookies_file = self.config.cookies_file
        if cookies_file.exists():
            try:
                cookies_file.unlink()
            except Exception as e:
                logger.error(f"清除 JM 登录信息失败: {e}")

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @property
    def current_user(self) -> str | None:
        return self._username if self._logged_in else None

    def get_client(self):
        """获取客户端：每次新建，避免并发操作共享同一已认证 client。

        若已恢复登录状态（cookies 已注入 option），新建的 client 会自动带上登录态。
        """
        return self._build_client()

    async def login(self, username: str, password: str) -> tuple[bool, str]:
        if not self.is_available():
            return False, "jmcomic 库未安装"
        try:
            return await self._run_sync(self._login_sync, username, password)
        except Exception as e:
            logger.error(f"JM 登录失败: {e}")
            return False, f"登录失败: {str(e)}"

    def _login_sync(self, username, password):
        try:
            option = self._get_option()
            if option is None:
                return False, "无法创建配置"
            client = option.new_jm_client()
            client.login(username, password)
            self._logged_in = True
            self._username = username

            cookies = None
            try:
                cookies = dict(client["cookies"])
            except Exception:
                pass
            if cookies:
                try:
                    option.update_cookies(cookies)
                except Exception:
                    pass
            self._save_session(cookies)
            logger.info(f"JM 用户 {username} 登录成功")
            return True, f"登录成功，欢迎 {username}！"
        except Exception as e:
            error_msg = str(e)
            if "password" in error_msg.lower() or "用户名" in error_msg:
                return False, "用户名或密码错误"
            elif "network" in error_msg.lower() or "connect" in error_msg.lower():
                return False, "网络连接失败，请稍后重试"
            return False, f"登录失败: {error_msg}"

    async def auto_login(self):
        if not self.config.has_credentials():
            return False, "未配置登录凭据"
        if self._logged_in:
            return True, f"已登录: {self._username}"
        return await self.login(self.config.jm_username, self.config.jm_password)

    async def ensure_logged_in(self):
        """确保已登录

        仅检查本地会话标志和 cookies 文件，不做端点点探测。
        真正的会话有效性由实际 API 调用判断（fail-open 策略）。
        """
        if self._logged_in:
            return True, f"已登录: {self._username}"
        if self.config.has_credentials():
            return await self.auto_login()
        return False, "未登录，请登录后使用"

    def logout(self):
        if not self._logged_in:
            return False, "当前未登录"
        username = self._username
        self._logged_in = False
        self._username = None
        self._clear_session()
        logger.info(f"JM 用户 {username} 已登出")
        return True, f"已登出账号 {username}"

    def get_login_status(self):
        return {
            "logged_in": self._logged_in,
            "username": self._username,
            "has_credentials": self.config.has_credentials(),
        }


# ═══════════════════════════════════════════════════════════
#  打包模块（ZIP / PDF / 长图）
# ═══════════════════════════════════════════════════════════

try:
    import pyzipper
    PYZIPPER_AVAILABLE = True
except ImportError:
    PYZIPPER_AVAILABLE = False

try:
    import fitz  # pymupdf
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

_LONG_IMG_WIDTH = 1200
_LONG_IMG_MAX_STRIP_HEIGHT = 12000
_LONG_IMG_MAX_PER_STRIP = 30
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@dataclass
class PackResult:
    """打包结果"""
    success: bool
    output_path: Path | None
    format: str
    encrypted: bool
    error_message: str | None = None


def _collect_images_sorted(source_dir: Path) -> list:
    import re as _re

    def natural_key(path: Path):
        rel = str(path.relative_to(source_dir))
        return [
            (0, int(token)) if token.isdigit() else (1, token.lower())
            for token in _re.split(r"(\d+)", rel)
        ]

    files = [
        Path(root) / name
        for root, _dirs, names in os.walk(source_dir)
        for name in names
        if (Path(root) / name).suffix.lower() in _IMAGE_EXTENSIONS
    ]
    files.sort(key=natural_key)
    return files


class JMPacker:
    """JMComic 打包器"""

    def __init__(self, pack_format: str = "zip", password: str = ""):
        self.pack_format = pack_format.lower()
        self.password = password

    def pack(self, source_dir: Path, output_name: str, output_dir: Path | None = None) -> PackResult:
        if not source_dir.exists():
            return PackResult(False, None, self.pack_format, bool(self.password),
                              error_message=f"源目录不存在: {source_dir}")
        if output_dir is None:
            output_dir = source_dir.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.pack_format == "zip":
            return self._pack_zip(source_dir, output_name, output_dir)
        elif self.pack_format == "pdf":
            return self._pack_pdf(source_dir, output_name, output_dir)
        elif self.pack_format == "long_img":
            return self._pack_long_img(source_dir, output_name, output_dir)
        elif self.pack_format == "none":
            return PackResult(True, source_dir, "none", False)
        else:
            return PackResult(False, None, self.pack_format, False,
                              error_message=f"不支持的打包格式: {self.pack_format}")

    def _pack_zip(self, source_dir, output_name, output_dir) -> PackResult:
        output_path = output_dir / f"{output_name}.zip"
        if self.password and not PYZIPPER_AVAILABLE:
            return PackResult(False, None, "zip", False,
                              error_message="已设置打包密码但未安装 pyzipper，无法生成加密 ZIP")
        try:
            if self.password:
                with pyzipper.AESZipFile(output_path, "w",
                                         compression=pyzipper.ZIP_DEFLATED,
                                         encryption=pyzipper.WZ_AES) as zf:
                    zf.setpassword(self.password.encode("utf-8"))
                    for root, dirs, files in os.walk(source_dir):
                        for file in files:
                            file_path = Path(root) / file
                            zf.write(file_path, file_path.relative_to(source_dir))
            else:
                import zipfile
                with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, files in os.walk(source_dir):
                        for file in files:
                            file_path = Path(root) / file
                            zf.write(file_path, file_path.relative_to(source_dir))
            return PackResult(True, output_path, "zip", bool(self.password))
        except Exception as e:
            return PackResult(False, None, "zip", False, error_message=str(e))

    def _pack_pdf(self, source_dir, output_name, output_dir) -> PackResult:
        if not PYMUPDF_AVAILABLE:
            return PackResult(False, None, "pdf", False, error_message="pymupdf 库未安装，无法创建PDF")
        output_path = output_dir / f"{output_name}.pdf"
        try:
            image_files = _collect_images_sorted(source_dir)
            if not image_files:
                return PackResult(False, None, "pdf", False, error_message="未找到图片文件")
            doc = fitz.open()
            for img_path in image_files:
                try:
                    img = fitz.open(img_path)
                    pdfbytes = img.convert_to_pdf()
                    img.close()
                    imgpdf = fitz.open("pdf", pdfbytes)
                    doc.insert_pdf(imgpdf)
                    imgpdf.close()
                except Exception:
                    continue
            if doc.page_count == 0:
                doc.close()
                return PackResult(False, None, "pdf", False, error_message="无法创建PDF页面")
            if self.password:
                doc.save(output_path, encryption=fitz.PDF_ENCRYPT_AES_256,
                         owner_pw=self.password, user_pw=self.password,
                         permissions=fitz.PDF_PERM_ACCESSIBILITY)
            else:
                doc.save(output_path)
            doc.close()
            return PackResult(True, output_path, "pdf", bool(self.password))
        except Exception as e:
            return PackResult(False, None, "pdf", False, error_message=str(e))

    def _pack_long_img(self, source_dir, output_name, output_dir) -> PackResult:
        if not PIL_AVAILABLE:
            return PackResult(False, None, "long_img", False, error_message="Pillow 库未安装，无法生成长图")
        image_files = _collect_images_sorted(source_dir)
        if not image_files:
            return PackResult(False, None, "long_img", False, error_message="未找到图片文件")
        try:
            strips = self._build_long_strips(image_files)
        except Exception as e:
            return PackResult(False, None, "long_img", False, error_message=str(e))
        if not strips:
            return PackResult(False, None, "long_img", False, error_message="无法生成长图")
        try:
            if len(strips) == 1:
                output_path = output_dir / f"{output_name}.png"
                strips[0].save(output_path)
                strips[0].close()
                return PackResult(True, output_path, "long_img", False)
            import tempfile
            tmp_dir = Path(tempfile.mkdtemp(prefix="jm_longimg_"))
            try:
                for index, strip in enumerate(strips, 1):
                    strip.save(tmp_dir / f"{output_name}_{index:03d}.png")
                    strip.close()
                zip_result = self._pack_zip(tmp_dir, output_name, output_dir)
                return PackResult(zip_result.success, zip_result.output_path, "long_img",
                                  zip_result.encrypted, zip_result.error_message)
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as e:
            return PackResult(False, None, "long_img", False, error_message=str(e))

    def _build_long_strips(self, image_files):
        strips = []
        batch = []
        batch_height = 0

        def flush_batch():
            nonlocal batch, batch_height
            if batch:
                strips.append(self._merge_vertical(batch))
                batch = []
                batch_height = 0

        for file_path in image_files:
            try:
                with Image.open(file_path) as raw:
                    scaled_height = max(1, int(raw.height * _LONG_IMG_WIDTH / raw.width))
                    img = raw.convert("RGB").resize((_LONG_IMG_WIDTH, scaled_height))
            except Exception:
                continue
            if batch and (batch_height + img.height > _LONG_IMG_MAX_STRIP_HEIGHT
                          or len(batch) >= _LONG_IMG_MAX_PER_STRIP):
                flush_batch()
            batch.append(img)
            batch_height += img.height
        flush_batch()
        return strips

    @staticmethod
    def _merge_vertical(images):
        total_height = sum(im.height for im in images)
        canvas = Image.new("RGB", (_LONG_IMG_WIDTH, total_height), (255, 255, 255))
        offset_y = 0
        for im in images:
            canvas.paste(im, (0, offset_y))
            offset_y += im.height
            im.close()
        return canvas

    @staticmethod
    def cleanup(path: Path) -> bool:
        import shutil
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.is_file():
                path.unlink()
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
#  配额管理（合并到主程序数据库）
# ═══════════════════════════════════════════════════════════

class DownloadQuotaManager:
    """下载配额管理器 - 使用主程序数据库"""

    def __init__(self):
        self._init_db()

    def _get_connection(self):
        return get_db_connection()

    def _init_db(self):
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS download_quota (
                        user_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        count INTEGER DEFAULT 0,
                        PRIMARY KEY (user_id, date)
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"初始化配额数据库失败: {e}")

    def _get_today(self) -> str:
        return date.today().isoformat()

    def get_used_count(self, user_id: str) -> int:
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT count FROM download_quota WHERE user_id = ? AND date = ?",
                    (str(user_id), self._get_today()),
                )
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def reserve(self, user_id: str, limit: int) -> tuple[bool, int, int]:
        if limit <= 0:
            return True, 0, 0
        today = self._get_today()
        conn = self._get_connection()
        try:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT count FROM download_quota WHERE user_id = ? AND date = ?",
                (str(user_id), today),
            ).fetchone()
            used = row[0] if row else 0
            if used >= limit:
                conn.execute("ROLLBACK")
                return False, used, limit
            conn.execute(
                """
                INSERT INTO download_quota (user_id, date, count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1
                """,
                (str(user_id), today),
            )
            conn.execute("COMMIT")
            return True, used + 1, limit
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            return True, 0, limit
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════
#  订阅管理（合并到主程序数据库）
# ═══════════════════════════════════════════════════════════

class SubscriptionManager:
    """本子更新订阅管理器 - 使用主程序数据库"""

    def __init__(self):
        self._init_db()

    def _get_connection(self):
        return get_db_connection()

    def _init_db(self):
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS jm_subscriptions (
                        umo TEXT NOT NULL,
                        album_id TEXT NOT NULL,
                        user_id TEXT,
                        title TEXT,
                        last_count INTEGER DEFAULT 0,
                        PRIMARY KEY (umo, album_id)
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"初始化订阅数据库失败: {e}")

    def add(self, umo: str, album_id: str, user_id: str, title: str, last_count: int) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO jm_subscriptions (umo, album_id, user_id, title, last_count)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(umo, album_id) DO UPDATE SET
                        user_id = excluded.user_id,
                        title = excluded.title,
                        last_count = excluded.last_count
                    """,
                    (str(umo), str(album_id), str(user_id), title, int(last_count)),
                )
                conn.commit()
            return True
        except Exception:
            return False

    def remove(self, umo: str, album_id: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM jm_subscriptions WHERE umo = ? AND album_id = ?",
                    (str(umo), str(album_id)),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception:
            return False

    def exists(self, umo: str, album_id: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM jm_subscriptions WHERE umo = ? AND album_id = ?",
                    (str(umo), str(album_id)),
                )
                return cursor.fetchone() is not None
        except Exception:
            return False

    def get_last_count(self, umo: str, album_id: str):
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT last_count FROM jm_subscriptions WHERE umo = ? AND album_id = ?",
                    (str(umo), str(album_id)),
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def update_count(self, umo: str, album_id: str, count: int):
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE jm_subscriptions SET last_count = ? WHERE umo = ? AND album_id = ?",
                    (int(count), str(umo), str(album_id)),
                )
                conn.commit()
        except Exception:
            pass

    def list_for(self, umo: str) -> list:
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT album_id, title, last_count FROM jm_subscriptions WHERE umo = ?",
                    (str(umo),),
                )
                return [{"album_id": r[0], "title": r[1], "last_count": r[2]}
                        for r in cursor.fetchall()]
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════
#  QThread 异步任务（基于主程序 PYQt5）
# ═══════════════════════════════════════════════════════════

class AsyncTask(QThread):
    """在线程中运行 asyncio 协程"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str, str)

    def __init__(self, coro_func, *args, parent=None):
        super().__init__(parent)
        self._coro_func = coro_func
        self._args = args

    def run(self):
        try:
            result = asyncio.run(self._coro_func(*self._args))
            self.finished.emit(result)
        except Exception as e:
            try:
                etype, emsg = classify_exception(e)
            except Exception:
                etype, emsg = "error", str(e)
            self.error.emit(etype, emsg)


class DownloadTask(QThread):
    """下载任务线程"""
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str, str)

    def __init__(self, downloader, album_id, skip=0, chapter_idx=None, parent=None):
        super().__init__(parent)
        self._downloader = downloader
        self._album_id = album_id
        self._skip = skip
        self._chapter_idx = chapter_idx

    def run(self):
        try:
            async def _run():
                progress_cb = self._make_cb()
                if self._chapter_idx is not None:
                    return await self._downloader.download_photo(self._album_id, progress_cb)
                return await self._downloader.download_album(self._album_id, progress_cb, self._skip)

            self.finished.emit(asyncio.run(_run()))
        except Exception as e:
            try:
                etype, emsg = classify_exception(e)
            except Exception:
                etype, emsg = "download_failed", str(e)
            self.error.emit(etype, emsg)

    def _make_cb(self):
        last_bucket = -1

        async def _on_progress(done, total, unit):
            nonlocal last_bucket
            if total <= 0:
                return
            bucket = int(done * 10 / total)
            if bucket != last_bucket:
                last_bucket = bucket
                self.progress.emit(done, total, unit)

        return _on_progress


# ═══════════════════════════════════════════════════════════
#  应用服务层（统一入口）
# ═══════════════════════════════════════════════════════════

class JMComicService(QObject):
    """JMComic 统一服务入口"""

    def __init__(self, data_dir: Path | str | None = None, parent=None):
        super().__init__(parent)

        if data_dir is None:
            from core.config import config as CFG
            data_dir = CFG.data
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 从主程序配置读取 jmcomic 设置
        settings = self._load_settings()

        self.config = JMConfigManager(settings, self.data_dir)
        self.browser = JMBrowser(self.config)
        self.downloader = JMDownloadManager(self.config)
        self.auth = JMAuthManager(self.config)
        self.quota = DownloadQuotaManager()
        self.subscribe = SubscriptionManager()

        self._tasks = []

    def _load_settings(self) -> dict:
        """从主程序配置加载 JM 设置"""
        from core.config import config as CFG
        settings = dict(JM_DEFAULTS)
        # 从主程序 config.json 读取 jmcomic 相关配置（如果有）
        for key in JM_DEFAULTS:
            cfg_key = f"jm_{key}" if key not in ("download_dir", "image_suffix", "client_type",
                                                  "client_domain", "retry_times", "use_proxy",
                                                  "proxy_url", "max_concurrent_photos",
                                                  "max_concurrent_images", "pack_format",
                                                  "pack_password", "filename_show_password") else key
            if cfg_key in CFG.cfg:
                settings[key] = CFG.cfg[cfg_key]
        return settings

    def save_settings(self, values: dict):
        """保存 JM 设置到主程序配置"""
        from core.config import config as CFG
        prefix_keys = ("jm_username", "jm_password", "subscribe_check_interval", "debug_mode",
                       "daily_download_limit", "auto_delete_after_send")
        for k, v in values.items():
            if k in prefix_keys:
                CFG[f"jm_{k}"] = v
            else:
                CFG[k] = v
        # 重新加载配置
        self.config = JMConfigManager(self._load_settings(), self.data_dir)
        self.browser = JMBrowser(self.config)
        self.downloader = JMDownloadManager(self.config)
        self.auth = JMAuthManager(self.config)

    # ---------- 通用异步 ----------
    def submit(self, coro_func, *args, on_done=None, on_error=None):
        task = AsyncTask(coro_func, *args, parent=self)
        task._gui_on_done = on_done
        task._gui_on_error = on_error
        task.finished.connect(self._handle_task_result)
        task.error.connect(self._handle_task_error)
        task.finished.connect(task.deleteLater)
        task.error.connect(task.deleteLater)
        self._tasks.append(task)
        task.finished.connect(lambda *_: self._prune_tasks(task))
        task.error.connect(lambda *_: self._prune_tasks(task))
        task.start()
        return task

    def _prune_tasks(self, task):
        try:
            if task in self._tasks:
                self._tasks.remove(task)
        except Exception:
            pass

    def _handle_task_result(self, result):
        callback = getattr(self.sender(), "_gui_on_done", None)
        if callback is not None:
            try:
                callback(result)
            except Exception:
                traceback.print_exc()

    def _handle_task_error(self, etype, emsg):
        callback = getattr(self.sender(), "_gui_on_error", None)
        if callback is not None:
            try:
                callback(etype, emsg)
            except Exception:
                traceback.print_exc()

    # ---------- 使用量记录 ----------
    @staticmethod
    def _record_usage(action: str, detail: str = '', username: str = ''):
        """记录 JMComic 使用量"""
        try:
            from core.database import record_usage
            record_usage('jmcomic', action, detail, username)
        except Exception:
            pass

    # ---------- 浏览 ----------
    def search(self, keyword, page, mode, on_done, on_error):
        self._record_usage('search', f'{mode}:{keyword}')
        return self.submit(self.browser.search_albums, keyword, page, mode,
                           on_done=on_done, on_error=on_error)

    def get_detail(self, album_id, on_done, on_error):
        self._record_usage('browse', f'detail:{album_id}')
        return self.submit(self.browser.get_album_detail, album_id,
                           on_done=on_done, on_error=on_error)

    def get_ranking(self, rank_type, page, category, on_done, on_error):
        self._record_usage('browse', f'rank:{rank_type}:{category}')
        method = {
            "day": self.browser.get_day_ranking,
            "week": self.browser.get_week_ranking,
            "month": self.browser.get_month_ranking,
        }[rank_type]
        return self.submit(method, page, category, on_done=on_done, on_error=on_error)

    def get_category_albums(self, category, order_by, time_range, page, on_done, on_error):
        self._record_usage('browse', f'category:{category}')
        return self.submit(self.browser.get_category_albums, category, order_by, time_range, page,
                           on_done=on_done, on_error=on_error)

    # ---------- 账号 ----------
    def login(self, username, password, on_done, on_error):
        self._record_usage('login', username)
        return self.submit(self.auth.login, username, password,
                           on_done=on_done, on_error=on_error)

    def ensure_valid_session(self, on_done, on_error):
        """确保会话有效，无效则尝试自动重新登录"""
        return self.submit(self.auth.ensure_valid_session,
                           on_done=on_done, on_error=on_error)

    def get_favorites(self, client, page, folder_id, username, on_done, on_error):
        self._record_usage('browse', 'favorites')
        return self.submit(self.browser.get_favorites, client, page, folder_id, username,
                           on_done=on_done, on_error=on_error)

    # ---------- 下载 ----------
    def download(self, album_id, skip, chapter_idx, on_progress, on_done, on_error):
        self._record_usage('download', album_id)
        task = DownloadTask(self.downloader, album_id, skip, chapter_idx, parent=self)
        task.progress.connect(on_progress)
        task.finished.connect(on_done)
        task.error.connect(on_error)
        task.finished.connect(task.deleteLater)
        task.error.connect(task.deleteLater)
        self._tasks.append(task)
        task.finished.connect(lambda *_: self._prune_tasks(task))
        task.error.connect(lambda *_: self._prune_tasks(task))
        task.start()
        return task

    def pack(self, source_dir, output_name, pack_format, password):
        self._record_usage('pack', pack_format)
        packer = JMPacker(pack_format=pack_format, password=password)
        return packer.pack(source_dir, output_name)

    def generate_filename(self, album_id, password, chapter_idx, show_password):
        timestamp = int(time.time())
        if chapter_idx is not None:
            name = f"{album_id}_Ch{chapter_idx}_{timestamp}"
        else:
            name = f"{album_id}_{timestamp}"
        if show_password and password:
            name += f"#PW{password}"
        return name

    def stop_all_tasks(self, timeout_ms=2000):
        for task in list(self._tasks):
            try:
                if task.isRunning():
                    task.wait(timeout_ms)
            except Exception:
                pass