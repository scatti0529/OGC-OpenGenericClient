# -*- coding: utf-8 -*-
"""Pixiv 下载服务核心模块

整合 pixivd-3.3 与 OGC多功能版 pixiv 下载器功能：
- OAuth 登录 / refresh token 管理（存入数据库）
- 按画师ID / 作品ID / 标签 / 排行榜 / 收藏 / 历史排行榜 下载
- 文件夹结构：pixiv-download 下按类型/画师分类
"""
import datetime
import hashlib
import math
import os
import queue
import re
import threading
import time
import traceback
from base64 import urlsafe_b64encode
from hashlib import sha256
from secrets import token_urlsafe
from urllib.parse import urlencode

import requests
from pixivpy3 import AppPixivAPI

from core.config import config as CFG
from core.database import (
    save_pixiv_refresh_token, get_pixiv_refresh_token,
)
from services.download_manager import (
    get_download_root, PLATFORM_FOLDERS,
)

# ═══════════════════════════════════════════════════════════
#  Pixiv App API 常量（与 pixivd-3.3 / PixivUtil2 一致）
# ═══════════════════════════════════════════════════════════
_APP_USER_AGENT = "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"
_OAUTH_HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
CLIENT_ID = 'MOBrBDS8blbauoSck0ZfDbtuzpyT'
CLIENT_SECRET = 'lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj'
AUTH_TOKEN_URL = 'https://oauth.secure.pixiv.net/auth/token'
LOGIN_URL = 'https://app-api.pixiv.net/web/v1/login'
REDIRECT_URI = 'https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback'

_THREADING_NUMBER = 10
_MAX_ERROR_COUNT = 5
_ILLUST_PER_PAGE = 30


class LoginRequiredError(Exception):
    """尚未登录 Pixiv 时抛出"""


