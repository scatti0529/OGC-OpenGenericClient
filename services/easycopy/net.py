# -*- coding: utf-8 -*-
"""拷贝漫画网络会话层：域名探测、登录会话、HTTP 客户端（移植自 OGC-EasyCopy）。"""
from __future__ import annotations

import socket
import threading
import time
from typing import Dict, List, Optional

import requests

from .config import (
    DEFAULT_HOSTS,
    DESKTOP_USER_AGENT,
    HostProbe,
    is_valid_host_name,
    normalize_host,
    normalize_host_input,
)


class AppSettings:
    """持久化设置（JSON）。"""

    def __init__(self, path: str):
        self.path = path
        self.data: Dict = {}

    def load(self) -> None:
        import json
        import os

        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def save(self) -> None:
        import json
        import os

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value


class Session:
    """登录会话：保存 token 与 cookies。"""

    def __init__(self, settings: AppSettings):
        self._settings = settings
        self.token: str = ""
        self.cookies: Dict[str, str] = {}

    def load(self) -> None:
        self.token = self._settings.get("token", "") or ""
        self.cookies = self._settings.get("cookies", {}) or {}

    def save(self) -> None:
        self._settings.set("token", self.token)
        self._settings.set("cookies", self.cookies)
        self._settings.save()

    @property
    def is_authenticated(self) -> bool:
        return bool(self.token)

    @property
    def cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items() if v)

    def update_from_login(self, token: str, cookies: Dict[str, str]) -> None:
        self.token = token
        self.cookies = dict(cookies)
        if token:
            self.cookies.setdefault("token", token)
        self.save()

    def clear(self) -> None:
        self.token = ""
        self.cookies = {}
        self.save()


class HostManager:
    """域名探测与选择，负责 failover。"""

    def __init__(self, settings: AppSettings, session: Session):
        self._settings = settings
        self._session = session
        self._hosts: List[str] = []
        self._custom_hosts: List[str] = []
        self._current_host: str = ""
        self._lock = threading.RLock()
        self._session_hosts: Dict[str, List[str]] = {}
        self.load_hosts()

    def load_hosts(self) -> None:
        with self._lock:
            stored = self._settings.get("hosts", [])
            if isinstance(stored, list) and stored:
                self._hosts = [normalize_host(h) for h in stored if h]
            else:
                self._hosts = list(DEFAULT_HOSTS)
            custom = self._settings.get("custom_hosts", [])
            self._custom_hosts = [normalize_host(h) for h in custom if h]
            current = self._settings.get("current_host", "")
            self._current_host = normalize_host(current) if current else (self._hosts[0] if self._hosts else DEFAULT_HOSTS[0])
            if not self._current_host:
                self._current_host = DEFAULT_HOSTS[0]

    @property
    def current_host(self) -> str:
        with self._lock:
            return self._current_host

    @property
    def base_url(self) -> str:
        return f"https://{self.current_host}/"

    @property
    def known_hosts(self) -> List[str]:
        with self._lock:
            result: List[str] = []
            for h in self._hosts + self._custom_hosts:
                if h and h not in result:
                    result.append(h)
            return result

    def resolve_url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self.base_url}{path}"

    def resolve_href(self, href: str, current_uri: str = "") -> str:
        from urllib.parse import urljoin

        href = href.strip()
        if not href:
            return current_uri or self.base_url
        if href.startswith(("http://", "https://")):
            return self.rewrite_to_current_host(href)
        return self.rewrite_to_current_host(urljoin(current_uri or self.base_url, href))

    def rewrite_to_current_host(self, url: str) -> str:
        from urllib.parse import urlparse, urlunparse

        parts = urlparse(url)
        if not parts.scheme:
            return url
        host = parts.hostname.lower() if parts.hostname else ""
        with self._lock:
            active = self._current_host
            allowed = set(self.known_hosts) | {active}
        if host != active and host not in allowed:
            return url
        base = urlparse(self.base_url)
        port = f":{base.port}" if base.port else ""
        return urlunparse((base.scheme, f"{active}{port}", parts.path, parts.params, parts.query, parts.fragment))

    def set_current_host(self, host: str) -> None:
        h = normalize_host(host)
        if not h:
            raise ValueError("域名不能为空。")
        if h not in self.known_hosts:
            raise ValueError("域名不存在。")
        with self._lock:
            self._current_host = h
            self._settings.set("current_host", h)
            self._settings.save()

    def add_custom_host(self, value: str) -> str:
        h = normalize_host_input(value)
        if not h:
            raise ValueError("域名不能为空。")
        if not is_valid_host_name(h):
            raise ValueError("域名格式不正确。")
        with self._lock:
            if h not in self._custom_hosts:
                self._custom_hosts.append(h)
                self._settings.set("custom_hosts", self._custom_hosts)
                self._settings.save()
        return h

    def delete_host(self, host: str) -> None:
        h = normalize_host(host)
        if not h:
            raise ValueError("域名不能为空。")
        with self._lock:
            remaining = [x for x in self._hosts if x != h]
            if not remaining:
                raise ValueError("至少保留一个域名。")
            self._hosts = remaining
            if h in self._custom_hosts:
                self._custom_hosts.remove(h)
            self._settings.set("hosts", self._hosts)
            self._settings.set("custom_hosts", self._custom_hosts)
            if self._current_host == h:
                self._current_host = self._hosts[0]
                self._settings.set("current_host", self._current_host)
            self._settings.save()

    def probe_host(self, host: str, timeout: float = 3.0) -> HostProbe:
        """探测单个域名可达性与延迟。"""
        start = time.time()
        status_code: Optional[int] = None
        success = False
        try:
            resp = requests.get(
                f"https://{host}/",
                headers={"User-Agent": DESKTOP_USER_AGENT},
                timeout=timeout,
                allow_redirects=True,
            )
            status_code = resp.status_code
            success = resp.status_code < 500
        except Exception:
            success = False
        latency = int((time.time() - start) * 1000)
        if not success:
            latency = 999999
        return HostProbe(host=host, success=success, latency_ms=latency, status_code=status_code)

    def probe_all(self, timeout: float = 3.0) -> List[HostProbe]:
        """并发探测所有已知域名，返回按成功/延迟排序的结果。"""
        hosts = self.known_hosts
        results: List[HostProbe] = []

        def worker(h: str):
            results.append(self.probe_host(h, timeout=timeout))

        threads = [threading.Thread(target=worker, args=(h,)) for h in hosts]
        for t in threads:
            t.daemon = True
            t.start()
        for t in threads:
            t.join(timeout + 1)

        results.sort(key=lambda p: (not p.success, p.latency_ms))
        return results

    def select_best_host(self) -> str:
        probes = self.probe_all()
        for p in probes:
            if p.success:
                try:
                    self.set_current_host(p.host)
                except ValueError:
                    pass
                return p.host
        return self.current_host

    def failover(self) -> str:
        """转移到下一个可用域名。"""
        failing = self.current_host
        probes = self.probe_all()
        for p in probes:
            if p.success and normalize_host(p.host) != normalize_host(failing):
                try:
                    self.set_current_host(p.host)
                except ValueError:
                    continue
                return p.host
        return self.current_host


