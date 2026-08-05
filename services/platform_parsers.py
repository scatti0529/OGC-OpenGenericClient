# -*- coding: utf-8 -*-
"""
多平台解析器（聚合层）
======================
兼容层：统一入口，将各平台解析功能转发到独立的 platform service 模块。

各平台独立服务文件（便于单独维护）：
    services/media_item.py      —— MediaItem 模型 / sanitize_filename
    services/twitter_service.py —— 推特(X) 解析（savetwitter + gallery-dl 备用）
    services/bilibili_service.py—— 哔哩哔哩解析
    services/xvideo_service.py  —— Xvideo 解析
    services/youtube_service.py —— YouTube 解析
    services/pixiv_service.py   —— Pixiv 下载/解析
    services/douyin_service.py  —— 抖音 下载/解析

本文件仅做导入转发 + 保留旧有统一接口（get_parser / parse_url / PARSER_MAP），
页面与既有调用方无需任何改动。
"""
import time

import requests

from services.media_item import MediaItem, sanitize_filename


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
#  各平台解析器（从独立 service 模块转发）
# ═══════════════════════════════════════════════════════════
from services.twitter_service import (
    TwitterParser, TwitterGalleryDLParser, GALLERY_DL_PROJECT_DIR,
)
from services.bilibili_service import BilibiliParser
from services.xvideo_service import XvideoParser
from services.youtube_service import YouTubeParser
from services.pixiv_service import PixivParser


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