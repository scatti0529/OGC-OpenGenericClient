# -*- coding: utf-8 -*-
"""拷贝漫画站点 HTML 解析层：首页、发现、排行、详情、阅读器（移植自 OGC-EasyCopy）。

解析策略针对真实站点 DOM 结构，包含繁->简转换。
注意：本程序 venv 未安装 lxml，BeautifulSoup 自动回退到 html.parser。
"""

from __future__ import annotations

import base64
import json
import re
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from .config import tab_index_for_path
from .models import (
    ComicCardData,
    ComicSectionData,
    DetailChapterData,
    DetailPageData,
    DiscoverPageData,
    FilterGroupData,
    FilterOptionData,
    HeroBannerData,
    HomePageData,
    LinkAction,
    PagerData,
    RankItemData,
    RankPageData,
    ReaderPageData,
    SitePageType,
)


class ParseException(Exception):
    pass


def make_soup(html: str) -> BeautifulSoup:
    """构造 BeautifulSoup，优先 lxml，缺失时回退 html.parser"""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


# ---------- 繁->简 常用字映射（站点内容为繁体，整体汉化为简体） ----------
_T2S_TABLE = {
    "畫": "画", "漫": "漫", "推": "推", "薦": "荐", "熱": "热", "門": "门",
    "更": "更", "新": "新", "全": "全", "上": "上", "架": "架", "排": "排",
    "行": "行", "榜": "榜", "體": "体", "檢": "检", "而": "而", "已": "已",
    "碧": "碧", "藍": "蓝", "之": "之", "海": "海", "轉": "转", "生": "生",
    "騎": "骑", "士": "士", "遊": "游", "戲": "戏", "知": "知", "識": "识",
    "開": "开", "無": "无", "雙": "双", "貓": "猫", "女": "女", "頻": "频",
    "男": "男", "管": "管", "理": "理", "員": "员", "作": "作", "者": "者",
    "戀": "恋", "人": "人", "手": "手", "中": "中", "四": "四", "葉": "叶",
    "草": "草", "魔": "魔", "法": "法", "少": "少", "與": "与", "糖": "糖",
    "果": "果", "戰": "战", "爭": "争", "廟": "庙", "不": "不", "可": "可",
    "言": "言", "反": "反", "派": "派", "偶": "偶", "像": "像", "狂": "狂",
    "坂": "坂", "本": "本", "日": "日", "常": "常", "某": "某", "天": "天",
    "變": "变", "成": "成", "了": "了", "幼": "幼", "龍": "龙", "館": "馆",
    "國": "国", "語": "语", "說": "说", "學": "学", "長": "长", "間": "间",
    "為": "为", "爲": "为", "會": "会", "們": "们", "這": "这", "個": "个", "從": "从",
    "來": "来", "時": "时", "後": "后", "點": "点", "頭": "头", "發": "发", "臺": "台", "灣": "湾",
    "現": "现", "資": "资", "訊": "讯", "頁": "页", "業": "业", "處": "处",
    "結": "结", "續": "续", "讀": "读", "視": "视", "聽": "听", "講": "讲",
    "買": "买", "賣": "卖", "錢": "钱", "銀": "银", "紅": "红", "綠": "绿",
    "藍": "蓝", "黃": "黄", "黑": "黑", "白": "白", "東": "东", "西": "西",
    "南": "南", "北": "北", "風": "风", "雲": "云", "電": "电", "影": "影",
    "視": "视", "遊": "游", "戲": "戏", "軟": "软", "體": "体", "詞": "词",
    "題": "题", "錄": "录", "組": "组", "隊": "队", "團": "团", "級": "级",
    "屆": "届", "數": "数", "據": "据", "庫": "库", "檔": "档", "案": "案",
    "標": "标", "簽": "签", "驗": "验", "證": "证", "識": "识", "設": "设",
    "計": "计", "務": "务", "業": "业", "賦": "赋", "費": "费", "買": "买",
    "賣": "卖", "賬": "账", "號": "号", "碼": "码", "網": "网", "絡": "络",
    "系": "系", "統": "统", "創": "创", "建": "建", "資": "资", "訊": "讯",
    "註": "注", "冊": "册", "登": "登", "錄": "录", "帳": "帐", "密": "密",
    "碼": "码", "錯": "错", "誤": "误", "請": "请", "稍": "稍", "後": "后",
    "重": "重", "試": "试", "失": "失", "敗": "败", "搜": "搜", "索": "索",
    "結": "结", "果": "果", "相": "相", "關": "关", "熱": "热", "門": "门",
    "推": "推", "薦": "荐", "收": "收", "藏": "藏", "歷": "历", "史": "史",
    "暫": "暂", "無": "无", "內": "内", "容": "容", "距": "距", "離": "离",
    "時": "时", "間": "间", "記": "记", "憶": "忆", "體": "体", "驗": "验",
    "檢": "检", "查": "查", "測": "测", "試": "试", "確": "确", "認": "认",
    "刪": "删", "除": "除", "添": "添", "加": "加", "編": "编", "輯": "辑",
    "複": "复", "製": "制", "貼": "贴", "粘": "粘", "取": "取", "消": "消",
    "返": "返", "回": "回", "繼": "继", "續": "续", "閱": "阅", "讀": "读",
    "評": "评", "論": "论", "點": "点", "讚": "赞", "舉": "举", "報": "报",
    "屏": "屏", "幕": "幕", "截": "截", "圖": "图", "導": "导", "航": "航",
    "設": "设", "置": "置", "關": "关", "閉": "闭", "啟": "启", "動": "动",
    "顯": "显", "示": "示", "隱": "隐", "藏": "藏", "選": "选", "擇": "择",
    "確": "确", "定": "定", "應": "应", "該": "该", "無": "无", "問": "问",
    "題": "题", "幫": "帮", "助": "助", "關": "关", "於": "于", "關": "关",
    "鍵": "键", "盤": "盘", "快": "快", "捷": "捷", "刷": "刷", "頁": "页",
}


