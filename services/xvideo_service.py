# -*- coding: utf-8 -*-
"""Xvideo 解析服务模块

集成 Xvideos 视频在线解析（XvideoParser）：
- 提取页面标题/缩略图/m3u8 流
- HLS 流媒体自动解析最高质量（is_hls 标记）
- 生成与聚合层一致的 MediaItem 列表

便于后续单独维护 Xvideo 平台功能，无需改动聚合层 platform_parsers。
"""
import json
import re
import time

import requests
from bs4 import BeautifulSoup

from services.media_item import MediaItem, sanitize_filename


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