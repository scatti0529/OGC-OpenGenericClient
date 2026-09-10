# -*- coding: utf-8 -*-
"""拷贝漫画数据模型（移植自 OGC-EasyCopy）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class SitePageType(Enum):
    HOME = "home"
    DISCOVER = "discover"
    RANK = "rank"
    DETAIL = "detail"
    READER = "reader"
    PROFILE = "profile"
    UNKNOWN = "unknown"


@dataclass
class LinkAction:
    label: str = ""
    href: str = ""
    active: bool = False

    @property
    def is_navigable(self) -> bool:
        return bool(self.href)


@dataclass
class HeroBannerData:
    title: str = ""
    subtitle: str = ""
    image_url: str = ""
    href: str = ""


@dataclass
class ComicCardData:
    title: str = ""
    cover_url: str = ""
    href: str = ""
    subtitle: str = ""
    secondary_text: str = ""
    badge: str = ""


@dataclass
class PagerData:
    current_label: str = ""
    total_label: str = ""
    prev_href: str = ""
    next_href: str = ""


@dataclass
class FilterOptionData:
    label: str = ""
    value: str = ""
    active: bool = False


@dataclass
class FilterGroupData:
    title: str = ""
    key: str = ""
    options: List[FilterOptionData] = field(default_factory=list)


@dataclass
class ComicSectionData:
    title: str = ""
    href: str = ""
    items: List[ComicCardData] = field(default_factory=list)


@dataclass
class HomePageData:
    title: str = "首页"
    uri: str = ""
    hero: Optional[HeroBannerData] = None
    banners: List[HeroBannerData] = field(default_factory=list)
    sections: List[ComicSectionData] = field(default_factory=list)


@dataclass
class DiscoverPageData:
    title: str = "发现"
    uri: str = ""
    filters: List[FilterGroupData] = field(default_factory=list)
    items: List[ComicCardData] = field(default_factory=list)
    pager: PagerData = field(default_factory=PagerData)
    spotlight: List[ComicCardData] = field(default_factory=list)


@dataclass
class RankItemData:
    rank: int = 0
    title: str = ""
    cover_url: str = ""
    href: str = ""
    subtitle: str = ""
    extra: str = ""


@dataclass
class RankPageData:
    title: str = "排行"
    uri: str = ""
    tabs: List[LinkAction] = field(default_factory=list)
    items: List[RankItemData] = field(default_factory=list)
    pager: PagerData = field(default_factory=PagerData)


@dataclass
class DetailChapterData:
    label: str = ""
    href: str = ""
    index: int = 0
    is_downloaded: bool = False
    is_read: bool = False


@dataclass
class DetailPageData:
    title: str = ""
    uri: str = ""
    cover_url: str = ""
    author: str = ""
    status: str = ""
    region: str = ""
    tags: List[str] = field(default_factory=list)
    description: str = ""
    chapters: List[DetailChapterData] = field(default_factory=list)
    chapter_tabs: List[LinkAction] = field(default_factory=list)
    prev_href: str = ""
    next_href: str = ""
    catalog_href: str = ""


@dataclass
class ReaderPageData:
    title: str = ""
    uri: str = ""
    chapter_label: str = ""
    images: List[str] = field(default_factory=list)
    prev_href: str = ""
    next_href: str = ""
    catalog_href: str = ""
    comic_href: str = ""


@dataclass
class ProfileUserData:
    user_id: str = ""
    username: str = ""
    avatar_url: str = ""
    is_vip: bool = False


@dataclass
class ProfileLibraryItem:
    title: str = ""
    cover_url: str = ""
    href: str = ""
    comic_id: str = ""
    updated_at: str = ""


@dataclass
class ProfileHistoryItem:
    title: str = ""
    cover_url: str = ""
    href: str = ""
    chapter_label: str = ""
    read_at: str = ""


@dataclass
class ProfilePageData:
    title: str = "我的"
    uri: str = ""
    is_logged_in: bool = False
    user: Optional[ProfileUserData] = None
    collections: List[ProfileLibraryItem] = field(default_factory=list)
    history: List[ProfileHistoryItem] = field(default_factory=list)


@dataclass
class ChapterComment:
    user_name: str = ""
    avatar_url: str = ""
    message: str = ""
    created_at: str = ""


@dataclass
class ChapterCommentFeed:
    total: int = 0
    comments: List[ChapterComment] = field(default_factory=list)


class SitePage:
    """页面基类。"""

    def __init__(self, page_type: SitePageType, uri: str = ""):
        self.page_type = page_type
        self.uri = uri
