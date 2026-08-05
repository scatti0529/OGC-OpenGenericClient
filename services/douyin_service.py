# -*- coding: utf-8 -*-
"""抖音视频/合集下载服务层

集成 douyinDL-main 的核心功能，适配当前项目的下载目录/数据库结构。
"""
import asyncio
import json
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml

# ── f2 msToken 兜底补丁（必须在导入 crawler/model 之前打） ──
from f2.apps.douyin.utils import TokenManager as _F2TokenManager

_original_gen_real_msToken = _F2TokenManager.gen_real_msToken.__func__


def _safe_gen_real_msToken(cls):
    try:
        return _original_gen_real_msToken(cls)
    except Exception:
        return _F2TokenManager.gen_false_msToken()


_F2TokenManager.gen_real_msToken = classmethod(_safe_gen_real_msToken)

from f2.apps.douyin.crawler import DouyinCrawler
from f2.apps.douyin.model import UserMix, PostDetail
from f2.apps.douyin.filter import UserMixFilter, PostDetailFilter
from f2.apps.douyin.utils import TokenManager

from core.config import config as CFG


# ══════════════ 配置加载 ══════════════

class DouyinConfig:
    """抖音下载配置，从全局配置中读取，缺失时用默认值。"""

    DEFAULTS = {
        'output_dir': '',
        'max_counts': 0,
        'force': False,
        'user_agent': ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"),
        'timeout': 15,
        'max_retries': 5,
        'max_tasks': 1,
        'max_connections': 5,
        'page_counts': 10,
        'api_request_interval': 2.0,
        'mix_download_interval': 10,
        'chunk_size': 65536,
        'filename_max_len': 60,
        'download_max_retries': 3,
        'download_retry_interval': 5.0,
        'max_download_speed': 10485760,
        'save_metadata': False,
        'save_cover': True,
        'save_desc': True,
        'save_music': True,
        'save_json': True,
        'enable_progress': True,
    }

    def __init__(self):
        for key, default in self.DEFAULTS.items():
            setattr(self, key, CFG.get(f'douyin_{key}', default))
        # 输出目录：优先使用配置的，否则用默认下载目录
        if not self.output_dir:
            self.output_dir = str(get_douyin_output_dir())

    @property
    def default_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Referer": "https://www.douyin.com/",
        }


# ══════════════ URL 解析 ══════════════

_MIX_PATH_PATTERN = re.compile(r"/(?:share/mix/detail|collection)/(\d+)")
_AWEME_ID_PATTERN = re.compile(r"/video/(\d+)")
_AWEME_ID_QS_PATTERN = re.compile(r"[?&]modal_id=(\d+)")
_MIX_ID_QS_PATTERN = re.compile(r"[?&](?:collection_id|mix_id)=(\d+)")


def _try_resolve(url: str) -> Optional[Tuple[str, str]]:
    m = _MIX_PATH_PATTERN.search(url)
    if m:
        return "mix", m.group(1)
    m = _AWEME_ID_PATTERN.search(url)
    if m:
        return "one", m.group(1)
    m = _MIX_ID_QS_PATTERN.search(url)
    if m:
        return "mix", m.group(1)
    m = _AWEME_ID_QS_PATTERN.search(url)
    if m:
        return "one", m.group(1)
    return None


async def resolve_share_url(share_url: str, config: DouyinConfig) -> Tuple[str, str]:
    """解析抖音分享短链接，返回 (资源类型, 资源ID)。"""
    url = share_url.strip()
    res = _try_resolve(url)
    if res:
        return res

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": config.user_agent},
        proxy=None,
        timeout=config.timeout,
    ) as client:
        resp = await client.get(url)
        final_url = str(resp.url)

    res = _try_resolve(final_url)
    if res:
        return res

    raise ValueError(f"无法从链接解析资源类型: {share_url} → {final_url}")


# ══════════════ Token 与 Crawler ══════════════

def build_cookie() -> str:
    ttwid = TokenManager.gen_ttwid()
    ms_token = TokenManager.gen_false_msToken()
    return f"ttwid={ttwid}; msToken={ms_token}"


def build_crawler_kwargs(cookie: str, config: DouyinConfig) -> Dict[str, Any]:
    return {
        "headers": config.default_headers,
        "cookie": cookie,
        "proxies": {"http://": None, "https://": None},
        "max_tasks": config.max_tasks,
        "max_connections": config.max_connections,
        "max_retries": config.max_retries,
        "timeout": config.timeout,
    }


# ══════════════ 合集/视频获取 ══════════════

