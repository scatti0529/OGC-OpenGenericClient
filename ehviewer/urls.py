# -*- coding: utf-8 -*-
"""URL 构造（移植自 Android 版 EhUrl + ListUrlBuilder）"""
import re
from urllib.parse import urlparse, quote, urlencode

from . import constants as C
from .config import CFG

DOMAIN_EX = "exhentai.org"
DOMAIN_E = "e-hentai.org"
DOMAIN_LOFI = "lofi.e-hentai.org"

REFERER_EX = "https://" + DOMAIN_EX
REFERER_E = "https://" + DOMAIN_E
HOST_EX = REFERER_EX + "/"
HOST_E = REFERER_E + "/"

API_SIGN_IN = "https://forums.e-hentai.org/index.php?act=Login&CODE=01"
URL_SIGN_IN = "https://forums.e-hentai.org/index.php?act=Login"
URL_REGISTER = "https://forums.e-hentai.org/index.php?act=Reg&CODE=00"
URL_NEWS_E = HOST_E + "news.php"
API_E = HOST_E + "api.php"
API_EX = HOST_EX + "api.php"
HOME_E = HOST_E + "home.php"
HOME_EX = HOST_EX + "home.php"
URL_POPULAR_E = "https://e-hentai.org/popular"
URL_POPULAR_EX = "https://exhentai.org/popular"
URL_TOP_LIST_E = HOST_E + "toplist.php"
URL_TOP_LIST_EX = HOST_EX + "toplist.php"
URL_IMAGE_SEARCH_E = "https://upld.e-hentai.org/image_lookup.php"
URL_IMAGE_SEARCH_EX = "https://upld.exhentai.org/upld/image_lookup.php"
URL_FAVORITES_E = HOST_E + "favorites.php"
URL_FAVORITES_EX = HOST_EX + "favorites.php"
DOMAIN_FORUMS = "forums.e-hentai.org"
URL_FORUMS = "https://forums.e-hentai.org/"
URL_UCONFIG_E = HOST_E + "uconfig.php"
URL_UCONFIG_EX = HOST_EX + "uconfig.php"
URL_MY_TAGS_E = HOST_E + "mytags"
URL_MY_TAGS_EX = HOST_EX + "mytags"
URL_WATCHED_E = HOST_E + "watched"
URL_WATCHED_EX = HOST_EX + "watched"
URL_PREFIX_THUMB = "https://ehgt.org/"

_PATTERN_SEEK_DATE = re.compile(r"seek=(\d+)-(\d+)-(\d+)")
_PATTERN_JUMP_NODE = re.compile(r"jump=(\d)[ymwd]")


def get_site():
    # 已取消里站（exhentai.org），仅保留表站（e-hentai.org）。
    # 固定返回 SITE_E，所有 URL 构造（host/api/referer/home/favorites/toplist/imagesearch）
    # 都会走 e-hentai.org，忽略配置里的 site 值。
    return C.SITE_E

def get_host():
    return HOST_EX if get_site() == C.SITE_EX else HOST_E

def get_api_url():
    return API_EX if get_site() == C.SITE_EX else API_E

def get_referer():
    return REFERER_EX if get_site() == C.SITE_EX else REFERER_E

def get_origin():
    return get_referer()

def get_home_url():
    return HOME_EX if get_site() == C.SITE_EX else HOME_E

def get_favorites_url():
    return URL_FAVORITES_EX if get_site() == C.SITE_EX else URL_FAVORITES_E

def get_my_tags_url():
    return URL_MY_TAGS_EX if get_site() == C.SITE_EX else URL_MY_TAGS_E

def get_watched_url():
    return URL_WATCHED_EX if get_site() == C.SITE_EX else URL_WATCHED_E

def get_uconfig_url():
    return URL_UCONFIG_EX if get_site() == C.SITE_EX else URL_UCONFIG_E

def get_popular_url():
    return URL_POPULAR_EX if get_site() == C.SITE_EX else URL_POPULAR_E

def get_image_search_url():
    return URL_IMAGE_SEARCH_EX if get_site() == C.SITE_EX else URL_IMAGE_SEARCH_E

def get_top_list_url():
    return URL_TOP_LIST_E

def get_news_url():
    return URL_NEWS_E

def get_gallery_detail_url(gid, token, index=0, all_comment=False):
    """画廊详情页 URL：/g/{gid}/{token}/?p={index}&hc=1"""
    url = get_host() + "g/%s/%s/" % (gid, token)
    params = []
    if index:
        params.append(("p", index))
    if all_comment:
        params.append(("hc", 1))
    if params:
        url += "?" + urlencode(params)
    return url

def get_page_url(gid, index, p_token):
    """单页图片页 URL：/s/{p_token}/{gid}-{index+1}"""
    return get_host() + "s/%s/%s-%d" % (p_token, gid, index + 1)

