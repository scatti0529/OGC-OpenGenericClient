# -*- coding: utf-8 -*-
"""
抖音服务层（完整移植自 douyin_parse-master + 本系统下载适配）
==========================================
- 解析：services/douyin_parser.py（a_bogus + X-Bogus，v2.0.4 算法）
- 下载：services/download_manager.py → download_media()
- 分类：videos/ / images/ / audios/ / sourcefiles/
- 数据库：DouyinProgressDB（douyin_downloads 表）
"""
import os
import re
import time
import random
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import config as CFG
from services.download_manager import download_media


# ═══════════════════════════════════════════════════════════
#  输出目录（使用主程序下载系统）
# ═══════════════════════════════════════════════════════════
def get_douyin_output_dir() -> Path:
    """抖音下载根目录（douyin-download）"""
    try:
        from services.download_manager import get_download_root, PLATFORM_FOLDERS
        root = get_download_root()
        folder = PLATFORM_FOLDERS.get('douyin', 'douyin-download')
        return Path(root) / folder
    except Exception:
        return Path('data') / 'douyin-download'


def get_douyin_media_dir(file_type: str = 'video') -> Path:
    """抖音指定类型文件下载目录（videos/images/audios/sourcefiles）"""
    try:
        from services.download_manager import get_platform_dir
        return Path(get_platform_dir('douyin', file_type))
    except Exception:
        base = get_douyin_output_dir()
        m = {'image': 'images', 'video': 'videos', 'audio': 'audios',
             'sourcefiles': 'sourcefiles'}
        return base / m.get(file_type, 'videos')


def get_douyin_sourcefiles_dir() -> Path:
    """抖音 sourcefiles 目录"""
    try:
        from services.download_manager import get_platform_dir
        return Path(get_platform_dir('douyin', 'sourcefiles'))
    except Exception:
        return get_douyin_output_dir() / 'sourcefiles'


# ═══════════════════════════════════════════════════════════
#  文件名工具
# ═══════════════════════════════════════════════════════════
def safe_filename(text: str, max_len: int = 60) -> str:
    """清洗字符串为合法文件名"""
    text = (text or '').replace('#', '').replace('\n', ' ')
    text = re.sub(r'[\\/:*?"<>|]', '', text).strip()
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > max_len:
        text = text[:max_len].strip()
    return text or 'untitled'


def _build_name(desc: str, aweme_id: str, max_len: int = 60) -> str:
    """构建视频文件名：文案_aweme_id"""
    desc = safe_filename(desc, 40)
    suffix = f"_{aweme_id}"
    budget = max_len - len(suffix)
    if budget > 0 and len(desc) > budget:
        desc = desc[:budget].strip()
    return f"{desc}{suffix}"


def _format_time(ts) -> str:
    if not ts:
        return ''
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ''


