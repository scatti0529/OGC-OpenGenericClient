# -*- coding: utf-8 -*-
"""
网易云音乐服务
==============
提供歌曲搜索、解析、歌单解析、下载等纯业务能力，
不含任何 GUI 依赖，替代原 ilbs/music_page.py 中的业务层。
"""
import hashlib
import json
import os
import random
import re
import time
from contextlib import suppress
from urllib.parse import parse_qs, urlparse

import requests

from core.logger import logger


# ============================================================
# 音乐品质常量
# ============================================================
MUSIC_QUALITIES = ['jymaster', 'dolby', 'sky', 'jyeffect', 'hires',
                   'lossless', 'exhigh', 'standard']

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
    'Referer': 'https://music.163.com/',
}


# ============================================================
# 工具函数
# ============================================================
def seconds2hms(seconds: float) -> str:
    """将秒数转换为 HH:MM:SS 格式"""
    if not seconds or seconds <= 0:
        return '-:-:-'
    h, remainder = divmod(int(seconds), 3600)
    m, s = divmod(remainder, 60)
    return f'{h:02d}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


def byte2mb(size_bytes: int) -> str:
    """将字节数转换为可读的文件大小"""
    if not size_bytes:
        return '0 B'
    mb = size_bytes / (1024 * 1024)
    if mb >= 1024:
        return f'{mb / 1024:.2f} GB'
    return f'{mb:.2f} MB'


def extract_urls(text: str) -> list:
    """从文本中提取所有URL"""
    return re.findall(r'https?://[^\s]+', text)


def clean_lrc(lrc_text: str) -> str:
    """清理歌词文本"""
    if not lrc_text or lrc_text == 'NULL':
        return ''
    lrc_text = re.sub(r'\[\w*:\w*\]', '', lrc_text)
    return lrc_text.strip()


def extract_duration_from_lrc(lrc_text: str) -> int:
    """从歌词文本中提取时长（秒）"""
    if not lrc_text:
        return 0
    matches = re.findall(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]', lrc_text)
    if not matches:
        return 0
    max_seconds = 0
    for m in matches:
        try:
            secs = int(m[0]) * 60 + int(m[1]) + int(m[2]) / 1000
            max_seconds = max(max_seconds, secs)
        except (ValueError, IndexError):
            continue
    return int(max_seconds)


def safe_extract(data, keys: list, default=None):
    """安全从嵌套字典中提取值"""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, (list, tuple)) and isinstance(key, int):
            try:
                current = current[key]
            except (IndexError, TypeError):
                return default
        else:
            return default
    return current if current is not None else default


def legalize_string(text) -> str:
    """合法化字符串，移除非法文件名字符"""
    if not text:
        return ''
    text = str(text).strip()
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    return text.strip()


# ============================================================
# 音频链接测试器
# ============================================================
class AudioLinkTester:
    """测试音频链接是否有效，获取文件信息"""

    VALID_AUDIO_EXTS = {'.mp3', '.flac', '.wav', '.aac', '.ogg', '.wma', '.m4a',
                        '.ape', '.dsf', '.dff', '.opus', '.aiff', '.alac',
                        '.ac3', '.eac3'}

    @classmethod
    def test(cls, url: str, timeout: int = 10, **kwargs) -> dict:
        """测试URL并返回文件信息"""
        result = {'ok': False, 'download_url': url, 'file_size_bytes': 0,
                  'file_size': '0 B', 'ext': ''}
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True, **kwargs)
            if resp.status_code >= 400:
                resp = requests.get(url, timeout=timeout, stream=True, **kwargs)
                resp.close()
            content_length = resp.headers.get('content-length')
            content_type = resp.headers.get('content-type', '')

            file_size = int(content_length) if (content_length and content_length.isdigit()) else 0
            result['file_size_bytes'] = file_size
            result['file_size'] = byte2mb(file_size)
            result['ok'] = True

            # 从URL猜测扩展名
            path = urlparse(url).path
            ext = os.path.splitext(path)[1].lower()
            if ext in cls.VALID_AUDIO_EXTS:
                result['ext'] = ext
            elif 'flac' in content_type:
                result['ext'] = '.flac'
            elif 'mpeg' in content_type or 'mp3' in content_type:
                result['ext'] = '.mp3'
            elif 'aac' in content_type:
                result['ext'] = '.aac'
            elif 'wav' in content_type:
                result['ext'] = '.wav'
            elif 'ogg' in content_type:
                result['ext'] = '.ogg'
            elif 'mp4' in content_type:
                result['ext'] = '.m4a'
            else:
                result['ext'] = '.mp3'
        except Exception:
            result['ok'] = False
        return result