def _extract_mix_name(response: Any) -> str:
    try:
        data = response.json() if hasattr(response, "json") else response
        if isinstance(data, dict):
            aweme_list = data.get("aweme_list") or []
            if aweme_list:
                mix_info = aweme_list[0].get("mix_info") or {}
                return mix_info.get("mix_name") or ""
    except Exception:
        pass
    return ""


def _extract_video_meta(aweme: Dict[str, Any]) -> Dict[str, Any]:
    if not aweme or not isinstance(aweme, dict):
        return {}
    video = aweme.get("video") or {}
    bit_rate_list = video.get("bit_rate") or []
    br0 = bit_rate_list[0] if bit_rate_list and len(bit_rate_list) > 0 else {}
    play_addr = br0.get("play_addr") or {}
    stats = aweme.get("statistics") or {}
    author = aweme.get("author") or {}
    create_ts = aweme.get("create_time")
    create_time_str = ""
    if create_ts and isinstance(create_ts, (int, float)):
        try:
            create_time_str = datetime.fromtimestamp(
                int(create_ts), tz=datetime.now().astimezone().tzinfo
            ).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            create_time_str = ""
    return {
        "duration": video.get("duration"),
        "width": video.get("width"),
        "height": video.get("height"),
        "file_size": play_addr.get("data_size"),
        "bit_rate": br0.get("bit_rate"),
        "fps": br0.get("FPS"),
        "ratio": video.get("ratio"),
        "video_format": video.get("format"),
        "is_h265": 1 if br0.get("is_h265") else 0,
        "nickname": author.get("nickname"),
        "digg_count": stats.get("digg_count"),
        "comment_count": stats.get("comment_count"),
        "share_count": stats.get("share_count"),
        "collect_count": stats.get("collect_count"),
        "create_time": create_time_str,
    }


async def fetch_mix_videos(
    mix_id: str,
    config: DouyinConfig,
    max_counts: int = 0,
) -> Tuple[str, List[Dict[str, Any]]]:
    cookie = build_cookie()
    kwargs = build_crawler_kwargs(cookie, config)

    limit = max_counts if max_counts > 0 else float("inf")
    cursor = 0
    collected: List[Dict[str, Any]] = []
    mix_name = ""

    while len(collected) < limit:
        current_size = min(config.page_counts, limit - len(collected))
        async with DouyinCrawler(kwargs) as crawler:
            params = UserMix(cursor=cursor, count=current_size, mix_id=mix_id)
            response = await crawler.fetch_user_mix(params)

        if not mix_name:
            mix_name = _extract_mix_name(response)

        mix = UserMixFilter(response)
        page_items = mix._to_list()
        if not page_items:
            break

        aweme_list = response.get("aweme_list", []) if isinstance(response, dict) else []
        for item, aweme in zip(page_items, aweme_list):
            item["_meta"] = _extract_video_meta(aweme)

        collected.extend(page_items)
        cursor = mix.max_cursor or 0
        if not mix.has_more:
            break
        await asyncio.sleep(config.api_request_interval)

    return mix_name, collected


async def fetch_one_video(aweme_id: str, config: DouyinConfig) -> Dict[str, Any]:
    cookie = build_cookie()
    kwargs = build_crawler_kwargs(cookie, config)

    async with DouyinCrawler(kwargs) as crawler:
        params = PostDetail(aweme_id=aweme_id)
        response = await crawler.fetch_post_detail(params)
        video = PostDetailFilter(response)

    item = video._to_dict()
    if not item:
        raise ValueError(f"未获取到视频信息，aweme_id={aweme_id}")

    aweme_detail = response.get("aweme_detail", {}) if isinstance(response, dict) else {}
    item["_meta"] = _extract_video_meta(aweme_detail)
    return item


# ══════════════ 文件名工具 ══════════════

def _random_interval(base: float) -> float:
    if base <= 0:
        return 0
    return random.uniform(base * 0.9, base)


def _sanitize_filename(name: str, max_len: int = 60) -> str:
    name = re.sub(r"#[^\s#]+", "", name)
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', "", name).strip()
    name = re.sub(r"[_\s]+", "_", name).strip("_")
    if len(name) > max_len:
        name = name[:max_len].strip("_")
    return name or "untitled"


def _extract_topics(desc: str) -> List[str]:
    return re.findall(r"#([^\s#_]+)", desc or "")