# ═══════════════════════════════════════════════════════════
#  进度数据库（主程序统一 douyin_downloads 表）
# ═══════════════════════════════════════════════════════════
class DouyinProgressDB:
    """抖音下载进度数据库（合并到主数据库 ogc_users.db）"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            from core.database import DB_PATH
            self.db_path = Path(DB_PATH)
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._migrate()
        return self

    def __exit__(self, *args):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _migrate(self):
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
            "CREATE INDEX IF NOT EXISTS idx_douyin_resource_id "
            "ON douyin_downloads(resource_id)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_douyin_status "
            "ON douyin_downloads(status)")
        self._conn.commit()

    def is_downloaded(self, aweme_id: str) -> bool:
        if not self._conn:
            return False
        cur = self._conn.execute(
            "SELECT 1 FROM douyin_downloads WHERE aweme_id=? AND status='success'",
            (aweme_id,))
        return cur.fetchone() is not None

    def record(self, aweme_id, resource_type, resource_id, mix_name, desc,
               file_path, url=None, meta=None, status='success',
               error_msg=None, retry_count=0):
        if not self._conn:
            return
        meta = meta or {}
        self._conn.execute("""
            INSERT INTO douyin_downloads
            (aweme_id, resource_type, resource_id, mix_name, desc, file_path, url,
             duration, width, height, file_size, bit_rate, fps, ratio,
             video_format, is_h265, nickname, digg_count, comment_count,
             share_count, collect_count, create_time, status, error_msg, retry_count)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(aweme_id) DO UPDATE SET
                resource_type=excluded.resource_type,
                resource_id=excluded.resource_id,
                mix_name=excluded.mix_name, desc=excluded.desc,
                file_path=excluded.file_path, url=COALESCE(excluded.url, url),
                duration=excluded.duration, width=excluded.width,
                height=excluded.height, file_size=excluded.file_size,
                bit_rate=excluded.bit_rate, fps=excluded.fps,
                ratio=excluded.ratio, video_format=excluded.video_format,
                is_h265=excluded.is_h265, nickname=excluded.nickname,
                digg_count=excluded.digg_count,
                comment_count=excluded.comment_count,
                share_count=excluded.share_count,
                collect_count=excluded.collect_count,
                create_time=excluded.create_time,
                status=excluded.status, error_msg=excluded.error_msg,
                retry_count=excluded.retry_count,
                downloaded_at=CURRENT_TIMESTAMP
        """, (
            aweme_id, resource_type, resource_id, mix_name, desc, file_path, url,
            meta.get('duration'), meta.get('width'), meta.get('height'),
            meta.get('file_size'), meta.get('bit_rate'), meta.get('fps'),
            meta.get('ratio'), meta.get('video_format'), meta.get('is_h265'),
            meta.get('nickname'), meta.get('digg_count'),
            meta.get('comment_count'), meta.get('share_count'),
            meta.get('collect_count'), meta.get('create_time'),
            status, error_msg, retry_count,
        ))
        self._conn.commit()


# ═══════════════════════════════════════════════════════════
#  下载器（整合解析 + 主程序下载系统）
# ═══════════════════════════════════════════════════════════
class DouyinDownloader:
    """抖音下载器

    解析使用 douyin_parse-master v2.0.4 的 a_bogus/X-Bogus 通道，
    下载统一走 services/download_manager.py → download_media()
    """

    def __init__(self, config=None):
        self.config = config or DouyinConfig()
        self._parser: Optional = None

    def _get_parser(self):
        if self._parser is None:
            from services.douyin_parser import DouyinVideoParser
            cookie = str(CFG.get('douyin_cookie', '') or '')
            max_pages = int(CFG.get('douyin_max_pages', 10) or 10)
            self._parser = DouyinVideoParser(
                cookie=cookie,
                timeout=self.config.timeout,
                api_interval=self.config.api_interval,
                max_pages=max_pages,
            )
        return self._parser

    # ── 单视频解析 ──
    def parse_single(self, url: str) -> dict:
        """解析单个分享链接，返回完整视频/图集信息"""
        return self._get_parser().parse_video(url)

    # ── 用户主页解析 ──
    def parse_user_home(self, user_url: str, max_pages: int = 10,
                        log_cb=None) -> dict:
        """解析用户主页（支持主页链接 / 视频链接反查）"""
        parser = self._get_parser()
        if '/user/' not in user_url and 'sec_uid=' not in user_url:
            if log_cb:
                log_cb('检测到视频链接，正在反查用户主页...')
            user_home = parser.get_user_home_from_video_url(user_url)
            if not user_home:
                raise ValueError('无法从视频链接反查用户主页')
            if log_cb:
                log_cb(f'反查主页: {user_home}')
        else:
            user_home = user_url

        if log_cb:
            log_cb('正在获取作品列表...')
        urls = parser.get_user_aweme_urls(user_home, max_pages=max_pages)
        if log_cb:
            log_cb(f'获取到 {len(urls)} 条作品，正在逐条解析...')

        videos = []
        for i, u in enumerate(urls, 1):
            try:
                info = parser.parse_video(u)
                info['share_url'] = u
                videos.append(info)
                if log_cb:
                    log_cb(f'  [{i}/{len(urls)}] {info.get("desc", "")[:40]}')
            except Exception as e:
                if log_cb:
                    log_cb(f'  [{i}/{len(urls)}] 解析失败: {e}')
            time.sleep(random.uniform(0.3, 0.8))

        sec_uid = parser.get_sec_uid(user_home) or ''
        return {
            'kind': 'user',
            'resource_id': sec_uid,
            'videos': videos,
        }

    # ── 下载单个媒体 ──
    def download_single(self, video_data: dict, share_url: str = '',
                        selected_quality: Optional[dict] = None,
                        progress_cb=None, log_cb=None) -> dict:
        """下载单个视频/图集

        video_data 来自 parse_single() 的返回值。
        视频下载到 videos/，图集下载到 images/（Live 图为 videos/）。
        下载统一走 download_manager.py → download_media()
        """
        def _log(msg):
            if log_cb:
                log_cb(msg)

        aweme_id = str(video_data.get('aweme_id', ''))
        desc = video_data.get('desc') or ''
        content_type = video_data.get('content_type', 'video')

        # 跳过已下载
        db = DouyinProgressDB()
        with db as progress_db:
            if progress_db.is_downloaded(aweme_id):
                _log(f'跳过（已下载）: {aweme_id}')
                return {'aweme_id': aweme_id, 'success': True, 'skipped': True}

        if content_type == 'video':
            return self._download_video(
                video_data, selected_quality, progress_cb, _log)
        else:
            return self._download_image(
                video_data, progress_cb, _log)

    def _download_video(self, info: dict, quality: Optional[dict],
                        progress_cb, _log) -> dict:
        """下载视频文件"""
        aweme_id = str(info.get('aweme_id', ''))
        desc = info.get('desc') or ''

        # 选择下载 URL
        if quality and quality.get('url'):
            download_url = quality['url']
            ratio = quality.get('ratio', '')
        else:
            qualities = info.get('qualities') or []
            if not qualities:
                return {'aweme_id': aweme_id, 'success': False,
                        'error': '无可用视频地址'}
            download_url = qualities[0]['url']
            ratio = qualities[0].get('ratio', '')

        # 构建文件名和保存路径
        name = _build_name(desc, aweme_id)
        ratio_suffix = f'_{ratio}' if ratio else ''
        filename = f'{name}{ratio_suffix}.mp4'

        save_dir = get_douyin_media_dir('video')
        save_path = save_dir / filename
        save_dir.mkdir(parents=True, exist_ok=True)

        # 检查文件是否存在
        if save_path.exists():
            return {'aweme_id': aweme_id, 'success': True, 'skipped': True,
                    'path': str(save_path)}

        _log(f'下载视频: {filename} ({ratio or "默认质量"})')

        # 使用主程序下载系统（download_manager → download_media）
        try:
            success, message, path = download_media(
                url=download_url, filename=filename, platform='douyin',
                file_type='video', progress_callback=progress_cb,
                referer='https://www.douyin.com/',
            )
        except Exception as e:
            return {'aweme_id': aweme_id, 'success': False, 'error': str(e)}

        if success:
            self._record_success(aweme_id, info, str(path or save_path))
            return {'aweme_id': aweme_id, 'success': True, 'skipped': False,
                    'path': str(path or save_path)}
        else:
            return {'aweme_id': aweme_id, 'success': False,
                    'error': message, 'path': str(path or save_path)}

    def _download_image(self, info: dict, progress_cb, _log) -> dict:
        """下载图集（多图）"""
        aweme_id = str(info.get('aweme_id', ''))
        desc = info.get('desc') or ''
        image_urls = info.get('image_urls') or []
        is_live = info.get('is_live', False)

        if not image_urls:
            return {'aweme_id': aweme_id, 'success': False,
                    'error': '图集无图片地址'}

        file_type = 'video' if is_live else 'image'
        ext = '.mp4' if is_live else '.jpg'
        save_dir = get_douyin_media_dir('video' if is_live else 'image')
        save_dir.mkdir(parents=True, exist_ok=True)

        name = _build_name(desc, aweme_id)
        date_str = datetime.now().strftime('%Y%m%d')
        success_count = 0
        paths = []

        for idx, img_url in enumerate(image_urls, 1):
            img_name = f'{name}_{date_str}_{idx:03d}{ext}'
            try:
                ok, _, p = download_media(
                    url=img_url, filename=img_name, platform='douyin',
                    file_type=file_type, progress_callback=None,
                    referer='https://www.douyin.com/',
                )
                if ok:
                    success_count += 1
                    paths.append(str(p))
            except Exception:
                pass
            if progress_cb:
                progress_cb(idx, len(image_urls))

        ok = success_count == len(image_urls)
        if ok:
            self._record_success(aweme_id, info, save_dir / name)
        return {
            'aweme_id': aweme_id,
            'success': success_count > 0,
            'skipped': False,
            'path': paths,
            'error': '' if ok else f'部分成功 {success_count}/{len(image_urls)}',
        }

    def _record_success(self, aweme_id, info, file_path):
        try:
            meta = {
                'duration': info.get('duration'),
                'width': info.get('width'),
                'height': info.get('height'),
                'nickname': info.get('author_nickname'),
                'digg_count': info.get('digg_count'),
                'comment_count': info.get('comment_count'),
                'share_count': info.get('share_count'),
                'collect_count': info.get('collect_count'),
                'create_time': _format_time(info.get('create_time')),
            }
            with DouyinProgressDB() as db:
                db.record(
                    aweme_id=aweme_id,
                    resource_type='one',
                    resource_id=aweme_id,
                    mix_name='',
                    desc=(info.get('desc') or '')[:200],
                    file_path=str(file_path),
                    url=info.get('share_url', ''),
                    meta=meta,
                    status='success',
                )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#  配置类
# ═══════════════════════════════════════════════════════════
class DouyinConfig:
    """抖音下载配置"""

    def __init__(self):
        self.timeout = int(CFG.get('douyin_timeout', 15))
        self.max_retries = int(CFG.get('douyin_max_retries', 5))
        self.max_tasks = int(CFG.get('douyin_max_tasks', 1))
        self.page_counts = int(CFG.get('douyin_page_counts', 10))
        self.api_interval = float(CFG.get('douyin_api_request_interval', 1.0))
        self.mix_interval = int(CFG.get('douyin_mix_download_interval', 10))
        self.chunk_size = int(CFG.get('douyin_chunk_size', 65536))
        self.filename_max_len = int(CFG.get('douyin_filename_max_len', 60))
        self.download_max_retries = int(CFG.get('douyin_download_max_retries', 3))
        self.download_retry_interval = float(CFG.get('douyin_download_retry_interval', 5.0))
        self.max_download_speed = int(CFG.get('douyin_max_download_speed', 10485760))
        self.save_metadata = bool(CFG.get('douyin_save_metadata', False))
        self.save_cover = bool(CFG.get('douyin_save_cover', True))
        self.save_desc = bool(CFG.get('douyin_save_desc', True))
        self.save_music = bool(CFG.get('douyin_save_music', True))
        self.save_json = bool(CFG.get('douyin_save_json', True))
        self.enable_progress = bool(CFG.get('douyin_enable_progress', True))