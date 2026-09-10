# -*- coding: utf-8 -*-
"""HTML/JSON 解析器（移植自 Android 版 client/parser 包，bs4 + 正则）"""
import re
import html
from datetime import datetime, timezone
from urllib.parse import unquote

from bs4 import BeautifulSoup

from . import constants as C
from .models import (GalleryInfo, GalleryDetail, GalleryTagGroup, GalleryComment,
                     GalleryCommentList, TorrentInfo, PreviewItem, NewVersion,
                     EhTopListDetail)
from .session import EhException, ParseException

# ================= 通用工具 =================

def unescape_xml(s):
    return html.unescape(s) if s is not None else s

def trim(s):
    return unescape_xml(s).strip() if s is not None else ""

def safe_int(s, default=0):
    try:
        return int(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return default

def safe_float(s, default=0.0):
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return default

def format_date(ms):
    try:
        return datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return ""

CATEGORY_STR_MAP = [
    ("misc", C.CAT_MISC), ("doujinshi", C.CAT_DOUJINSHI), ("manga", C.CAT_MANGA),
    ("artistcg", C.CAT_ARTIST_CG), ("artist cg sets", C.CAT_ARTIST_CG), ("artist cg", C.CAT_ARTIST_CG),
    ("gamecg", C.CAT_GAME_CG), ("game cg sets", C.CAT_GAME_CG), ("game cg", C.CAT_GAME_CG),
    ("imageset", C.CAT_IMAGE_SET), ("image sets", C.CAT_IMAGE_SET), ("image set", C.CAT_IMAGE_SET),
    ("cosplay", C.CAT_COSPLAY), ("asianporn", C.CAT_ASIAN_PORN), ("asian porn", C.CAT_ASIAN_PORN),
    ("non-h", C.CAT_NON_H), ("western", C.CAT_WESTERN),
]

def get_category(type_str):
    if not type_str:
        return C.UNKNOWN_CATEGORY
    t = type_str.strip().lower()
    for s, v in CATEGORY_STR_MAP:
        if s == t:
            return v
    return C.UNKNOWN_CATEGORY

FAVORITE_SLOT_RGB = [(0, 0, 0), (240, 0, 0), (240, 160, 0), (208, 208, 0), (0, 128, 0),
                     (144, 240, 64), (64, 176, 240), (0, 0, 240), (80, 0, 128), (224, 128, 224)]

def favorite_slot_from_style(style):
    if not style:
        return -2
    m = re.search(r"background-color:rgba\((\d+),(\d+),(\d+),", style)
    if not m:
        return -2
    rgb = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    for i, ref in enumerate(FAVORITE_SLOT_RGB):
        if rgb == ref:
            return i
    return -2

# ================= 列表页 =================

PATTERN_NEXT_PAGE = re.compile(r"page=(\d+)")
PATTERN_RESULT_COUNT = re.compile(r"Found .* results")
PATTERN_PAGES = re.compile(r"(\d+) page")
PATTERN_THUMB_SIZE = re.compile(r"height:(\d+)px;width:(\d+)px")
PATTERN_GID_TOKEN = re.compile(r"(\d+)/([0-9a-f]{10})(?:[^0-9a-f]|$)")
PATTERN_RATING_PX = re.compile(r"\d+px")


class ListResult(object):
    __slots__ = ("pages", "next_page", "result_count", "first_href", "prev_href",
                 "next_href", "last_href", "no_watched_tags", "items", "fav_order")

    def __init__(self):
        self.pages = 0
        self.next_page = None
        self.result_count = ""
        self.first_href = ""
        self.prev_href = ""
        self.next_href = ""
        self.last_href = ""
        self.no_watched_tags = False
        self.items = []
        self.fav_order = ""


def _parse_rating(ir):
    """从 .ir 元素解析评分与 rated"""
    if ir is None:
        return 0.0, False
    style = ir.get("style") or ""
    nums = PATTERN_RATING_PX.findall(style)
    rate = 0.0
    if len(nums) >= 2:
        num1 = safe_int(nums[0])
        num2 = safe_int(nums[1])
        if num1 != 0:
            rate = 5 - num1 / 16.0
            if num2 == 21:
                rate -= 0.5
    rated = any(c in (ir.get("class") or []) for c in ("irr", "irg", "irb"))
    return rate, rated


def parse_gallery_list(body, mode=C.MODE_NORMAL):
    """解析画廊列表页（兼容 table/div 两种结构）"""
    result = ListResult()
    try:
        soup = BeautifulSoup(body, "html.parser")
    except Exception:
        return result
    # 零结果 / 无关注标签
    if "No hits found</p>" in body:
        result.pages = 0
        return result
    if "You do not have any watched tags" in body:
        result.no_watched_tags = True

    # 分页
    ptt = soup.find(class_="ptt")
    if ptt is not None:
        tds = ptt.find_all("td")
        if len(tds) >= 2:
            result.pages = safe_int(tds[-2].get_text(" ", strip=True))
            last = tds[-1].find("a")
            if last is not None:
                href = last.get("href") or ""
                m = PATTERN_NEXT_PAGE.search(href)
                if m:
                    result.next_page = int(m.group(1))
    else:
        nav = soup.find(class_="searchnav")
        if nav is not None:
            ids = ("ufirst", "uprev", "unext", "ulast")
            vals = {}
            for a in nav.find_all("a"):
                aid = (a.get("id") or "").lower()
                if aid in ids:
                    vals[aid] = a.get("href") or ""
            result.first_href = vals.get("ufirst", "")
            result.prev_href = vals.get("uprev", "")
            result.next_href = vals.get("unext", "")
            result.last_href = vals.get("ulast", "")
            result.pages = -1
            # 游标式翻页：next= 或 page=
            m = re.search(r"[?&]next=(\d+)", result.next_href)
            if m:
                result.next_page = int(m.group(1))
            else:
                m = PATTERN_NEXT_PAGE.search(result.next_href)
                if m:
                    result.next_page = int(m.group(1))
            st = nav.find(class_="searchtext")
            if st is not None:
                txt = st.get_text(" ", strip=True)
                if "thousands" in txt or "about" in txt:
                    result.result_count = "1,000+"
                else:
                    m = re.search(r"Found ([\d,]+) results", txt)
                    result.result_count = m.group(1) if m else ""
    if result.pages == 0:
        return result

    # 卡片行
    itg = soup.find(class_="itg")
    rows = []
    if itg is not None:
        rows = itg.find_all("tr") if itg.name == "table" else itg.find_all("div")
        if not rows:
            rows = [itg]
    for row in rows:
        gi = _parse_gallery_row(row)
        if gi is not None:
            result.items.append(gi)
    if result.pages == 0:
        result.pages = 1
    return result


def _parse_gallery_row(row):
    """解析一行画廊卡片，无标题（广告/表头）返回 None"""
    if row.get("id") and str(row.get("id")).startswith("ad_"):
        return None
    glname = row.find(class_="glname")
    if glname is None:
        return None
    gi = GalleryInfo()
    # gid / token
    a = glname.find("a")
    if a is None:
        a = glname.parent.find("a") if glname.parent else None
    if a is not None:
        m = PATTERN_GID_TOKEN.search(a.get("href") or "")
        if m:
            gi.gid = int(m.group(1))
            gi.token = m.group(2)
    # title（最深叶子）
    node = glname
    while node is not None and hasattr(node, "contents") and len(node.contents) > 0:
        first = node.contents[0]
        if getattr(first, "name", None) is None:
            break
        node = first
    title = node.get_text(" ", strip=True) if node is not None else ""
    if not title:
        title = glname.get_text(" ", strip=True).strip()
    if not title:
        return None
    gi.title = title
    # 标签（glname 内 tbody）
    tbody = glname.find("tbody")
    if tbody is not None:
        groups = _parse_tag_groups(tbody.find_all("tr"))
        tags = []
        for g in groups:
            for t in g.tags:
                tags.append("%s:%s" % (g.group_name, t))
        if tags:
            gi.simple_tags = tags
    # 分类
    cn = row.find(class_="cn") or row.find(class_="cs")
    gi.category = get_category(cn.get_text(" ", strip=True) if cn else "")
    # 缩略图
    glthumb = row.find(class_="glthumb")
    if glthumb is not None:
        img = None
        try:
            img = glthumb.select_one("div:nth-child(1)>img")
        except Exception:
            pass
        if img is not None:
            style = img.get("style") or ""
            m = PATTERN_THUMB_SIZE.search(style)
            if m:
                gi.thumb_height = int(m.group(1))
                gi.thumb_width = int(m.group(2))
            gi.thumb = img.get("data-src") or img.get("src") or ""
        try:
            pdiv = glthumb.select_one("div:nth-child(2)>div:nth-child(2)>div:nth-child(2)")
            if pdiv is not None:
                m = PATTERN_PAGES.search(pdiv.get_text(" ", strip=True))
                if m:
                    gi.pages = int(m.group(1))
        except Exception:
            pass
    if not gi.thumb:
        for cls in ("gl1e", "gl3t"):
            el = row.find(class_=cls)
            if el is not None and el.find("img"):
                img = el.find("img")
                style = img.get("style") or ""
                m = PATTERN_THUMB_SIZE.search(style)
                if m:
                    gi.thumb_height = int(m.group(1))
                    gi.thumb_width = int(m.group(2))
                gi.thumb = img.get("data-src") or img.get("src") or ""
                break
    # posted / favoriteSlot
    posted_el = None
    for el in row.find_all(id=re.compile(r"posted_\d+")):
        posted_el = el
        break
    if posted_el is not None:
        gi.posted = posted_el.get_text(" ", strip=True)
        gi.favorite_slot = favorite_slot_from_style(posted_el.get("style") or "")
    else:
        gi.favorite_slot = -2
    # 悬停标签
    tg = []
    for gt in row.find_all(class_="gt"):
        t = gt.get("title")
        if t:
            tg.append(t)
    for gt in row.find_all(class_="gtl"):
        t = gt.get("title")
        if t:
            tg.append(t)
    gi.tg_list = tg or None
    # 评分
    ir = row.find(class_="ir")
    gi.rating, gi.rated = _parse_rating(ir)
    # uploader / pages（compact 与 extended）
    glhide = row.find(class_="glhide")
    if glhide is not None:
        ch = glhide.find_all(recursive=False)
        if len(ch) > 0 and ch[0].find("a"):
            gi.uploader = ch[0].find("a").get_text(" ", strip=True)
        if len(ch) > 1:
            m = PATTERN_PAGES.search(ch[1].get_text(" ", strip=True))
            if m:
                gi.pages = int(m.group(1))
    else:
        gl3e = row.find(class_="gl3e")
        if gl3e is not None:
            ch = gl3e.find_all(recursive=False)
            if len(ch) > 3:
                gi.uploader = ch[3].get_text(" ", strip=True)
            if len(ch) > 4:
                m = PATTERN_PAGES.search(ch[4].get_text(" ", strip=True))
                if m:
                    gi.pages = int(m.group(1))
    if gi.pages == 0:
        gl5t = row.find(class_="gl5t")
        if gl5t is not None:
            try:
                pdiv = gl5t.select_one("div:nth-child(2)>div:nth-child(2)")
                if pdiv is not None:
                    m = PATTERN_PAGES.search(pdiv.get_text(" ", strip=True))
                    if m:
                        gi.pages = int(m.group(1))
            except Exception:
                pass
    return gi


# ================= gdata =================

def parse_gdata(data, items):
    """解析 gdata API 返回，将元数据合并进 items（按 gid 匹配）"""
    gmetadata = data.get("gmetadata") or []
    by_gid = {}
    for g in gmetadata:
        try:
            by_gid[int(g.get("gid", 0))] = g
        except (TypeError, ValueError):
            continue
    for gi in items:
        g = by_gid.get(gi.gid)
        if not g:
            continue
        title = trim(g.get("title"))
        if title:
            gi.title = title
        tj = trim(g.get("title_jpn"))
        if tj:
            gi.title_jpn = tj
        cat = g.get("category")
        if cat:
            gi.category = get_category(cat)
        up = trim(g.get("uploader"))
        if up:
            gi.uploader = up
        try:
            ts = int(g.get("posted", 0))
            if ts:
                gi.posted = format_date(ts * 1000)
        except (TypeError, ValueError):
            pass
        try:
            r = float(g.get("rating", 0))
            gi.rating = r
        except (TypeError, ValueError):
            pass
        tags = g.get("tags")
        if isinstance(tags, list) and tags:
            gi.simple_tags = [trim(t) for t in tags if t]
        fc = g.get("filecount")
        if fc:
            gi.pages = safe_int(fc)
        thumb = g.get("thumb")
        if thumb:
            gi.thumb = thumb
        gi.generate_s_lang()


# ================= 详情页 =================

PATTERN_ERROR = re.compile(r'<div class="d">\s*<p>([^<]+)</p>')
PATTERN_DETAIL = re.compile(r'var gid = (\d+);.+?var token = "([a-f0-9]+)";.+?var apiuid = ([\-?\d]+);.+?var apikey = "([a-f0-9]+)";', re.S)
PATTERN_TORRENT = re.compile(r'<a[^<>]*onclick="return popUp\(\'([^\']+)\'[^)]+\)">Torrent Download \((\d+)\)</a>')
PATTERN_ARCHIVE = re.compile(r'<a[^<>]*onclick="return popUp\(\'([^\']+)\'[^)]+\)">Archive Download</a>')
PATTERN_LENGTH = re.compile(r'<tr><td[^<>]*>Length:</td><td[^<>]*>([\d,]+) pages</td></tr>')
PATTERN_PREVIEW_PAGES = re.compile(r'<td[^>]+><a[^>]+>([\d,]+)</a></td><td[^>]+>(?:<a[^>]+>)?&gt;(?:</a>)?</td>')
PATTERN_COVER = re.compile(r'width:(\d+)px; height:(\d+)px.+?url\((.+?)\)')

OFFENSIVE_STRING = "<p>(And if you choose to ignore this warning, you lose all rights to complain about it in the future.)</p>"
PINING_STRING = "<p>This gallery is pining for the fjords.</p>"
UNAVAILABLE_STRING = "This gallery is unavailable"


class DetailError(Exception):
    def __init__(self, message, kind="error"):
        super(DetailError, self).__init__(message)
        self.kind = kind  # error / offensive / pining / unavailable


def parse_gallery_detail(body):
    """解析画廊详情页"""
    if OFFENSIVE_STRING in body:
        raise DetailError("该画廊包含不当内容，已被站点标记。", "offensive")
    if PINING_STRING in body:
        raise DetailError("该画廊已被移除（pining for the fjords）。", "pining")
    if UNAVAILABLE_STRING in body:
        raise DetailError("该画廊不可用（已删除或被屏蔽）。", "unavailable")
    m = PATTERN_ERROR.search(body)
    if m:
        raise DetailError(m.group(1).strip())
    m = PATTERN_DETAIL.search(body)
    if not m:
        raise ParseException("详情页解析失败：缺少 gid/token 变量", body)
    detail = GalleryDetail()
    detail.gid = int(m.group(1))
    detail.token = m.group(2)
    detail.api_uid = safe_int(m.group(3), -1)
    detail.api_key = m.group(4)
    try:
        soup = BeautifulSoup(body, "html.parser")
    except Exception:
        return detail

    # 封面
    gd1 = soup.find(id="gd1")
    if gd1 is not None:
        style = gd1.get("style") or ""
        cm = PATTERN_COVER.search(style)
        if cm:
            detail.thumb = cm.group(3).strip()
    # 标题
    gn = soup.find(id="gn")
    if gn is not None:
        detail.title = gn.get_text(" ", strip=True)
    gj = soup.find(id="gj")
    if gj is not None:
        detail.title_jpn = gj.get_text(" ", strip=True)
    # 分类
    gdc = soup.find(id="gdc")
    if gdc is not None:
        cn = gdc.find(class_="cn") or gdc.find(class_="cs")
        detail.category = get_category(cn.get_text(" ", strip=True) if cn else "")
    # 上传者
    gdn = soup.find(id="gdn")
    if gdn is not None:
        detail.uploader = gdn.get_text(" ", strip=True)
    # 信息表格
    gdd = soup.find(id="gdd")
    if gdd is not None:
        table = gdd.find("table")
        if table is not None:
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                key = tds[0].get_text(" ", strip=True)
                val_el = tds[1]
                value = val_el.get_text(" ", strip=True)
                if key.startswith("Posted"):
                    detail.posted = value
                elif key.startswith("Parent"):
                    a = val_el.find("a")
                    if a is not None:
                        detail.parent = a.get("href") or ""
                elif key.startswith("Visible"):
                    detail.visible = value
                elif key.startswith("Language"):
                    detail.language = value
                elif key.startswith("File Size"):
                    detail.size = value
                elif key.startswith("Length"):
                    detail.pages = safe_int(value.split(" ")[0])
                elif key.startswith("Favorited"):
                    if "Never" in value:
                        detail.favorite_count = 0
                    elif "Once" in value:
                        detail.favorite_count = 1
                    else:
                        mm = re.search(r"(\d+)", value)
                        detail.favorite_count = safe_int(mm.group(1)) if mm else 0
    # 评分
    rc = soup.find(id="rating_count")
    if rc is not None:
        detail.rating_count = safe_int(rc.get_text(" ", strip=True))
    rl = soup.find(id="rating_label")
    if rl is not None:
        txt = rl.get_text(" ", strip=True)
        if "Not Yet Rated" in txt:
            detail.rating = -1.0
        else:
            parts = txt.split(" ")
            if len(parts) > 1:
                detail.rating = safe_float(parts[1], -1.0)
            else:
                detail.rating = -1.0
    # 收藏状态
    gdf = soup.find(id="gdf")
    if gdf is not None:
        txt = gdf.get_text(" ", strip=True)
        if "Add to Favorites" not in txt:
            detail.is_favorited = True
            detail.favorite_name = txt
    # 新版/相关
    gnd = soup.find(id="gnd")
    if gnd is not None:
        vers = []
        text_nodes = []
        for child in gnd.children:
            if getattr(child, "name", None) is None:
                t = (child or "").strip()
                if t:
                    text_nodes.append(t)
        for a in gnd.find_all("a"):
            name = a.get_text(" ", strip=True)
            url_ = a.get("href") or ""
            vers.append(NewVersion(name, url_))
        detail.new_versions = vers
    # 种子 / 存档链接
    tm = PATTERN_TORRENT.search(body)
    if tm:
        detail.torrent_url = html.unescape(tm.group(1))
        detail.torrent_count = int(tm.group(2))
    am = PATTERN_ARCHIVE.search(body)
    if am:
        detail.archive_url = html.unescape(am.group(1))
    # 页数
    pm = PATTERN_LENGTH.search(body)
    if pm:
        detail.pages = safe_int(pm.group(1))
    # 标签
    taglist = soup.find(id="taglist")
    if taglist is not None:
        table = taglist.find("table")
        if table is not None:
            detail.tags = _parse_tag_groups(table.find_all("tr"))
    # 评论
    detail.comments = _parse_comments_dom(soup)
    # 预览页数
    ptt = soup.find(class_="ptt")
    if ptt is not None:
        tds = ptt.find_all("td")
        if len(tds) >= 2:
            detail.preview_pages = safe_int(tds[-2].get_text(" ", strip=True))
    if detail.preview_pages == 0:
        ppm = PATTERN_PREVIEW_PAGES.search(body)
        if ppm:
            detail.preview_pages = safe_int(ppm.group(1))
    # 预览图
    try:
        detail.preview_set = _parse_preview_set(body)
    except Exception:
        detail.preview_set = []
    return detail


def _parse_tag_groups(trs):
    """解析标签分组：每行 <td>ns:</td><td>标签们</td>"""
    groups = []
    for tr in trs:
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        ns = tds[0].get_text(" ", strip=True)
        if ns.endswith(":"):
            ns = ns[:-1]
        ns = ns.strip()
        tags = []
        for a in tds[1].find_all("a"):
            t = a.get_text(" ", strip=True)
            if "|" in t:
                t = t.split("|")[0].strip()
            if t:
                tags.append(t)
        if ns and tags:
            groups.append(GalleryTagGroup(ns, tags))
    return groups


def parse_preview_pages(body):
    m = PATTERN_PREVIEW_PAGES.search(body)
    return safe_int(m.group(1)) if m else 0


def _parse_preview_set(body):
    """解析预览图集合，返回 list[list[PreviewItem]]（按预览页分组）"""
    # 选择容器
    container_html = ""
    for cls in ("gt200", "gt100"):
        m = re.search(r'<div class="%s">(.*?)</div>\s*</div>' % cls, body, re.S)
        if not m:
            m = re.search(r'class="%s"' % cls, body)
        if m:
            break
    html_src = body
    # 尝试四种 normal 正则
    pats = [
        re.compile(r'<a href="(.+?)">[^<>]*<div[^<>]*title="Page (\d+):[^<>]*width:(\d+)[^<>]*height:(\d+)[^<>]*\((.+?)\)[^<>]*\-(\d+)px[^<>]*>'),
        re.compile(r'<a href="(.+?)">[^<>]*<div[^<>]*title="Page (\d+):[^<>]*width:(\d+)[^<>]*height:(\d+)[^<>]*\((.+?)\)[^<>]*"></div>[^<>]*</a>'),
        re.compile(r'<a href="(.+?)">[^<>]*<div>[^<>]*<div[^<>]*title="Page (\d+):[^<>]*width:(\d+)[^<>]*height:(\d+)[^<>]*\((.+?)\)[^<>]*\-(\d+)px[^<>]*>'),
        re.compile(r'<a href="(.+?)">[^<>]*<div>[^<>]*<div[^<>]*title="Page (\d+):[^<>]*width:(\d+)[^<>]*height:(\d+)[^<>]*\((.+?)\)[^<>]*"></div>[^<>]*</div>[^<>]*</a>'),
    ]
    matches = None
    for p in pats:
        ms = list(p.finditer(html_src))
        if ms:
            matches = ms
            break
    items = []
    if matches:
        for m in matches:
            item = PreviewItem()
            item.page_url = m.group(1)
            item.position = int(m.group(2)) - 1
            item.width = int(m.group(3))
            item.height = int(m.group(4))
            item.image_url = m.group(5).strip()
            if item.width <= 0 or item.height <= 0:
                continue
            key = item.image_url.split("/")[0]
            item.image_key = key
            item.offset_x = 0
            item.offset_y = 0
            items.append(item)
    if not items:
        # 老格式
        p = re.compile(r'<div class="gdtm"[^<>]*><div[^<>]*width:(\d+)[^<>]*height:(\d+)[^<>]*\((.+?)\)[^<>]*\-(\d+)px[^<>]*><a[^<>]*href="(.+?)"[^<>]*><img alt="([\d,]+)"')
        for m in p.finditer(html_src):
            item = PreviewItem()
            item.width = int(m.group(1))
            item.height = int(m.group(2))
            item.image_url = m.group(3).strip()
            item.offset_x = int(m.group(4))
            item.page_url = m.group(5)
            item.position = safe_int(m.group(6), 1) - 1
            if item.width <= 0 or item.height <= 0:
                continue
            item.image_key = item.image_url.split("/")[0]
            item.offset_y = 0
            items.append(item)
    if not items:
        # 大图预览
        p1 = re.compile(r'<a href="(.+?)">[^<>]*<div title="Page (\d+):[^<>]*\((.+?)\)[^<>]*0 0[^<>]*>')
        for m in p1.finditer(html_src):
            item = PreviewItem()
            item.page_url = m.group(1)
            item.position = int(m.group(2)) - 1
            item.image_url = m.group(3).strip()
            item.width = 0
            item.height = 0
            item.image_key = item.image_url.split("/")[0]
            items.append(item)
    if not items:
        p2 = re.compile(r'<div class="gdtl".+?<a href="(.+?)"><img alt="([\d,]+)".+?src="(.+?)"', re.S)
        for m in p2.finditer(html_src):
            item = PreviewItem()
            item.page_url = m.group(1)
            item.position = safe_int(m.group(2), 1) - 1
            item.image_url = m.group(3).strip()
            item.width = 0
            item.height = 0
            item.image_key = item.image_url.split("/")[0]
            items.append(item)
    # 按预览页分组（每页 40 个，最后不齐）
    pages = []
    per = 40
    for i in range(0, len(items), per):
        pages.append(items[i:i + per])
    return pages


def parse_preview_set(body):
    """独立预览页解析：返回 (pages_list, preview_pages)"""
    return _parse_preview_set(body), parse_preview_pages(body)

# ================= 评论解析 =================

def _parse_comments_dom(soup):
    """从详情页 DOM 解析评论"""
    cdiv = soup.find(id="cdiv")
    if cdiv is None:
        return None
    comments = []
    has_more = False
    # hasMore 判断
    chd = soup.find(id="chd")
    if chd is not None and "click to show all" in chd.get_text(" ", strip=True):
        has_more = True
    for c1 in cdiv.find_all(class_="c1"):
        c = GalleryComment()
        # id：前一个兄弟 <a name="c123">
        prev = c1.find_previous_sibling()
        if prev is not None and prev.name == "a":
            nm = prev.get("name") or ""
            if nm.startswith("c"):
                c.id = safe_int(nm[1:])
        # 投票/编辑
        c4 = c1.find(class_="c4")
        if c4 is not None:
            for ch in c4.find_all(recursive=False):
                t = ch.get_text(" ", strip=True)
                if t == "Vote+":
                    c.vote_up_able = True
                    c.vote_up_ed = bool(ch.get("style"))
                elif t == "Vote-":
                    c.vote_down_able = True
                    c.vote_down_ed = bool(ch.get("style"))
                elif t == "Edit":
                    c.editable = True
        c7 = c1.find(class_="c7")
        if c7 is not None:
            c.vote_state = c7.get_text(" ", strip=True)
        c5 = c1.find(class_="c5")
        if c5 is not None:
            first = c5.find(recursive=False)
            c.score = safe_int(first.get_text(" ", strip=True) if first is not None else "")
        c3 = c1.find(class_="c3")
        if c3 is not None:
            own = "".join(str(x) for x in c3.contents if getattr(x, "name", None) is None)
            own = own.replace("Posted on ", "").replace(" by:", "").strip()
            c.time = _parse_comment_time(own)
            a = c3.find("a")
            if a is not None:
                c.user = a.get_text(" ", strip=True)
            elif c4 is not None:
                c.user = c4.get_text(" ", strip=True)
        c6 = c1.find(class_="c6")
        if c6 is not None:
            c.comment = str(c6)
        c8 = c1.find(class_="c8")
        if c8 is not None and c8.find(recursive=False) is not None:
            c.last_edited = c.time
        comments.append(c)
    return GalleryCommentList(comments, has_more)


def _parse_comment_time(text):
    """解析 '07 March 2016, 08:12' (UTC) 为 epoch 毫秒"""
    try:
        dt = datetime.strptime(text.strip(), "%d %B %Y, %H:%M")
        dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def parse_comments(body):
    """发表/编辑评论后的响应页解析评论"""
    try:
        soup = BeautifulSoup(body, "html.parser")
        r = _parse_comments_dom(soup)
        return r if r is not None else GalleryCommentList([], False)
    except Exception:
        return GalleryCommentList([], False)


# ================= 图片页解析 =================

def parse_gallery_page(body):
    """解析图片页 HTML"""
    from .session import ParseException as _PE
    im = re.search(r'<img[^>]*src="([^"]+)" style', body)
    sm = re.search(r'var showkey="([0-9a-z]+)";', body)
    if not im or not sm:
        raise _PE("图片页解析失败")
    result = {"image_url": im.group(1).strip(), "show_key": sm.group(1)}
    nm = re.search(r"onclick=\"return nl\('([^\)]+)'\)", body)
    if nm:
        result["skip_hath_key"] = nm.group(1)
    fm = re.search(r'<a href="([^"]+)fullimg([^"]+)">', body)
    if fm:
        result["origin_image_url"] = fm.group(1) + "fullimg" + fm.group(2)
    return result


def parse_gallery_page_api(d):
    """解析 showpage API 响应"""
    from .session import ParseException as _PE
    if "error" in d:
        raise _PE(d["error"])
    i3 = d.get("i3") or ""
    im = re.search(r'<img[^>]*src="([^"]+)" style', i3)
    if not im:
        raise _PE("showpage 响应缺少图片地址")
    result = {"image_url": im.group(1).strip()}
    i6 = d.get("i6") or ""
    nm = re.search(r"onclick=\"return nl\('([^\)]+)'\)", i6)
    if nm:
        result["skip_hath_key"] = nm.group(1)
    om = re.search(r"<a href=\"#\" onclick=\"prompt\('Copy the URL below.', '([^\"']+)'\)", i6)
    if om:
        result["other_image_url"] = om.group(1)
    src = d.get("i7") if d.get("i7") is not None else i6
    fm = re.search(r'<a href="([^"]+)fullimg([^"]+)">', src)
    if fm:
        result["origin_image_url"] = fm.group(1) + "fullimg" + fm.group(2)
    return result


# ================= 种子 =================

def parse_torrents(body):
    out = []
    for form in re.findall(r"<form\b[^>]*>.*?</form>", body, re.S):
        t = TorrentInfo()
        m = re.search(r'<td colspan="5">\s*&nbsp;\s*<a href="([^"]+)"[^<]*>([^<]+)</a></td>', form, re.S)
        if m:
            url_ = m.group(1)
            url_ = re.sub(r"\?p=", "", url_) if "?p=" in url_ else url_
            t.hash = url_.split("=")[-1] if "=" in url_ else url_
            t.name = html.unescape(m.group(2)).strip()
        pm = re.search(r'<span[^>]*>\s*Posted:\s*</span>\s*<span>([^<]+)</span>', form, re.S)
        if pm:
            t.added = pm.group(1).strip()
        if t.name:
            out.append(t)
    return out


# ================= 收藏 =================

class FavoritesResult(object):
    __slots__ = ("cat_names", "cat_counts", "pages", "next_page", "fav_order", "items", "result_count")

    def __init__(self):
        self.cat_names = ["", "", "", "", "", "", "", "", "", ""]
        self.cat_counts = [0] * 10
        self.pages = 0
        self.next_page = None
        self.fav_order = "p"
        self.items = []
        self.result_count = ""


def parse_favorites(body):
    from .session import EhException as _E
    if "This page requires you to log on.</p>" in body:
        raise _E("收藏功能需要登录（请在设置中登录账户）。")
    result = FavoritesResult()
    try:
        soup = BeautifulSoup(body, "html.parser")
    except Exception:
        return result
    ido = soup.find(class_="ido")
    if ido is not None:
        fps = ido.find_all(class_="fp")
        for i in range(min(10, len(fps))):
            fp = fps[i]
            ch = fp.find_all(recursive=False)
            if len(ch) > 2:
                result.cat_counts[i] = safe_int(ch[0].get_text(" ", strip=True))
                result.cat_names[i] = ch[2].get_text(" ", strip=True)
    nav = soup.find(class_="searchnav")
    if nav is not None:
        sel = nav.find("select")
        if sel is not None:
            opt = sel.find("option", selected=True) or sel.find("option", attrs={"selected": "selected"})
            if opt is None:
                for o in sel.find_all("option"):
                    if o.has_attr("selected"):
                        opt = o
                        break
            if opt is not None:
                result.fav_order = opt.get("value", "p") or "p"
    # 画廊列表
    lst = parse_gallery_list(body, C.MODE_NORMAL)
    result.items = lst.items
    result.pages = lst.pages
    result.next_page = lst.next_page
    result.result_count = lst.result_count
    return result


# ================= 存档 =================

def parse_archive_options(body):
    """解析存档方案：返回 (or 参数, [(res, name), ...])"""
    or_param = ""
    m = re.search(r'<form id="hathdl_form" action="[^"]*?or=([^="]*?)" method="post">', body)
    if m:
        or_param = m.group(1)
    pairs = []
    for m in re.finditer(r'<a href="[^"]*" onclick="return do_hathdl\(\'([0-9]+|org)\'\)">([^<]+)</a>', body):
        pairs.append((m.group(1), m.group(2).strip()))
    return or_param, pairs


def parse_archiver(body):
    """解析存档确认页：GP 余额 + 两个方案的 URL/花费/大小"""
    data = ArchiverData()
    m = re.search(r"funds.{0,80}?(\d[\d,]*)", body, re.I)
    if m:
        data.ads = m.group(1)
    # 表单
    forms = re.findall(r'<form[^>]*action="([^"]*or=[^"]*)"[^>]*method="post"[^>]*>', body)
    if forms:
        data.or_ = forms[0]
    # do_hathdl 链接
    for m in re.finditer(r"onclick=\"return do_hathdl\('([0-9]+|org)'\)\"[^>]*>([^<]+)<", body):
        data.res = m.group(1)
    return data


def parse_archiver_download_url(body):
    m = re.search(r'href="(.*)">Click Here To Start Downloading', body)
    return m.group(1) if m else None


# ================= 登录 =================

def parse_sign_in(body):
    from .session import EhException as _E
    m = re.search(r"<p>You are now logged in as: (.+?)<", body)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?:<h4>The error returned was:</h4>\s*<p>(.+?)</p>)|(?:<span class=\"postcolor\">(.+?)</span>)", body, re.S)
    if m:
        err = m.group(1) or m.group(2)
        raise _E("登录失败：" + err.strip())
    raise ParseException("登录响应解析失败", body)


