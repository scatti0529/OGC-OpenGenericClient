# -*- coding: utf-8 -*-
"""E-Hentai API 引擎（移植自 Android 版 EhEngine）"""
import re
import time
import html as html_mod

from . import urls
from . import constants as C
from .config import CFG, is_login, get
from .session import (make_session, EhException, ParseException, http_get,
                      http_post_form, http_post_json, save_cookies_from)
from .models import (GalleryInfo, GalleryDetail, GalleryCommentList, TorrentInfo,
                     PreviewItem, HomeDetail, EhTopListDetail, EhNewsDetail,
                     ArchiverData)
from . import parsers

_sessions = {}


def get_session():
    """每个调用线程一个会话（requests.Session 非线程安全）"""
    tid = id(__import__("threading").current_thread())
    s = _sessions.get(tid)
    if s is None:
        s = make_session()
        _sessions[tid] = s
    return s


class ListResult(object):
    """列表解析结果"""
    __slots__ = ("items", "pages", "next_page", "no_watched_tags", "result_count")

    def __init__(self, items=None, pages=0, next_page=None, no_watched_tags=False,
                 result_count=""):
        self.items = items or []
        self.pages = pages
        self.next_page = next_page
        self.no_watched_tags = no_watched_tags
        self.result_count = result_count


def get_gallery_list(url, mode=C.MODE_NORMAL):
    """获取画廊列表（HTML 解析）"""
    s = get_session()
    resp = http_get(s, url, referer=urls.get_referer())
    body = resp.text
    result = parsers.parse_gallery_list(body, mode)
    # 自动补全字段：需要页数显示但缺失，或有 rated 标记，或需要标签过滤时调用 gdata
    need_api = False
    if CFG.get("show_gallery_pages", True):
        for gi in result.items:
            if gi.pages == 0:
                need_api = True
                break
    if not need_api:
        for gi in result.items:
            if gi.rated:
                need_api = True
                break
    if need_api and result.items:
        try:
            fill_gallery_list_by_api(result.items, url)
        except Exception:
            pass
    for gi in result.items:
        if gi.thumb:
            gi.thumb = urls.get_fixed_preview_thumb_url(gi.thumb)
        gi.generate_s_lang()
    _apply_blocked_filter(result.items)
    return result


def _apply_blocked_filter(items):
    """按 FILTER（标签屏蔽）过滤列表结果"""
    try:
        from . import db
        blocked = db.blocked_tag_set()
    except Exception:
        return
    if not blocked:
        return
    out = []
    for gi in items:
        hit = False
        tags = [t.lower() for t in (gi.simple_tags or [])]
        for b in blocked:
            if not b:
                continue
            if b in tags:
                hit = True
                break
            if ":" not in b and any(t.endswith(":" + b) for t in tags):
                hit = True
                break
        if not hit:
            out.append(gi)
    items[:] = out


def fill_gallery_list_by_api(gallery_list, referer):
    """gdata 批量补全元数据（每次最多 25 条）"""
    for i in range(0, len(gallery_list), 25):
        batch = gallery_list[i:i + 25]
        _do_fill_by_api(batch, referer)


def _do_fill_by_api(items, referer):
    payload = {
        "method": "gdata",
        "gidlist": [[gi.gid, gi.token] for gi in items],
        "namespace": 1,
    }
    s = get_session()
    resp = http_post_json(s, urls.get_api_url(), payload,
                          referer=referer, origin=urls.get_origin())
    data = resp.json()
    parsers.parse_gdata(data, items)


def get_gallery_detail(gid, token, index=0, all_comment=False):
    """获取画廊详情"""
    url = urls.get_gallery_detail_url(gid, token, index, all_comment)
    s = get_session()
    resp = http_get(s, url, referer=urls.get_referer())
    body = resp.text
    detail = parsers.parse_gallery_detail(body)
    return detail


def get_preview_page(url):
    """获取某一预览页的预览图集合"""
    s = get_session()
    resp = http_get(s, url, referer=urls.get_referer())
    body = resp.text
    return parsers.parse_preview_set(body), parsers.parse_preview_pages(body)


