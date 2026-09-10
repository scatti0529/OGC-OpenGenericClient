# -*- coding: utf-8 -*-
"""数据模型（移植自 Android 版 client/data 包）"""
import re

from . import constants as C


class GalleryInfo(object):
    """画廊信息（列表项 / 详情基础字段）"""

    __slots__ = ("gid", "token", "title", "title_jpn", "thumb", "category", "posted",
                 "uploader", "rating", "rated", "simple_tags", "pages", "thumb_width",
                 "thumb_height", "favorite_slot", "favorite_name", "simple_language",
                 "tg_list", "is_favorited", "state", "label", "time", "finished",
                 "total", "downloaded", "legacy", "archive_uri")

    def __init__(self):
        self.gid = 0
        self.token = ""
        self.title = ""
        self.title_jpn = ""
        self.thumb = ""
        self.category = C.UNKNOWN_CATEGORY
        self.posted = ""
        self.uploader = ""
        self.rating = 0.0
        self.rated = False
        self.simple_tags = None       # list[str] 或 None
        self.pages = 0
        self.thumb_width = 0
        self.thumb_height = 0
        self.favorite_slot = -2       # -2 未知，-1 未收藏，0-9 收藏夹
        self.favorite_name = ""
        self.simple_language = None
        self.tg_list = None
        self.is_favorited = False
        self.state = 0
        self.label = None
        self.time = 0
        self.finished = 0
        self.total = 0
        self.downloaded = 0
        self.legacy = 0
        self.archive_uri = None

    # ---------- 序列化 ----------
    def to_dict(self):
        d = {"gid": self.gid, "token": self.token, "title": self.title,
             "titleJpn": self.title_jpn, "thumb": self.thumb, "category": self.category,
             "posted": self.posted, "uploader": self.uploader, "rating": self.rating,
             "rated": self.rated, "pages": self.pages, "simpleLanguage": self.simple_language,
             "favoriteSlot": self.favorite_slot, "favoriteName": self.favorite_name,
             "thumbWidth": self.thumb_width, "thumbHeight": self.thumb_height}
        if self.simple_tags is not None:
            d["simpleTags"] = list(self.simple_tags)
        if self.tg_list is not None:
            d["tgList"] = list(self.tg_list)
        return d

    @classmethod
    def from_dict(cls, d):
        g = cls()
        g.gid = int(d.get("gid", 0) or 0)
        g.token = d.get("token") or ""
        g.title = d.get("title") or ""
        g.title_jpn = d.get("titleJpn") or ""
        g.thumb = d.get("thumb") or ""
        g.category = int(d.get("category", C.UNKNOWN_CATEGORY) or C.UNKNOWN_CATEGORY)
        g.posted = d.get("posted") or ""
        g.uploader = d.get("uploader") or ""
        try:
            g.rating = float(d.get("rating", 0) or 0)
        except (TypeError, ValueError):
            g.rating = 0.0
        g.rated = bool(d.get("rated", False))
        g.pages = int(d.get("pages", 0) or 0)
        g.simple_language = d.get("simpleLanguage")
        st = d.get("simpleTags")
        g.simple_tags = list(st) if st else None
        tg = d.get("tgList")
        g.tg_list = list(tg) if tg else None
        g.favorite_slot = int(d.get("favoriteSlot", -2) if d.get("favoriteSlot") is not None else -2)
        g.favorite_name = d.get("favoriteName") or ""
        g.thumb_width = int(d.get("thumbWidth", 0) or 0)
        g.thumb_height = int(d.get("thumbHeight", 0) or 0)
        return g

    # ---------- 便捷 ----------
    def suitable_title(self, show_jpn=False):
        """按设置返回合适标题"""
        if show_jpn:
            return self.title_jpn or self.title
        return self.title or self.title_jpn

    def generate_s_lang(self):
        """从标签或标题推断语言"""
        if self.simple_tags:
            for tag in self.simple_tags:
                for i, lt in enumerate(C.LANG_TAGS):
                    if lt == tag:
                        self.simple_language = C.LANG_NAMES[i]
                        return
        if self.title:
            for pattern, name in C.LANG_TITLE_PATTERNS:
                try:
                    if re.search(pattern, self.title, re.IGNORECASE):
                        self.simple_language = name
                        return
                except re.error:
                    continue
        self.simple_language = None

    def __repr__(self):
        return "<GalleryInfo gid=%s %r>" % (self.gid, (self.title or "")[:40])


class GalleryTagGroup(object):
    """标签分组（namespace + 标签列表）"""

    __slots__ = ("group_name", "tags")

    def __init__(self, group_name="", tags=None):
        self.group_name = group_name
        self.tags = list(tags) if tags else []

    def to_dict(self):
        return {"groupName": self.group_name, "tags": list(self.tags)}


