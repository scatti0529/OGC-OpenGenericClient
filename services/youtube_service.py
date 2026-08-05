# -*- coding: utf-8 -*-
"""YouTube 解析服务模块

集成 YouTube 视频在线解析（YouTubeParser）：
- 匹配常规/watch 与短链 youtu.be
- 解析 ytInitialPlayerResponse 提取最高画质流
- 生成与聚合层一致的 MediaItem 列表

便于后续单独维护 YouTube 平台功能，无需改动聚合层 platform_parsers。
"""
import json
import re

import requests

from services.media_item import MediaItem, sanitize_filename


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