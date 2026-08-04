# -*- coding: utf-8 -*-
"""
多平台解析器
============
提供哔哩哔哩、推特(X)、Xvideo、Pixiv、YouTube 等平台的链接解析功能。
"""
import os
import re
import json
import html
import time
import threading
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# ═══════════════════════════════════════════════════════════
#  通用工具
# ═══════════════════════════════════════════════════════════
def sanitize_filename(filename: str) -> str:
    """去除 Windows 文件名中的无效字符"""
    if not filename:
        return 'untitled'
    filename = filename.replace('\n', '')
    filename = filename.replace(' ', '')
    filename = filename.replace('#', '_')
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    return filename.strip() or 'untitled'


def extract_url(text: str) -> str:
    """从文本中提取 URL"""
    if not text:
        return None
    i = text.rfind("http://")
    if i == -1:
        i = text.rfind("https://")
    if i == -1:
        return None
    e = text[i:]
    r = e.rfind(" ")
    if r != -1:
        e = e[:r]
    return e


class MediaItem:
    """媒体下载项"""
    def __init__(self, title='', url='', preview_url='', media_type='video', quality='',
                 is_hls=False, referer=''):
        self.title = title
        self.url = url
        self.preview_url = preview_url
        self.media_type = media_type  # 'image' | 'video' | 'audio'
        self.quality = quality        # 清晰度（如 '1080p'、'720p'），可为空
        self.is_hls = is_hls          # 是否为 HLS 流媒体（需下载分片合并）
        self.referer = referer        # 下载时需要的 Referer（部分站点防盗链）

    def to_dict(self):
        return {
            'title': self.title,
            'url': self.url,
            'preview_url': self.preview_url,
            'media_type': self.media_type,
            'quality': self.quality,
            'is_hls': self.is_hls,
            'referer': self.referer,
        }