class GalleryComment(object):
    """画廊评论"""

    __slots__ = ("id", "score", "editable", "vote_up_able", "vote_up_ed", "vote_down_able",
                 "vote_down_ed", "vote_state", "time", "user", "comment", "last_edited")

    def __init__(self):
        self.id = 0
        self.score = 0
        self.editable = False
        self.vote_up_able = True
        self.vote_up_ed = False
        self.vote_down_able = True
        self.vote_down_ed = False
        self.vote_state = ""
        self.time = 0
        self.user = ""
        self.comment = ""
        self.last_edited = 0


class GalleryCommentList(object):
    __slots__ = ("comments", "has_more")

    def __init__(self, comments=None, has_more=False):
        self.comments = list(comments) if comments else []
        self.has_more = has_more


class TorrentInfo(object):
    """种子信息"""

    __slots__ = ("hash", "added", "name", "tsize", "fsize", "seeders", "leechers", "downloads", "snatches")

    def __init__(self):
        self.hash = ""
        self.added = ""
        self.name = ""
        self.tsize = ""
        self.fsize = ""
        self.seeders = 0
        self.leechers = 0
        self.downloads = 0
        self.snatches = 0


class NewVersion(object):
    """新版/相关画廊（重制版）"""

    __slots__ = ("version_name", "version_url")

    def __init__(self, name="", url=""):
        self.version_name = name
        self.version_url = url


class PreviewItem(object):
    """预览图（详情页缩略图 / 阅读器页面索引）"""

    __slots__ = ("image_key", "image_url", "page_url", "position", "offset_x", "offset_y",
                 "clip_width", "clip_height", "width", "height")

    def __init__(self):
        self.image_key = ""
        self.image_url = ""
        self.page_url = ""
        self.position = 0
        self.offset_x = None
        self.offset_y = None
        self.clip_width = None
        self.clip_height = None
        self.width = 0
        self.height = 0


class GalleryDetail(GalleryInfo):
    """画廊详情"""

    __slots__ = ("api_uid", "api_key", "torrent_count", "torrent_url", "archive_url",
                 "parent", "visible", "language", "size", "favorite_count", "is_favorited",
                 "rating_count", "tags", "comments", "preview_pages", "preview_set",
                 "new_versions", "body")

    def __init__(self):
        super(GalleryDetail, self).__init__()
        self.api_uid = -1
        self.api_key = ""
        self.torrent_count = 0
        self.torrent_url = ""
        self.archive_url = ""
        self.parent = ""
        self.visible = ""
        self.language = ""
        self.size = ""
        self.favorite_count = 0
        self.rating_count = 0
        self.tags = []                # list[GalleryTagGroup]
        self.comments = None          # GalleryCommentList
        self.preview_pages = 0
        self.preview_set = []         # list[list[PreviewItem]] 每页一组
        self.new_versions = []        # list[NewVersion]
        self.body = ""

    def get_new_gallery_detail(self, index):
        """返回重制版对应的 gid/token（用于跳转）"""
        if index < 0 or index >= len(self.new_versions):
            return None
        url = self.new_versions[index].version_url
        parts = [p for p in url.split("/") if p]
        if len(parts) < 2:
            return None
        try:
            gid = int(parts[-2])
        except (ValueError, IndexError):
            return None
        return {"gid": gid, "token": parts[-1]}


class EhTopListDetail(object):
    """排行榜页"""

    __slots__ = ("title", "body", "url")

    def __init__(self):
        self.title = ""
        self.body = ""
        self.url = ""


class HomeDetail(object):
    """首页（home.php）"""

    __slots__ = ("limit_html", "featured", "popular", "body")

    def __init__(self):
        self.limit_html = ""
        self.featured = None
        self.popular = None
        self.body = ""


class EhNewsDetail(object):
    __slots__ = ("html",)

    def __init__(self, html=""):
        self.html = html


class ArchiverData(object):
    """存档下载信息"""

    __slots__ = ("or_", "res", "ads", "url", "error")

    def __init__(self):
        self.or_ = ""     # 表单 or 参数
        self.res = ""     # 表单 res 参数
        self.ads = ""     # 广告链接
        self.url = ""     # 下载页
        self.error = ""


class UserTag(object):
    """关注标签"""

    __slots__ = ("name", "tag", "index")

    def __init__(self, name="", tag="", index=0):
        self.name = name
        self.tag = tag
        self.index = index

    def delete_param(self):
        return "user_tag=%d&tag=%s" % (self.index, self.tag)


class TagPushParam(object):
    """标签推送参数"""

    __slots__ = ("index", "tag", "old_name", "new_name")

    def __init__(self, index=0, tag="", old_name="", new_name=""):
        self.index = index
        self.tag = tag
        self.old_name = old_name
        self.new_name = new_name

    def add_tag_param(self):
        return "user_tag=%d&tag=%s&old_name=%s&new_name=%s" % (
            self.index, self.tag, self.old_name, self.new_name)
