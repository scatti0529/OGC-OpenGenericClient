# -*- coding: utf-8 -*-
"""拷贝漫画应用上下文：聚合所有服务，提供页面加载编排（移植自 OGC-EasyCopy）。"""
from __future__ import annotations

import os
import re
import threading
from typing import Callable, Optional
from urllib.parse import urlparse

import requests
from PyQt5.QtCore import QObject, pyqtSignal

from .api import SiteApiClient, SiteApiException
from .config import APP_NAME, DESKTOP_USER_AGENT, PROFILE_PATH
from .image_service import ImageCache, ImageFetcher
from .models import (
    DetailPageData,
    DiscoverPageData,
    HomePageData,
    ProfilePageData,
    RankPageData,
    ReaderPageData,
    SitePageType,
)
from .net import AppSettings, HostManager, HttpClient, Session
from .parser import ParseException, SiteHtmlParser


def default_data_dir() -> str:
    """用户数据目录：优先使用 OGC 的 data/easycopy 文件夹。"""
    try:
        from core.config import config as CFG
        path = os.path.join(CFG.data, 'easycopy')
    except Exception:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "EasyCopy")
    os.makedirs(path, exist_ok=True)
    return path


class _PageLoadBridge(QObject):
    """把网页加载结果与进度安全地投递到主线程。"""

    finished = pyqtSignal(object, object)
    progress = pyqtSignal(str)