class PixivDownloader:
    """Pixiv 下载器主类

    Args:
        log_callback: 可调用对象, 接收 (str) 日志消息
        progress_callback: 可调用对象, 接收 (current:int, total:int, speed:str) 下载进度
    """

    def __init__(self, log_callback=None, progress_callback=None):
        self.log_callback = log_callback
        self.progress_callback = progress_callback

        self._finished_download = 0
        self._global_download = 0
        self._error_count = {}
        self._create_folder_lock = threading.Lock()
        self._progress_lock = threading.Lock()
        self._speed_lock = threading.Lock()

        self._api = None
        self._code_verifier = None
        # pixivpy3 全局实例
        self._aapi = AppPixivAPI()

    # ---------------------------------------------------------------- 工具方法
    def _log(self, msg):
        if self.log_callback:
            try:
                self.log_callback(str(msg))
            except Exception:
                traceback.print_exc()

    def _emit_progress(self, current, total, speed=''):
        if self.progress_callback:
            try:
                self.progress_callback(current, total, speed)
            except Exception:
                traceback.print_exc()

    # ---------------------------------------------------------------- OAuth
    @staticmethod
    def _oauth_headers():
        """生成带签名的 OAuth 请求头（与 pixivd-3.3 一致）

        Pixiv OAuth 接口要求 App-OS / X-Client-Time / X-Client-Hash 等字段，
        缺少签名会导致 invalid_request 错误。
        """
        tzinfo = datetime.datetime.now(datetime.timezone.utc).astimezone().strftime('%z')
        tz = '%s:%s' % (tzinfo[:3], tzinfo[3:5])
        time_str = '%s%s' % (datetime.datetime.now().isoformat()[0:19], tz)
        time_hash = hashlib.md5(
            ('%s%s' % (time_str, _OAUTH_HASH_SECRET)).encode('utf-8'))
        return {
            'User-Agent': _APP_USER_AGENT,
            'Accept-Language': 'en_US',
            'App-OS': 'android',
            'App-OS-Version': '4.4.2',
            'App-Version': '5.0.145',
            'X-Client-Time': time_str,
            'X-Client-Hash': time_hash.hexdigest(),
        }

    def _oauth_post(self, data):
        """POST 到 Pixiv OAuth token 接口（带签名头）"""
        r = requests.post(AUTH_TOKEN_URL, data=data,
                          headers=self._oauth_headers(),
                          timeout=20)
        try:
            resp = r.json()
        except Exception:
            raise RuntimeError('登录响应解析失败: %s' % r.text[:200])
        if 'error' in resp:
            raise RuntimeError('登录失败: %s' % (resp.get('error_description')
                                              or resp.get('error') or '未知错误'))
        return resp

    def _oauth_refresh(self, refresh_token):
        """使用 refresh token 刷新 access token"""
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'include_policy': 'true',
            'refresh_token': refresh_token,
        }
        resp = self._oauth_post(data)
        return resp['access_token'], resp['refresh_token']

    @staticmethod
    def _s256(data):
        """S256 transformation method."""
        return urlsafe_b64encode(sha256(data).digest()).rstrip(b'=').decode('ascii')

    @staticmethod
    def _oauth_pkce(transform):
        """Proof Key for Code Exchange by OAuth Public Clients (RFC7636)."""
        code_verifier = token_urlsafe(32)
        code_challenge = transform(code_verifier.encode('ascii'))
        return code_verifier, code_challenge

    # ---------------------------------------------------------------- 登录
    @property
    def api(self):
        """懒加载并返回已登录的 Pixiv API 实例

        未登录或 token 失效时抛出 LoginRequiredError
        """
        if self._api is None:
            refresh_token = get_pixiv_refresh_token()
            if not refresh_token:
                raise LoginRequiredError('尚未登录，请先获取 Refresh Token')
            try:
                access_token, new_refresh = self._oauth_refresh(refresh_token)
            except Exception as e:
                self._log('刷新登录 token 失败: %s' % e)
                raise LoginRequiredError('登录已过期，请重新获取 Refresh Token')
            # 更新数据库中的 token（token 轮换）
            save_pixiv_refresh_token(new_refresh, access_token)
            self._aapi.access_token = access_token
            self._aapi.refresh_token = new_refresh
            self._api = self._aapi
        if not self._api.access_token:
            raise LoginRequiredError('尚未登录，请先获取 Refresh Token')
        return self._api

    def get_login_url(self):
        """生成登录地址，返回 (url, 操作提示文字)"""
        code_verifier, code_challenge = self._oauth_pkce(self._s256)
        self._code_verifier = code_verifier
        login_params = {
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'client': 'pixiv-android',
        }
        url = '%s?%s' % (LOGIN_URL, urlencode(login_params))
        hint = ('1. 使用浏览器打开上面的登录地址，并按网页提示登录 Pixiv\n'
                '2. 登录成功后页面会自动跳转，最终浏览器地址栏会变成类似：\n'
                '   .../callback?state=xxx&code=XXXXXXXXXXXXXXXXXXXX\n'
                '3. 复制整个跳转后的地址（或其中 code= 后面那一长串），粘贴到下方输入框\n'
                '4. 点击「完成登录」')
        return url, hint

    @staticmethod
    def extract_code(text):
        """从粘贴内容中提取授权 code

        支持直接粘贴 code 值，或粘贴完整的回调地址（自动提取 code 参数）
        """
        text = (text or '').strip()
        if not text:
            return ''
        if text.startswith(('http://', 'https://')):
            match = re.search(r'(?:[?&#])code=([^&#]+)', text)
            if match:
                return match.group(1)
            raise ValueError('未在地址中找到 code 参数，请确认复制的是登录后跳转的完整地址')
        return text.split()[0] if text else ''

    def login_with_code(self, code):
        """使用授权 code 完成登录，并将 refresh token 存入数据库"""
        code = self.extract_code(code)
        if not code:
            raise ValueError('请输入授权 code，或粘贴登录后跳转的完整地址')
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'code': code,
            'code_verifier': self._code_verifier or '',
            'grant_type': 'authorization_code',
            'include_policy': 'true',
            'redirect_uri': REDIRECT_URI,
        }
        resp = self._oauth_post(data)
        access_token, refresh_token = resp['access_token'], resp['refresh_token']
        self._aapi.access_token = access_token
        self._aapi.refresh_token = refresh_token
        self._api = self._aapi
        save_pixiv_refresh_token(refresh_token, access_token)
        self._log('登录成功，refresh token 已保存到数据库')

    def login_with_refresh_token(self, refresh_token):
        """使用 refresh token 直接登录，并存入数据库"""
        refresh_token = (refresh_token or '').strip()
        if not refresh_token:
            raise ValueError('请输入 refresh token')
        access_token, new_refresh = self._oauth_refresh(refresh_token)
        self._aapi.access_token = access_token
        self._aapi.refresh_token = new_refresh
        self._api = self._aapi
        save_pixiv_refresh_token(new_refresh, access_token)
        self._log('refresh token 登录成功，已保存到数据库')

    # ---------------------------------------------------------------- 文件下载工具
    def get_pixiv_save_path(self):
        """获取 pixiv-download 根目录（所有 pixiv 数据都存放在此）"""
        root = get_download_root()
        folder = PLATFORM_FOLDERS.get('pixiv', 'pixiv-download')
        return os.path.join(root, folder)

    @staticmethod
    def _is_manga(illustrate):
        return True if illustrate.is_manga or illustrate.type == 'manga' else False

    @staticmethod
    def _count_illustrations(illustrations):
        return sum(len(i.image_urls) for i in illustrations)

    def _get_speed(self, elapsed):
        """计算当前下载速度"""
        with self._speed_lock:
            down = self._global_download
            self._global_download = 0
        if elapsed <= 0:
            elapsed = 0.001
        speed = down / elapsed
        if speed == 0:
            return '0 B/s'
        units = [' B', 'KB', 'MB', 'GB', 'TB', 'PB']
        unit = min(math.floor(math.log(speed, 1024.0)), len(units) - 1)
        speed /= math.pow(1024.0, unit)
        return '%.2f %s/s' % (speed, units[unit])

    def _download_file(self, url, filepath):
        headers = {'Referer': 'https://www.pixiv.net/', 'User-Agent': 'PixivIOSApp/6.4.0'}
        r = requests.get(url, headers=headers, stream=True, timeout=20)
        if r.status_code == requests.codes.ok:
            total_length = r.headers.get('content-length')
            if total_length:
                data = []
                for chunk in r.iter_content(1024 * 16):
                    data.append(chunk)
                    with self._speed_lock:
                        self._global_download += len(chunk)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, 'wb') as f:
                    list(map(f.write, data))
        else:
            raise ConnectionError('Connection error: %s' % r.status_code)

    def _download_worker(self, download_queue):
        while not download_queue.empty():
            illustration = download_queue.get()
            filepath = illustration['path']
            filename = illustration['file']
            url = illustration['url']
            count = self._error_count.get(url, 0)
            if count < _MAX_ERROR_COUNT:
                if not os.path.exists(filepath):
                    with self._create_folder_lock:
                        if not os.path.exists(os.path.dirname(filepath)):
                            os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    try:
                        self._download_file(url, filepath)
                        with self._progress_lock:
                            self._finished_download += 1
                    except Exception as e:
                        if count < _MAX_ERROR_COUNT:
                            self._log('%s => %s download error, retry' % (e, filename))
                            download_queue.put(illustration)
                            self._error_count[url] = count + 1
            else:
                self._log('%s reach max retries, canceled' % url)
                with self._progress_lock:
                    self._finished_download += 1
            download_queue.task_done()

    def _track_progress(self, max_size):
        """进度跟踪线程：通过回调上报 (current, total, speed)"""
        last_time = time.time()
        while self._finished_download != max_size:
            current = self._finished_download
            elapsed = time.time() - last_time
            speed = self._get_speed(elapsed)
            last_time = time.time()
            self._emit_progress(current, max_size, speed)
            time.sleep(0.5)
        self._emit_progress(self._finished_download, max_size, self._get_speed(1))

    def _start_and_wait(self, download_queue, count):
        """启动下载线程并等待全部完成"""
        progress_t = threading.Thread(target=self._track_progress, args=(count,))
        progress_t.daemon = True
        progress_t.start()
        for _ in range(_THREADING_NUMBER):
            download_t = threading.Thread(target=self._download_worker, args=(download_queue,))
            download_t.daemon = True
            download_t.start()
        progress_t.join()
        download_queue.join()

    def _get_filepath(self, url, illustration, save_path='.', add_user_folder=False,
                      add_rank=False):
        """return (filename, filepath)"""
        if add_user_folder:
            user_id = illustration.user_id
            user_name = illustration.user_name
            dir_name = re.sub(r'[<>:"/\\|\?\*]', ' ', user_id + ' ' + user_name)
            save_path = os.path.join(save_path, dir_name)

        # 多图帖子：在作者/标签文件夹下再创建独立帖子文件夹（按作品ID命名）
        image_urls = getattr(illustration, 'image_urls', []) or []
        if len(image_urls) > 1:
            illust_id = getattr(illustration, 'id', None)
            if illust_id:
                save_path = os.path.join(save_path, str(illust_id))

        filename = url.split('/')[-1]
        if add_rank:
            filename = '%d - %s' % (illustration.rank, filename)
        filepath = os.path.join(save_path, filename)
        return filename, filepath

    def _check_files(self, illustrations, save_path='.', add_user_folder=False,
                     add_rank=False):
        """检查文件是否已存在，构建下载队列"""
        download_queue = queue.Queue()
        index_list = []
        count = 0
        update_existing = True
        try:
            update_existing = bool(CFG.get('pixiv_update_existing', True))
        except Exception:
            pass
        if illustrations:
            last_i = -1
            for index, illustration in enumerate(illustrations):
                if not illustration.image_urls:
                    continue
                for url in illustration.image_urls:
                    filename, filepath = self._get_filepath(
                        url, illustration, save_path, add_user_folder, add_rank)
                    if os.path.exists(filepath) and update_existing:
                        continue
                    if last_i != index:
                        last_i = index
                        index_list.append(index)
                    download_queue.put({'url': url, 'file': filename, 'path': filepath})
                    count += 1
        return download_queue, count, index_list

    # ---------------------------------------------------------------- 下载功能
    def download_illustrations(self, api, data_list, save_path='.', add_user_folder=False,
                               add_rank=False, skip_manga=False, max_images=0):
        """下载插图列表"""
        illustrations = PixivIllustModel.from_data(data_list)
        if skip_manga:
            manga_number = sum(self._is_manga(i) for i in illustrations)
            if manga_number:
                self._log('skip %d manga' % manga_number)
                illustrations = [i for i in illustrations if not self._is_manga(i)]
        # 最大抓取图片数限制
        if max_images and max_images > 0:
            total = self._count_illustrations(illustrations)
            if total > max_images:
                self._log('达到最大图片数限制 %d，共 %d 张' % (max_images, total))
                # 截断到最大图片数
                new_list = []
                count = 0
                for ill in illustrations:
                    if count >= max_images:
                        break
                    new_list.append(ill)
                    count += len(ill.image_urls)
                illustrations = new_list
        download_queue, count = self._check_files(illustrations, save_path, add_user_folder, add_rank)[0:2]
        if count > 0:
            self._log('Start download, total illustrations %d' % count)
            self._finished_download = 0
            self._global_download = 0
            self._error_count = {}
            self._start_and_wait(download_queue, count)
            self._log('下载完成，共 %d 张' % count)
        else:
            self._log('There is no new illustration need to download')

    def _get_config(self, key, default):
        """读取 pixiv 配置"""
        try:
            return CFG.get(key, default)
        except Exception:
            return default

    def download_by_user_id(self, user_ids):
        """按画师 ID 下载

        Args:
            user_ids: str, 画师 ID，多个用空格/逗号分隔
        """
        api = self.api
        save_path = self.get_pixiv_save_path()
        user_ids = re.split(r'[\s,，]+', (user_ids or '').strip())
        user_ids = [u for u in user_ids if u]
        if not user_ids:
            raise ValueError('请输入画师ID')
        max_posts = int(self._get_config('pixiv_max_posts', 0) or 0)
        skip_manga = bool(self._get_config('pixiv_skip_manga', False))
        max_images = int(self._get_config('pixiv_max_images', 0) or 0)
        for user_id in user_ids:
            self._log('Artists %s' % user_id)
            try:
                data_list = get_all_user_illustrations(self, user_id)
            except Exception as e:
                self._log('获取画师 %s 作品失败: %s' % (user_id, e))
                continue
            if max_posts and max_posts > 0:
                data_list = data_list[:max_posts]
            self.download_illustrations(api, data_list, save_path,
                                        add_user_folder=True,
                                        skip_manga=skip_manga,
                                        max_images=max_images)

    def download_by_illust_id(self, illust_ids):
        """按作品 ID 下载

        Args:
            illust_ids: str, 作品 ID，多个用空格/逗号分隔
        """
        api = self.api
        save_path = self.get_pixiv_save_path()
        illust_ids = re.split(r'[\s,，]+', (illust_ids or '').strip())
        illust_ids = [i for i in illust_ids if i]
        if not illust_ids:
            raise ValueError('请输入作品ID')
        skip_manga = bool(self._get_config('pixiv_skip_manga', False))
        max_images = int(self._get_config('pixiv_max_images', 0) or 0)
        data_list = []
        for illust_id in illust_ids:
            self._log('Work %s' % illust_id)
            try:
                detail = self._aapi.illust_detail(illust_id)
                illust = detail.get('illust')
                if illust:
                    data_list.append(illust)
                else:
                    self._log('作品 %s 不存在或不可见' % illust_id)
            except Exception as e:
                self._log('获取作品 %s 失败: %s' % (illust_id, e))
                continue
        if data_list:
            self.download_illustrations(api, data_list, save_path,
                                        add_user_folder=True,
                                        skip_manga=skip_manga,
                                        max_images=max_images)
        else:
            self._log('没有获取到任何作品')

    def download_by_tag(self, tag, page=3):
        """按标签搜索下载（pixivpy3 search_illust）

        Args:
            tag: str, 搜索标签
            page: int, 抓取页数（每页约 30 张）
        """
        api = self.api
        tag = (tag or '').strip()
        if not tag:
            raise ValueError('请输入要搜索的标签')
        page = max(1, min(int(page), 20))
        save_path = os.path.join(self.get_pixiv_save_path(), 'tag ' + tag)
        skip_manga = bool(self._get_config('pixiv_skip_manga', False))
        max_images = int(self._get_config('pixiv_max_images', 0) or 0)
        data_list = []
        offset = 0
        for _ in range(page):
            try:
                result = self._aapi.search_illust(tag, offset=offset)
                illusts = result.get('illusts') or []
            except Exception as e:
                self._log('搜索标签 %s 失败: %s' % (tag, e))
                break
            if not illusts:
                break
            data_list.extend(illusts)
            if not result.get('next_url'):
                break
            offset += 30
        self._log('搜索到 %d 个作品' % len(data_list))
        self.download_illustrations(api, data_list, save_path,
                                    skip_manga=skip_manga,
                                    max_images=max_images)

    def download_by_bookmarks(self, user_id='', page=3):
        """下载用户收藏（pixivpy3 user_bookmarks_illust，留空表示查询自己）

        Args:
            user_id: str, 用户 ID，留空查询自己的收藏
            page: int, 抓取页数（每页约 30 张）
        """
        api = self.api
        user_id = (user_id or '').strip()
        page = max(1, min(int(page), 50))
        save_path = os.path.join(self.get_pixiv_save_path(), 'bookmarks')
        skip_manga = bool(self._get_config('pixiv_skip_manga', False))
        max_images = int(self._get_config('pixiv_max_images', 0) or 0)
        data_list = []
        offset = 0
        for _ in range(page):
            try:
                result = self._aapi.user_bookmarks_illust(user_id or None, offset=offset)
                illusts = result.get('illusts') or []
            except Exception as e:
                self._log('获取收藏失败: %s' % e)
                break
            if not illusts:
                break
            data_list.extend(illusts)
            if not result.get('next_url'):
                break
            offset += 30
        self._log('获取到 %d 个收藏作品' % len(data_list))
        self.download_illustrations(api, data_list, save_path,
                                    add_user_folder=True,
                                    skip_manga=skip_manga,
                                    max_images=max_images)

    def download_by_ranking(self, pages=3):
        """下载今日排行榜"""
        api = self.api
        today = str(datetime.date.today())
        save_path = os.path.join(self.get_pixiv_save_path(), today + ' ranking')
        skip_manga = bool(self._get_config('pixiv_skip_manga', False))
        max_images = int(self._get_config('pixiv_max_images', 0) or 0)
        data_list = get_ranking_illustrations(self, total_page=pages)
        self.download_illustrations(api, data_list, save_path,
                                    add_rank=True,
                                    skip_manga=skip_manga,
                                    max_images=max_images)

    def download_by_history_ranking(self, date='', total_page=3):
        """下载历史排行榜

        Args:
            date: str, 日期, 格式 YYYY-MM-DD
            total_page: int, 请求页数
        """
        api = self.api
        date = (date or '').strip()
        if not re.search(r'^\d{4}-\d{2}-\d{2}$', date):
            raise ValueError('日期格式应为 YYYY-MM-DD，例如 2016-09-24')
        save_path = os.path.join(self.get_pixiv_save_path(), date + ' ranking')
        skip_manga = bool(self._get_config('pixiv_skip_manga', False))
        max_images = int(self._get_config('pixiv_max_images', 0) or 0)
        data_list = get_ranking_illustrations(self, date=date, total_page=total_page)
        self.download_illustrations(api, data_list, save_path,
                                    add_rank=True,
                                    skip_manga=skip_manga,
                                    max_images=max_images)

    # ---------------------------------------------------------------- 更新 & 清理
    def update_exist(self, fast=True):
        """扫描并更新已存在的画师文件夹"""
        api = self.api
        current_path = self.get_pixiv_save_path()
        if not os.path.isdir(current_path):
            self._log('不存在 pixiv-download 文件夹或没有已下载内容')
            return
        final_list = []
        user_id_list = queue.Queue()
        for folder in os.listdir(current_path):
            if os.path.isdir(os.path.join(current_path, folder)):
                user_id = re.search(r'^(\d+) ', folder)
                if user_id:
                    user_id_list.put({'id': user_id.group(1), 'folder': folder})
        if user_id_list.empty():
            self._log('没有找到已存在的画师文件夹')
            return

        while not user_id_list.empty():
            user_info = user_id_list.get()
            user_id = user_info['id']
            folder = user_info['folder']
            try:
                if fast:
                    data_list = []
                    offset = 0
                    page_result = self._get_all_user_illustrations_page(api, user_id, offset)
                    if len(page_result) > 0:
                        data_list.extend(page_result)
                        file_path = os.path.join(current_path, folder,
                                                 self._get_last_image_name(page_result))
                        while not os.path.exists(file_path) and len(page_result) == _ILLUST_PER_PAGE:
                            offset += _ILLUST_PER_PAGE
                            page_result = self._get_all_user_illustrations_page(api, user_id, offset)
                            data_list.extend(page_result)
                            file_path = os.path.join(current_path, folder,
                                                     self._get_last_image_name(page_result))
                            time.sleep(1)
                else:
                    data_list = get_all_user_illustrations(self, user_id)
                if data_list:
                    try:
                        self._log('Artists %s [%s]' % (folder, len(data_list)))
                    except UnicodeError:
                        self._log('Artists %s ?? [%s]' % (user_id, len(data_list)))
                    final_list.extend(data_list)
            except Exception:
                traceback.print_exc()
            user_id_list.task_done()

        if final_list:
            skip_manga = bool(self._get_config('pixiv_skip_manga', False))
            self.download_illustrations(api, final_list, current_path,
                                        add_user_folder=True,
                                        skip_manga=skip_manga)

    def _get_all_user_illustrations_page(self, api, user_id, offset):
        """获取画师的单页作品"""
        try:
            data = self._aapi.user_illusts(user_id, offset=offset)
            return data.get('illusts') or []
        except Exception:
            return []

    @staticmethod
    def _get_last_image_name(data_list):
        """获取最后一幅作品的文件名"""
        try:
            last = data_list[-1]
            urls = last.get('image_urls', {}) or last.get('meta_single_page', {})
            if last.get('meta_single_page'):
                return last['meta_single_page'].get('original_image_url', '').split('/')[-1]
            return urls.get('large', '').split('/')[-1]
        except Exception:
            return ''

    def remove_repeat(self):
        """删除 xxxxx.img（若 xxxxx_p0.img 存在）"""
        illust_path = self.get_pixiv_save_path()
        deleted = 0
        for folder in os.listdir(illust_path):
            if os.path.isdir(os.path.join(illust_path, folder)):
                if re.search(r'^(\d+) ', folder):
                    path = os.path.join(illust_path, folder)
                    for file_name in os.listdir(path):
                        illustration_id = re.search(r'^\d+\.', file_name)
                        if illustration_id:
                            dot_file = illustration_id.string.replace('.', '_p0.')
                            if os.path.isfile(os.path.join(path, dot_file)):
                                os.remove(os.path.join(path, file_name))
                                self._log('Delete %s' % os.path.join(path, file_name))
                                deleted += 1
        if deleted == 0:
            self._log('没有找到需要删除的重复图片')
        else:
            self._log('已删除 %d 个重复图片' % deleted)