class HttpClient:
    """带会话与自动 failover 的 HTTP 客户端。"""

    def __init__(self, host_manager: HostManager, session: Session, settings: Optional[AppSettings] = None):
        self._host = host_manager
        self._session = session
        self._settings = settings

    def use_proxy(self) -> bool:
        if self._settings is not None:
            return bool(self._settings.get("use_proxy", True))
        return True

    def _headers(self, include_auth: bool = True, content_type: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": DESKTOP_USER_AGENT,
            "platform": "2",
        }
        if content_type:
            headers["Content-Type"] = content_type
        if include_auth and self._session.token:
            headers["Authorization"] = f"Token {self._session.token}"
        if self._session.cookie_header:
            headers["Cookie"] = self._session.cookie_header
        return headers

    def _make_session(self):
        session = requests.Session()
        # 默认跟随系统代理；可在设置中关闭
        session.trust_env = self.use_proxy()
        return session

    def get(self, path: str, params: Optional[Dict] = None, timeout: float = 10.0) -> requests.Response:
        url = self._host.resolve_url(path)
        last_error: Optional[Exception] = None
        for attempt in range(2):
            try:
                resp = self._make_session().get(
                    url,
                    params=params,
                    headers=self._headers(),
                    timeout=timeout,
                    allow_redirects=True,
                )
                return resp
            except Exception as e:
                last_error = e
                time.sleep(0.5 * (attempt + 1))
        raise last_error if last_error else RuntimeError("请求失败")

    def get_html(self, url: str, timeout: float = 8.0) -> requests.Response:
        last_error: Optional[Exception] = None
        for attempt in range(1):
            try:
                resp = self._make_session().get(
                    url,
                    headers={"User-Agent": DESKTOP_USER_AGENT, "Accept": "text/html"},
                    timeout=timeout,
                    allow_redirects=True,
                )
                return resp
            except Exception as e:
                last_error = e
                time.sleep(0.5 * (attempt + 1))
        raise last_error if last_error else RuntimeError("请求失败")

    def post(self, path: str, data: Optional[Dict] = None, timeout: float = 10.0, **kw) -> requests.Response:
        url = self._host.resolve_url(path)
        last_error: Optional[Exception] = None
        for attempt in range(2):
            try:
                resp = self._make_session().post(
                    url,
                    data=data,
                    headers=self._headers(),
                    timeout=timeout,
                    allow_redirects=True,
                    **kw,
                )
                return resp
            except Exception as e:
                last_error = e
                time.sleep(0.5)
        raise last_error if last_error else RuntimeError("请求失败")
