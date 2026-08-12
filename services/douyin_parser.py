# -*- coding: utf-8 -*-
"""
抖音解析核心模块（完整移植自 douyin_parse-master/douyin_video_parser.py v2.0.4）
============================================================================
- a_bogus / X-Bogus 签名生成（自动选择可用通道）
- 视频 ID 提取（分享链接 → aweme_id）
- 无水印视频地址 + 多清晰度提取
- 图集（含 Live 动图）数据提取
- 用户主页作品列表提取

适配本系统：
- Cookie 可从全局配置 CFG['douyin_cookie'] / douyin_cookie.txt 读取
- 保持 douyin_parse-master 全部核心接口对齐
"""
import re
import time
from typing import Optional
from urllib.parse import quote, urlencode

import requests

from services.douyin.abogus import ABogus
from services.douyin.xbogus import XBogus

try:
    from core.config import config as _CFG
except Exception:
    _CFG = None


class DouyinParseError(Exception):
    """抖音解析错误"""


# ═══════════════════════════════════════════════════════════
#  视频 ID 提取
# ═══════════════════════════════════════════════════════════
_ID_PATTERNS = [
    r'/video/(\d+)',
    r'/aweme/detail/(\d+)',
    r'/note/(\d+)',
    r'video_id=(\d+)',
    r'aweme_id=(\d+)',
    r'note_id=(\d+)',
]


def _extract_url(text: str) -> str:
    """从文本中提取第一个 URL"""
    patterns = [
        r'https?://[^\s]+',
        r'v\.douyin\.com/[^\s]+',
        r'douyin\.com/(video|note|user|aweme)/[^\s]+',
    ]
    for p in patterns:
        m = re.search(p, text or '')
        if m:
            url = m.group(0).strip('.,;!?')
            if not url.startswith('http'):
                url = 'https://' + url
            return url
    return (text or '').strip()


