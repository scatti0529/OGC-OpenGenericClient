# -*- coding: utf-8 -*-
"""媒体数据模型与通用工具（平台服务层共享基座）

所有平台解析服务（twitter_service / bilibili_service / pixiv_service ...）
与聚合层 platform_parsers 共用本模块的 MediaItem / sanitize_filename，
避免循环导入。
"""
import re


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


def sanitize_filename(filename: str) -> str:
    """去除 Windows 文件名中的无效字符"""
    if not filename:
        return 'untitled'
    filename = filename.replace('\n', '')
    filename = filename.replace(' ', '')
    filename = filename.replace('#', '_')
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    return filename.strip() or 'untitled'