# ═══════════════════════════════════════════════════════════
#  抖音解析器（SnapAny，与现有 video_page 一致的逻辑）
# ═══════════════════════════════════════════════════════════
class DouyinParser:
    """抖音视频解析（SnapAny）"""

    @staticmethod
    def md5(message):
        import hashlib
        return hashlib.md5(message).hexdigest()

    def parse(self, url: str) -> list:
        """解析抖音链接，返回 MediaItem 列表"""
        url = extract_url(url)
        if not url:
            return []

        timestamp = int(time.time() * 1000)
        input_str = url + "zh" + str(timestamp) + "6HTugjCXxR"
        footer = self.md5(input_str.encode())

        headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'G-Footer': footer,
            'G-Timestamp': str(timestamp),
            'Origin': 'https://snapany.com',
            'Referer': 'https://snapany.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
        }
        try:
            response = requests.post(
                'https://api.snapany.com/v1/extract',
                headers=headers,
                json={'link': url},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                text = data.get("text", "")
                items = []
                for media in data.get("medias", []):
                    if "media_type" in media and "resource_url" in media:
                        mtype = media["media_type"]
                        items.append(MediaItem(
                            title=text or f'douyin_{int(time.time())}',
                            url=media["resource_url"],
                            preview_url=media.get("preview_url", media["resource_url"]),
                            media_type=mtype
                        ))
                return items
        except Exception:
            pass
        return []


# ═══════════════════════════════════════════════════════════
#  哔哩哔哩解析器
# ═══════════════════════════════════════════════════════════
class BilibiliParser:
    """哔哩哔哩视频解析"""

    BILI_HEADERS = {
        'referer': 'https://www.bilibili.com',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
    }

    @staticmethod
    def get_id(url_input, id_type):
        # 匹配 /BVxxxx 或 ?v=BVxxxx
        match = re.search(id_type + r'([A-Za-z0-9]+)', url_input)
        return match.group(1) if match else ''

    def get_bv_info(self, bv, sessdata=''):
        """获取视频基本信息"""
        url = 'https://api.bilibili.com/x/web-interface/wbi/view?'
        data = {'bvid': bv}
        headers = self.BILI_HEADERS
        cookies = {'SESSDATA': sessdata} if sessdata else {}
        try:
            request = requests.get(url, params=data, headers=headers, cookies=cookies, timeout=10)
            info = request.json()
            if info.get('code') != 0:
                return None
            title = sanitize_filename(info['data']['title'])
            cover = info['data']['pic']
            pages = info['data']['pages']
            result = []
            for page in pages:
                cid = page['cid']
                subtitle = sanitize_filename(page['part'])
                result.append({
                    'bv': bv,
                    'cid': cid,
                    'title': title,
                    'subtitle': subtitle,
                    'cover': cover,
                })
            return result
        except Exception:
            return None

    def get_stream_info(self, bv, cid, sessdata=''):
        """获取视频和音频流 URL"""
        url = 'https://api.bilibili.com/x/player/playurl?'
        data = {'bvid': bv, 'cid': cid, 'fnval': '16', 'fnver': '0', 'fourk': '1'}
        headers = self.BILI_HEADERS
        cookies = {'SESSDATA': sessdata} if sessdata else {}
        try:
            request = requests.get(url, params=data, headers=headers, cookies=cookies, timeout=10)
            info = request.json()
            if info.get('code') != 0:
                return None
            dash = info['data'].get('dash', {})
            # 视频流：选择最高画质
            videos = dash.get('video', [])
            if not videos:
                return None
            best_video = max(videos, key=lambda v: v.get('id', 0))
            # 音频流
            audios = dash.get('audio', [])
            best_audio = max(audios, key=lambda a: a.get('id', 0)) if audios else None
            return {
                'video_url': best_video['baseUrl'],
                'audio_url': best_audio['baseUrl'] if best_audio else None,
                'quality': f"{best_video['id']}",
            }
        except Exception:
            return None

    def parse(self, url: str, sessdata='') -> list:
        """解析 B 站链接，返回 MediaItem 列表"""
        bv = self.get_id(url, 'BV')
        if not bv:
            return []
        info_list = self.get_bv_info(bv, sessdata)
        if not info_list:
            return []
        items = []
        for info in info_list:
            stream = self.get_stream_info(info['bv'], info['cid'], sessdata)
            if stream and stream['video_url']:
                items.append(MediaItem(
                    title=info['subtitle'] or info['title'],
                    url=stream['video_url'],
                    preview_url=info['cover'],
                    media_type='video'
                ))
                if stream.get('audio_url'):
                    items.append(MediaItem(
                        title=f"{info['subtitle'] or info['title']}_audio",
                        url=stream['audio_url'],
                        preview_url=info['cover'],
                        media_type='audio'
                    ))
        return items


# ═══════════════════════════════════════════════════════════
#  推特(X)解析器（SaveTwitter）
# ═══════════════════════════════════════════════════════════
class TwitterParser:
    """推特/X 解析（savetwitter.net）

    从每个 tw-video 容器中的下载按钮文字精确判断媒体类型：
    - "Download Photo" → 图片
    - "Download MP4" → 视频
    """

    HEADERS = {
        'accept': '*/*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'origin': 'https://savetwitter.net',
        'referer': 'https://savetwitter.net/en',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
    }

    # 下载链接往往是无扩展名的 dl.snapcdn.app/get?token=...，需用 HEAD 探测真实类型
    @staticmethod
    def _probe_type(dl_url: str) -> str:
        """通过 HEAD 请求 Content-Type 探测实际文件类型"""
        try:
            resp = requests.head(dl_url, allow_redirects=True, timeout=8)
            ct = resp.headers.get('Content-Type', '').lower()
            if ct.startswith('image/'):
                return 'image'
            if ct.startswith('video/'):
                return 'video'
            if ct.startswith('audio/'):
                return 'audio'
            # 从 URL 扩展名兜底
            clean = dl_url.split('?')[0].lower()
            if clean.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')):
                return 'image'
            if clean.endswith(('.mp4', '.webm', '.mkv', '.mov', '.avi')):
                return 'video'
        except Exception:
            pass
        return 'video'  # 兜底默认视频

    # 常见清晰度标识
    QUALITY_PATTERNS = [
        (r'(\d{3,4})[pP]', lambda m: f"{m.group(1)}p"),       # 720p/1080p
        (r'4[Kk]', lambda m: '4K'),
        (r'`?2[Kk]', lambda m: '2K'),
        (r'([Hh][Dd])', lambda m: 'HD'),
        (r'([Ff][Uu][Ll]{2} ?[Hh][Dd])', lambda m: 'FullHD'),
    ]

    @staticmethod
    def _extract_quality(text: str) -> str:
        """从按钮文字中提取清晰度标识，找不到返回空"""
        for pattern, fmt in TwitterParser.QUALITY_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return fmt(m)
        return ''

    def parse(self, url: str) -> list:
        """解析推特链接，返回 MediaItem 列表（精确标注图片/视频类型 + 清晰度）"""
        try:
            data = {'q': url, 'lang': 'en'}
            response = requests.post(
                'https://savetwitter.net/api/ajaxSearch',
                headers=self.HEADERS,
                data=data,
                timeout=15
            )
            response_json = response.json()
            html_content = response_json.get('data', '')
            soup = BeautifulSoup(html_content, "html.parser")

            # 收集 (下载链接, 类型, 清晰度) 列表：遍历每个 tw-video 容器
            media_items = []
            tw_video_divs = soup.find_all("div", class_="tw-video")
            # 每个视频容器可能包含多个清晰度按钮
            for video_div in tw_video_divs:
                for a in video_div.find_all("a", href=True):
                    text = a.get_text().strip()
                    href = a['href'].strip()
                    if not href:
                        continue
                    quality = self._extract_quality(text)
                    if "Photo" in text or "图片" in text or "image" in text.lower():
                        media_items.append((href, 'image', ''))
                    elif "MP4" in text or "Video" in text or "视频" in text or quality:
                        media_items.append((href, 'video', quality))

            # 若上面未解析到（页面结构变化），使用正则提取下载链接 + HEAD 探测类型
            if not media_items:
                pattern_data = r'https://dl\.snapcdn\.app/get\?token=[\w\.-]+'
                raw_links = re.findall(pattern_data, response.text)
                for dl in raw_links:
                    media_items.append((dl, self._probe_type(dl), ''))

            # 提取封面（供预览）
            covers = re.findall(r'https://pbs\.twimg\.com/(?:amplify_video_thumb/\d+/img/[\w-]+\.(?:jpg|jpeg|png|gif)|media/[\w-]+\.(?:jpg|jpeg|png|gif)|ext_tw_video_thumb/\d+/pu/img/[\w-]+\.(?:jpg|jpeg|png|gif))', response.text)

            # 同一视频多个清晰度按清晰度降序排序（4K > 1080p > 720p > ...）
            def quality_rank(q):
                if not q:
                    return 0
                if '4K' in q:
                    return 100000
                if '2K' in q:
                    return 90000
                m = re.search(r'(\d+)', q)
                return int(m.group(1)) if m else 1000
            media_items.sort(key=lambda x: quality_rank(x[2]), reverse=True)

            items = []
            ts = int(time.time())
            for i, (dl_url, mtype, quality) in enumerate(media_items):
                cover = covers[i if i < len(covers) else -1] if covers else ''
                title = f'twitter_{ts}'
                if quality:
                    title += f'_{quality}'
                title += f'_{i+1}'
                items.append(MediaItem(
                    title=title,
                    url=dl_url,
                    preview_url=cover,
                    media_type=mtype,
                    quality=quality
                ))
            return items
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════
#  Xvideo 解析器
# ═══════════════════════════════════════════════════════════
class XvideoParser:
    """Xvideo 视频解析"""

    REGEX_M3U8 = re.compile(r"html5player\.setVideoHLS\('([^']+)'\);")
    REGEX_TITLE = re.compile(r'<title>(.*?)</title>', re.DOTALL)
    REGEX_THUMB = re.compile(r'<meta property="og:image" content="(.*?)"')

    def parse(self, url: str) -> list:
        """解析 Xvideos 链接，返回 MediaItem 列表"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.xvideos.com/',
        }
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                return []
            text = response.text
            # 提取标题
            title_match = self.REGEX_TITLE.search(text)
            title = sanitize_filename(title_match.group(1).strip()) if title_match else f'xvideo_{int(time.time())}'
            # 提取缩略图
            thumb_match = self.REGEX_THUMB.search(text)
            thumb = thumb_match.group(1) if thumb_match else ''
            # 提取 m3u8 链接
            m3u8_match = self.REGEX_M3U8.search(text)
            if m3u8_match:
                m3u8_url = m3u8_match.group(1)
                # 获取最高质量流
                best_url = self._resolve_m3u8(m3u8_url)
                # HLS 流媒体：需要下载分片合并，is_hls=True
                return [MediaItem(
                    title=title, url=best_url, preview_url=thumb,
                    media_type='video', is_hls=True,
                    referer='https://www.xvideos.com/'
                )]
            # 尝试提取直链
            content_url = self._extract_content_url(text)
            if content_url:
                return [MediaItem(title=title, url=content_url, preview_url=thumb, media_type='video')]
        except Exception:
            pass
        return []

    def _extract_content_url(self, html_text):
        # 尝试从 JSON-LD 中提取 contentUrl
        soup = BeautifulSoup(html_text, 'html.parser')
        for script in soup.find_all('script', {'type': 'application/ld+json'}):
            try:
                data = json.loads(script.string.strip())
                content_url = data.get('contentUrl', '')
                if content_url:
                    return content_url
            except Exception:
                pass
        return ''

    def _resolve_m3u8(self, m3u8_url):
        """解析 m3u8 主列表，选择最高质量流"""
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            resp = requests.get(m3u8_url, headers=headers, timeout=10)
            lines = resp.text.strip().split('\n')
            best = None
            best_res = 0
            for i, line in enumerate(lines):
                if line.startswith('#EXT-X-STREAM-INF'):
                    # 解析分辨率
                    res_match = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
                    if res_match:
                        res = int(res_match.group(1)) * int(res_match.group(2))
                        if res > best_res:
                            best_res = res
                            if i + 1 < len(lines):
                                url = lines[i+1].strip()
                                if not url.startswith('http'):
                                    url = m3u8_url.rsplit('/', 1)[0] + '/' + url
                                best = url
            return best or m3u8_url
        except Exception:
            return m3u8_url


# ═══════════════════════════════════════════════════════════
#  Pixiv 解析器
# ═══════════════════════════════════════════════════════════
class PixivParser:
    """Pixiv 插画/图片解析"""

    def parse(self, url: str) -> list:
        """解析 Pixiv 链接，返回 MediaItem 列表"""
        # Pixiv 链接格式通常为 https://www.pixiv.net/artworks/{id}
        match = re.search(r'pixiv\.net/(?:en/)?artworks/(\d+)', url)
        if not match:
            return []
        artwork_id = match.group(1)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.pixiv.net/',
            }
            resp = requests.get(f'https://www.pixiv.net/ajax/illust/{artwork_id}',
                                headers=headers, timeout=15)
            data = resp.json()
            if data.get('error'):
                return []
            body = data['body']
            title = sanitize_filename(body.get('title', f'pixiv_{artwork_id}'))
            # 提取原始图片 URL
            urls = body.get('urls', {})
            items = []
            original = urls.get('original', urls.get('regular', ''))
            if original:
                items.append(MediaItem(
                    title=title,
                    url=original,
                    preview_url=urls.get('regular', original),
                    media_type='image'
                ))
            # 多图作品
            for i, page in enumerate(body.get('metaPages', [])[:10], start=2):
                page_url = page.get('imageUrls', {}).get('original', '')
                if page_url:
                    items.append(MediaItem(
                        title=f"{title}_{i}",
                        url=page_url,
                        preview_url=page.get('imageUrls', {}).get('regular', page_url),
                        media_type='image'
                    ))
            return items
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════
#  YouTube 解析器
# ═══════════════════════════════════════════════════════════
class YouTubeParser:
    """YouTube 视频解析"""

    def parse(self, url: str) -> list:
        """解析 YouTube 链接，返回 MediaItem 列表"""
        match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})', url)
        if not match:
            return []
        video_id = match.group(1)
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = requests.get(f'https://www.youtube.com/watch?v={video_id}',
                                headers=headers, timeout=15)
            # 提取标题
            title_match = re.search(r'<title>(.*?)</title>', resp.text)
            title = sanitize_filename(title_match.group(1).replace(' - YouTube', '')) if title_match else f'youtube_{video_id}'
            # 提取缩略图
            thumb = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'
            # 提取 streamingData 中的视频 URL
            urls = self._extract_stream_urls(resp.text)
            if urls:
                return [MediaItem(title=title, url=urls[0], preview_url=thumb, media_type='video')]
        except Exception:
            pass
        return []

    def _extract_stream_urls(self, html_text):
        """从页面中提取视频流 URL（尝试解析 ytInitialPlayerResponse）"""
        # 寻找 ytInitialPlayerResponse
        match = re.search(r'var ytInitialPlayerResponse\s*=\s*({.*?});', html_text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(1))
            formats = data.get('streamingData', {}).get('formats', [])
            adaptive = data.get('streamingData', {}).get('adaptiveFormats', [])
            all_formats = formats + adaptive
            # 按画质排序
            def get_quality(fmt):
                h = fmt.get('height', 0) or 0
                w = fmt.get('width', 0) or 0
                return w * h
            all_formats.sort(key=get_quality, reverse=True)
            urls = []
            for fmt in all_formats:
                url = fmt.get('url')
                if url:
                    urls.append(url)
            return urls
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════
#  解析器工厂
# ═══════════════════════════════════════════════════════════
PARSER_MAP = {
    'douyin': DouyinParser,
    'bilibili': BilibiliParser,
    'twitter': TwitterParser,
    'pixiv': PixivParser,
    'xvideo': XvideoParser,
    'youtube': YouTubeParser,
}


def get_parser(platform: str):
    """获取对应平台的解析器实例"""
    cls = PARSER_MAP.get(platform)
    return cls() if cls else None


def parse_url(platform: str, url: str, **kwargs) -> list:
    """解析指定平台的链接，返回 MediaItem 列表"""
    parser = get_parser(platform)
    if not parser:
        return []
    return parser.parse(url, **kwargs)