def get_add_favorites_url(gid, token):
    return get_host() + "gallerypopups.php?gid=%s&t=%s&act=addfav" % (gid, token)

def get_download_archive_url(gid, token, or_=""):
    if not or_:
        return get_host() + "archiver.php?gid=%s&token=%s" % (gid, token)
    return get_host() + "archiver.php?gid=%s&token=%s&or=%s" % (gid, token, or_)

def get_tag_definition_url(tag):
    return "https://ehwiki.org/wiki/" + tag.replace(" ", "_")


def get_fixed_preview_thumb_url(origin_url):
    """将缩略图 URL 修正为 ehgt.org 前缀的稳定地址"""
    try:
        parsed = urlparse(origin_url)
        segs = [s for s in parsed.path.split("/") if s]
        if len(segs) < 3:
            return origin_url
        last = segs[-1]
        second = segs[-2]
        third = segs[-3]
        if last.startswith(third) and last.startswith(second, len(third)):
            return URL_PREFIX_THUMB + third + "/" + second + "/" + last
    except Exception:
        pass
    return origin_url


class ListUrlBuilder(object):
    """画廊列表 URL 构造器（移植自 ListUrlBuilder）"""

    def __init__(self, mode=C.MODE_NORMAL):
        self.mode = mode
        self.page_index = 0
        self.category = C.NONE
        self.keyword = None
        self.follow = None
        self.advance_search = -1
        self.min_rating = -1
        self.page_from = -1
        self.page_to = -1

    def reset(self):
        self.mode = C.MODE_NORMAL
        self.page_index = 0
        self.category = C.NONE
        self.keyword = None
        self.advance_search = -1
        self.min_rating = -1
        self.page_from = -1
        self.page_to = -1

    def clone(self):
        import copy
        return copy.copy(self)

    def build(self):
        m = self.mode
        if m in (C.MODE_NORMAL, C.MODE_SUBSCRIPTION):
            url = get_watched_url() if m == C.MODE_SUBSCRIPTION else get_host()
            params = []
            if self.category != C.NONE:
                params.append(("f_cats", (~self.category) & C.ALL_CATEGORY))
            if self.keyword:
                kw = self.keyword.strip()
                if kw:
                    params.append(("f_search", kw))
            if self.page_index != 0:
                params.append(("page", self.page_index))
            if self.advance_search != -1:
                params.append(("advsearch", "1"))
                adv = self.advance_search
                if adv & C.SNAME: params.append(("f_sname", "on"))
                if adv & C.STAGS: params.append(("f_stags", "on"))
                if adv & C.SDESC: params.append(("f_sdesc", "on"))
                if adv & C.STORR: params.append(("f_storr", "on"))
                if adv & C.STO:   params.append(("f_sto", "on"))
                if adv & C.SDT1:  params.append(("f_sdt1", "on"))
                if adv & C.SDT2:  params.append(("f_sdt2", "on"))
                if adv & C.SH:    params.append(("f_sh", "on"))
                if adv & C.SFL:   params.append(("f_sfl", "on"))
                if adv & C.SFU:   params.append(("f_sfu", "on"))
                if adv & C.SFT:   params.append(("f_sft", "on"))
                if self.min_rating != -1:
                    params.append(("f_sr", "on"))
                    params.append(("f_srdd", self.min_rating))
                if self.page_from != -1 or self.page_to != -1:
                    params.append(("f_sp", "on"))
                    params.append(("f_spf", str(self.page_from) if self.page_from != -1 else ""))
                    params.append(("f_spt", str(self.page_to) if self.page_to != -1 else ""))
            if params:
                return url + "?" + urlencode(params)
            return url
        if m == C.MODE_UPLOADER:
            return get_host() + "uploader/" + quote(self.keyword or "") + (("/%d" % self.page_index) if self.page_index else "")
        if m == C.MODE_TAG:
            return get_host() + "tag/" + quote(self.keyword or "") + (("/%d" % self.page_index) if self.page_index else "")
        if m == C.MODE_FILTER:
            parts = []
            if self.page_index:
                parts.append("page=%d" % self.page_index)
            parts.append("f_search=" + quote(self.keyword or ""))
            return get_host() + "?" + "&".join(parts)
        if m == C.MODE_WHATS_HOT:
            return get_popular_url()
        if m == C.MODE_IMAGE_SEARCH:
            return get_image_search_url()
        if m == C.MODE_TOP_LIST:
            sb = get_top_list_url() + "?"
            sb += self.follow or ""
            if self.page_index == 0:
                return sb
            if 0 < self.page_index < 200:
                return sb + "&p=%d" % self.page_index
            return "127.0.0.1:8888"
        return get_host()