# ================= 首页配额 =================

PATTERN_IMAGE_LIMIT_NEW = re.compile(
    r"<p>You are currently at <strong>(.+?)</strong> towards your account limit of <strong>(.+?)</strong>.</p>\s*<p>You can reset your image quota by spending <strong>(.+?)</strong> GP.</p>", re.S)
PATTERN_IMAGE_LIMIT = re.compile(
    r"<p>You are currently at <strong>(\d+)</strong> towards a limit of <strong>(\d+)</strong>.</p>.+?<p>Reset Cost: <strong>(\d+)</strong> GP</p>", re.S)


def parse_home_limit(body):
    """解析首页图片配额，返回 dict 或 None"""
    m = PATTERN_IMAGE_LIMIT_NEW.search(body)
    if m:
        return {"used": safe_int(m.group(1)), "total": safe_int(m.group(2)),
                "reset_cost": safe_int(m.group(3))}
    m = PATTERN_IMAGE_LIMIT.search(body)
    if m:
        return {"used": safe_int(m.group(1)), "total": safe_int(m.group(2)),
                "reset_cost": safe_int(m.group(3))}
    return None


def parse_event_pane(body):
    """从 news.php 提取事件面板 HTML"""
    try:
        soup = BeautifulSoup(body, "html.parser")
        ep = soup.find(id="eventpane")
        return str(ep) if ep is not None else None
    except Exception:
        return None