# ============================================================
# EAPI 加密工具
# ============================================================
class EapiCryptoUtils:
    """网易云音乐 EAPI 加密"""

    @staticmethod
    def encryptparams(url: str, payload: dict) -> str:
        """模拟 EAPI 加密"""
        payload_str = json.dumps(payload, separators=(',', ':'))
        text = f"nobody{url}use{payload_str}md5forencrypt"
        return hashlib.md5(text.encode('utf-8')).hexdigest()


# ============================================================
# 歌曲信息数据类
# ============================================================
class SongInfo:
    """歌曲信息"""

    def __init__(self, **kwargs):
        self.source = kwargs.get('source', '')
        self.song_name = kwargs.get('song_name', '')
        self.singers = kwargs.get('singers', '')
        self.album = kwargs.get('album', '')
        self.identifier = kwargs.get('identifier', '')
        self.duration = kwargs.get('duration', '')
        self.duration_s = kwargs.get('duration_s', 0)
        self.ext = kwargs.get('ext', '')
        self.file_size_bytes = kwargs.get('file_size_bytes', 0)
        self.file_size = kwargs.get('file_size', '0 B')
        self.download_url = kwargs.get('download_url', '')
        self.lyric = kwargs.get('lyric', '')
        self.cover_url = kwargs.get('cover_url', '')
        self.quality = kwargs.get('quality', '')
        self.raw_data = kwargs.get('raw_data', {})
        self.work_dir = kwargs.get('work_dir', '')
        self.downloaded_contents = kwargs.get('downloaded_contents', None)
        self.episodes = kwargs.get('episodes', [])

    @property
    def with_valid_download_url(self) -> bool:
        return bool(self.download_url) and isinstance(self.download_url, str) \
            and self.download_url.startswith('http')

    def largerthan(self, other: 'SongInfo') -> bool:
        """比较两个歌曲信息的文件大小"""
        if not other or not other.file_size_bytes:
            return True
        return self.file_size_bytes > other.file_size_bytes