def rate_gallery(gid, token, rating, api_uid, api_key):
    """评分（0.5-5.0）"""
    payload = {
        "method": "rategallery",
        "apiuid": api_uid, "apikey": api_key,
        "gid": gid, "token": token,
        "rating": int(math_ceil(rating * 2)),
    }
    s = get_session()
    resp = http_post_json(s, urls.get_api_url(), payload,
                          referer=urls.get_gallery_detail_url(gid, token),
                          origin=urls.get_origin())
    d = resp.json()
    return float(d.get("rating_avg", 0)), int(d.get("rating_cnt", 0))


def math_ceil(x):
    return int(x) + 1 if x > int(x) else int(x)


def comment_gallery(gid, token, comment, edit_id=None):
    """发表/编辑评论，返回 (comments, has_more)"""
    url = urls.get_gallery_detail_url(gid, token)
    data = {}
    if edit_id is None:
        data["commenttext_new"] = comment
    else:
        data["commenttext_edit"] = comment
        data["edit_comment"] = edit_id
    s = get_session()
    resp = http_post_form(s, url, data, referer=url, origin=urls.get_origin())
    body = resp.text
    if "#chd + p" in body:
        m = re.search(r'id="chd"[^>]*>.*?<p[^>]*>(.*?)</p>', body, re.S)
        if m:
            raise EhException(m.group(1).strip())
    return parsers.parse_comments(body)


def get_edit_comment(api_uid, api_key, gid, token, comment_id):
    payload = {"method": "geteditcomment", "apiuid": api_uid, "apikey": api_key,
               "gid": gid, "token": token, "comment_id": comment_id}
    s = get_session()
    resp = http_post_json(s, urls.get_api_url(), payload,
                          referer=urls.get_gallery_detail_url(gid, token),
                          origin=urls.get_origin())
    d = resp.json()
    if "error" in d:
        raise EhException(d["error"])
    return d.get("comment_id", 0), d.get("editable_comment", "")


def get_gallery_token(gid, gtoken, page):
    """gtoken：换取页面 token"""
    payload = {"method": "gtoken", "pagelist": [[gid, gtoken, page + 1]]}
    s = get_session()
    resp = http_post_json(s, urls.get_api_url(), payload,
                          referer=urls.get_referer(), origin=urls.get_origin())
    d = resp.json()
    if "error" in d:
        raise EhException(d["error"])
    tl = d.get("tokenlist") or []
    if tl:
        return tl[0].get("token", "")
    return ""


def get_favorites(url, call_api=True):
    """获取收藏列表页"""
    s = get_session()
    resp = http_get(s, url, referer=urls.get_referer())
    body = resp.text
    result = parsers.parse_favorites(body)
    if call_api and result.items:
        try:
            fill_gallery_list_by_api(result.items, url)
        except Exception:
            pass
    return result


def add_favorite(gid, token, dst_cat, note=""):
    """添加/移动收藏（dst_cat: -1 删除，0-9 收藏夹）"""
    if dst_cat == -1:
        cat_str = "favdel"
    elif 0 <= dst_cat <= 9:
        cat_str = str(dst_cat)
    else:
        raise EhException("无效的收藏夹: %d" % dst_cat)
    url = urls.get_add_favorites_url(gid, token)
    data = {"favcat": cat_str, "favnote": note or "",
            "submit": "Apply Changes", "update": "1"}
    s = get_session()
    http_post_form(s, url, data, referer=url, origin=urls.get_origin())
    return True


def modify_favorites(url, gid_list, dst_cat):
    """批量移动/删除收藏（-1 删除，0-9 移动到）"""
    if dst_cat == -1:
        cat_str = "delete"
    elif 0 <= dst_cat <= 9:
        cat_str = "fav%d" % dst_cat
    else:
        raise EhException("无效的收藏夹: %d" % dst_cat)
    data = {"ddact": cat_str, "apply": "Apply"}
    for gid in gid_list:
        data["modifygids[]"] = gid
    s = get_session()
    resp = http_post_form(s, url, data, referer=url, origin=urls.get_origin())
    return parsers.parse_favorites(resp.text)


