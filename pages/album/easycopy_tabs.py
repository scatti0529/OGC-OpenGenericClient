# -*- coding: utf-8 -*-
"""
拷贝漫画五个标签页（OGC 集成版）
===============================
首页（含搜索）/ 发现 / 排行 / 我的 / 设置 —— 合并进同一个页面，
由 EasyCopyPage 顶部的分段导航栏（SegmentedWidget）切换。
"""
from __future__ import annotations

import threading

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SubtitleLabel,
    SwitchButton,
    TitleLabel,
)

from services.easycopy.api import SiteApiException
from services.easycopy.app import AppContext
from services.easycopy.models import (
    DiscoverPageData,
    HomePageData,
    ProfilePageData,
    RankPageData,
)
from ui.widgets.theme import text_primary, text_secondary, text_tertiary

from .easycopy_widgets import (
    ComicCard,
    CoverImage,
    EmptyLabel,
    ErrorLabel,
    FlowLayout,
    LoadingLabel,
    SectionHeader,
)


# ═══════════════════════════════════════════
#  滚动页面基类
# ═══════════════════════════════════════════
class EasyCopyScrollPage(QScrollArea):
    """基础滚动页面：提供内容区与清空方法。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._content = QWidget()
        self._content.setObjectName("easycopyPageContent")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(24, 20, 24, 32)
        self._layout.setSpacing(16)

        self.setWidget(self._content)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    @property
    def layout(self):
        return self._layout

    @property
    def content(self):
        return self._content

    def clear(self):
        """清空内容。"""
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


# ═══════════════════════════════════════════
#  首页（含搜索）
# ═══════════════════════════════════════════
class HomeTab(EasyCopyScrollPage):
    """首页标签页：搜索框 + 轮播/板块；搜索结果显示在首页内。"""

    def __init__(self, ctx: AppContext, on_open_comic, on_navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_open_comic = on_open_comic
        self.on_navigate = on_navigate
        self._cards = []
        self._loading_label = None
        self._query = ""
        self._search_page = 1
        self._search_worker = None

        self._build_search_bar()

    # ---------------- 搜索栏 ----------------
    def _build_search_bar(self):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)

        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("搜索漫画…")
        self.search_edit.setFixedHeight(36)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._on_search)
        layout.addWidget(self.search_edit, 1)

        self.search_btn = PrimaryPushButton(FluentIcon.SEARCH, "搜索", self)
        self.search_btn.setFixedSize(92, 36)
        self.search_btn.clicked.connect(self._on_search)
        layout.addWidget(self.search_btn)

        self.back_btn = PushButton("← 返回首页", self)
        self.back_btn.setFixedSize(110, 36)
        self.back_btn.clicked.connect(self._back_home)
        self.back_btn.setVisible(False)
        layout.addWidget(self.back_btn)

        self.layout.addWidget(row)

    def _on_search(self):
        query = self.search_edit.text().strip()
        if not query:
            InfoBar.warning(
                "提示", "请输入搜索关键词", parent=self, position=InfoBarPosition.TOP, duration=2000
            )
            return
        self._query = query
        self._search_page = 1
        self._show_search_loading()
        self._run_search_worker(query, 1)
        self.back_btn.setVisible(True)

    def _back_home(self):
        self.back_btn.setVisible(False)
        self.search_edit.clear()
        self.load()

    def _show_search_loading(self):
        self.clear()
        self._build_search_bar()
        self.back_btn.setVisible(True)
        self._cards = []
        self._loading_label = LoadingLabel(f"正在搜索「{self._query}」…")
        self.layout.addWidget(self._loading_label)

    def _run_search_worker(self, query: str, page: int):
        self._search_worker = _SearchWorker(self.ctx, query, page)
        self._search_worker.done.connect(self._on_search_done)
        self._search_worker.start()

    def _on_search_done(self, payload):
        status, data = payload
        if status == "error":
            self.clear()
            self._build_search_bar()
            self.back_btn.setVisible(True)
            self.layout.addWidget(ErrorLabel(data))
            return
        page: DiscoverPageData = data
        self.clear()
        self._build_search_bar()
        self.back_btn.setVisible(True)
        self._cards = []

        header = QLabel(f"搜索「{self._query}」的结果")
        header.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {text_primary()};")
        self.layout.addWidget(header)

        if page.items:
            flow_widget = QWidget()
            flow = FlowLayout(flow_widget, spacing=10)
            for item in page.items:
                card = ComicCard(
                    item.title, item.cover_url, item.href, self.ctx.image_fetcher,
                    subtitle=item.subtitle, secondary=item.secondary_text,
                )
                card.clicked.connect(self.on_open_comic)
                self._cards.append(card)
                flow.addWidget(card)
            self.layout.addWidget(flow_widget)
        else:
            self.layout.addWidget(EmptyLabel("没有找到相关漫画。"))

        # 分页
        if page.pager and (page.pager.prev_href or page.pager.next_href):
            pager_box = QWidget()
            pager_layout = QHBoxLayout(pager_box)
            pager_layout.setContentsMargins(0, 0, 0, 0)
            pager_layout.setSpacing(12)
            pager_layout.addStretch(1)
            if page.pager.prev_href:
                prev = QLabel("上一页")
                prev.setCursor(Qt.PointingHandCursor)
                prev.setContentsMargins(14, 8, 14, 8)
                prev.setStyleSheet("background: #28AFE9; color: white; border-radius: 16px;")
                prev.mouseReleaseEvent = lambda e: self._goto_page(self._search_page - 1)
                pager_layout.addWidget(prev)
            total = QLabel(page.pager.total_label or "")
            total.setStyleSheet(f"color: {text_tertiary()};")
            pager_layout.addWidget(total)
            if page.pager.next_href:
                next_btn = QLabel("下一页")
                next_btn.setCursor(Qt.PointingHandCursor)
                next_btn.setContentsMargins(14, 8, 14, 8)
                next_btn.setStyleSheet("background: #28AFE9; color: white; border-radius: 16px;")
                next_btn.mouseReleaseEvent = lambda e: self._goto_page(self._search_page + 1)
                pager_layout.addWidget(next_btn)
            pager_layout.addStretch(1)
            self.layout.addWidget(pager_box)

        self.layout.addStretch(1)

    def _goto_page(self, page: int):
        if page < 1:
            return
        self._search_page = page
        self._show_search_loading()
        self._run_search_worker(self._query, page)

    # ---------------- 首页内容 ----------------
    def load(self):
        if self.back_btn.isVisible():
            self._back_home()
            return
        self._show_loading()
        self.ctx.load_page(self.ctx.home_uri(), self._on_loaded, self._set_loading_text)

    def _show_loading(self, text: str = "正在加载首页…"):
        self.clear()
        self._build_search_bar()
        self._cards = []
        self._loading_label = LoadingLabel(text)
        self.layout.addWidget(self._loading_label)

    def _set_loading_text(self, text: str):
        if self._loading_label is not None:
            self._loading_label.setText(text)

    def show_error(self, msg: str):
        self.clear()
        self._build_search_bar()
        self._loading_label = None
        self.layout.addWidget(ErrorLabel(f"首页加载失败：{msg}"))

    def _on_loaded(self, page, error):
        if error is not None:
            self.show_error(str(error))
            return
        if not isinstance(page, HomePageData):
            self.show_error("数据格式异常")
            return
        self.clear()
        self._build_search_bar()
        self._cards = []
        if page.banners:
            self._build_banner(page.banners)
        if page.sections:
            for section in page.sections:
                self._build_section(section)
        else:
            self.layout.addWidget(EmptyLabel())
        self.layout.addStretch(1)

    def _build_banner(self, banners):
        banner_container = QWidget()
        banner_container.setFixedHeight(240)
        banner_layout = QHBoxLayout(banner_container)
        banner_layout.setContentsMargins(0, 0, 0, 0)
        banner_layout.setSpacing(12)

        for b in banners[:5]:
            cover = CoverImage(b.image_url, self.ctx.image_fetcher, radius=18, placeholder_text=b.title or "封面")
            cover.setFixedSize(400, 220)
            cover.mouseReleaseEvent = (lambda e, href=b.href: self.on_open_comic(href) if href else None)
            banner_layout.addWidget(cover)

        banner_layout.addStretch(1)
        self.layout.addWidget(banner_container)

    def _build_section(self, section):
        self.layout.addWidget(
            SectionHeader(
                section.title,
                show_more=bool(section.href),
                on_more=(lambda: self.on_navigate(section.href)) if section.href else None,
            )
        )
        row = QWidget()
        flow = FlowLayout(row, spacing=10)
        for item in section.items[:6]:
            card = ComicCard(
                item.title, item.cover_url, item.href, self.ctx.image_fetcher,
                subtitle=item.subtitle, secondary=item.secondary_text,
            )
            card.clicked.connect(self.on_open_comic)
            self._cards.append(card)
            flow.addWidget(card)
        self.layout.addWidget(row)


# ═══════════════════════════════════════════
#  发现页
# ═══════════════════════════════════════════
class DiscoverTab(EasyCopyScrollPage):
    """发现页：筛选器 + 漫画网格 + 分页。"""

    def __init__(self, ctx: AppContext, on_open_comic, on_navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_open_comic = on_open_comic
        self.on_navigate = on_navigate
        self._cards = []
        self._page_uri = ""

    def load(self, uri=None):
        self._page_uri = uri or self.ctx.discover_uri()
        self._show_loading()
        self.ctx.load_page(self._page_uri, self._on_loaded)

    def _show_loading(self):
        self.clear()
        self._cards = []
        self.layout.addWidget(LoadingLabel("正在加载发现页…"))

    def show_error(self, msg: str):
        self.clear()
        self.layout.addWidget(ErrorLabel(f"发现页加载失败：{msg}"))

    def _on_loaded(self, page, error):
        if error is not None:
            self.show_error(str(error))
            return
        if not isinstance(page, DiscoverPageData):
            self.show_error("数据格式异常")
            return
        self.clear()
        self._cards = []

        if page.filters:
            self._build_filters(page)
        if page.items:
            grid_container = QWidget()
            flow = FlowLayout(grid_container, spacing=10)
            for item in page.items:
                card = ComicCard(
                    item.title, item.cover_url, item.href, self.ctx.image_fetcher,
                    subtitle=item.subtitle, secondary=item.secondary_text,
                )
                card.clicked.connect(self.on_open_comic)
                self._cards.append(card)
                flow.addWidget(card)
            self.layout.addWidget(grid_container)
        else:
            self.layout.addWidget(EmptyLabel())

        if page.pager and (page.pager.prev_href or page.pager.next_href):
            self._build_pager(page.pager)
        self.layout.addStretch(1)

    def _build_filters(self, page: DiscoverPageData):
        filter_panel = QWidget()
        panel_layout = QVBoxLayout(filter_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(8)

        for group in page.filters:
            group_box = QWidget()
            box_layout = QVBoxLayout(group_box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(4)

            label = QLabel(group.title)
            label.setStyleSheet(f"color: {text_secondary()}; font-weight: 600;")
            box_layout.addWidget(label)

            chips = QWidget()
            chips_layout = QHBoxLayout(chips)
            chips_layout.setContentsMargins(0, 0, 0, 0)
            chips_layout.setSpacing(8)
            for opt in group.options[:12]:
                chip = QLabel(opt.label)
                chip.setCursor(Qt.PointingHandCursor)
                chip.setContentsMargins(12, 6, 12, 6)
                if opt.active:
                    chip.setStyleSheet("background: #28AFE9; color: white; border-radius: 14px;")
                else:
                    chip.setStyleSheet(f"background: rgba(128,128,128,0.10); color: {text_primary()}; border-radius: 14px;")
                chip.mouseReleaseEvent = (lambda e, href=opt.value: self.on_navigate(href) if href else None)
                chips_layout.addWidget(chip)
            chips_layout.addStretch(1)
            box_layout.addWidget(chips)
            panel_layout.addWidget(group_box)

        self.layout.addWidget(filter_panel)

    def _build_pager(self, pager):
        pager_box = QWidget()
        pager_layout = QHBoxLayout(pager_box)
        pager_layout.setContentsMargins(0, 0, 0, 0)
        pager_layout.setSpacing(12)
        pager_layout.addStretch(1)
        if pager.prev_href:
            pager_layout.addWidget(self._pager_button("上一页", pager.prev_href))
        total_label = QLabel(pager.total_label or "")
        total_label.setStyleSheet(f"color: {text_tertiary()};")
        pager_layout.addWidget(total_label)
        if pager.next_href:
            pager_layout.addWidget(self._pager_button("下一页", pager.next_href))
        pager_layout.addStretch(1)
        self.layout.addWidget(pager_box)

    def _pager_button(self, text: str, href: str) -> QLabel:
        btn = QLabel(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setContentsMargins(14, 8, 14, 8)
        btn.setStyleSheet("background: #28AFE9; color: white; border-radius: 16px;")
        btn.mouseReleaseEvent = lambda e: self.on_navigate(href)
        return btn


# ═══════════════════════════════════════════
#  排行页
# ═══════════════════════════════════════════
class RankTab(EasyCopyScrollPage):
    """排行页：标签切换 + 排行列表。"""

    def __init__(self, ctx: AppContext, on_open_comic, on_navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_open_comic = on_open_comic
        self.on_navigate = on_navigate
        self._covers = []
        self._page_uri = ""

    def load(self, uri=None):
        self._page_uri = uri or self.ctx.rank_uri()
        self.clear()
        self._covers = []
        self.layout.addWidget(LoadingLabel("正在加载排行榜…"))
        self.ctx.load_page(self._page_uri, self._on_loaded)

    def show_error(self, msg: str):
        self.clear()
        self.layout.addWidget(ErrorLabel(f"排行榜加载失败：{msg}"))

    def _on_loaded(self, page, error):
        if error is not None:
            self.show_error(str(error))
            return
        if not isinstance(page, RankPageData):
            self.show_error("数据格式异常")
            return
        self.clear()
        self._covers = []

        if page.tabs:
            self._build_tabs(page.tabs)
        if page.items:
            list_container = QWidget()
            list_layout = QVBoxLayout(list_container)
            list_layout.setContentsMargins(0, 0, 0, 0)
            list_layout.setSpacing(10)
            for item in page.items:
                list_layout.addWidget(self._build_rank_item(item))
            self.layout.addWidget(list_container)
        else:
            self.layout.addWidget(EmptyLabel())
        self.layout.addStretch(1)

    def _build_tabs(self, tabs):
        tab_bar = QWidget()
        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(8)
        for tab in tabs:
            btn = QLabel(tab.label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setContentsMargins(16, 8, 16, 8)
            if tab.active:
                btn.setStyleSheet("background: #28AFE9; color: white; border-radius: 16px;")
            else:
                btn.setStyleSheet(f"background: rgba(128,128,128,0.10); color: {text_primary()}; border-radius: 16px;")
            btn.mouseReleaseEvent = (lambda e, href=tab.href: self.on_navigate(href) if href else None)
            tab_layout.addWidget(btn)
        tab_layout.addStretch(1)
        self.layout.addWidget(tab_bar)

    def _build_rank_item(self, item):
        row = QWidget()
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 14px;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(12)

        rank_label = QLabel(str(item.rank))
        rank_label.setFixedWidth(36)
        rank_label.setAlignment(Qt.AlignCenter)
        rank_label.setStyleSheet(
            f"color: {'#E05B1F' if item.rank <= 3 else text_tertiary()}; font-size: 18px; font-weight: 800;"
        )
        row_layout.addWidget(rank_label)

        cover = CoverImage(item.cover_url, self.ctx.image_fetcher, radius=10)
        cover.setFixedSize(56, 78)
        self._covers.append(cover)
        row_layout.addWidget(cover)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        title = QLabel(item.title)
        title.setStyleSheet(f"color: {text_primary()}; font-size: 15px; font-weight: 600;")
        text_box.addWidget(title)
        if item.subtitle:
            sub = QLabel(item.subtitle)
            sub.setStyleSheet(f"color: {text_tertiary()}; font-size: 12px;")
            text_box.addWidget(sub)
        row_layout.addLayout(text_box, 1)

        row.mouseReleaseEvent = (lambda e: self.on_open_comic(item.href) if item.href else None)
        return row


# ═══════════════════════════════════════════
#  我的（个人中心）
# ═══════════════════════════════════════════
class _LoginWorker(QThread):
    """后台登录线程。"""

    done = pyqtSignal(bool, str)

    def __init__(self, api, session, username, password):
        super().__init__()
        self.api = api
        self.session = session
        self.username = username
        self.password = password

    def run(self):
        try:
            token, cookies = self.api.login(self.username, self.password)
            self.session.update_from_login(token, cookies)
            self.done.emit(True, "")
        except SiteApiException as e:
            self.done.emit(False, str(e))
        except Exception as e:
            self.done.emit(False, f"登录失败：{e}")


class ProfileTab(EasyCopyScrollPage):
    """我的标签页：登录态展示用户信息、收藏、历史；未登录展示登录入口。"""

    def __init__(self, ctx: AppContext, on_open_comic, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_open_comic = on_open_comic
        self._covers = []
        self._worker = None

    def load(self, uri=None):
        self.clear()
        self._covers = []
        if not self.ctx.session.is_authenticated:
            self._build_login_view()
        else:
            self.layout.addWidget(LoadingLabel("正在加载个人中心…"))
            self.ctx.load_page(self.ctx.profile_uri(), self._on_loaded)

    def _on_loaded(self, page, error):
        self.clear()
        self._covers = []
        if error is not None:
            self.layout.addWidget(ErrorLabel(f"个人中心加载失败：{error}"))
            return
        if not isinstance(page, ProfilePageData):
            self.layout.addWidget(ErrorLabel("数据格式异常"))
            return
        self._build_profile_view(page)

    # ---------------- 登录视图 ----------------
    def _build_login_view(self):
        card = CardWidget(self)
        card.setStyleSheet(
            "background: rgba(128,128,128,0.08); border-radius: 20px; padding: 20px;"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(16)

        title = SubtitleLabel("登录拷贝漫画", card)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {text_primary()};")
        card_layout.addWidget(title)

        desc = CaptionLabel("登录后可使用收藏、评论、历史等功能", card)
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet(f"color: {text_tertiary()};")
        card_layout.addWidget(desc)

        self.username_edit = LineEdit(card)
        self.username_edit.setPlaceholderText("账号")
        self.username_edit.setFixedHeight(38)
        card_layout.addWidget(self.username_edit)

        self.password_edit = PasswordLineEdit(card)
        self.password_edit.setPlaceholderText("密码")
        self.password_edit.setFixedHeight(38)
        card_layout.addWidget(self.password_edit)

        self.login_btn = PrimaryPushButton("登 录", card)
        self.login_btn.setFixedHeight(40)
        self.login_btn.clicked.connect(self._do_login)
        card_layout.addWidget(self.login_btn)

        center = QWidget()
        center_layout = QHBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addStretch(1)
        center_layout.addWidget(card, 2)
        center_layout.addStretch(1)
        self.layout.addWidget(center)
        self.layout.addStretch(1)

    def _do_login(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip()
        if not username or not password:
            InfoBar.warning(
                "提示", "请输入账号和密码", parent=self, position=InfoBarPosition.TOP, duration=2000
            )
            return
        self.login_btn.setEnabled(False)
        self.login_btn.setText("登录中…")
        self._worker = _LoginWorker(self.ctx.api, self.ctx.session, username, password)
        self._worker.done.connect(self._on_login_done)
        self._worker.start()

    def _on_login_done(self, success: bool, msg: str):
        self.login_btn.setEnabled(True)
        self.login_btn.setText("登 录")
        if success:
            InfoBar.success("登录成功", "欢迎回来！", parent=self, position=InfoBarPosition.TOP, duration=2000)
            self.load()
        else:
            InfoBar.error("登录失败", msg, parent=self, position=InfoBarPosition.TOP, duration=3000)

    # ---------------- 已登录视图 ----------------
    def _build_profile_view(self, page: ProfilePageData):
        user_card = CardWidget(self)
        user_card.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 20px;")
        user_layout = QHBoxLayout(user_card)
        user_layout.setContentsMargins(20, 20, 20, 20)
        user_layout.setSpacing(16)

        if page.user is not None:
            name = page.user.username or page.user.user_id or "已登录"
            if page.user.avatar_url:
                avatar = CoverImage(page.user.avatar_url, self.ctx.image_fetcher, radius=28)
                avatar.setFixedSize(56, 56)
                user_layout.addWidget(avatar)
            name_label = SubtitleLabel(name, user_card)
            name_label.setStyleSheet(f"color: {text_primary()};")
            user_layout.addWidget(name_label)
            user_layout.addStretch(1)
        else:
            name_label = SubtitleLabel("已登录", user_card)
            user_layout.addWidget(name_label)
            user_layout.addStretch(1)

        logout_btn = PushButton("退出登录", user_card)
        logout_btn.clicked.connect(self._logout)
        user_layout.addWidget(logout_btn)

        self.layout.addWidget(user_card)

        self.layout.addWidget(SectionHeader("我的收藏"))
        if page.collections:
            flow_widget = QWidget()
            flow = FlowLayout(flow_widget, spacing=10)
            for item in page.collections[:12]:
                cover = CoverImage(item.cover_url, self.ctx.image_fetcher, radius=12, placeholder_text=item.title)
                cover.setFixedSize(120, 166)
                cover.mouseReleaseEvent = (lambda e, href=item.href: self.on_open_comic(href) if href else None)
                self._covers.append(cover)
                flow.addWidget(cover)
            self.layout.addWidget(flow_widget)
        else:
            self.layout.addWidget(EmptyLabel("暂无收藏。"))

        self.layout.addWidget(SectionHeader("浏览历史"))
        if page.history:
            for item in page.history[:10]:
                self.layout.addWidget(self._build_history_item(item))
        else:
            self.layout.addWidget(EmptyLabel("暂无浏览记录。"))
        self.layout.addStretch(1)

    def _build_history_item(self, item):
        row = QWidget()
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 14px;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(12)

        cover = CoverImage(item.cover_url, self.ctx.image_fetcher, radius=8)
        cover.setFixedSize(46, 64)
        self._covers.append(cover)
        row_layout.addWidget(cover)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        title = QLabel(item.title)
        title.setStyleSheet(f"color: {text_primary()}; font-size: 14px; font-weight: 600;")
        text_box.addWidget(title)
        if item.chapter_label:
            sub = QLabel(item.chapter_label)
            sub.setStyleSheet(f"color: {text_tertiary()}; font-size: 12px;")
            text_box.addWidget(sub)
        row_layout.addLayout(text_box, 1)

        row.mouseReleaseEvent = (lambda e: self.on_open_comic(item.href) if item.href else None)
        return row

    def _logout(self):
        self.ctx.session.clear()
        InfoBar.success("已退出", "已退出登录", parent=self, position=InfoBarPosition.TOP, duration=2000)
        self.load()


# ═══════════════════════════════════════════
#  设置页
# ═══════════════════════════════════════════
class _ProbeWorker(QThread):
    done = pyqtSignal(list)

    def __init__(self, hosts):
        super().__init__()
        self.hosts = hosts

    def run(self):
        try:
            results = self.hosts.probe_all()
            self.done.emit(results)
        except Exception:
            self.done.emit([])


class SettingsTab(EasyCopyScrollPage):
    """设置页：域名管理、网络、缓存、下载目录、关于。"""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._worker = None
        self.domain_edit = None

    def load(self, uri=None):
        self._build()

    def _build(self):
        self.clear()

        title = TitleLabel("设置", self)
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self.layout.addWidget(title)

        # ---- 下载目录 ----
        self.layout.addWidget(SectionHeader("下载目录"))
        dir_card = CardWidget(self)
        dir_card.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 16px;")
        dir_layout = QHBoxLayout(dir_card)
        dir_layout.setContentsMargins(16, 14, 16, 14)
        dir_label = BodyLabel("漫画下载保存位置", dir_card)
        dir_layout.addWidget(dir_label)
        dir_layout.addStretch(1)
        try:
            from services.easycopy.downloader import EasyCopyDownloader
            from services.easycopy.app import AppContext
            tmp_ctx = self.ctx if isinstance(self.ctx, AppContext) else None
            dl = EasyCopyDownloader(_dummy_config(), ctx=tmp_ctx)
            dir_text = dl.download_root()
        except Exception:
            dir_text = "data/easycopy-download"
        self.download_dir_label = CaptionLabel(dir_text, dir_card)
        self.download_dir_label.setStyleSheet(f"color: {text_tertiary()};")
        self.download_dir_label.setWordWrap(True)
        dir_layout.addWidget(self.download_dir_label, 1)
        self.layout.addWidget(dir_card)

        # ---- 网络 ----
        self.layout.addWidget(SectionHeader("网络"))
        net_card = CardWidget(self)
        net_card.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 16px;")
        net_layout = QHBoxLayout(net_card)
        net_layout.setContentsMargins(16, 14, 16, 14)
        net_label = BodyLabel("使用系统代理", net_card)
        net_layout.addWidget(net_label)
        net_layout.addStretch(1)
        self.proxy_switch = SwitchButton(net_card)
        self.proxy_switch.setChecked(bool(self.ctx.settings.get("use_proxy", True)))
        self.proxy_switch.checkedChanged.connect(self._on_proxy_toggled)
        net_layout.addWidget(self.proxy_switch)
        self.layout.addWidget(net_card)

        # ---- 域名管理 ----
        self.layout.addWidget(SectionHeader("域名管理"))
        domain_card = CardWidget(self)
        domain_card.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 16px;")
        domain_layout = QVBoxLayout(domain_card)
        domain_layout.setContentsMargins(16, 14, 16, 14)
        domain_layout.setSpacing(10)

        current_label = CaptionLabel(f"当前域名：{self.ctx.hosts.current_host}", domain_card)
        current_label.setStyleSheet("color: #28AFE9; font-weight: 600;")
        domain_layout.addWidget(current_label)

        for host in self.ctx.hosts.known_hosts:
            host_row = QWidget()
            host_layout = QHBoxLayout(host_row)
            host_layout.setContentsMargins(0, 0, 0, 0)
            host_layout.setSpacing(8)
            host_name = BodyLabel(host, host_row)
            host_name.setStyleSheet(f"color: {text_primary()};")
            host_layout.addWidget(host_name)
            host_layout.addStretch(1)
            use_btn = PushButton("使用", host_row)
            use_btn.clicked.connect(lambda checked=False, h=host: self._use_host(h))
            host_layout.addWidget(use_btn)
            del_btn = PushButton("删除", host_row)
            del_btn.clicked.connect(lambda checked=False, h=host: self._delete_host(h))
            host_layout.addWidget(del_btn)
            domain_layout.addWidget(host_row)

        add_row = QWidget()
        add_layout = QHBoxLayout(add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.setSpacing(8)
        self.domain_edit = QLineEdit(add_row)
        self.domain_edit.setPlaceholderText("输入域名，如 example.com")
        self.domain_edit.setFixedHeight(36)
        add_layout.addWidget(self.domain_edit, 1)
        add_btn = PrimaryPushButton("添加", add_row)
        add_btn.clicked.connect(self._add_host)
        add_layout.addWidget(add_btn)
        domain_layout.addWidget(add_row)
        self.layout.addWidget(domain_card)

        # ---- 网络诊断 ----
        self.layout.addWidget(SectionHeader("网络诊断"))
        diag_card = CardWidget(self)
        diag_card.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 16px;")
        diag_layout = QHBoxLayout(diag_card)
        diag_layout.setContentsMargins(16, 14, 16, 14)
        diag_label = BodyLabel("测试所有域名可达性", diag_card)
        diag_layout.addWidget(diag_label)
        diag_layout.addStretch(1)
        probe_btn = PrimaryPushButton("开始测速", diag_card)
        probe_btn.clicked.connect(self._probe)
        diag_layout.addWidget(probe_btn)
        self.layout.addWidget(diag_card)

        # ---- 缓存 ----
        self.layout.addWidget(SectionHeader("缓存"))
        cache_card = CardWidget(self)
        cache_card.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 16px;")
        cache_layout = QHBoxLayout(cache_card)
        cache_layout.setContentsMargins(16, 14, 16, 14)
        cache_label = BodyLabel("清除图片缓存", cache_card)
        cache_layout.addWidget(cache_label)
        cache_layout.addStretch(1)
        clear_btn = PushButton("清除", cache_card)
        clear_btn.clicked.connect(self._clear_cache)
        cache_layout.addWidget(clear_btn)
        self.layout.addWidget(cache_card)

        # ---- 关于 ----
        self.layout.addWidget(SectionHeader("关于"))
        about_label = BodyLabel(
            "拷贝漫画 · 基于 EasyCopy（2026copy 等站点）\n首页 / 发现 / 排行 / 我的 / 设置 · 支持章节下载",
            self,
        )
        about_label.setWordWrap(True)
        about_label.setStyleSheet(f"color: {text_secondary()};")
        self.layout.addWidget(about_label)

        self.layout.addStretch(1)

    # ---------------- 事件 ----------------
    def _on_proxy_toggled(self, checked: bool):
        self.ctx.settings.set("use_proxy", bool(checked))
        self.ctx.settings.save()
        InfoBar.success(
            "已保存", f"系统代理已{'开启' if checked else '关闭'}",
            parent=self, position=InfoBarPosition.TOP, duration=2000,
        )

    def _use_host(self, host: str):
        try:
            self.ctx.hosts.set_current_host(host)
            InfoBar.success("已切换", f"当前域名：{host}", parent=self, position=InfoBarPosition.TOP, duration=2000)
            self._build()
        except ValueError as e:
            InfoBar.error("错误", str(e), parent=self, position=InfoBarPosition.TOP, duration=2000)

    def _delete_host(self, host: str):
        try:
            self.ctx.hosts.delete_host(host)
            InfoBar.success("已删除", f"已删除域名：{host}", parent=self, position=InfoBarPosition.TOP, duration=2000)
            self._build()
        except ValueError as e:
            InfoBar.error("错误", str(e), parent=self, position=InfoBarPosition.TOP, duration=2000)

    def _add_host(self):
        value = (self.domain_edit.text() if self.domain_edit else "").strip()
        if not value:
            InfoBar.warning("提示", "请输入域名", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        try:
            host = self.ctx.hosts.add_custom_host(value)
            InfoBar.success("已添加", f"已添加域名：{host}", parent=self, position=InfoBarPosition.TOP, duration=2000)
            self.domain_edit.clear()
            self._build()
        except ValueError as e:
            InfoBar.error("错误", str(e), parent=self, position=InfoBarPosition.TOP, duration=3000)

    def _probe(self):
        self._worker = _ProbeWorker(self.ctx.hosts)
        self._worker.done.connect(self._on_probe_done)
        self._worker.start()
        InfoBar.info(
            "测速中", "正在测试域名可达性…", parent=self, position=InfoBarPosition.TOP, duration=1500
        )

    def _on_probe_done(self, results):
        if not results:
            InfoBar.warning("测速结果", "未能获取测速结果。", parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        best = results[0]
        lines = [f"最优：{best.host}（{best.latency_ms}ms）"]
        for p in results[:5]:
            status = "✓" if p.success else "✗"
            lines.append(f"{status} {p.host} · {p.latency_ms}ms")
        msg = "\n".join(lines)

        from qfluentwidgets import MessageBox
        box = MessageBox("测速结果", msg, self.window())
        box.cancelButton.hide()
        box.yesButton.setText("确定")
        box.exec_()

        if best.success:
            try:
                self.ctx.hosts.set_current_host(best.host)
                self._build()
            except ValueError:
                pass

    def _clear_cache(self):
        self.ctx.image_cache.clear()
        InfoBar.success("已清除", "图片缓存已清除。", parent=self, position=InfoBarPosition.TOP, duration=2000)


# ═══════════════════════════════════════════
#  搜索线程
# ═══════════════════════════════════════════
class _SearchWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, ctx, query, page):
        super().__init__()
        self.ctx = ctx
        self.query = query
        self.page = page

    def run(self):
        try:
            result = self.ctx.api.search(self.query, self.page)
            self.done.emit(("ok", result))
        except SiteApiException as e:
            self.done.emit(("error", str(e)))
        except Exception as e:
            self.done.emit(("error", f"搜索失败：{e}"))


def _dummy_config():
    from services.easycopy.downloader import EasyCopyDownloadConfig
    return EasyCopyDownloadConfig()