class PixivIllustModel:
    """Pixiv 插画数据模型（与 pixivd-3.3 model.py 一致）"""

    @classmethod
    def create_illust_from_data(cls, data):
        illust = cls()
        for k, v in data.items():
            setattr(illust, k, v)
        illust.user_id = str(illust.user['id'])
        illust.user_name = illust.user['name']
        if data['meta_single_page']:
            illust.image_urls = [data['meta_single_page']['original_image_url']]
            if data['type'] == 'ugoira':
                illust.image_urls = [
                    illust.image_urls[0].replace('img-original', 'img-zip-ugoira')
                        .replace('ugoira0.jpg', 'ugoira600x600.zip')
                        .replace('ugoira0.png', 'ugoira600x600.zip')]
        elif data['meta_pages']:
            illust.image_urls = [i['image_urls']['original'] for i in data['meta_pages']]
        return illust

    @classmethod
    def from_data(cls, data_list):
        """parse data to dict contains illust information"""
        illusts = []
        for data in list(data_list):
            illust = cls.create_illust_from_data(data)
            illusts.append(illust)
        return illusts


def get_all_user_illustrations(downloader, user_id, offset=0, size=-1):
    """获取画师全部作品（兼容 pixivd-3.3 api.get_all_user_illustrations）"""
    r = []
    done = False
    cur_size = 0
    while not done:
        data = downloader._aapi.user_illusts(user_id, offset=offset)
        try:
            r.extend(data['illusts'])
        except Exception:
            pass
        offset += 30
        cur_size += 30
        if not data.get('next_url') or (0 <= size <= cur_size):
            done = True
    return r[:size] if size >= 0 else r


def get_ranking_illustrations(downloader, mode='day', date=None, total_page=3):
    """获取排行榜数据（兼容 pixivd-3.3 api.get_ranking_illustrations）

    Args:
        downloader: PixivDownloader 实例
        mode: str, 排行榜模式（day/week/month/day_male/day_female 等）
        date: str or None, 历史排行榜日期 YYYY-MM-DD；None 表示最新排行榜
        total_page: int, 抓取页数
    """
    r = []
    page = 0
    offset = 0
    while page <= total_page:
        data = downloader._aapi.illust_ranking(
            mode, date=(date or None), offset=offset)
        r.extend(data.get('illusts', []))
        offset += 30
        page += 1
        if not data.get('next_url'):
            break
    for index, i in enumerate(r):
        i['rank'] = index + 1
    return r

