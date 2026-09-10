# -*- coding: utf-8 -*-
"""HTTP 会话层（移植 Android 版 OkHttp 封装 + EhEngine 的错误处理）"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import urls
from .config import get, get_cookie, set_cookies


class EhException(Exception):
    """业务异常（带中文提示）"""
    pass


class ParseException(Exception):
    def __init__(self, message, body=None):
        super(ParseException, self).__init__(message)
        self.body = body or ""


class StatusCodeException(Exception):
    def __init__(self, code):
        super(StatusCodeException, self).__init__("HTTP 状态码异常: %d" % code)
        self.code = code


class CancelledException(Exception):
    pass


class NoHAtHClientException(EhException):
    pass


SAD_PANDA_DISPOSITION = 'attachment; filename="sadpanda.jpg"'
SAD_PANDA_TYPE = "image/jpeg"
SAD_PANDA_LENGTH = "9615"
KOKOMADE_URL = "https://exhentai.org/img/kokomade.jpg"


def make_session():
    """创建配置好的 requests.Session"""
    s = requests.Session()
    ua = get("user_agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    s.headers.update({
        "User-Agent": ua,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    })
    retry = Retry(total=get("retry_count", 3), connect=2, read=2, backoff_factor=0.5,
                  status_forcelist=[429, 500, 502, 503, 504], allowed_methods=None,
                  raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    proxy = get("proxy", "")
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    _load_cookies_into(s)
    return s


def _load_cookies_into(session):
    cj = get("cookies", {}) or {}
    for k, v in cj.items():
        if v:
            session.cookies.set(k, v, domain="e-hentai.org", path="/")
            session.cookies.set(k, v, domain="exhentai.org", path="/")
            session.cookies.set(k, v, domain="forums.e-hentai.org", path="/")


def save_cookies_from(session):
    """将会话中的关键 Cookie 保存到配置"""
    want = ("ipb_member_id", "ipb_pass_hash", "igneous", "hath_perms", "hath_used",
            "ipb_session_id", "uconfig", "nw")
    out = {}
    for k in want:
        v = session.cookies.get(k)
        if v:
            out[k] = v
    if out:
        set_cookies(out)


def check_error_response(session, code, headers, body, url):
    """模拟 doThrowException 的错误检查"""
    if headers is not None:
        if headers.get("Content-Disposition") == SAD_PANDA_DISPOSITION and \
           headers.get("Content-Type") == SAD_PANDA_TYPE and \
           str(headers.get("Content-Length", "")) == SAD_PANDA_LENGTH:
            raise EhException("Sad Panda：您访问了里站但 igneous Cookie 无效或缺失。")
    if body and KOKOMADE_URL in body:
        raise EhException("今回はここまで\n\n今日的配额已用完，明天再来吧。")
    if code == 403:
        if body and "sadpanda" in body.lower():
            raise EhException("Sad Panda：里站访问被拒绝（请检查 igneous Cookie 或登录状态）。")
    if code >= 400:
        raise StatusCodeException(code)


def http_get(session, url, referer=None, timeout=None, stream=False, allow_redirects=True):
    """GET 请求 + 统一错误处理"""
    timeout = timeout or get("timeout", 20)
    headers = {}
    if referer:
        headers["Referer"] = referer
    elif url.startswith("https://e-hentai.org") or url.startswith("https://exhentai.org"):
        headers["Referer"] = urls.get_referer()
    resp = session.get(url, headers=headers, timeout=timeout, stream=stream,
                       allow_redirects=allow_redirects)
    check_error_response(session, resp.status_code, resp.headers, None, url)
    if not stream:
        check_error_response(session, resp.status_code, resp.headers, resp.text, url)
    return resp


def http_post_form(session, url, data, referer=None, origin=None, timeout=None):
    timeout = timeout or get("timeout", 20)
    headers = {}
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    resp = session.post(url, data=data, headers=headers, timeout=timeout)
    check_error_response(session, resp.status_code, resp.headers, resp.text, url)
    return resp


def http_post_json(session, url, payload, referer=None, origin=None, timeout=None):
    timeout = timeout or get("timeout", 20)
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    resp = session.post(url, json=payload, headers=headers, timeout=timeout)
    check_error_response(session, resp.status_code, resp.headers, resp.text, url)
    return resp


def make_image_session():
    """轻量图片会话：无重试退避、更大连接池，用于缩略图/图片下载（线程内复用）"""
    s = requests.Session()
    ua = get("user_agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    s.headers.update({
        "User-Agent": ua,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    })
    adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=0)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    proxy = get("proxy", "")
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    _load_cookies_into(s)
    return s