def get_torrent_list(gid, token):
    """获取种子列表（需先有详情页的 torrentUrl）"""
    url = urls.get_host() + "gallerytorrents.php?gid=%s&t=%s" % (gid, token)
    s = get_session()
    resp = http_get(s, url, referer=urls.get_gallery_detail_url(gid, token))
    return parsers.parse_torrents(resp.text)


def get_top_list(follow, page=0):
    """获取排行榜（按时间段返回画廊列表，兼容游标/页码两种翻页）"""
    sb = urls.get_top_list_url() + "?"
    sb += follow or ""
    if page and isinstance(page, int) and 0 < page < 200:
        sb += "&p=%d" % page
    elif isinstance(page, str) and page.startswith("http"):
        sb = page
    s = get_session()
    resp = http_get(s, sb, referer=urls.get_top_list_url())
    result = parsers.parse_gallery_list(resp.text, C.MODE_TOP_LIST)
    # 排行榜页也是标准画廊表，页数/下一页从 ptt 提取
    for gi in result.items:
        if gi.thumb:
            gi.thumb = urls.get_fixed_preview_thumb_url(gi.thumb)
        gi.generate_s_lang()
    return result


def get_home_detail():
    """获取首页配额信息"""
    s = get_session()
    resp = http_get(s, urls.get_home_url(), referer=urls.get_referer())
    body = resp.text
    detail = HomeDetail()
    detail.limit_html = parsers.parse_home_limit(body)
    detail.body = body
    return detail


def reset_image_limit():
    s = get_session()
    resp = http_post_form(s, urls.get_home_url(), {"reset_imagelimit": "Reset Limit"},
                          referer=urls.get_referer())
    return parsers.parse_home_limit(resp.text)


def get_news():
    s = get_session()
    resp = http_get(s, urls.get_news_url())
    return EhNewsDetail(resp.text)


def get_watched_list():
    """获取关注标签列表"""
    if not is_login():
        return []
    s = get_session()
    resp = http_get(s, urls.get_watched_url())
    return parsers.parse_my_tag_list(resp.text)


def get_gallery_page(gid, token, p_token, index):
    """HTML 方式获取单页图片信息"""
    url = urls.get_page_url(gid, index, p_token)
    s = get_session()
    resp = http_get(s, url, referer=urls.get_gallery_detail_url(gid, token))
    return parsers.parse_gallery_page(resp.text)


def get_gallery_page_api(gid, index, p_token, show_key, prev_p_token=None):
    """API 方式获取单页图片信息（showpage）"""
    payload = {"method": "showpage", "gid": gid, "page": index + 1,
               "imgkey": p_token, "showkey": show_key}
    referer = None
    if index > 0 and prev_p_token:
        referer = urls.get_page_url(gid, index - 1, prev_p_token)
    s = get_session()
    resp = http_post_json(s, urls.get_api_url(), payload, referer=referer,
                          origin=urls.get_origin())
    d = resp.json()
    if "error" in d:
        raise ParseException(d["error"])
    return parsers.parse_gallery_page_api(d)

def image_search(image_path, uss=True, osc=False, se=False):
    """以图搜图：POST multipart 到 upld，返回 ListResult"""
    import os
    s = get_session()
    name = os.path.basename(image_path)
    if "." not in name:
        name = name + ".jpg"
    files = [("sfile", (name, open(image_path, "rb"), "image/jpeg"))]
    data = {"f_sfile": "File Search"}
    if uss:
        data["fs_similar"] = "on"
    if osc:
        data["fs_covers"] = "on"
    if se:
        data["fs_exp"] = "on"
    headers = {"Referer": urls.get_referer() + "/", "Origin": urls.get_origin()}
    resp = s.post(urls.get_image_search_url(), files=files, data=data,
                  headers=headers, timeout=60, allow_redirects=False)
    # 302 跟随
    if resp.status_code == 302:
        loc = resp.headers.get("Location")
        if loc:
            resp = s.get(loc, headers={"Referer": urls.get_referer()}, timeout=60)
    check_error_response(s, resp.status_code, resp.headers, resp.text, resp.url)
    result = parsers.parse_gallery_list(resp.text, C.MODE_NORMAL)
    fill_gallery_list_by_api(result.items, urls.get_referer())
    return result