# ═══════════════════════════════════════════════════════════
#  DouyinVideoParser（与 douyin_parse-master v2.0.4 对齐）
# ═══════════════════════════════════════════════════════════
class DouyinVideoParser:
    """抖音视频解析器（a_bogus + X-Bogus 双通道签名）

    完整移植自 douyin_parse-master/douyin_video_parser.py v2.0.4
    """

    # 与 video_parse_api 保持一致的基础请求参数
    BASE_PARAMS = {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "pc_client_type": "1",
        "version_code": "190500",
        "version_name": "19.5.0",
        "cookie_enabled": "true",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Edge",
        "browser_online": "true",
        "engine_name": "Blink",
        "os_name": "Windows",
        "os_version": "10",
        "platform": "PC",
        "screen_width": "1920",
        "screen_height": "1080",
    }

    def __init__(self, user_agent: Optional[str] = None, cookie: str = '',
                 timeout: int = 15, api_interval: float = 1.0,
                 max_pages: int = 10):
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")
        # Cookie 优先级：显式传入 > 全局配置 > douyin_cookie.txt 文件
        self.cookie = (cookie or '').lstrip('\ufeff').strip() or self._load_cookie()
        self.timeout = timeout
        self.api_interval = api_interval
        self.max_pages = max_pages
        self.abogus = ABogus() if ABogus is not None else None
        self.xbogus = XBogus(self.user_agent) if XBogus is not None else None

    @staticmethod
    def _load_cookie() -> str:
        """从全局配置 / douyin_cookie.txt 加载 Cookie"""
        # 1. 全局配置
        if _CFG is not None:
            try:
                v = str(_CFG.get('douyin_cookie', '') or '')
                if v.strip():
                    return v.strip()
            except Exception:
                pass
        # 2. douyin_cookie.txt 文件
        try:
            import os
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(base, "douyin_cookie.txt"), "r", encoding="utf-8") as f:
                return f.read().lstrip("\ufeff").strip()
        except FileNotFoundError:
            return ""
        except Exception:
            return ""

    # ── Cookie ──
    def set_cookie(self, cookie: str):
        self.cookie = (cookie or '').lstrip('\ufeff').strip()
        if _CFG is not None:
            try:
                _CFG['douyin_cookie'] = self.cookie
            except Exception:
                pass

    # ── 视频 ID 提取 ──
    def get_video_id(self, share_url: str) -> Optional[str]:
        """从分享链接中提取视频ID，支持多种格式（v2.0.4 实现）"""
        # 先尝试从文本中提取URL（处理复制时可能包含的文本、换行等）
        url_patterns = [
            r'https?://[^\s]+',  # 标准URL
            r'v\.douyin\.com/[^\s]+',  # 短链接
            r'douyin\.com/video/\d+',  # 直接视频链接
            r'douyin\.com/aweme/detail/\d+',  # aweme detail链接
        ]

        extracted_url = None
        for pattern in url_patterns:
            match = re.search(pattern, share_url)
            if match:
                extracted_url = match.group(0)
                if not extracted_url.startswith('http'):
                    extracted_url = 'https://' + extracted_url
                break

        if not extracted_url:
            # 如果没有匹配到，尝试直接使用原字符串
            extracted_url = share_url.strip()

        # Method 1: 如果已经是完整URL格式，直接提取ID
        for pattern in _ID_PATTERNS:
            m = re.search(pattern, extracted_url)
            if m:
                return m.group(1)

        # Method 2: 尝试访问并获取重定向后的URL
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.user_agent,
            "Referer": "https://www.douyin.com/"
        })
        try:
            resp = session.get(extracted_url, allow_redirects=True, timeout=15)
            real_url = resp.url

            # 从重定向后的URL提取ID
            for pattern in _ID_PATTERNS:
                m = re.search(pattern, real_url)
                if m:
                    return m.group(1)

            # Method 3: 从页面HTML内容中提取视频ID
            html_content = resp.text
            id_patterns = [
                r'"aweme_id":"(\d+)"',
                r'"itemId":"(\d+)"',
                r'"video_id":"(\d+)"',
                r'"note_id":"(\d+)"',
                r'/video/(\d+)',
                r'/aweme/detail/(\d+)',
                r'/note/(\d+)',  # Note format
                r'aweme_id=(\d+)',
                r'video_id=(\d+)',
                r'note_id=(\d+)',
            ]
            for pattern in id_patterns:
                m = re.search(pattern, html_content)
                if m:
                    video_id = m.group(1)
                    # 验证ID是否为纯数字且长度合理（通常19位）
                    if video_id.isdigit() and len(video_id) >= 15:
                        return video_id
            return None
        except Exception:
            return None

    # ── 请求与签名 ──
    def _build_headers(self, referer: str = "https://www.douyin.com/") -> dict:
        h = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer,
            "Origin": "https://www.douyin.com",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    def _sign_abogus_url(self, base_url: str, params: dict) -> Optional[str]:
        """按 video_parse_api 方式签名：先 urlencode，再拼 a_bogus，避免二次编码（v2.0.3 修复）"""
        if self.abogus is None:
            return None
        try:
            param_str = urlencode(params)
            a_bogus = self.abogus.get_value(params)
            return f"{base_url}?{param_str}&a_bogus={quote(a_bogus, safe='')}"
        except Exception:
            return None

    def _request_json(self, api_url: str, params: dict, headers: dict) -> dict:
        """带签名请求（优先 A-Bogus，失败回退 X-Bogus）（v2.0.4 实现）"""
        # 先试 A-Bogus（完整 URL，避免 requests 对 a_bogus 二次编码）
        signed_url = self._sign_abogus_url(api_url, params)
        if signed_url:
            try:
                resp = requests.get(signed_url, headers=headers, timeout=self.timeout)
                if resp.status_code == 200 and resp.content:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("status_code") == 0:
                        return data
            except Exception:
                pass

        # 再试 X-Bogus
        if self.xbogus is None:
            return {}
        try:
            param_str = urlencode(params)
            signed_path, _, _ = self.xbogus.get_xbogus(param_str)
            xb_url = f"{api_url}?{signed_path}"
            resp = requests.get(xb_url, headers=headers, timeout=self.timeout)
            if resp.status_code == 200 and resp.content:
                data = resp.json()
                if isinstance(data, dict) and data.get("status_code") == 0:
                    return data
        except Exception:
            pass
        return {}

    # ── 视频详情 ──
    def get_aweme_detail(self, video_id: str,
                         original_url: Optional[str] = None) -> dict:
        """获取视频详情（aweme_detail）"""
        if self.abogus is None and self.xbogus is None:
            raise DouyinParseError("签名模块不可用（缺少 gmssl 依赖）")

        params = self.BASE_PARAMS.copy()
        params["aweme_id"] = video_id

        is_note = bool(original_url and "/note/" in original_url)
        referer = (f"https://www.douyin.com/note/{video_id}"
                   if is_note else f"https://www.douyin.com/video/{video_id}")
        headers = self._build_headers(referer)
        api_url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
        result = self._request_json(api_url, params, headers)

        if not result and not is_note:
            headers["Referer"] = f"https://www.douyin.com/note/{video_id}"
            result = self._request_json(api_url, params, headers)

        # status_code=0 但内容被过滤/删除时，视为失败
        if result and result.get("aweme_detail"):
            return result

        # 解析失败明细
        if result:
            raise DouyinParseError(
                f"解析失败（status_code={result.get('status_code', '无响应')}，"
                f"内容可能已被删除/过滤，请检查链接和 Cookie）")
        raise DouyinParseError("解析失败：无法获取API数据，请检查Cookie是否有效")

    # ── 内容类型判定 ──
    @staticmethod
    def get_content_type(data: dict) -> str:
        """Determine content type based on aweme_type"""
        aweme = data.get("aweme_detail") or {}
        aweme_type = aweme.get("aweme_type", 0)
        # Video: 0 or 4, Album: 2, 68, or other image types
        if aweme_type in (0, 4):
            return "video"
        if aweme_type in (2, 68):
            return "image"
        # Check if images field exists (for live albums or other special types)
        if aweme.get("images"):
            return "image"
        return "video"  # Default to video

    # ── 无水印地址提取 ──
    @staticmethod
    def extract_nwm_url(data: dict) -> Optional[str]:
        """Extract single watermark-free URL (backward compatibility)"""
        qualities = DouyinVideoParser.extract_video_qualities(data)
        if not qualities:
            return None
        # Return the highest quality URL by default
        return qualities[0]["url"]

    # ── 简化解析 ──
    def parse_to_nwm_url(self, share_url: str) -> Optional[str]:
        """简化调用：输入分享链接，返回无水印视频地址"""
        video_id = self.get_video_id(share_url)
        if not video_id:
            return None
        data = self.get_aweme_detail(video_id, original_url=share_url)
        if not data:
            return None
        return self.extract_nwm_url(data)

    def parse_video_meta(self, share_url: str) -> Optional[dict]:
        """仅解析视频基础信息（不计算无水印地址）"""
        video_id = self.get_video_id(share_url)
        if not video_id:
            return None
        data = self.get_aweme_detail(video_id, original_url=share_url)
        if not data:
            return None
        return self.extract_video_meta(data)

    # ── 图集数据提取（含 Live 动图） ──
    @staticmethod
    def extract_image_data(data: dict) -> Optional[dict]:
        """Extract album image URLs (including live images/GIFs)（v2.0.2 实现）"""
        aweme = data.get("aweme_detail") or {}
        images = aweme.get("images") or []

        if not images:
            return None

        # Separate live images and static images
        live_urls_set = set()  # GIF/live images
        static_urls_set = set()  # Static images
        watermark_urls_set = set()  # Watermarked images

        for img in images:
            if not isinstance(img, dict):
                continue

            # Check if this image is marked as animated/live
            live_photo_type = img.get("live_photo_type", 0)
            clip_type = img.get("clip_type", 0)
            has_video = bool(img.get("video"))

            is_animated_flag = (
                live_photo_type == 1 or
                clip_type == 5 or
                has_video or
                img.get("is_animated") == True or
                img.get("is_animated") == 1 or
                img.get("animated") == True or
                img.get("animated") == 1 or
                img.get("image_type") == "animated" or
                img.get("type") == "animated" or
                img.get("format") == "gif" or
                str(img.get("image_type", "")).lower() == "live"
            )

            # Priority 0: Extract video URL from video field (for live images)
            if has_video and is_animated_flag:
                video_obj = img.get("video", {})
                # Try play_addr first (watermark-free)
                play_addr = video_obj.get("play_addr", {})
                play_url_list = play_addr.get("url_list", [])
                if play_url_list:
                    url = play_url_list[0]
                    if url and isinstance(url, str):
                        clean_url = url.split("&watermark=")[0].split("&logo_name=")[0]
                        live_urls_set.add(clean_url)
                        continue
                # Fallback to download_addr (but remove watermark)
                download_addr = video_obj.get("download_addr", {})
                download_url_list = download_addr.get("url_list", [])
                if download_url_list:
                    url = download_url_list[0]
                    if url and isinstance(url, str):
                        clean_url = url.split("&watermark=")[0].split("&logo_name=")[0]
                        live_urls_set.add(clean_url)
                        continue

            # Priority 1: Try animated/live image fields
            animated_fields = [
                "animated_url_list", "animated_url",
                "gif_url_list", "gif_url",
                "live_url_list", "live_url",
                "motion_url_list", "motion_url",
            ]
            for field in animated_fields:
                url_data = img.get(field)
                if url_data:
                    if isinstance(url_data, str):
                        if url_data:
                            live_urls_set.add(url_data)
                    elif isinstance(url_data, list):
                        for url in url_data:
                            if url and isinstance(url, str):
                                live_urls_set.add(url)

            # Priority 2: Try url_list (static images, watermark-free)
            if not (has_video and is_animated_flag):
                url_list = img.get("url_list") or []
                if url_list:
                    url = url_list[0]
                    if url and isinstance(url, str):
                        url_lower = url.lower()
                        is_live_indicator = (
                            is_animated_flag or
                            any(indicator in url_lower for indicator in
                                [".gif", "gif", "animated", "motion", "live"]) or
                            "format=gif" in url_lower or
                            "animated=1" in url_lower or
                            "motion=1" in url_lower or
                            "type=animated" in url_lower or
                            "is_animated=1" in url_lower
                        )
                        if is_live_indicator:
                            live_urls_set.add(url)
                        else:
                            static_urls_set.add(url)

            # Priority 3: Try download_url_list (may have watermark)
            if not (has_video and is_animated_flag):
                download_list = img.get("download_url_list") or []
                if download_list:
                    url = download_list[0]
                    if url and isinstance(url, str):
                        watermark_urls_set.add(url)

            # Priority 4: Try other possible fields
            if not (has_video and is_animated_flag):
                for field in ["url", "origin_url"]:
                    url = img.get(field)
                    if url:
                        if isinstance(url, str):
                            url_lower = url.lower()
                            is_live_indicator = (
                                is_animated_flag or
                                any(indicator in url_lower for indicator in
                                    [".gif", "gif", "animated", "motion", "live"]) or
                                "format=gif" in url_lower or
                                "animated=1" in url_lower or
                                "motion=1" in url_lower or
                                "type=animated" in url_lower or
                                "is_animated=1" in url_lower
                            )
                            if is_live_indicator:
                                live_urls_set.add(url)
                            elif url not in static_urls_set and url not in watermark_urls_set:
                                static_urls_set.add(url)
                        elif isinstance(url, list) and url:
                            u = url[0]
                            if u and isinstance(u, str):
                                url_lower = u.lower()
                                is_live_indicator = (
                                    any(indicator in url_lower for indicator in
                                        [".gif", "gif", "animated", "motion", "live"]) or
                                    "format=gif" in url_lower or
                                    "animated=1" in url_lower or
                                    "motion=1" in url_lower or
                                    "type=animated" in url_lower or
                                    "is_animated=1" in url_lower
                                )
                                if is_live_indicator:
                                    live_urls_set.add(u)
                                elif u not in static_urls_set and u not in watermark_urls_set:
                                    static_urls_set.add(u)

        # Priority: Use live URLs if available, otherwise static, finally watermarked
        if live_urls_set:
            final_urls = list(live_urls_set)
            is_live = True
        elif static_urls_set:
            final_urls = list(static_urls_set)
            is_live = False
        elif watermark_urls_set:
            final_urls = list(watermark_urls_set)
            is_live = False
        else:
            return None

        # Final deduplication: remove URLs that are duplicates when query params are removed
        seen_clean = set()
        deduplicated_urls = []
        for url in final_urls:
            clean_url = url.split("?")[0] if "?" in url else url
            if clean_url not in seen_clean:
                seen_clean.add(clean_url)
                deduplicated_urls.append(url)

        if not deduplicated_urls:
            return None

        return {
            "image_urls": deduplicated_urls,
            "image_urls_watermark": list(watermark_urls_set),
            "image_count": len(deduplicated_urls),
            "preview_url": deduplicated_urls[0] if deduplicated_urls else None,
            "is_live": is_live,
        }

    # ── 视频多清晰度提取 ──
    @staticmethod
    def extract_video_qualities(data: dict) -> list:
        """Extract all available video quality options（v2.0.1 实现）"""
        aweme = data.get("aweme_detail") or {}
        video = aweme.get("video") or {}
        play_addr = video.get("play_addr") or {}
        bit_rate_list = video.get("bit_rate") or []
        uri = play_addr.get("uri")
        url_list = play_addr.get("url_list") or []

        qualities = []

        # Method 1: Extract from bit_rate list (most comprehensive)
        if bit_rate_list:
            for bit_rate_info in bit_rate_list:
                if not isinstance(bit_rate_info, dict):
                    continue

                play_addr_br = bit_rate_info.get("play_addr") or {}
                url_list_br = play_addr_br.get("url_list") or []
                bit_rate = bit_rate_info.get("bit_rate", 0)
                gear_name = bit_rate_info.get("gear_name", "")

                # Extract ratio from quality_type (handle both dict and int cases)
                ratio = ""
                quality_type = bit_rate_info.get("quality_type")
                if isinstance(quality_type, dict):
                    ratio = quality_type.get("name", "")
                elif isinstance(quality_type, (int, str)):
                    quality_str = str(quality_type)
                    ratio_match = re.search(r'(\d+p)', quality_str.lower())
                    if ratio_match:
                        ratio = ratio_match.group(1)

                # Parse ratio from gear_name if not found
                if not ratio and gear_name:
                    ratio_match = re.search(r'(\d+p)', gear_name.lower())
                    if ratio_match:
                        ratio = ratio_match.group(1)

                # If no ratio found, try to infer from bit_rate
                if not ratio:
                    if bit_rate >= 2000000:
                        ratio = "1080p"
                    elif bit_rate >= 1000000:
                        ratio = "720p"
                    elif bit_rate >= 500000:
                        ratio = "540p"
                    else:
                        ratio = "480p"

                if url_list_br:
                    for url in url_list_br:
                        nwm_url = url.replace("playwm", "play")
                        quality_label = f"{ratio} ({bit_rate // 1000}Kbps)" if bit_rate else ratio
                        qualities.append({
                            "url": nwm_url,
                            "ratio": ratio,
                            "bit_rate": bit_rate,
                            "quality_label": quality_label,
                            "gear_name": gear_name,
                        })

        # Method 2: Extract from play_addr url_list (fallback)
        if not qualities and url_list:
            for url in url_list:
                nwm_url = url.replace("playwm", "play")
                ratio_match = re.search(r'ratio=(\d+p)', url.lower())
                ratio = ratio_match.group(1) if ratio_match else "1080p"
                qualities.append({
                    "url": nwm_url,
                    "ratio": ratio,
                    "bit_rate": 0,
                    "quality_label": ratio,
                    "gear_name": "",
                })

        # Method 3: Construct from uri with different ratios (last resort)
        if not qualities and uri:
            for ratio in ["1080p", "720p", "540p", "480p", "360p"]:
                nwm_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio={ratio}&line=0"
                qualities.append({
                    "url": nwm_url,
                    "ratio": ratio,
                    "bit_rate": 0,
                    "quality_label": ratio,
                    "gear_name": "",
                })

        # Remove duplicates and sort by quality (highest first)
        seen_urls = set()
        unique_qualities = []
        for q in qualities:
            if q["url"] not in seen_urls:
                seen_urls.add(q["url"])
                unique_qualities.append(q)

        def sort_key(q):
            ratio_order = {"1080p": 5, "720p": 4, "540p": 3, "480p": 2, "360p": 1}
            return (q["bit_rate"], ratio_order.get(q["ratio"], 0))

        unique_qualities.sort(key=sort_key, reverse=True)

        return unique_qualities

    # ── 视频元数据 ──
    @staticmethod
    def extract_video_meta(data: dict) -> dict:
        aweme = data.get("aweme_detail") or {}
        author = aweme.get("author") or {}
        video = aweme.get("video") or {}
        cover = video.get("cover") or {}
        cover_list = cover.get("url_list") or []
        stats = aweme.get("statistics") or {}

        # Determine content type
        content_type = DouyinVideoParser.get_content_type(data)

        meta = {
            "aweme_id": aweme.get("aweme_id"),
            "desc": aweme.get("desc"),
            "create_time": aweme.get("create_time"),
            "author_nickname": author.get("nickname"),
            "author_sec_uid": author.get("sec_uid"),
            "author_signature": author.get("signature"),
            "avatar_url": (author.get("avatar_thumb") or {}).get("url_list", [None])[0],
            "cover_url": cover_list[0] if cover_list else None,
            "content_type": content_type,
            "digg_count": stats.get("digg_count"),
            "comment_count": stats.get("comment_count"),
            "share_count": stats.get("share_count"),
            "collect_count": stats.get("collect_count"),
            "duration": video.get("duration"),
            "width": video.get("width"),
            "height": video.get("height"),
        }

        # Add image data for albums
        if content_type == "image":
            image_data = DouyinVideoParser.extract_image_data(data)
            if image_data:
                meta["image_count"] = image_data.get("image_count", 0)
                meta["image_urls"] = image_data.get("image_urls", [])
                meta["is_live"] = image_data.get("is_live", False)
                # Use first image as cover if no video cover
                if not meta["cover_url"] and image_data.get("preview_url"):
                    meta["cover_url"] = image_data["preview_url"]

        return meta

    # ── 统一解析入口 ──
    def parse_video(self, share_url: str) -> dict:
        """返回完整解析结果（无水印地址 + 基本信息 + 所有质量选项/图集数据）"""
        video_id = self.get_video_id(share_url)
        if not video_id:
            raise DouyinParseError("无法提取视频 ID，请确认链接是否为有效的抖音视频/图集链接")

        data = self.get_aweme_detail(video_id, original_url=share_url)
        if not data:
            raise DouyinParseError("解析失败：无法获取API数据，请检查Cookie是否有效")

        meta = self.extract_video_meta(data)
        content_type = meta.get("content_type", "video")

        result = {**meta}

        if content_type == "video":
            # Video: return nwm_url and qualities
            nwm_url = self.extract_nwm_url(data)
            qualities = self.extract_video_qualities(data)
            result["nwm_url"] = nwm_url
            result["qualities"] = qualities
            # If no video data found, raise error
            if not nwm_url and not qualities:
                raise DouyinParseError("未找到视频地址（可能已删除或被过滤）")
        elif content_type == "image":
            # Album: return image_data
            image_data = self.extract_image_data(data)
            if image_data:
                result["image_data"] = image_data
                result["image_urls"] = image_data.get("image_urls", [])
                result["image_count"] = image_data.get("image_count", 0)
                result["is_live"] = image_data.get("is_live", False)
            else:
                raise DouyinParseError("未找到图集数据（可能已删除或被过滤）")

        return result

    # ── 用户主页解析 ──
    @staticmethod
    def get_sec_uid(user_url: str) -> Optional[str]:
        """从用户链接中提取sec_uid，支持多种格式"""
        url = _extract_url(user_url) or (user_url or "").strip()
        patterns = [
            r"/user/([^/?\s]+)",
            r"sec_uid=([^&\s]+)",
            r"user/([^/?\s]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                return m.group(1)
        return None

    def get_user_home_from_video_url(self, share_url: str) -> Optional[str]:
        """从视频链接反查用户主页"""
        video_id = self.get_video_id(share_url)
        if not video_id:
            return None
        data = self.get_aweme_detail(video_id, original_url=share_url)
        if not data:
            return None
        aweme = data.get("aweme_detail") or {}
        author = aweme.get("author") or {}
        sec_uid = author.get("sec_uid")
        if not sec_uid:
            return None
        return f"https://www.douyin.com/user/{sec_uid}"

    def get_user_aweme_urls_from_video_url(
        self,
        share_url: str,
        max_pages: Optional[int] = None,
        count: int = 20
    ) -> list:
        """从视频链接反查用户主页并获取作品列表"""
        user_home = self.get_user_home_from_video_url(share_url)
        if not user_home:
            return []
        max_pages = max_pages or self.max_pages
        return self.get_user_aweme_urls(user_home, max_pages=max_pages, count=count)

    def get_user_aweme_urls(self, user_url: str, max_pages: Optional[int] = None,
                            count: int = 20) -> list:
        """批量获取用户主页作品 URL 列表"""
        sec_uid = self.get_sec_uid(user_url)
        if not sec_uid:
            raise DouyinParseError("无法提取用户 sec_uid")

        max_pages = max_pages or self.max_pages
        headers = self._build_headers("https://www.douyin.com/")
        api_url = "https://www.douyin.com/aweme/v1/web/aweme/post/"
        max_cursor = 0
        urls = []
        seen = set()

        for _ in range(max_pages):
            params = self.BASE_PARAMS.copy()
            params.update({
                "sec_user_id": sec_uid,
                "max_cursor": str(max_cursor),
                "count": str(count),
                "locate_query": "false",
                "show_live_replay_strategy": "1",
                "need_time_list": "1",
                "time_list_query": "0",
                "whale_cut_token": "",
                "cut_version": "1",
                "publish_video_strategy_type": "2",
            })

            data = self._request_json(api_url, params, headers)
            if not data:
                break

            aweme_list = data.get("aweme_list") or []
            for aweme in aweme_list:
                aweme_id = aweme.get("aweme_id")
                if aweme_id:
                    url = f"https://www.douyin.com/video/{aweme_id}"
                    if url not in seen:
                        seen.add(url)
                        urls.append(url)

            if not data.get("has_more"):
                break
            max_cursor = data.get("max_cursor") or 0
            time.sleep(self.api_interval)

        return urls


def get_nwm_url(share_url: str) -> Optional[str]:
    """简化调用：输入分享链接，输出无水印真实地址"""
    return DouyinVideoParser().parse_to_nwm_url(share_url)