def to_simplified(text: str) -> str:
    if not text:
        return text
    return "".join(_T2S_TABLE.get(ch, ch) for ch in text)


def _text(el: Optional[Tag]) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _attr(el: Optional[Tag], *names: str) -> str:
    if el is None:
        return ""
    for name in names:
        v = el.get(name)
        if v:
            return str(v).strip()
    return ""


def _href(el: Optional[Tag]) -> str:
    return _attr(el, "href")


def _img_src(el: Optional[Tag]) -> str:
    return _attr(el, "data-src", "src", "data-original", "data-lazy-src", "data-url")


def _resolve_url(url: str, base: str) -> str:
    if not url:
        return ""
    from urllib.parse import urljoin

    return urljoin(base, url)


def _clean_path(value: str) -> str:
    if not value:
        return ""
    from urllib.parse import urlparse

    parts = urlparse(value)
    return parts.path or "/"


class SiteHtmlParser:
    """解析站点 HTML 页面。"""

    def __init__(self, resolve_href=None):
        self.resolve_href = resolve_href or (lambda href, current: href)

    # ---------- 页面类型识别 ----------
    def detect_type(self, uri: str, soup: BeautifulSoup) -> SitePageType:
        path = _clean_path(uri).lower()
        if "/chapter/" in path:
            return SitePageType.READER
        if soup.select_one(".comicParticulars-title"):
            return SitePageType.DETAIL
        if path == "/rank" or path.startswith("/rank/") or path == "/rank.html":
            return SitePageType.RANK
        if (
            soup.select_one(".exemptComicList")
            or soup.select_one(".correlationList .exemptComic_Item")
            or path.startswith(("/comics", "/filter", "/recommend", "/newest", "/author", "/search"))
        ):
            return SitePageType.DISCOVER
        if soup.select_one(".container.comicRank") or path in ("", "/"):
            return SitePageType.HOME
        if path.startswith(("/web/login", "/person")):
            return SitePageType.PROFILE
        return SitePageType.UNKNOWN

    def parse(self, uri: str, html: str):
        soup = make_soup(html)
        page_type = self.detect_type(uri, soup)
        if page_type == SitePageType.HOME:
            return self.parse_home(uri, soup)
        if page_type == SitePageType.DISCOVER:
            return self.parse_discover(uri, soup)
        if page_type == SitePageType.RANK:
            return self.parse_rank(uri, soup)
        if page_type == SitePageType.DETAIL:
            return self.parse_detail(uri, soup)
        if page_type == SitePageType.READER:
            return self.parse_reader(uri, html, soup)
        raise ParseException(f"无法解析此页面：{_clean_path(uri)}")

    # ---------- 首页 ----------
    def parse_home(self, uri: str, soup: BeautifulSoup) -> HomePageData:
        sections: List[ComicSectionData] = []
        banners: List[HeroBannerData] = []

        for slide in soup.select(".carousel-item"):
            link = slide.find("a")
            img = slide.select_one("img")
            caption = slide.select_one("p")
            href = link.get("href") if link else ""
            src = _img_src(img)
            title = _text(caption) if caption else ""
            if src:
                banners.append(HeroBannerData(title=to_simplified(title), image_url=_resolve_url(src, uri), href=href))

        seen_titles = set()
        for container in soup.select(".container"):
            header = container.select_one(".index-all-icon")
            if header is None:
                continue
            title_el = header.select_one(".index-all-icon-left-txt")
            right_el = header.select_one(".index-all-icon-right-txt")
            title = to_simplified(_text(title_el))
            section_href = right_el.get("href") if right_el else ""
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)

            items = self._extract_home_cards(container, uri)
            if items:
                sections.append(ComicSectionData(title=title, href=section_href, items=items))

        if not sections:
            all_cards = self._extract_home_cards(soup, uri)
            if all_cards:
                sections.append(ComicSectionData(title="全部漫画", href="", items=all_cards))

        return HomePageData(title="首页", uri=uri, banners=banners, sections=sections)

    def _extract_home_cards(self, root: Tag, base: str) -> List[ComicCardData]:
        cards: List[ComicCardData] = []
        seen: List[str] = []

        for col in root.select(".col-auto"):
            a = col.find("a")
            if a is None:
                continue
            comic = self._extract_from_anchor(a, base)
            if comic.title and comic.cover_url and comic.href not in seen:
                seen.append(comic.href)
                cards.append(comic)

        for rank in root.select(".comicRank-yi"):
            title_a = rank.select_one(".comicRank-txt-p a") or rank.select_one("a")
            img = rank.select_one("img")
            cover = _img_src(img)
            href = title_a.get("href") if title_a else ""
            title = _text(title_a)
            if title and cover and href not in seen:
                seen.append(href)
                cards.append(
                    ComicCardData(
                        title=to_simplified(title),
                        cover_url=_resolve_url(cover, base),
                        href=href,
                        subtitle="",
                        secondary_text="",
                    )
                )

        return cards

    def _extract_from_anchor(self, a: Tag, base: str) -> ComicCardData:
        href = a.get("href") or ""
        img = a.select_one("img")
        cover = _img_src(img)
        title = ""
        for sel in [".edit-txt", ".comicRank-txt-p", ".title", ".name"]:
            el = a.select_one(sel)
            if el:
                title = _text(el)
                break
        if not title:
            title = img.get("alt") or img.get("title") if img else ""
        if not title:
            title = _text(a)
        subtitle = ""
        secondary = ""
        author_el = a.select_one(".comicRank-txt-span, .author")
        if author_el:
            subtitle = to_simplified(_text(author_el))
        return ComicCardData(
            title=to_simplified(title),
            cover_url=_resolve_url(cover, base),
            href=href,
            subtitle=subtitle,
            secondary_text=secondary,
        )

    # ---------- 发现 ----------
    def parse_discover(self, uri: str, soup: BeautifulSoup) -> DiscoverPageData:
        filters: List[FilterGroupData] = []
        items: List[ComicCardData] = []

        for dl in soup.select(".classify-txt-all"):
            dt = dl.select_one("dt")
            group_title = to_simplified(_text(dt)) or "筛选"
            options: List[FilterOptionData] = []
            for opt in dl.select("a"):
                dd = opt.select_one("dd")
                label = to_simplified(_text(dd)) or to_simplified(_text(opt))
                href = _href(opt)
                if not label:
                    continue
                active = "active" in (dd.get("class") or []) if dd else False
                options.append(FilterOptionData(label=label, value=href, active=active))
            if options:
                filters.append(FilterGroupData(title=group_title, key=group_title, options=options))

        for item_el in soup.select(".exemptComic_Item"):
            img = item_el.select_one("img")
            a = item_el.select_one("a") or (item_el if item_el.name == "a" else None)
            cover = _img_src(img)
            if a is None:
                continue
            href = _href(a)
            title = img.get("alt") if img else ""
            txt_el = item_el.select_one(".exemptComicItem-txt, .twoLines, .exemptComicItem-txt-box")
            if not title:
                title = _text(txt_el)
            if title:
                title = title.split("作者")[0].split("  ")[0].strip()
            subtitle = ""
            span_el = item_el.select_one(".exemptComicItem-txt-span")
            if span_el:
                subtitle = to_simplified(_text(span_el))
            if title and cover:
                items.append(
                    ComicCardData(
                        title=to_simplified(title),
                        cover_url=_resolve_url(cover, uri),
                        href=href,
                        subtitle=subtitle,
                    )
                )

        if not items:
            for anchor in soup.select(".col-auto > a"):
                comic = self._extract_from_anchor(anchor, uri)
                if comic.title and comic.cover_url:
                    items.append(comic)

        if not items:
            items = self._extract_discover_from_js(soup, uri)

        pager = self._extract_pager(uri, soup)
        return DiscoverPageData(title="发现", uri=uri, filters=filters, items=items, pager=pager)

    def _extract_discover_from_js(self, soup: BeautifulSoup, uri: str) -> List[ComicCardData]:
        import ast

        box = soup.select_one(".exemptComic-box")
        if box is None:
            return []
        raw = (box.get("list") or "").strip()
        if not raw:
            return []

        try:
            data = ast.literal_eval(raw)
        except Exception:
            data = None
        if not isinstance(data, list):
            return []

        result: List[ComicCardData] = []
        for it in data:
            if not isinstance(it, dict):
                continue
            path_word = str(it.get("path_word") or "").strip()
            name = str(it.get("name") or "").strip()
            cover = str(it.get("cover") or "").strip()
            author = it.get("author") or []
            subtitle = ""
            if isinstance(author, list) and author and isinstance(author[0], dict):
                subtitle = str(author[0].get("name") or "").strip()
            if not name or not cover:
                continue
            href = f"/comic/{path_word}" if path_word else ""
            result.append(
                ComicCardData(
                    title=to_simplified(name),
                    cover_url=_resolve_url(cover, uri),
                    href=href,
                    subtitle=to_simplified(subtitle),
                )
            )
        return result

    # ---------- 排行 ----------
    def parse_rank(self, uri: str, soup: BeautifulSoup) -> RankPageData:
        tabs: List[LinkAction] = []
        items: List[RankItemData] = []

        for a in soup.select(".classify-right a, .rankingTime a"):
            dd = a.select_one("dd")
            label = to_simplified(_text(dd)) or to_simplified(_text(a))
            href = _href(a)
            if not label or not href:
                continue
            active = ("active" in (dd.get("class") or [])) if dd else ("active" in (a.get("class") or []))
            tabs.append(LinkAction(label=label, href=href, active=active))

        for box in soup.select(".ranking-all-box"):
            rank_no = 0
            rank_el = box.select_one(".ranking-all-icon")
            if rank_el:
                m = re.search(r"\d+", _text(rank_el))
                if m:
                    rank_no = int(m.group())
            if rank_no == 0:
                rank_no = len(items) + 1

            title_el = box.select_one(".threeLines, .comicRank-txt-p, .comicRank-all-txt")
            title_a = box.select_one("a")
            img = box.select_one("img")
            cover = _img_src(img)
            href = _href(title_a)
            title = to_simplified(_text(title_el)) if title_el is not None else ""
            if not title and title_a is not None:
                p_el = title_a.select_one("p")
                title = to_simplified(_text(p_el))
            if not title and img:
                title = to_simplified(img.get("alt") or img.get("title") or "")
            author_el = box.select_one(".oneLines, .comicRank-txt-span")
            subtitle = to_simplified(_text(author_el)) if author_el else ""
            if subtitle.startswith("作者"):
                subtitle = subtitle.split("作者", 1)[-1].lstrip("：: ")

            if title and cover:
                items.append(
                    RankItemData(
                        rank=rank_no,
                        title=title,
                        cover_url=_resolve_url(cover, uri),
                        href=href,
                        subtitle=subtitle,
                    )
                )

        pager = self._extract_pager(uri, soup)
        return RankPageData(title="排行", uri=uri, tabs=tabs, items=items, pager=pager)

    # ---------- 详情 ----------
    def parse_detail(self, uri: str, soup: BeautifulSoup) -> DetailPageData:
        title = to_simplified(_text(soup.select_one("h6[title]"))) or to_simplified(
            _text(soup.select_one(".comicParticulars-title"))
        )
        cover = _img_src(
            soup.select_one(
                ".comicParticulars-left-img img, .deInfo__comic img, .comicParticulars-left img, .detail-cover img"
            )
        )
        if not title:
            title = to_simplified(_text(soup.select_one("h1, .detail-title, .comic-title")))

        author = ""
        status = ""
        region = ""
        tags: List[str] = []
        description = to_simplified(
            _text(soup.select_one(".comicParticulars-intro, .intro, .description, .detail-desc"))
        )

        for info in soup.select(".comicParticulars-title-right li"):
            txt = to_simplified(_text(info))
            if "作者" in txt:
                author = txt.split("作者", 1)[-1].lstrip("：: ")
            elif "狀態" in txt or "状态" in txt:
                status = txt.split("狀態", 1)[-1].split("状态", 1)[-1].lstrip("：: ")
            elif "地區" in txt or "地区" in txt:
                region = txt.split("地區", 1)[-1].split("地区", 1)[-1].lstrip("：: ")

        for tag_el in soup.select(".comicParticulars-tag a, .tags a, .tag-list a"):
            t = to_simplified(_text(tag_el)).lstrip("#")
            if t:
                tags.append(t)

        chapters: List[DetailChapterData] = []
        chapter_tabs: List[LinkAction] = []
        chapter_els = soup.select(".chapter-item, .chapterItem, .chapter-item-list a, .chapterList a, .item-chapter, .chapter-link a")
        for idx, ch in enumerate(chapter_els):
            if ch.name != "a":
                link = ch.select_one("a")
                if link is None:
                    continue
                ch = link
            label = to_simplified(_text(ch))
            href = _href(ch)
            if not label or not href:
                continue
            chapters.append(DetailChapterData(label=label, href=href, index=idx))

        nav = soup.select_one(".rdList, .chapter-navigation, .reader-nav, .chapterNav")
        prev_href = next_href = catalog_href = ""
        if nav is not None:
            for a in nav.select("a"):
                txt = _text(a)
                href = _href(a)
                if "上一话" in txt or "上一章" in txt or "上一卷" in txt:
                    prev_href = href
                elif "下一话" in txt or "下一章" in txt or "下一卷" in txt:
                    next_href = href
                elif "目录" in txt or "目錄" in txt or "列表" in txt:
                    catalog_href = href

        return DetailPageData(
            title=title,
            uri=uri,
            cover_url=_resolve_url(cover, uri),
            author=author,
            status=status,
            region=region,
            tags=tags,
            description=description,
            chapters=chapters,
            chapter_tabs=chapter_tabs,
            prev_href=prev_href,
            next_href=next_href,
            catalog_href=catalog_href,
        )

    # ---------- 阅读器 ----------
    def parse_reader(self, uri: str, html: str, soup: BeautifulSoup) -> ReaderPageData:
        images: List[str] = []

        # 优先通过 contentKey + cct AES 解密得到真实漫画图
        content_key = ""
        cct = ""
        m = re.search(r"var\s+contentKey\s*=\s*['\"]([^'\"]+)['\"]", html)
        if m:
            content_key = m.group(1).strip()
        m = re.search(r"var\s+cct\s*=\s*['\"]([^'\"]+)['\"]", html)
        if m:
            cct = m.group(1).strip()

        if content_key and cct:
            try:
                plain_text = self._aes_cbc_decrypt(cct, content_key)
                decoded = json.loads(plain_text)
                if isinstance(decoded, list):
                    for it in decoded:
                        raw_url = ""
                        if isinstance(it, str):
                            raw_url = it.strip()
                        elif isinstance(it, dict):
                            raw_url = str(it.get("url") or "").strip()
                        if raw_url:
                            images.append(_resolve_url(raw_url, uri))
                images = list(dict.fromkeys(images))
            except Exception:
                images = []

        # 回退：DOM 图片
        if not images:
            container = soup.select_one(".rdInner, .reader-content, .comic-read, .mh-read, .read-container")
            if container is not None:
                for img in container.select("img"):
                    src = _img_src(img)
                    if src:
                        images.append(_resolve_url(src, uri))

        if not images:
            for img in soup.select("img.lazyload, img[data-src], img[data-original]"):
                src = _img_src(img)
                if src and self._looks_like_comic_image(src):
                    images.append(_resolve_url(src, uri))

        if not images:
            images = self._extract_images_from_json(html, uri)

        images = list(dict.fromkeys(images))

        chapter_label = to_simplified(
            _text(soup.select_one(".rdTitle, .chapter-title, .reader-title, h1")) or _text(soup.title)
        )

        prev_href = next_href = catalog_href = ""
        for a in soup.select("a"):
            txt = _text(a)
            if prev_href and next_href:
                break
            if not prev_href and ("上一话" in txt or "上一章" in txt or "上一頁" in txt):
                prev_href = _href(a)
            if not next_href and ("下一话" in txt or "下一章" in txt or "下一頁" in txt):
                next_href = _href(a)
            if not catalog_href and ("目录" in txt or "目錄" in txt or "列表" in txt):
                catalog_href = _href(a)

        return ReaderPageData(
            title=chapter_label,
            uri=uri,
            chapter_label=chapter_label,
            images=images,
            prev_href=prev_href,
            next_href=next_href,
            catalog_href=catalog_href,
        )

    @staticmethod
    def _looks_like_comic_image(src: str) -> bool:
        low = src.lower()
        if any(k in low for k in ["logo", "icon", "avatar", "banner", "recommend/"]):
            return False
        return any(k in low for k in [".jpg", ".png", ".webp", ".gif", "chapter", "comic", "manga"])

    def _extract_images_from_json(self, html: str, base: str) -> List[str]:
        result: List[str] = []
        patterns = [
            r'"photos"\s*:\s*\[(.*?)\]',
            r'"images"\s*:\s*\[(.*?)\]',
            r'var\s+chapterImages\s*=\s*\[(.*?)\]',
            r'var\s+_images\s*=\s*\[(.*?)\]',
            r'"chapterImages"\s*:\s*\[(.*?)\]',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.S)
            if m:
                body = m.group(1)
                urls = re.findall(r'["\']([^"\']+\.(?:jpg|jpeg|png|webp|gif)[^"\']*)["\']', body, re.I)
                for u in urls:
                    u = u.replace("\\/", "/")
                    if u not in result:
                        result.append(_resolve_url(u, base))
                if result:
                    break
        if not result:
            urls = re.findall(r'["\'](https?://[^"\']+\.(?:jpg|jpeg|png|webp|gif)[^"\']*)["\']', html, re.I)
            for u in urls:
                u = u.replace("\\/", "/")
                if u not in result:
                    result.append(u)
        return result

    # ---------- 通用 ----------
    def _extract_pager(self, uri: str, soup: BeautifulSoup) -> PagerData:
        pager = PagerData()
        pager_box = soup.select_one(".pagination, .pager, .pageBox, .pageNav")
        if pager_box is None:
            return pager
        prev_el = pager_box.select_one(".prev, .previous, a[rel='prev']")
        next_el = pager_box.select_one(".next, a[rel='next']")
        current_el = pager_box.select_one(".active, .current, .cur")
        if prev_el:
            pager.prev_href = _href(prev_el)
        if next_el:
            pager.next_href = _href(next_el)
        total = ""
        pages = pager_box.select("a")
        if pages:
            total = str(len(pages))
        pager.current_label = _text(current_el) or "1"
        if total:
            pager.total_label = f"共{total}页"
        return pager

    # ---------- AES 解密 ----------
    @staticmethod
    def _aes_cbc_decrypt(key_material: str, encrypted: str) -> str:
        """AES-CBC 解密（key 为 UTF-8 字节，IV 取密文前 16 字节，密文为 hex 或 base64）。"""
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad

        key = key_material.encode("utf-8")
        iv = encrypted[:16].encode("utf-8")
        cipher_text = encrypted[16:]

        if re.fullmatch(r"[0-9a-fA-F]+", cipher_text) and len(cipher_text) % 2 == 0:
            raw = bytes.fromhex(cipher_text)
        else:
            raw = base64.b64decode(cipher_text)

        cipher = AES.new(key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(raw), AES.block_size).decode("utf-8")

    @staticmethod
    def decrypt_detail_chapters(slug: str, ccz: str, encrypted_results: str) -> List[DetailChapterData]:
        """解密详情页章节接口返回的 AES 密文，返回章节列表。"""
        plain_text = SiteHtmlParser._aes_cbc_decrypt(ccz, encrypted_results)
        decoded = json.loads(plain_text)
        if not isinstance(decoded, dict):
            return []

        build = decoded.get("build") or {}
        path_word = str(build.get("path_word") or "").strip() or slug

        type_labels: dict = {1: "话", 2: "卷", 3: "番外篇"}
        for t in build.get("type") or []:
            if isinstance(t, dict):
                tid = t.get("id")
                name = str(t.get("name") or "").strip()
                if tid is not None and name:
                    type_labels[int(tid)] = name

        groups = decoded.get("groups") or {}
        if isinstance(groups, dict):
            group_list = list(groups.values())
        elif isinstance(groups, list):
            group_list = groups
        else:
            group_list = []

        chapters: List[DetailChapterData] = []
        seen: set = set()
        for group in group_list:
            if not isinstance(group, dict):
                continue
            for ch in group.get("chapters") or []:
                if not isinstance(ch, dict):
                    continue
                ch_id = str(ch.get("id") or "").strip()
                label = str(ch.get("name") or "").strip()
                if not label:
                    ch_type = int(ch.get("type") or 0)
                    label = type_labels.get(ch_type, "章节")
                if not ch_id or not label:
                    continue
                href = f"/comic/{path_word}/chapter/{ch_id}"
                if href in seen:
                    continue
                seen.add(href)
                chapters.append(
                    DetailChapterData(label=to_simplified(label), href=href, index=len(chapters))
                )
        return chapters