# ================= 排行榜 =================

TOP_LIST_TYPES = ["GALLERY", "UPLOADER", "TAGGING", "HENTAI_HOME",
                  "EH_TRACKER", "CLEANUP", "RATING_AND_REVIEWING"]


class TopListInfo(object):
    __slots__ = ("title", "list_type", "all_time", "past_year", "past_month", "yesterday")

    def __init__(self, title="", list_type=""):
        self.title = title
        self.list_type = list_type
        self.all_time = []
        self.past_year = []
        self.past_month = []
        self.yesterday = []


def parse_top_list(body):
    """解析排行榜，返回 EhTopListDetail"""
    detail = EhTopListDetail()
    if "pining for the fjords" in body or "unavailable" in body:
        return detail
    m = PATTERN_ERROR.search(body)
    if m:
        detail.body = m.group(1).strip()
        return detail
    try:
        soup = BeautifulSoup(body, "html.parser")
        ido = soup.find(class_="ido")
        if ido is None:
            return detail
        children = [c for c in ido.children if getattr(c, "name", None) is not None]
        if not children:
            return detail
        detail.title = children[0].get_text(" ", strip=True)
        groups = []
        for i, idx in enumerate(range(1, 14, 2)):
            if idx < len(children):
                groups.append((TOP_LIST_TYPES[i] if i < len(TOP_LIST_TYPES) else "", children[idx]))
        for gtype, node in groups:
            info = TopListInfo(node.get_text(" ", strip=True)[:60], gtype)
            sub = [c for c in node.children if getattr(c, "name", None) is not None]
            periods = [("all_time", 1), ("past_year", 2), ("past_month", 3), ("yesterday", 4)]
            for attr, pi in periods:
                if pi < len(sub):
                    try:
                        tun_list = sub[pi].find_all(class_="tun")
                        items = []
                        for tun in tun_list[:10]:
                            c0 = tun.find(recursive=False)
                            if c0 is None:
                                continue
                            a = c0 if c0.name == "a" else c0.find("a")
                            items.append({"value": c0.get_text(" ", strip=True),
                                          "href": (a.get("href") if a else "") or ""})
                        setattr(info, attr, items)
                    except Exception:
                        pass
            detail.__setattr__("_g%d" % len(groups), info)
        detail.body = "ok"
        detail._groups = groups  # 兼容
    except Exception:
        pass
    return detail


