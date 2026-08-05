# -*- coding: utf-8 -*-
"""推特(X)解析服务模块

集成 savetwitter.net 原解析 + gallery-dl 专用备用解析：
- TwitterParser：savetwitter.net 在线解析（默认方式）
- TwitterGalleryDLParser：调用 OGC多功能版/twitter 中的 gallery-dl 专用下载器
  （原解析重试 3 次仍失败时自动切换的备用方案）

便于后续单独维护推特平台功能，无需改动聚合层 platform_parsers。
"""
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from services.media_item import MediaItem, sanitize_filename


# ═══════════════════════════════════════════════════════════
#  gallery-dl 推特备用解析器
# ═══════════════════════════════════════════════════════════
# 独立调用 OGC多功能版/twitter 中的 gallery-dl（--dump-json），
# 用于在 savetwitter.net 原解析重试 3 次仍失败时作为备用解析手段。
GALLERY_DL_PROJECT_DIR = r'E:\项目程序\PY项目\测试程序\OGC多功能版\twitter'


class TwitterGalleryDLParser:
    """推特/X 备用解析（调用 gallery-dl，专用 Twitter 下载器）

    通过子进程运行 gallery-dl：
       python -m gallery_dl --no-colors -o input=true --dump-json <url>
    从输出消息流中提取所有文件的直链、类型、预览图、标题，
    生成与 savetwitter.net 相同的 MediaItem 列表。
    """

    # 常见媒体类型 → MediaItem.media_type
    EXT2TYPE = {
        '.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.gif': 'image',
        '.webp': 'image', '.bmp': 'image', '.avif': 'image',
        '.mp4': 'video', '.webm': 'video', '.mkv': 'video', '.mov': 'video',
        '.mp3': 'audio', '.m4a': 'audio', '.aac': 'audio', '.wav': 'audio',
        '.flac': 'audio', '.ogg': 'audio',
    }

    @staticmethod
    def _resolve_project_dir() -> str:
        """返回 gallery-dl 项目根目录（存在指定目录时使用，否则尝试相对定位）"""
        if os.path.isdir(GALLERY_DL_PROJECT_DIR):
            return GALLERY_DL_PROJECT_DIR
        # 兜底：尝试从当前项目相对路径定位
        alt = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '..', 'OGC多功能版', 'twitter')
        if os.path.isdir(alt):
            return os.path.normpath(alt)
        # 再兜底：环境变量
        env = os.environ.get('GALLERY_DL_TWITTER_DIR', '')
        if env and os.path.isdir(env):
            return env
        return ''

    # 常见浏览器（gallery-dl --cookies-from-browser 支持）
    BROWSERS = ('firefox', 'chrome', 'edge', 'chromium', 'brave', 'opera', 'vivaldi')

    @staticmethod
    def _find_browser_with_cookie() -> str:
        """探测常见浏览器中是否存在 Cookie 数据库，返回第一个可用的浏览器名；全无返回''"""
        found = []
        home = os.path.expanduser('~')
        for browser in TwitterGalleryDLParser.BROWSERS:
            candidates = []
            if browser == 'firefox':
                candidates.extend([
                    os.path.join(home, 'AppData', 'Roaming', 'Mozilla', 'Firefox', 'Profiles'),
                    os.path.join(home, '.mozilla', 'firefox'),
                ])
            elif browser in ('chrome', 'chromium', 'edge', 'brave', 'opera', 'vivaldi'):
                bases = {
                    'chrome': ('AppData/Local/Google/Chrome/User Data', '.config/google-chrome'),
                    'chromium': ('AppData/Local/Chromium/User Data', '.config/chromium'),
                    'edge': ('AppData/Local/Microsoft/Edge/User Data', '.config/microsoft-edge'),
                    'brave': ('AppData/Local/BraveSoftware/Brave-Browser/User Data',
                              '.config/BraveSoftware/Brave-Browser'),
                    'opera': ('AppData/Roaming/Opera Software/Opera Stable', '.config/opera'),
                    'vivaldi': ('AppData/Local/Vivaldi/User Data', '.config/vivaldi'),
                }
                for rel in bases[browser]:
                    candidates.append(os.path.join(home, rel.replace('/', os.sep)))
            for cand in candidates:
                if os.path.isdir(cand) or os.path.isfile(cand):
                    found.append(browser)
                    break
        if not found:
            return ''
        # 优先 firefox（gallery-dl twitter 默认浏览器）
        return 'firefox' if 'firefox' in found else found[0]

    def _run(self, url: str, timeout: int = 60) -> str:
        """运行 gallery-dl --dump-json，返回标准输出文本；失败返回''。

        自动从浏览器加载 Twitter 登录 Cookie（auth_token），避免 X 反爬
        （ConnectionResetError / 返回 ['error']）。与 OGC多功能版/twitter
        的默认行为（--cookies-from-browser）保持一致。
        """
        project_dir = self._resolve_project_dir()
        if not project_dir:
            return ''
        import subprocess

        browser = self._find_browser_with_cookie()
        attempted_cmds = []
        if browser:
            # 优先携带浏览器 Cookie 运行（公开/受限推文均可解析）
            attempted_cmds.append([
                sys.executable, '-m', 'gallery_dl',
                '--no-colors', '-o', 'input=true',
                '--cookies-from-browser', browser,
                '--dump-json', url,
            ])
        # 无 Cookie 时兜底再试一次（部分公开推文不登录也能获取）
        attempted_cmds.append([
            sys.executable, '-m', 'gallery_dl',
            '--no-colors', '-o', 'input=true',
            '--dump-json', url,
        ])

        for cmd in attempted_cmds:
            try:
                proc = subprocess.run(
                    cmd, cwd=project_dir, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=timeout)
                if proc.returncode != 0:
                    continue
                stdout = proc.stdout
                if self._is_error_output(stdout):
                    continue
                return stdout
            except Exception:
                continue
        return ''

    @staticmethod
    def _is_error_output(stdout: str) -> bool:
        """检测 gallery-dl 输出是否为错误消息流（[负数, {error...}]）"""
        if not stdout:
            return True
        import json as _json
        for line in stdout.splitlines()[:3]:
            s = line.strip()
            if not s.startswith('['):
                continue
            try:
                obj = _json.loads(s)
            except Exception:
                continue
            if isinstance(obj, list) and obj and isinstance(obj[0], int) and obj[0] < 0:
                return True
        return False

    @staticmethod
    def _json_lines(stdout: str) -> list:
        """从 gallery-dl --dump-json 输出中解析尽量多的 JSON 值。

        兼容多种输出格式：
        1. JSONL：每行一个 JSON 对象（简单提取器）
        2. Pretty-printed 嵌套 JSON：顶层是数组（twitter 等复杂提取器），
           元素形如 [code, data] 或 [code, url, metadata]（gallery-dl 消息格式）
        使用 json.JSONDecoder.raw_decode 扫描并提取顶层所有 JSON 值（含 list）。
        """
        import json as _json
        results = []

        # 方式一：逐行 JSONL 快速解析
        jsonl_found = False
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('[') or line.startswith('{'):
                try:
                    obj = _json.loads(line)
                    jsonl_found = True
                    # 展开顶层 list（gallery-dl 消息流格式 [[code, ...], ...]）
                    if isinstance(obj, list):
                        results.extend(obj)
                    else:
                        results.append(obj)
                except Exception:
                    continue
        if jsonl_found:
            return results

        # 方式二：raw_decode 扫描整个文本（兼容 pretty-printed 多行 JSON）
        try:
            decoder = _json.JSONDecoder()
            idx = 0
            n = len(stdout)
            while idx < n:
                # 跳过空白/non-JSON 前缀
                while idx < n and stdout[idx] in ' \t\r\n':
                    idx += 1
                if idx >= n:
                    break
                try:
                    obj, end = decoder.raw_decode(stdout, idx)
                except Exception:
                    # 跳过无法解析的字符
                    idx += 1
                    continue
                # 同样展开顶层 list（gallery-dl 消息流格式 [[code, ...], ...]）
                if isinstance(obj, list):
                    results.extend(obj)
                else:
                    results.append(obj)
                idx = end
        except Exception:
            pass
        return results

    def parse(self, url: str) -> list:
        """解析推特链接（gallery-dl 备用方案），返回 MediaItem 列表

        gallery-dl --dump-json 对推特推文输出消息流格式：
            [
              [2, {目录元数据}],                     # Directory 消息
              [3, 'https://...', {文件元数据}],      # Url 消息（url 是字符串）
              ...
            ]
        同时兼容简单提取器的 JSONL 输出（每行 _type=url 的对象）。
        """
        stdout = self._run(url)
        if not stdout:
            return []
        data_list = self._json_lines(stdout)
        if not data_list:
            return []

        # ── 解析为统一的 (url, 元数据dict) 列表 ──
        url_posts = []          # (url, metadata) 列表
        metadata_posts = []     # 目录/元数据消息（提取标题、tweet_id 等）

        for msg in data_list:
            # 格式1：gallery-dl 消息 [code, ...]
            if isinstance(msg, list) and msg:
                code = msg[0]
                if code == 3 and len(msg) >= 2:
                    # Url 消息：[3, url_string, {metadata}]
                    u = msg[1]
                    md = msg[2] if len(msg) > 2 and isinstance(msg[2], dict) else {}
                    if isinstance(u, str):
                        url_posts.append((u, md))
                        continue
                if code == 2 and len(msg) >= 2 and isinstance(msg[1], dict):
                    # Directory 消息（收藏元数据）
                    metadata_posts.append(msg[1])
                    continue
                # 兼容 [code, url, ...] 但 code 非 2/3 的情况：跳过
                continue

            # 格式2：JSONL 对象 {"_type": "url", "url": ..., ...}
            if isinstance(msg, dict):
                if msg.get('_type') == 'url' and msg.get('url'):
                    url_posts.append((msg['url'], msg))
                else:
                    metadata_posts.append(msg)

        if not url_posts:
            return []

        # ── 从 Directory 元数据中提取 tweet 标题/作者信息 ──
        tweet_title = ''
        tweet_id = ''
        user_avatar = ''   # user 头像（视频媒体预览兜底）
        for md in metadata_posts:
            if not isinstance(md, dict):
                continue
            if md.get('_type') == 'directory':
                if not tweet_id:
                    tweet_id = str(md.get('tweet_id') or '')
                if not tweet_title:
                    tweet_title = str(md.get('content') or '')[:50] or \
                                  str(md.get('title') or '')
                user = md.get('user') or md.get('author')
                if isinstance(user, dict) and not user_avatar:
                    for k in ('profile_image_url', 'profile_banner_url'):
                        v = user.get(k)
                        if isinstance(v, str) and v.startswith('http'):
                            # 头像可能带 _normal 小图后缀，提升为大图
                            user_avatar = v.replace('_normal', '')
                            break

        # ── 预览图推导：gallery-dl 输出无缩略图字段 ──
        # 图片媒体直接复用媒体 URL（本身是 pbs.twimg.com 大图）；
        # 视频媒体复用同推文中的任意图片 URL（视频封面通常为推文首图），无图片则用 user 头像兜底。
        IS_IMG_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif')

        def _is_preview_image(u, post) -> bool:
            """判断 URL 是否为图片（含 query format 兜底）"""
            ext = str(post.get('extension') or '').lower()
            if ext and not ext.startswith('.'):
                ext = '.' + ext
            if ext in IS_IMG_EXT:
                return True
            parts = str(u).split('?', 1)
            if os.path.splitext(parts[0])[1].lower() in IS_IMG_EXT:
                return True
            if len(parts) > 1:
                m = re.search(r'[?&]format=([\w.]+)', parts[1])
                if m and ('.' + m.group(1).lower()) in IS_IMG_EXT:
                    return True
            return False

        video_preview_img = ''
        for file_url, post in url_posts:
            if _is_preview_image(file_url, post):
                video_preview_img = file_url
                break

        items = []
        ts = int(time.time())
        for idx, (file_url, post) in enumerate(url_posts):
            # 扩展名匹配：gallery-dl 的 extension 字段通常无点前缀（如 'jpg'），
            # URL 可能带查询参数（如 ?format=jpg），需从 query 中兜底提取。
            ext = str(post.get('extension') or '').lower()
            if ext and not ext.startswith('.'):
                ext = '.' + ext
            if ext not in self.EXT2TYPE:
                # 从 URL 路径兜底（去掉 query 参数）
                path_ext = os.path.splitext(file_url.split('?')[0])[1].lower()
                if path_ext in self.EXT2TYPE:
                    ext = path_ext
                else:
                    # 从查询参数兜底（如 ...?format=jpg&name=orig）
                    q = file_url.split('?', 1)
                    if len(q) > 1:
                        m = re.search(r'[?&]format=([\w.]+)', q[1])
                        if m:
                            fmtext = '.' + m.group(1).lower()
                            if fmtext in self.EXT2TYPE:
                                ext = fmtext
            media_type = self.EXT2TYPE.get(
                ext, 'image' if post.get('type') == 'image' else 'video')
            # 标题：文件名 > 推文元数据
            title = post.get('filename') or ''
            if not title and tweet_title:
                title = tweet_title
            if not title:
                title = f'twitter_{ts}'
            title = sanitize_filename(title)
            # 预览图：优先取文件元数据字段；gallery-dl 无缩略图时推导：
            # 图片 → 复用媒体 URL；视频 → 同推文首图或 user 头像
            preview = ''
            for k in ('thumbnail', 'preview', 'preview_url'):
                v = post.get(k)
                if isinstance(v, str) and v.startswith('http'):
                    preview = v
                    break
            if not preview:
                if media_type == 'image':
                    preview = file_url
                else:
                    preview = video_preview_img or user_avatar
            # 推特媒体（pbs.twimg.com / video.twimg.com）下载需携带 Referer 防防盗链
            referer = 'https://x.com/'
            items.append(MediaItem(
                title=title,
                url=file_url,
                preview_url=preview,
                media_type=media_type,
                quality='',
                referer=referer
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