def _build_video_name(desc: str, aweme_id: str, max_len: int = 60) -> str:
    text = re.sub(r"#[^\s#]+", "", desc or "")
    text = re.sub(r'[\\/:*?"<>|\n\r\t]', "", text).strip()
    text = re.sub(r"[_\s]+", "_", text).strip("_")
    if not text:
        text = "_".join(_extract_topics(desc)).strip("_")
    if not text:
        text = "untitled"
    suffix = f"_{aweme_id}"
    budget = max_len - len(suffix)
    if budget > 0 and len(text) > budget:
        text = text[:budget].strip("_")
    return f"{text}{suffix}"


# ══════════════ 输出目录 ══════════════

def get_douyin_output_dir() -> Path:
    """获取抖音下载根目录（douyin-download）。"""
    try:
        from services.download_manager import get_download_root, PLATFORM_FOLDERS
        root = get_download_root()
        folder = PLATFORM_FOLDERS.get('douyin', 'douyin-download')
        return Path(root) / folder
    except Exception:
        return Path('data') / 'douyin-download'


def get_douyin_media_dir(file_type: str = 'video') -> Path:
    """获取抖音指定类型文件的下载目录（自动分类到 videos/images/audios）。"""
    try:
        from services.download_manager import get_platform_dir
        return Path(get_platform_dir('douyin', file_type))
    except Exception:
        base = get_douyin_output_dir()
        type_map = {'image': 'images', 'video': 'videos', 'audio': 'audios'}
        return base / type_map.get(file_type, 'videos')


class _NullContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


# ══════════════ 进度数据库（合并主库） ══════════════