# ================= 我的标签 =================

def parse_my_tag_list(body):
    """解析 mytags 页，返回 list[dict]"""
    from .session import EhException as _E
    m = PATTERN_ERROR.search(body)
    if m:
        raise _E(m.group(1).strip())
    out = []
    try:
        soup = BeautifulSoup(body, "html.parser")
        outer = soup.find(id="usertags_outer")
        if outer is None:
            return out
        children = [c for c in outer.children if getattr(c, "name", None) is not None]
        for node in children[1:]:
            tag_id = (node.get("id") or "")
            if tag_id.startswith("tagrow"):
                tid = tag_id[len("tagrow"):]
            else:
                tid = tag_id
            if not tid.isdigit():
                continue
            name = ""
            pv = soup.find(id="tagpreview" + tid)
            if pv is not None:
                name = pv.get("title") or ""
            watched = False
            tw = soup.find(id="tagwatch" + tid)
            if tw is not None:
                watched = (tw.get("checked") == "checked")
            hidden = False
            th = soup.find(id="taghide" + tid)
            if th is not None:
                hidden = (th.get("checked") == "checked")
            weight = 0
            tw2 = soup.find(id="tagweight" + tid)
            if tw2 is not None:
                weight = safe_int(tw2.get("value"))
            if name:
                out.append({"id": int(tid), "name": name, "watched": watched,
                            "hidden": hidden, "weight": weight})
    except Exception:
        pass
    return out


