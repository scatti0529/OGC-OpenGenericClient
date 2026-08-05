# -*- coding: utf-8 -*-
"""哔哩哔哩解析服务模块

集成 B 站视频在线解析（BilibiliParser）：
- 通过 BV 号查询视频信息（wbi/view）
- 获取最高画质流（dash video + audio）
- 生成与聚合层一致的 MediaItem 列表

便于后续单独维护哔哩哔哩平台功能，无需改动聚合层 platform_parsers。
"""
import re

import requests

from services.media_item import MediaItem, sanitize_filename


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
            request = requests.get(url, params=data, headers=headers,
                                   cookies=cookies, timeout=10)
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
            request = requests.get(url, params=data, headers=headers,
                                   cookies=cookies, timeout=10)
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