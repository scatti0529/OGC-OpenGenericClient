# -*- coding: utf-8 -*-
"""拷贝漫画站点 API 客户端：登录、搜索、个人中心、收藏、评论（移植自 OGC-EasyCopy）。"""
from __future__ import annotations

import base64
import json
import random
from typing import Dict, List, Optional, Tuple

from .config import DESKTOP_USER_AGENT
from .models import (
    ChapterComment,
    ChapterCommentFeed,
    ProfileHistoryItem,
    ProfileLibraryItem,
    ProfilePageData,
    ProfileUserData,
    DiscoverPageData,
    ComicCardData,
    PagerData,
)
from .net import HttpClient, Session


class SiteApiException(Exception):
    pass


def _str(value) -> str:
    return str(value).strip() if value is not None else ""


def _first_non_empty_map(source: Dict, keys: List[str]) -> Dict:
    for key in keys:
        value = source.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


class SiteApiClient:
    SEARCH_PAGE_SIZE = 12
    PROFILE_PAGE_SIZE = 20

    def __init__(self, http: HttpClient, session: Session):
        self._http = http
        self._session = session

    # ---------- 登录 ----------
    def login(self, username: str, password: str) -> Tuple[str, Dict[str, str]]:
        username = username.strip()
        password = password.strip()
        if not username or not password:
            raise SiteApiException("请输入账号和密码。")

        salt = random.randint(100000, 999999)
        encoded_pwd = base64.b64encode(f"{password}-{salt}".encode("utf-8")).decode("ascii")
        data = {
            "username": username,
            "password": encoded_pwd,
            "salt": str(salt),
            "platform": "2",
            "version": "2025.12.10",
            "source": "freeSite",
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": DESKTOP_USER_AGENT,
            "platform": "2",
        }

        last_error: Optional[Exception] = None
        for path in ["/api/kb/web/login", "/api/v1/login"]:
            try:
                url = self._http._host.resolve_url(path)
                import requests

                resp = requests.post(url, data=data, headers=headers, timeout=20, allow_redirects=True)
                payload = self._decode_json(resp, "登录返回格式异常。")
                code = int(payload.get("code", resp.status_code))
                if code != 200:
                    raise SiteApiException(payload.get("message") or f"登录失败：{code}")
                results = payload.get("results") or {}
                token = str(results.get("token", "")).strip()
                if not token:
                    raise SiteApiException("登录成功，但未拿到有效凭证。")
                cookies: Dict[str, str] = {"token": token}
                for k in ["username", "user_id", "avatar", "datetime_created"]:
                    v = results.get(k)
                    if v:
                        cookies[k] = str(v)
                return token, cookies
            except SiteApiException as e:
                last_error = e
            except Exception as e:
                last_error = e
        if isinstance(last_error, SiteApiException):
            raise last_error
        raise SiteApiException("登录失败，请稍后重试。")

    # ---------- 搜索 ----------
    def search(self, query: str, page: int = 1, q_type: str = "") -> DiscoverPageData:
        query = query.strip()
        if not query:
            return DiscoverPageData(title="搜索", uri="", filters=[], items=[], pager=PagerData(), spotlight=[])

        page = max(1, page)
        offset = (page - 1) * self.SEARCH_PAGE_SIZE

        last_error: Optional[Exception] = None
        for path in ["/api/kb/web/searchci/comics", "/api/kb/web/searchch/comics"]:
            try:
                resp = self._http.get(
                    path,
                    params={
                        "offset": str(offset),
                        "platform": "2",
                        "limit": str(self.SEARCH_PAGE_SIZE),
                        "q": query,
                        "q_type": q_type,
                    },
                )
                payload = self._decode_json(resp, "搜索接口返回格式异常。")
                code = int(payload.get("code", resp.status_code))
                if code != 200:
                    raise SiteApiException(payload.get("message") or f"搜索失败：{code}")
                results = payload.get("results") or {}
                items_raw = self._extract_list(results)
                items = [self._parse_search_comic(it) for it in items_raw]
                items = [it for it in items if it.title]
                total = self._pick_int(results, ["total", "count", "total_count"], len(items))
                total_pages = 1 if total <= 0 else max(1, (total + self.SEARCH_PAGE_SIZE - 1) // self.SEARCH_PAGE_SIZE)

                base_uri = self._http._host.resolve_url("/search")
                pager = PagerData(
                    current_label=str(page),
                    total_label=f"共{total_pages}页 · {total}条",
                    prev_href=self._search_uri(query, page - 1, q_type) if page > 1 else "",
                    next_href=self._search_uri(query, page + 1, q_type) if page < total_pages else "",
                )
                return DiscoverPageData(
                    title="搜索",
                    uri=self._search_uri(query, page, q_type),
                    filters=[],
                    items=items,
                    pager=pager,
                    spotlight=[],
                )
            except SiteApiException as e:
                last_error = e
            except Exception as e:
                last_error = e
        if isinstance(last_error, SiteApiException):
            raise last_error
        raise SiteApiException("搜索失败，请稍后重试。")

    def _search_uri(self, query: str, page: int, q_type: str) -> str:
        from urllib.parse import urlencode

        base = self._http._host.resolve_url("/search")
        params: Dict[str, str] = {"q": query}
        if page > 1:
            params["page"] = str(page)
        if q_type:
            params["q_type"] = q_type
        return f"{base}?{urlencode(params)}"

    # ---------- 个人中心 ----------
    def load_profile(self) -> ProfilePageData:
        if not self._session.is_authenticated:
            return ProfilePageData(is_logged_in=False)

        try:
            user = self.load_user_info()
        except SiteApiException:
            user = None
        collections, _ = self._load_paged_list_or_empty(
            ["/api/v3/member/collect/comics"], page=1, sort="-datetime_updated"
        )
        history, _ = self._load_paged_list_or_empty(
            ["/api/kb/web/browses", "/api/v2/web/browses"], page=1, is_history=True
        )
        return ProfilePageData(
            title="我的",
            uri="",
            is_logged_in=True,
            user=user,
            collections=collections,
            history=history,
        )

    def load_user_info(self) -> ProfileUserData:
        if not self._session.is_authenticated:
            raise SiteApiException("请先登录后再操作。")
        payload = self._get_json("/api/v2/web/user/info")
        results = payload.get("results") or {}
        if not results and isinstance(payload.get("data"), dict):
            results = payload.get("data")
        user_id = self._pick_str(results, ["user_id", "id", "uid", "uuid"])
        username = self._pick_str(results, ["username", "mobile", "email", "name", "nickname"])
        avatar = self._pick_str(results, ["avatar", "avatar_url", "portrait"])
        return ProfileUserData(user_id=user_id, username=username, avatar_url=avatar)

    def load_collections_page(self, page: int = 1, sort: str = "-datetime_updated") -> Tuple[List[ProfileLibraryItem], int]:
        if not self._session.is_authenticated:
            raise SiteApiException("请先登录后再操作。")
        return self._load_paged_list_or_empty(["/api/v3/member/collect/comics"], page=page, sort=sort)

    def load_history_page(self, page: int = 1) -> Tuple[List[ProfileHistoryItem], int]:
        if not self._session.is_authenticated:
            raise SiteApiException("请先登录后再操作。")
        return self._load_paged_list_or_empty(
            ["/api/kb/web/browses", "/api/v2/web/browses"], page=page, is_history=True
        )

    def set_collection(self, comic_id: str, is_collected: bool) -> None:
        if not self._session.is_authenticated:
            raise SiteApiException("请先登录后再操作收藏。")
        comic_id = comic_id.strip()
        if not comic_id:
            raise SiteApiException("漫画收藏信息缺失。")

        import requests

        url = self._http._host.resolve_url("/api/v2/web/collect")
        headers = {
            "Authorization": f"Token {self._session.token}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": DESKTOP_USER_AGENT,
            "platform": "2",
        }
        if self._session.cookie_header:
            headers["Cookie"] = self._session.cookie_header
        try:
            resp = requests.post(
                url,
                data={"comic_id": comic_id, "is_collect": "1" if is_collected else "0"},
                headers=headers,
                timeout=20,
                allow_redirects=True,
            )
        except Exception:
            raise SiteApiException("收藏请求失败，请检查网络。")
        if resp.status_code in (401, 403):
            raise SiteApiException("登录已失效，请重新登录。")
        payload = self._decode_json(resp, "收藏接口返回格式异常。")
        code = int(payload.get("code", resp.status_code))
        if code != 200:
            raise SiteApiException(payload.get("message") or f"收藏失败：{code}")

    # ---------- 评论 ----------
    def load_comments(self, chapter_id: str, limit: int = 40, offset: int = 0) -> ChapterCommentFeed:
        chapter_id = chapter_id.strip()
        if not chapter_id:
            raise SiteApiException("章节评论信息缺失。")

        import requests

        current_host = self._http._host.current_host
        bare = current_host[4:] if current_host.startswith("www.") else current_host
        candidates = []
        for h in [f"api.{bare}" if bare else "", "api.mangacopy.com", "api.copy-manga.com", "api.2026copy.com"]:
            if h and h not in candidates:
                candidates.append(h)

        last_error: Optional[Exception] = None
        for host in candidates:
            try:
                url = f"https://{host}/api/v3/roasts"
                resp = requests.get(
                    url,
                    params={"chapter_id": chapter_id, "limit": str(limit), "offset": str(offset), "_update": "true"},
                    headers={"User-Agent": DESKTOP_USER_AGENT, "Accept": "application/json"},
                    timeout=20,
                )
                payload = self._decode_json(resp, "章节评论返回格式异常。")
                code = int(payload.get("code", resp.status_code))
                if code != 200:
                    raise SiteApiException(payload.get("message") or f"评论加载失败：{code}")
                results = payload.get("results") or {}
                raw_list = self._extract_list(results)
                comments = [self._parse_comment(c) for c in raw_list]
                comments = [c for c in comments if c.message]
                total = self._pick_int(results, ["total", "count", "total_count"], len(comments))
                return ChapterCommentFeed(total=total, comments=comments)
            except SiteApiException as e:
                last_error = e
            except Exception as e:
                last_error = e
        if isinstance(last_error, SiteApiException):
            raise last_error
        raise SiteApiException("评论加载失败，请稍后重试。")

    # ---------- 内部工具 ----------
    def _decode_json(self, resp, malformed_msg: str) -> Dict:
        try:
            body = resp.content.decode("utf-8", errors="replace")
            decoded = json.loads(body)
        except Exception:
            raise SiteApiException(malformed_msg)
        if not isinstance(decoded, dict):
            raise SiteApiException(malformed_msg)
        return decoded

    def _get_json(self, path: str) -> Dict:
        resp = self._http.get(path)
        if resp.status_code in (401, 403):
            raise SiteApiException("登录已失效，请重新登录。")
        return self._decode_json(resp, "接口返回格式异常。")

    def _extract_list(self, results: Dict) -> List[Dict]:
        # 兼容多种列表键
        for key in ["list", "data", "items", "results", "comics", "records", "browse", "browses"]:
            v = results.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        # 可能直接是数组
        for v in results.values():
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return []

    def _pick_str(self, source: Dict, keys: List[str], default: str = "") -> str:
        for k in keys:
            v = source.get(k)
            if v is not None:
                return str(v).strip()
        return default

    def _pick_int(self, source: Dict, keys: List[str], default: int = 0) -> int:
        for k in keys:
            v = source.get(k)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
        return default

    def _parse_search_comic(self, item: Dict) -> ComicCardData:
        nested = _first_non_empty_map(item, ["comic", "comic_info", "cartoon", "results"])
        source = nested if nested else item
        title = self._pick_str(source, ["name", "title", "comic_name"])
        cover = self._pick_str(source, ["cover", "cover_url", "path_word", "vertical_cover"])
        href = ""
        path_word = self._pick_str(source, ["path_word", "pathWord", "slug"])
        if path_word:
            href = f"/comic/{path_word}"
        else:
            href = self._pick_str(source, ["url", "href"])
        subtitle = ""
        secondary = ""
        author = self._pick_str(source, ["author", "authors", "author_name"])
        region = self._pick_str(source, ["region", "area"])
        theme = self._pick_str(source, ["theme", "types", "tags"])
        if author:
            subtitle = author
        if theme:
            secondary = theme
        return ComicCardData(title=title, cover_url=cover, href=href, subtitle=subtitle, secondary_text=secondary, badge="")

    def _parse_comment(self, item: Dict) -> ChapterComment:
        user_name = self._pick_str(item, ["user_name", "nickname", "name", "username"])
        avatar = self._pick_str(item, ["avatar", "avatar_url"])
        message = self._pick_str(item, ["content", "message", "roast", "comment"])
        created = self._pick_str(item, ["datetime", "created_at", "create_time"])
        return ChapterComment(user_name=user_name, avatar_url=avatar, message=message, created_at=created)

    def _load_paged_list_or_empty(
        self,
        paths: List[str],
        page: int = 1,
        sort: str = "-datetime_updated",
        is_history: bool = False,
    ):
        if not self._session.is_authenticated:
            raise SiteApiException("请先登录后再操作。")
        page = max(1, page)
        offset = (page - 1) * self.PROFILE_PAGE_SIZE
        last_error: Optional[Exception] = None
        for path in paths:
            try:
                payload = self._get_json(
                    _path_with_params(
                        path,
                        {"offset": str(offset), "limit": str(self.PROFILE_PAGE_SIZE), **({"ordering": sort} if not is_history else {})},
                    )
                )
                results = payload.get("results") or {}
                raw_list = self._extract_list(results)
                total = self._pick_int(results, ["total", "count", "total_count"], len(raw_list))
                if is_history:
                    items = [self._parse_history(it) for it in raw_list]
                else:
                    items = [self._parse_collection(it) for it in raw_list]
                items = [it for it in items if it.title]
                return items, total
            except SiteApiException as e:
                last_error = e
            except Exception as e:
                last_error = e
        return [], 0

    def _parse_collection(self, item: Dict) -> ProfileLibraryItem:
        nested = _first_non_empty_map(item, ["comic", "comic_info", "cartoon", "results"])
        source = nested if nested else item
        title = self._pick_str(source, ["name", "title", "comic_name"])
        cover = self._pick_str(source, ["cover", "cover_url", "vertical_cover"])
        comic_id = self._pick_str(source, ["comic_id", "id", "uuid"])
        updated = self._pick_str(source, ["datetime_updated", "updated_at", "updated"])
        path_word = self._pick_str(source, ["path_word", "pathWord", "slug"])
        href = f"/comic/{path_word}" if path_word else self._pick_str(source, ["url", "href"])
        return ProfileLibraryItem(title=title, cover_url=cover, href=href, comic_id=comic_id, updated_at=updated)

    def _parse_history(self, item: Dict) -> ProfileHistoryItem:
        comic = _first_non_empty_map(item, ["comic", "comic_info", "cartoon"])
        chapter = _first_non_empty_map(item, ["chapter", "last_chapter", "browse"])
        source = comic if comic else item
        title = self._pick_str(source, ["name", "title", "comic_name"])
        cover = self._pick_str(source, ["cover", "cover_url", "vertical_cover"])
        path_word = self._pick_str(source, ["path_word", "pathWord", "slug"])
        chapter_label = self._pick_str(chapter, ["name", "title", "chapter_name"])
        chapter_uuid = self._pick_str(chapter, ["uuid", "chapter_uuid", "id"])
        read_at = self._pick_str(item, ["datetime_created", "datetime_updated", "updated_at", "browse_at", "read_at"])
        href = f"/comic/{path_word}" if path_word else self._pick_str(source, ["url", "href"])
        return ProfileHistoryItem(title=title, cover_url=cover, href=href, chapter_label=chapter_label, read_at=read_at)


def _path_with_params(path: str, params: Dict[str, str]) -> str:
    from urllib.parse import urlencode

    if "?" in path:
        sep = "&"
    else:
        sep = "?"
    return f"{path}{sep}{urlencode(params)}"