# ================= 个人资料 =================

def parse_profile(body):
    """解析论坛个人页，返回 (display_name, avatar_url)"""
    try:
        soup = BeautifulSoup(body, "html.parser")
        pn = soup.find(id="profilename")
        name = ""
        if pn is not None:
            first = pn.find(recursive=False)
            if first is not None:
                name = first.get_text(" ", strip=True)
            else:
                name = pn.get_text(" ", strip=True)
        avatar = ""
        if pn is not None:
            sib = pn.find_next_sibling()
            if sib is not None:
                sib2 = sib.find_next_sibling()
                if sib2 is not None and sib2.find(recursive=False) is not None:
                    img = sib2.find(recursive=False).find("img")
                    if img is not None:
                        avatar = img.get("src") or ""
        if avatar and not avatar.startswith("http"):
            avatar = "https://forums.e-hentai.org/" + avatar.lstrip("/")
        return name, avatar
    except Exception:
        return "", ""


def parse_forums_profile_url(body):
    """从论坛首页提取个人主页 URL"""
    try:
        soup = BeautifulSoup(body, "html.parser")
        ul = soup.find(id="userlinks")
        if ul is None:
            return None
        child = ul.find(recursive=False)
        if child is None:
            child = ul.find("a")
        if child is not None:
            a = child.find("a") if child.find("a") else child
            return a.get("href") if a.name == "a" else None
        a = ul.find("a")
        return a.get("href") if a else None
    except Exception:
        return None