class DouyinProgressDB:
    """抖音下载进度数据库（合并到项目主数据库 data/ogc_users.db）。"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            from core.database import DB_PATH
            self.db_path = Path(DB_PATH)
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> "DouyinProgressDB":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._migrate_schema()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _migrate_schema(self) -> None:
        if not self._conn:
            return
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS douyin_downloads (
                aweme_id        TEXT PRIMARY KEY,
                resource_type   TEXT NOT NULL,
                resource_id     TEXT NOT NULL,
                mix_name        TEXT,
                desc            TEXT,
                url             TEXT,
                file_path       TEXT,
                duration        INTEGER,
                width           INTEGER,
                height          INTEGER,
                file_size       INTEGER,
                bit_rate        INTEGER,
                fps             REAL,
                ratio           TEXT,
                video_format    TEXT,
                is_h265         INTEGER,
                nickname        TEXT,
                digg_count      INTEGER,
                comment_count   INTEGER,
                share_count     INTEGER,
                collect_count   INTEGER,
                create_time     TEXT,
                status          TEXT DEFAULT 'success',
                error_msg       TEXT,
                retry_count     INTEGER DEFAULT 0,
                downloaded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_douyin_resource_id ON douyin_downloads(resource_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_douyin_status ON douyin_downloads(status)"
        )
        self._conn.commit()

    def is_success_downloaded(self, aweme_id: str) -> bool:
        if not self._conn:
            return False
        cur = self._conn.execute(
            "SELECT 1 FROM douyin_downloads WHERE aweme_id = ? AND status = 'success'",
            (aweme_id,),
        )
        return cur.fetchone() is not None

    def record(self, aweme_id, resource_type, resource_id, mix_name, desc, file_path,
               url=None, meta=None, status="success", error_msg=None, retry_count=0):
        if not self._conn:
            return
        meta = meta or {}
        self._conn.execute(
            """INSERT INTO douyin_downloads
               (aweme_id, resource_type, resource_id, mix_name, desc, file_path, url,
                duration, width, height, file_size, bit_rate, fps, ratio,
                video_format, is_h265, nickname, digg_count, comment_count,
                share_count, collect_count, create_time,
                status, error_msg, retry_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(aweme_id) DO UPDATE SET
                   resource_type=excluded.resource_type,
                   resource_id=excluded.resource_id,
                   mix_name=excluded.mix_name,
                   desc=excluded.desc,
                   file_path=excluded.file_path,
                   url=COALESCE(excluded.url, url),
                   duration=excluded.duration,
                   width=excluded.width,
                   height=excluded.height,
                   file_size=excluded.file_size,
                   bit_rate=excluded.bit_rate,
                   fps=excluded.fps,
                   ratio=excluded.ratio,
                   video_format=excluded.video_format,
                   is_h265=excluded.is_h265,
                   nickname=excluded.nickname,
                   digg_count=excluded.digg_count,
                   comment_count=excluded.comment_count,
                   share_count=excluded.share_count,
                   collect_count=excluded.collect_count,
                   create_time=excluded.create_time,
                   status=excluded.status,
                   error_msg=excluded.error_msg,
                   retry_count=excluded.retry_count,
                   downloaded_at=CURRENT_TIMESTAMP
            """,
            (
                aweme_id, resource_type, resource_id, mix_name, desc, file_path, url,
                meta.get("duration"), meta.get("width"), meta.get("height"),
                meta.get("file_size"), meta.get("bit_rate"), meta.get("fps"),
                meta.get("ratio"), meta.get("video_format"), meta.get("is_h265"),
                meta.get("nickname"), meta.get("digg_count"),
                meta.get("comment_count"), meta.get("share_count"),
                meta.get("collect_count"), meta.get("create_time"),
                status, error_msg, retry_count,
            ),
        )
        self._conn.commit()

    def query_failed(self) -> List[Dict[str, Any]]:
        if not self._conn:
            return []
        cur = self._conn.execute(
            """SELECT aweme_id, resource_type, resource_id, mix_name, desc,
                      file_path, error_msg, retry_count
               FROM douyin_downloads WHERE status = 'failed'
               ORDER BY downloaded_at"""
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def count_by_resource(self, resource_id: str) -> int:
        if not self._conn:
            return 0
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM douyin_downloads WHERE resource_id = ? AND status = 'success'",
            (resource_id,),
        )
        return cur.fetchone()[0]


# ══════════════ 下载与元数据 ══════════════

async def download_video(video_url, save_path, config, headers=None, progress_callback=None) -> int:
    """流式下载视频文件。"""
    if not video_url:
        raise ValueError("视频下载地址为空")
    if video_url.startswith("//"):
        video_url = "https:" + video_url

    save_path.parent.mkdir(parents=True, exist_ok=True)
    req_headers = config.default_headers | (headers or {})

    max_speed = config.max_download_speed
    speed_limit_start = time.monotonic() if max_speed > 0 else 0

    downloaded = 0
    total = 0
    async with httpx.AsyncClient(
        follow_redirects=True, headers=req_headers, proxy=None, timeout=60,
    ) as client:
        async with client.stream("GET", video_url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            with open(save_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=config.chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        try:
                            progress_callback(downloaded, total)
                        except Exception:
                            pass
                    if max_speed > 0:
                        expected_time = downloaded / max_speed
                        actual_time = time.monotonic() - speed_limit_start
                        if actual_time < expected_time:
                            await asyncio.sleep(expected_time - actual_time)
    return downloaded


async def _download_simple(url: str, save_path: Path, config: DouyinConfig) -> int:
    """下载小文件（封面/音乐）。"""
    if not url:
        return 0
    if url.startswith("//"):
        url = "https:" + url
    save_path.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(
        follow_redirects=True, headers=config.default_headers, proxy=None, timeout=60,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        save_path.write_bytes(resp.content)
    return len(resp.content)


def _sanitize_dir_name(name: str, max_len: int = 60) -> str:
    """清理目录名中的非法字符。"""
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', "", name).strip()
    name = re.sub(r"[_\s]+", "_", name).strip("_")
    if len(name) > max_len:
        name = name[:max_len].strip("_")
    return name or "source"


def get_douyin_sourcefiles_dir() -> Path:
    """获取抖音 sourcefiles 目录（与 videos/images/audios 同级）。"""
    try:
        from services.download_manager import get_download_root, PLATFORM_FOLDERS
        root = get_download_root()
        folder = PLATFORM_FOLDERS.get('douyin', 'douyin-download')
        return Path(root) / folder / 'sourcefiles'
    except Exception:
        return get_douyin_output_dir() / 'sourcefiles'


async def download_metadata(video_data: Dict[str, Any], base_path: Path, config: DouyinConfig) -> None:
    """保存视频元数据（封面/文案/原声/JSON）。

    音频（原声 MP3）存入 audios/ 目录；
    封面/文案/JSON 存入 sourcefiles/文案名文件夹中。
    """
    if not config.save_metadata:
        return

    name = base_path.name
    desc = video_data.get("desc") or ""

    # ═══ 音频（原声）→ audios/ ═══
    if config.save_music:
        if video_data.get("music_status") == 1:
            music_url = video_data.get("music_play_url")
            if music_url:
                audio_dir = get_douyin_media_dir('audio')
                audio_dir.mkdir(parents=True, exist_ok=True)
                try:
                    await _download_simple(music_url, audio_dir / f"{name}.mp3", config)
                except Exception as e:
                    print(f"      原声下载失败: {e}")

    # ═══ 封面/文案/JSON → sourcefiles/文案名文件夹 ═══
    # 以链接文案命名文件夹
    folder_name = _sanitize_dir_name(desc, config.filename_max_len)
    source_dir = get_douyin_sourcefiles_dir() / folder_name
    source_dir.mkdir(parents=True, exist_ok=True)

    if config.save_cover:
        cover_url = video_data.get("cover")
        if cover_url:
            try:
                await _download_simple(cover_url, source_dir / f"{name}.jpg", config)
            except Exception as e:
                print(f"      封面下载失败: {e}")

    if config.save_desc:
        if desc:
            (source_dir / f"{name}.txt").write_text(desc, encoding="utf-8")

    if config.save_json:
        (source_dir / f"{name}.json").write_text(
            json.dumps(video_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


# ══════════════ 主下载器 ══════════════

class DouyinDownloader:
    """抖音视频/合集下载器。"""

    def __init__(self, output_dir=None, max_counts=0, config=None, force=False):
        self.config = config or DouyinConfig()
        # 输出目录优先级：显式参数 > config.output_dir > 默认下载目录
        if output_dir:
            self.output_dir = Path(output_dir)
        elif getattr(self.config, 'output_dir', ''):
            self.output_dir = Path(self.config.output_dir)
        else:
            self.output_dir = get_douyin_output_dir()
        self.max_counts = max_counts
        self.force = force

    def _get_progress_db(self) -> Optional[DouyinProgressDB]:
        if not self.config.enable_progress:
            return None
        return DouyinProgressDB()

    async def _download_with_retry(self, play_addr, save_path, progress_callback=None):
        cfg = self.config
        attempt = 0
        last_error = ""
        max_attempts = 1 + cfg.download_max_retries
        for attempt in range(max_attempts):
            try:
                await download_video(play_addr, save_path, cfg, progress_callback=progress_callback)
                return True, "", attempt
            except Exception as e:
                last_error = str(e)
                if attempt < cfg.download_max_retries:
                    print(f"      下载失败（第{attempt+1}次尝试），"
                          f"{cfg.download_retry_interval}秒后重试: {e}")
                    await asyncio.sleep(cfg.download_retry_interval)
                else:
                    print(f"      下载失败（共尝试{max_attempts}次，已用尽重试次数）: {e}")
        return False, last_error, attempt

    async def parse(self, share_url, log_callback=None) -> Dict[str, Any]:
        """解析抖音分享链接，返回视频列表（不下载）。

        Returns:
            {
                'kind': 'mix' 或 'one',
                'resource_id': 合集ID 或 视频ID,
                'mix_name': 合集名,
                'videos': 视频信息字典列表,
            }
        """
        def _log(msg):
            if log_callback:
                log_callback(msg)
            else:
                print(msg)

        cfg = self.config
        _log(f"解析分享链接: {share_url}")
        kind, resource_id = await resolve_share_url(share_url, cfg)

        mix_name = ""
        if kind == "mix":
            _log(f"检测到合集链接, mix_id={resource_id}")
            mix_name, videos = await fetch_mix_videos(
                resource_id, config=cfg, max_counts=self.max_counts)
            if mix_name:
                _log(f"合集名称: {mix_name}")
        else:
            _log(f"检测到单视频链接, aweme_id={resource_id}")
            videos = [await fetch_one_video(resource_id, cfg)]

        _log(f"共获取 {len(videos)} 个视频")
        return {
            'kind': kind,
            'resource_id': resource_id,
            'mix_name': mix_name,
            'videos': videos,
        }

    def _detect_media_type(self, video_data: Dict[str, Any]) -> str:
        """从视频数据推断媒体类型（video/image/audio）。"""
        # 检查是否有图片（图集模式）
        if video_data.get('images'):
            return 'image'
        # 视频类型
        aweme_type = video_data.get('aweme_type')
        if aweme_type in (2, 68, 150):  # 视频/直播等
            return 'video'
        # 兜底
        return 'video'

    async def download_single(
        self,
        video_data: Dict[str, Any],
        kind: str,
        resource_id: str,
        mix_name: str,
        share_url: str,
        index: int = 1,
        total: int = 1,
        progress_callback=None,
        log_callback=None,
    ) -> Dict[str, Any]:
        """下载单个视频（自动按文件类型分类到 videos/images/audios）。

        Returns:
            统计字典
        """
        def _log(msg):
            if log_callback:
                log_callback(msg)
            else:
                print(msg)

        cfg = self.config
        date_str = datetime.now().strftime("%Y%m%d")
        aweme_id = video_data.get("aweme_id", f"unknown_{index}")
        desc = video_data.get("desc") or ""
        play_addr = video_data.get("video_play_addr")
        if isinstance(play_addr, list):
            play_addr = play_addr[0] if play_addr else None

        if not play_addr:
            _log(f"[{index}/{total}] {aweme_id} 无视频地址，跳过")
            return {'aweme_id': aweme_id, 'success': False, 'skipped': True, 'error': '无视频地址'}

        # 判断媒体类型，自动分目录
        media_type = self._detect_media_type(video_data)
        type_dir = get_douyin_media_dir(media_type)

        # 合集：在类型目录下创建 日期_合集名 子目录
        if kind == "mix" and mix_name:
            safe_name = _sanitize_filename(mix_name, cfg.filename_max_len) or resource_id
            save_dir = type_dir / f"{date_str}_{safe_name}"
        else:
            save_dir = type_dir

        save_dir.mkdir(parents=True, exist_ok=True)

        # 文件扩展名
        if media_type == 'image':
            ext = '.jpg'
        elif media_type == 'audio':
            ext = '.mp3'
        else:
            ext = '.mp4'

        name = _build_video_name(desc, str(aweme_id), cfg.filename_max_len)
        if kind == "mix":
            save_path = save_dir / f"{index:03d}_{name}{ext}"
        else:
            save_path = save_dir / f"{date_str}_{name}{ext}"

        # 跳过判断
        progress_db = self._get_progress_db()
        if not self.force:
            if save_path.exists():
                _log(f"[{index}/{total}] {save_path.name} 文件已存在，跳过")
                return {'aweme_id': aweme_id, 'success': True, 'skipped': True,
                        'path': str(save_path)}
            if progress_db and progress_db.is_success_downloaded(str(aweme_id)):
                _log(f"[{index}/{total}] {save_path.name} 进度记录已存在，跳过")
                return {'aweme_id': aweme_id, 'success': True, 'skipped': True,
                        'path': str(save_path)}

        _log(f"[{index}/{total}] 下载 {save_path.name}")

        def _make_progress_cb():
            def _inner(cur, tot):
                if progress_callback:
                    progress_callback(cur, tot, index, total)
            return _inner

        download_ok, last_error, attempt = await self._download_with_retry(
            play_addr, save_path, _make_progress_cb())

        meta = video_data.get("_meta") or {}

        if download_ok:
            if meta:
                dur = meta.get("duration") or 0
                w = meta.get("width") or 0
                h = meta.get("height") or 0
                info = []
                if dur:
                    info.append(f"时长 {dur/1000:.1f}s")
                if w and h:
                    info.append(f"分辨率 {w}x{h}")
                if info:
                    _log(f"      元数据: {', '.join(info)}")

            # 保存元数据（开启时）
            if cfg.save_metadata:
                base_path = save_path.with_suffix("")
                await download_metadata(video_data, base_path, cfg)

            # 记录到数据库
            if progress_db:
                progress_db.record(
                    aweme_id=str(aweme_id), resource_type=kind,
                    resource_id=resource_id, mix_name=mix_name,
                    desc=desc[:200], file_path=str(save_path),
                    url=share_url, meta=meta, status="success",
                    error_msg=None, retry_count=attempt)

            return {'aweme_id': aweme_id, 'success': True, 'skipped': False,
                    'path': str(save_path), 'media_type': media_type}
        else:
            if progress_db:
                progress_db.record(
                    aweme_id=str(aweme_id), resource_type=kind,
                    resource_id=resource_id, mix_name=mix_name,
                    desc=desc[:200], file_path=str(save_path),
                    url=share_url, meta=meta, status="failed",
                    error_msg=last_error[:500], retry_count=attempt)
            return {'aweme_id': aweme_id, 'success': False, 'skipped': False,
                    'path': str(save_path), 'error': last_error}

    async def run(self, share_url, progress_callback=None, log_callback=None) -> Dict[str, Any]:
        """主入口：解析链接 → 获取视频列表 → 下载。"""
        def _log(msg):
            if log_callback:
                log_callback(msg)
            else:
                print(msg)

        cfg = self.config
        date_str = datetime.now().strftime("%Y%m%d")

        _log(f"[1/4] 解析分享链接: {share_url}")
        kind, resource_id = await resolve_share_url(share_url, cfg)

        mix_name = ""
        if kind == "mix":
            _log(f"      检测到合集链接, mix_id={resource_id}")
            mix_name, videos = await fetch_mix_videos(resource_id, config=cfg, max_counts=self.max_counts)
            if mix_name:
                _log(f"      合集名称: {mix_name}")
            safe_name = _sanitize_filename(mix_name, cfg.filename_max_len) or resource_id
            target_dir = self.output_dir / f"{date_str}_{safe_name}"
            download_interval = cfg.mix_download_interval
        else:
            _log(f"      检测到单视频链接, aweme_id={resource_id}")
            videos = [await fetch_one_video(resource_id, cfg)]
            target_dir = self.output_dir
            download_interval = 0

        _log(f"[2/4] 共获取 {len(videos)} 个视频:")
        for i, v in enumerate(videos, 1):
            desc = (v.get("desc") or "").replace("\n", " ")[:40]
            _log(f"  {i:>3d}. [{v.get('aweme_id')}] {desc}")

        db = self._get_progress_db()
        db_ctx = db if db is not None else _NullContext()

        _log(f"[3/4] 开始下载到 {target_dir}/ ...")
        target_dir.mkdir(parents=True, exist_ok=True)
        success = 0
        skipped = 0
        with db_ctx as progress_db:
            for i, v in enumerate(videos, 1):
                aweme_id = v.get("aweme_id", f"unknown_{i}")
                desc = v.get("desc") or ""
                play_addr = v.get("video_play_addr")
                if isinstance(play_addr, list):
                    play_addr = play_addr[0] if play_addr else None

                if not play_addr:
                    _log(f"  [{i}/{len(videos)}] {aweme_id} 无视频地址，跳过")
                    continue

                name = _build_video_name(desc, str(aweme_id), cfg.filename_max_len)
                if kind == "mix":
                    save_path = target_dir / f"{i:03d}_{name}.mp4"
                else:
                    save_path = target_dir / f"{date_str}_{name}.mp4"

                if not self.force:
                    if save_path.exists():
                        _log(f"  [{i}/{len(videos)}] {save_path.name} 文件已存在，跳过")
                        success += 1
                        skipped += 1
                        continue
                    if progress_db and progress_db.is_success_downloaded(str(aweme_id)):
                        _log(f"  [{i}/{len(videos)}] {save_path.name} 进度记录已存在，跳过")
                        skipped += 1
                        continue

                _log(f"  [{i}/{len(videos)}] 下载 {save_path.name}")

                def _make_progress_cb(index, total_videos=len(videos)):
                    def _inner(cur, tot):
                        if progress_callback:
                            progress_callback(cur, tot, index, total_videos)
                    return _inner

                download_ok, last_error, attempt = await self._download_with_retry(
                    play_addr, save_path, _make_progress_cb(i))

                meta = v.get("_meta") or {}

                if download_ok:
                    success += 1
                    if meta:
                        dur = meta.get("duration") or 0
                        w = meta.get("width") or 0
                        h = meta.get("height") or 0
                        size = meta.get("file_size") or 0
                        info_parts = []
                        if dur:
                            info_parts.append(f"时长 {dur/1000:.1f}s")
                        if w and h:
                            info_parts.append(f"分辨率 {w}x{h}")
                        if size:
                            info_parts.append(f"大小 {size/1024/1024:.1f}MB")
                        if meta.get("ratio"):
                            info_parts.append(meta["ratio"])
                        if meta.get("is_h265"):
                            info_parts.append("H.265")
                        if info_parts:
                            _log(f"      元数据: {', '.join(info_parts)}")

                    if cfg.save_metadata:
                        base_path = save_path.with_suffix("")
                        await download_metadata(v, base_path, cfg)

                    if progress_db:
                        progress_db.record(
                            aweme_id=str(aweme_id), resource_type=kind,
                            resource_id=resource_id, mix_name=mix_name,
                            desc=desc[:200], file_path=str(save_path),
                            url=share_url, meta=meta, status="success",
                            error_msg=None, retry_count=attempt)
                else:
                    if progress_db:
                        progress_db.record(
                            aweme_id=str(aweme_id), resource_type=kind,
                            resource_id=resource_id, mix_name=mix_name,
                            desc=desc[:200], file_path=str(save_path),
                            url=share_url, meta=meta, status="failed",
                            error_msg=last_error[:500], retry_count=attempt)

                if download_interval and i < len(videos):
                    actual_interval = _random_interval(download_interval)
                    _log(f"      等待 {actual_interval:.1f} 秒后继续下载下一个...")
                    await asyncio.sleep(actual_interval)

        _log(f"\n[4/4] 完成: 成功 {success}/{len(videos)}，跳过 {skipped}")
        _log(f"      保存目录: {target_dir}/")
        return {
            "url": share_url, "kind": kind, "resource_id": resource_id,
            "mix_name": mix_name, "total": len(videos), "success": success,
            "skipped": skipped, "target_dir": str(target_dir),
        }

    async def retry_failed(self, progress_callback=None) -> Dict[str, Any]:
        """重试数据库中所有下载失败的记录。"""
        cfg = self.config
        print("[retry-failed] 开始重试数据库中的失败记录...")

        db = self._get_progress_db()
        if db is None:
            print("错误: 进度数据库未启用，无法查询失败记录", file=sys.stderr)
            return {"total": 0, "success": 0, "still_failed": 0}

        with db as progress_db:
            failed_list = progress_db.query_failed()

        if not failed_list:
            print("没有失败记录需要重试")
            return {"total": 0, "success": 0, "still_failed": 0}

        total = len(failed_list)
        print(f"共 {total} 条失败记录需要重试:")
        success = 0
        still_failed = 0
        with db as progress_db:
            for i, r in enumerate(failed_list, 1):
                aweme_id = r["aweme_id"]
                save_path = Path(r["file_path"]) if r.get("file_path") else None
                desc = r.get("desc") or ""
                mix_name = r.get("mix_name") or ""
                resource_id = r.get("resource_id") or aweme_id
                resource_type = r.get("resource_type") or "one"

                print(f"\n  [{i}/{total}] 重试 {aweme_id}")

                try:
                    video = await fetch_one_video(str(aweme_id), cfg)
                except Exception as e:
                    print(f"      获取视频信息失败: {e}")
                    progress_db.record(
                        aweme_id=str(aweme_id), resource_type=resource_type,
                        resource_id=resource_id, mix_name=mix_name,
                        desc=desc[:200], file_path=str(save_path) if save_path else "",
                        meta=None, status="failed",
                        error_msg=f"获取视频信息失败: {str(e)[:400]}",
                        retry_count=r.get("retry_count", 0) + cfg.download_max_retries)
                    still_failed += 1
                    continue

                play_addr = video.get("video_play_addr")
                if isinstance(play_addr, list):
                    play_addr = play_addr[0] if play_addr else None
                if not play_addr:
                    print(f"      无视频地址，跳过")
                    progress_db.record(
                        aweme_id=str(aweme_id), resource_type=resource_type,
                        resource_id=resource_id, mix_name=mix_name,
                        desc=desc[:200], file_path=str(save_path) if save_path else "",
                        meta=video.get("_meta"), status="failed",
                        error_msg="无视频下载地址",
                        retry_count=r.get("retry_count", 0) + cfg.download_max_retries)
                    still_failed += 1
                    continue

                if not save_path:
                    name = _build_video_name(desc, str(aweme_id), cfg.filename_max_len)
                    date_str = datetime.now().strftime("%Y%m%d")
                    save_path = self.output_dir / f"{date_str}_{name}.mp4"
                save_path.parent.mkdir(parents=True, exist_ok=True)

                download_ok, last_error, attempt = await self._download_with_retry(
                    play_addr, save_path, progress_callback)

                if download_ok:
                    success += 1
                    if cfg.save_metadata:
                        base_path = save_path.with_suffix("")
                        await download_metadata(video, base_path, cfg)
                    progress_db.record(
                        aweme_id=str(aweme_id), resource_type=resource_type,
                        resource_id=resource_id, mix_name=mix_name,
                        desc=desc[:200], file_path=str(save_path),
                        meta=video.get("_meta"), status="success",
                        error_msg=None, retry_count=attempt)
                else:
                    still_failed += 1
                    progress_db.record(
                        aweme_id=str(aweme_id), resource_type=resource_type,
                        resource_id=resource_id, mix_name=mix_name,
                        desc=desc[:200], file_path=str(save_path),
                        meta=video.get("_meta"), status="failed",
                        error_msg=last_error[:500],
                        retry_count=r.get("retry_count", 0) + attempt + 1)

                if i < total and cfg.mix_download_interval > 0:
                    actual_interval = _random_interval(cfg.mix_download_interval)
                    print(f"      等待 {actual_interval:.1f} 秒后继续...")
                    await asyncio.sleep(actual_interval)

        print(f"\n[retry-failed] 完成: 成功 {success}/{total}，仍失败 {still_failed}")
        return {"total": total, "success": success, "still_failed": still_failed}