# ============================================================
# 网易云音乐客户端
# ============================================================
class NeteaseMusicClient:
    """网易云音乐搜索与解析客户端"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.default_cookies = {
            'os': 'pc',
            'appver': '',
            'osver': '',
            'deviceId': 'pyncm!',
        }

    # ---------------------------------------------------------------
    # 搜索歌曲
    # ---------------------------------------------------------------
    def search(self, keyword: str, limit: int = 10) -> list:
        """搜索歌曲，返回搜索结果列表"""
        url = 'https://music.163.com/api/cloudsearch/pc'
        data = {'s': keyword, 'type': 1, 'limit': limit, 'offset': 0}
        try:
            resp = self.session.post(url, data=data, timeout=15)
            resp.raise_for_status()
            return safe_extract(resp.json(), ['result', 'songs'], [])
        except Exception as e:
            logger.error(f"网易云音乐搜索失败: {e}")
            return []

    # ---------------------------------------------------------------
    # 获取歌曲详细信息/歌词
    # ---------------------------------------------------------------
    def get_song_detail(self, song_id) -> dict:
        """获取歌曲详细信息"""
        url = 'https://interface3.music.163.com/api/v3/song/detail'
        data = {'c': json.dumps([{"id": song_id, "v": 0}])}
        try:
            resp = self.session.post(url, data=data, timeout=15)
            resp.raise_for_status()
            return safe_extract(resp.json(), ['songs', 0], {})
        except Exception:
            return {}

    def get_lyric(self, song_id) -> str:
        """获取歌词"""
        url = 'https://interface3.music.163.com/api/song/lyric'
        data = {'id': song_id, 'cp': 'false', 'tv': '0', 'lv': '0', 'rv': '0',
                'kv': '0', 'yv': '0', 'ytv': '0', 'yrv': '0'}
        try:
            resp = self.session.post(url, data=data, timeout=15)
            resp.raise_for_status()
            return clean_lrc(safe_extract(resp.json(), ['lrc', 'lyric'], ''))
        except Exception:
            return ''

    # ---------------------------------------------------------------
    # 官方API解析
    # ---------------------------------------------------------------
    def parse_with_official(self, search_result: dict, quality: str = 'hires') -> SongInfo:
        """使用官方API解析歌曲"""
        song_id = search_result.get('id')
        if not song_id:
            return SongInfo()

        if not search_result.get('name'):
            search_result.update(self.get_song_detail(song_id))

        # 尝试按品质从高到低解析
        qualities = (MUSIC_QUALITIES[MUSIC_QUALITIES.index(quality):]
                     if quality in MUSIC_QUALITIES else MUSIC_QUALITIES)
        for music_quality in qualities:
            try:
                params = {
                    'ids': [song_id],
                    'level': music_quality,
                    'encodeType': 'mp4' if music_quality == 'dolby' else 'flac',
                    'header': json.dumps({
                        "os": "pc", "appver": "", "osver": "",
                        "deviceId": "pyncm!",
                        "requestId": str(random.randrange(20000000, 30000000))
                    })
                }
                if music_quality == 'sky':
                    params['immerseType'] = 'c51'

                params_encrypted = EapiCryptoUtils.encryptparams(
                    url='https://interface3.music.163.com/eapi/song/enhance/player/url/v1',
                    payload=params
                )

                cookies = {"os": "pc", "appver": "", "osver": "",
                           "deviceId": "pyncm!"}
                cookies.update(self.default_cookies)

                resp = self.session.post(
                    'https://interface3.music.163.com/eapi/song/enhance/player/url/v1',
                    data={"params": params_encrypted},
                    cookies=cookies,
                    timeout=15
                )
                resp.raise_for_status()
                download_url = safe_extract(resp.json(), ['data', 0, 'url'], '')
                if not download_url or not download_url.startswith('http'):
                    continue

                duration_s = float(search_result.get('dt', 0) or 0) / 1000
                tester_result = AudioLinkTester.test(url=download_url)

                return SongInfo(
                    source='NeteaseMusicClient',
                    song_name=legalize_string(search_result.get('name')),
                    singers=legalize_string(', '.join([
                        s.get('name') for s in (safe_extract(search_result, ['ar'], []) or [])
                        if isinstance(s, dict) and s.get('name')
                    ])),
                    album=legalize_string(safe_extract(search_result, ['al', 'name'], '')),
                    ext=tester_result['ext'],
                    file_size_bytes=tester_result['file_size_bytes'],
                    file_size=tester_result['file_size'],
                    identifier=str(song_id),
                    duration_s=duration_s,
                    duration=seconds2hms(duration_s),
                    lyric=self.get_lyric(song_id),
                    cover_url=safe_extract(search_result, ['al', 'picUrl'], ''),
                    download_url=download_url,
                    quality=music_quality,
                    raw_data={'search': search_result, 'download': resp.json(),
                              'quality': music_quality},
                )
            except Exception:
                continue

        return SongInfo()

    # ---------------------------------------------------------------
    # 第三方API解析
    # ---------------------------------------------------------------
    def parse_with_thirdparty(self, search_result: dict) -> SongInfo:
        """使用第三方API解析歌曲"""
        song_id = search_result.get('id')
        if not song_id:
            return SongInfo()

        parsers = [
            self._parse_cunyu,
            self._parse_bugpk,
            self._parse_yutangxiaowu,
            self._parse_xiaoqin,
        ]

        for parser in parsers:
            try:
                song_info = parser(search_result)
                if song_info.with_valid_download_url:
                    return song_info
            except Exception:
                continue

        return SongInfo()

    def _build_song_info(self, song_id, data, search_result, quality,
                         name_key='name', singer_key='ar_name', album_key='al_name',
                         cover_key='pic'):
        """公共的第三方解析结果构建"""
        download_url = data.get('url', '') or data.get('song_file_url', '')
        tester = AudioLinkTester.test(url=download_url)
        lyric = clean_lrc(data.get('lyric', ''))
        return SongInfo(
            source='NeteaseMusicClient',
            song_name=legalize_string(data.get(name_key)),
            singers=legalize_string(str(data.get(singer_key, '')).replace('/', ', ')),
            album=legalize_string(data.get(album_key)),
            ext=tester['ext'],
            file_size_bytes=tester['file_size_bytes'],
            file_size=tester['file_size'],
            identifier=str(song_id),
            duration_s=extract_duration_from_lrc(lyric),
            duration=seconds2hms(extract_duration_from_lrc(lyric)),
            lyric=lyric,
            cover_url=data.get(cover_key, ''),
            download_url=download_url,
            quality=quality,
            raw_data={'search': search_result, 'download': data, 'quality': quality},
        )

    def _parse_cunyu(self, search_result: dict) -> SongInfo:
        """Cunyu API解析"""
        song_id = search_result.get('id')
        headers = {"user-agent": DEFAULT_HEADERS['User-Agent']}
        for quality in MUSIC_QUALITIES:
            try:
                resp = requests.get(
                    f'https://www.cunyuapi.top/163music_play?id={song_id}&quality={quality}',
                    timeout=10, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                download_url = data.get('song_file_url', '')
                if not download_url or not download_url.startswith('http'):
                    break
                return self._build_song_info(
                    song_id, data, search_result, quality,
                    name_key='name', singer_key='ar_name', album_key='al_name', cover_key='img'
                )
            except Exception:
                continue
        return SongInfo()

    def _parse_bugpk(self, search_result: dict) -> SongInfo:
        """Bugpk API解析"""
        song_id = search_result.get('id')
        headers = {"user-agent": DEFAULT_HEADERS['User-Agent']}
        for quality in MUSIC_QUALITIES:
            try:
                resp = requests.get(
                    f'https://api.bugpk.com/api/163_music?ids={song_id}&level={quality}&type=json',
                    timeout=10, headers=headers, verify=False
                )
                resp.raise_for_status()
                data = resp.json()
                download_url = data.get('url', '')
                if not download_url or not download_url.startswith('http') or \
                        download_url.startswith('https://music.163.com/song/media/outer/url?id='):
                    break
                return self._build_song_info(song_id, data, search_result, quality)
            except Exception:
                continue
        return SongInfo()

    def _parse_yutangxiaowu(self, search_result: dict) -> SongInfo:
        """雨堂小坞API解析"""
        song_id = search_result.get('id')
        headers = {"user-agent": DEFAULT_HEADERS['User-Agent']}
        for quality in MUSIC_QUALITIES:
            try:
                resp = requests.get(
                    f'https://yutangxiaowu.cn:4000/Song_V1?url={song_id}&level={quality}&type=json',
                    timeout=10, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                download_url = data.get('url', '')
                if not download_url or not download_url.startswith('http'):
                    break
                return self._build_song_info(song_id, data, search_result, quality)
            except Exception:
                continue
        return SongInfo()

    def _parse_xiaoqin(self, search_result: dict) -> SongInfo:
        """小Qin API解析"""
        song_id = search_result.get('id')
        headers = {
            "Accept": "*/*",
            "Origin": "https://wyapi.toubiec.cn",
            "Referer": "https://wyapi.toubiec.cn/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0"
        }
        for quality in MUSIC_QUALITIES:
            payload = {"id": str(song_id), "level": quality,
                       "timestamp": int(time.time() * 1000)}
            try:
                resp = requests.post(
                    "https://nextmusic.toubiec.cn/api/getSongUrl",
                    headers=headers, json=payload, verify=False, timeout=10
                )
                resp.raise_for_status()
                data = resp.json()
                download_url = safe_extract(data, ['data', 'url'], '')
                if not download_url or not download_url.startswith('http'):
                    resp = requests.post(
                        "https://nextmusic.toubiec.cn/api/getMusicUrl",
                        headers=headers, json=payload, verify=False, timeout=10
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    download_url = safe_extract(data, ['data', 'url'], '')

                if not download_url or not download_url.startswith('http'):
                    break

                # 获取歌曲信息
                info_resp = requests.post(
                    "https://nextmusic.toubiec.cn/api/getSongInfo",
                    headers=headers,
                    json={"id": str(song_id), "timestamp": int(time.time() * 1000)},
                    verify=False, timeout=10
                )
                info_resp.raise_for_status()
                song_data = info_resp.json()

                tester = AudioLinkTester.test(url=download_url)
                return SongInfo(
                    source='NeteaseMusicClient',
                    song_name=legalize_string(safe_extract(song_data, ['data', 'name'], '')),
                    singers=legalize_string(
                        str(safe_extract(song_data, ['data', 'singer'], '')).replace('/', ', ')),
                    album=legalize_string(safe_extract(song_data, ['data', 'album'], '')),
                    ext=tester['ext'],
                    file_size_bytes=tester['file_size_bytes'],
                    file_size=tester['file_size'],
                    identifier=str(song_id),
                    duration_s=0,
                    duration='',
                    lyric='',
                    cover_url=safe_extract(song_data, ['data', 'picimg'], ''),
                    download_url=download_url,
                    quality=quality,
                    raw_data={'search': search_result, 'download': data, 'quality': quality},
                )
            except Exception:
                continue
        return SongInfo()

    # ---------------------------------------------------------------
    # 解析歌单
    # ---------------------------------------------------------------
    def parse_playlist(self, playlist_url: str) -> tuple:
        """解析歌单，返回(歌曲列表, 歌单名称)"""
        song_infos = []

        try:
            resp = self.session.head(playlist_url, allow_redirects=True, timeout=15)
            final_url = resp.url

            # 提取歌单ID
            playlist_id = None
            with suppress(Exception):
                playlist_id = parse_qs(
                    urlparse(urlparse(final_url).fragment).query
                ).get('id', [None])[0]
            if not playlist_id:
                playlist_id = urlparse(final_url).path.strip('/').split('/')[-1] \
                    .removesuffix('.html').removesuffix('.htm')

            if not playlist_id or not playlist_id.isdigit():
                return [], ''

            # 获取歌单详情
            resp = self.session.post(
                'https://music.163.com/api/v6/playlist/detail',
                data={'id': playlist_id},
                timeout=15
            )
            resp.raise_for_status()
            playlist_data = resp.json()
            playlist_name = legalize_string(
                safe_extract(playlist_data, ['playlist', 'name'], f'playlist-{playlist_id}'))
            track_ids = safe_extract(playlist_data, ['playlist', 'trackIds'], [])

            # 分批次获取歌曲详情
            total_tracks = len(track_ids)
            batch_size = 200
            all_songs = []

            for i in range(0, total_tracks, batch_size):
                batch = track_ids[i:i + batch_size]
                batch_ids = [t.get('id') for t in batch if isinstance(t, dict)]
                if not batch_ids:
                    continue
                try:
                    resp = self.session.post(
                        'https://interface3.music.163.com/api/v3/song/detail',
                        data={'c': json.dumps([{"id": sid, "v": 0} for sid in batch_ids])},
                        timeout=15
                    )
                    resp.raise_for_status()
                    all_songs.extend(safe_extract(resp.json(), ['songs'], []))
                except Exception:
                    continue

            # 构建SongInfo列表
            for song_data in all_songs:
                song_id = song_data.get('id')
                song_info = SongInfo(
                    source='NeteaseMusicClient',
                    song_name=legalize_string(song_data.get('name')),
                    singers=legalize_string(', '.join([
                        s.get('name') for s in (safe_extract(song_data, ['ar'], []) or [])
                        if isinstance(s, dict) and s.get('name')
                    ])),
                    album=legalize_string(safe_extract(song_data, ['al', 'name'], '')),
                    identifier=str(song_id),
                    duration_s=float(song_data.get('dt', 0) or 0) / 1000,
                    duration=seconds2hms(float(song_data.get('dt', 0) or 0) / 1000),
                    cover_url=safe_extract(song_data, ['al', 'picUrl'], ''),
                )
                song_infos.append(song_info)

            return song_infos, playlist_name

        except Exception as e:
            logger.error(f"解析歌单失败: {e}")
            return [], ''

    # ---------------------------------------------------------------
    # 下载歌曲
    # ---------------------------------------------------------------
    def download_song(self, song_info: SongInfo, save_dir: str) -> bool:
        """下载歌曲到指定目录（使用自适应多模式下载引擎）

        自动选择并发分块/流式模式，失败自动切换重试，
        下载成功后才落盘最终文件，失败自动清理残留数据。
        """
        if not song_info.with_valid_download_url:
            return False

        try:
            filename = f"{song_info.song_name} - {song_info.singers}{song_info.ext}"
            filename = legalize_string(filename)
            if not filename:
                filename = f"song_{int(time.time())}{song_info.ext or '.mp3'}"
            filepath = os.path.join(save_dir, filename)

            download_url = song_info.download_url
            if isinstance(download_url, dict):
                # 特殊格式（POST 请求的下载链接）走原逻辑
                url = download_url.get('url', '')
                data = download_url.get('data', {})
                resp = self.session.post(url, data=data, timeout=30, stream=True)
                resp.raise_for_status()

                os.makedirs(save_dir, exist_ok=True)
                tmp_path = f"{filepath}.part"
                with open(tmp_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                os.rename(tmp_path, filepath)
                return True

            # 使用自适应多模式下载引擎
            os.makedirs(save_dir, exist_ok=True)
            from services.download_manager import AdaptiveDownloader

            downloader = AdaptiveDownloader(
                url=download_url,
                file_path=filepath,
                referer=DEFAULT_HEADERS.get('Referer', ''),
            )
            success = downloader.download()
            if not success:
                # 清理失败残留的临时文件
                tmp_path = f"{filepath}.part"
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
            return success
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return False