# ================= 排行榜（非画廊类：上传者/标签/H@H 等） =================

def parse_top_list_names(body):
    """解析上传者/标签/服务器类排行榜：返回 list[{rank, score, name, href}]"""
    out = []
    try:
        soup = BeautifulSoup(body, "html.parser")
        itg = soup.find(class_="itg")
        if itg is None:
            return out
        rows = itg.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            texts = [c.get_text(" ", strip=True) for c in cells]
            if not texts:
                continue
            # 两列一组：#rank score name
            for i in range(0, len(texts) - 2, 3):
                if not texts[i].startswith("#"):
                    continue
                a = cells[i + 2].find("a") if i + 2 < len(cells) else None
                out.append({"rank": texts[i].lstrip("#"),
                            "score": texts[i + 1],
                            "name": texts[i + 2],
                            "href": (a.get("href") or "") if a else ""})
            # 兜底：单列结构
            if not out:
                for i in range(0, len(texts) - 2):
                    if texts[i].startswith("#"):
                        a = cells[i + 2].find("a") if i + 2 < len(cells) else None
                        out.append({"rank": texts[i].lstrip("#"),
                                    "score": texts[i + 1],
                                    "name": texts[i + 2],
                                    "href": (a.get("href") or "") if a else ""})
    except Exception:
        pass
    return out