class AppContext:
    """全局服务容器。"""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or default_data_dir()
        self.settings = AppSettings(os.path.join(self.data_dir, "settings.json"))
        self.settings.load()

        self.session = Session(self.settings)
        self.session.load()

        self.hosts = HostManager(self.settings, self.session)
        self.http = HttpClient(self.hosts, self.session, self.settings)
        self.api = SiteApiClient(self.http, self.session)
        self.parser = SiteHtmlParser(resolve_href=self._resolve_href)

        self.image_cache = ImageCache(os.path.join(self.data_dir, "images"))
        self.image_fetcher = ImageFetcher(self.image_cache)

        self._page_cache: dict[str, object] = {}
        self._lock = threading.RLock()

    def _resolve_href(self, href: str, current: str) -> str:
        return self.hosts.resolve_href(href, current)

    @property
    def base_url(self) -> str:
        return self.hosts.base_url

    # ---------- 页面加载 ----------
    def load_page(self, uri: str, callback=None, on_progress=None) -> None:
        """在线程中加载并解析页面，回调通过 Qt 信号安全投递到主线程。"""
        bridge = _PageLoadBridge()
        if callback:
            bridge.finished.connect(callback)
        if on_progress:
            bridge.progress.connect(on_progress)

        def report(msg: str):
            bridge.progress.emit(msg)

        def runner():
            try:
                page = self._load_page_sync(uri, report)
                bridge.finished.emit(page, None)
            except Exception as e:
                bridge.finished.emit(None, e)

        threading.Thread(target=runner, daemon=True).start()

    def load_page_sync(self, uri: str, on_progress=None):
        """同步加载页面（供后台下载线程等复用）。"""
        return self._load_page_sync(uri, on_progress)

    def _load_page_sync(self, uri: str, on_progress=None):
        uri = self.hosts.resolve_href(uri, self.base_url)
        cache_key = uri
        with self._lock:
            if cache_key in self._page_cache:
                if on_progress:
                    on_progress("已从缓存加载")
                return self._page_cache[cache_key]

        # 个人中心走 API（登录态）
        path = self._path_of(uri)
        if path.startswith("/person") or path.startswith("/web/login"):
            page = self.api.load_profile()
            page.uri = uri
            return page

        if on_progress:
            on_progress("正在请求页面…")
        resp, final_uri = self._get_html_with_failover(uri, on_progress)
        if on_progress:
            on_progress("正在解析页面内容…")
        html = resp.content.decode("utf-8", errors="replace")
        page = self.parser.parse(final_uri, html)

        # 详情页：章节为 JS 动态加载，需额外请求并解密章节接口
        if isinstance(page, DetailPageData):
            self._attach_detail_chapters(page, html, final_uri, on_progress)

        with self._lock:
            self._page_cache[cache_key] = page
            # 限制缓存大小
            if len(self._page_cache) > 32:
                for key in list(self._page_cache.keys()):
                    self._page_cache.pop(key)
                    if len(self._page_cache) <= 32:
                        break
        return page

    def _get_html_with_failover(self, uri: str, on_progress=None):
        """加载 HTML，连接超时或 HTTP 错误时自动切换备用域名重试。"""
        last_error: Optional[Exception] = None

        def report(msg: str):
            if on_progress:
                on_progress(msg)

        def fetch(url: str, timeout: float = 8.0):
            host = self.hosts.current_host
            report(f"正在连接 {host} …")
            resp = self.http.get_html(url, timeout=timeout)
            if resp.status_code != 200:
                raise ParseException(f"HTTP {resp.status_code}")
            return resp, url

        current = self.hosts.current_host
        try:
            return fetch(uri)
        except Exception as e:
            last_error = e

        report("连接失败，正在探测可用域名…")
        probes = self.hosts.probe_all(timeout=3.0)
        for p in probes:
            host = p.host
            if not p.success or host == current:
                continue
            report(f"已切换到备用域名 {host} …")
            try:
                self.hosts.set_current_host(host)
            except ValueError:
                continue
            try_url = self.hosts.rewrite_to_current_host(uri)
            try:
                return fetch(try_url, timeout=5.0)
            except Exception as e:
                last_error = e

        raise last_error if last_error else ParseException("页面加载失败")

    def _attach_detail_chapters(self, page: DetailPageData, html: str, page_uri: str, on_progress=None):
        """详情页章节为 JS 动态加载，请求章节接口并用 ccz 解密后填充。"""
        if page.chapters:
            return

        slug = ""
        parts = urlparse(page_uri).path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "comic":
            slug = parts[1]
        if not slug:
            return

        # 提取 ccz 与 dnt
        ccz = ""
        m = re.search(r"var\s+ccz\s*=\s*['\"]([^'\"]+)['\"]", html)
        if m:
            ccz = m.group(1).strip()
        dnt = ""
        m = re.search(r'id=["\']dnt["\'][^>]*value=["\']([^"\']*)["\']', html)
        if m:
            dnt = m.group(1).strip()
        if not ccz or not dnt:
            return

        try:
            if on_progress:
                on_progress("正在加载章节列表…")
            results = self._fetch_detail_chapter_results(slug, page_uri, dnt)
            chapters = SiteHtmlParser.decrypt_detail_chapters(slug, ccz, results)
            if chapters:
                page.chapters = chapters
        except Exception:
            # 章节加载失败不阻断详情页展示，保持空章节
            return

    def _fetch_detail_chapter_results(self, slug: str, page_uri: str, dnt: str) -> str:
        """请求详情页章节接口，返回加密的 results 字符串。"""
        session = requests.Session()
        session.trust_env = self.http.use_proxy()
        url = self.hosts.resolve_url(f"/comicdetail/{slug}/chapters")
        headers = {
            "User-Agent": DESKTOP_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": page_uri,
            "dnts": dnt,
        }
        resp = session.get(url, headers=headers, timeout=10, allow_redirects=True)
        payload = resp.json()
        code = int(payload.get("code", resp.status_code))
        results = (payload.get("results") or "").strip()
        if code != 200 or not results:
            raise ParseException(payload.get("message") or f"章节接口请求失败：{code}")
        return results

    def load_search(self, query: str, page: int = 1, callback=None) -> Optional[DiscoverPageData]:
        """搜索（阻塞，供调用方在线程中执行）。"""
        return self.api.search(query, page)

    @staticmethod
    def _path_of(uri: str) -> str:
        parts = urlparse(uri)
        return parts.path or "/"

    # ---------- 便捷 ----------
    def home_uri(self) -> str:
        return self.base_url

    def discover_uri(self) -> str:
        return self.hosts.resolve_url("/comics")

    def rank_uri(self) -> str:
        return self.hosts.resolve_url("/rank")

    def profile_uri(self) -> str:
        return self.hosts.resolve_url(PROFILE_PATH)
