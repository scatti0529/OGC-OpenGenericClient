# -*- coding: utf-8 -*-
"""
JMComic 漫画下载页面
====================
整合 OGC-jmcomic 全部功能到单个页面：
- 搜索浏览（搜索 / 排行榜 / 分类推荐）
- 下载中心（本子/章节下载 + 打包）
- 账号与收藏（登录/登出/收藏夹）
- 订阅管理
- 设置
使用 TabWidget 组织为单一页面，重构排版样式适配主程序。
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, CheckBox, ComboBox,
    FluentIcon as FIF, InfoBar, InfoBarPosition, LineEdit,
    MessageBox, PrimaryPushButton, ProgressBar, PushButton,
    ScrollArea, SpinBox, StrongBodyLabel, SubtitleLabel,
    SwitchButton, TitleLabel, TabWidget,
)

from services.jmcomic_service import (
    JMComicService, JMCOMIC_AVAILABLE,
    CATEGORY_LIST, ORDER_LIST, TIME_LIST, PACK_FORMATS,
    SEARCH_MODES, RANK_TYPES, JM_DEFAULTS,
)


# ═══════════════════════════════════════════════════════════
#  通用提示函数
# ═══════════════════════════════════════════════════════════

def show_info(widget, title, content="", duration=3000):
    return InfoBar.success(
        title=title, content=content, orient=Qt.Horizontal,
        isClosable=True, position=InfoBarPosition.TOP_RIGHT,
        duration=duration, parent=widget,
    )


def show_error(widget, title, content="", duration=5000):
    return InfoBar.error(
        title=title, content=content, orient=Qt.Horizontal,
        isClosable=True, position=InfoBarPosition.TOP_RIGHT,
        duration=duration, parent=widget,
    )


def show_warning(widget, title, content="", duration=4000):
    return InfoBar.warning(
        title=title, content=content, orient=Qt.Horizontal,
        isClosable=True, position=InfoBarPosition.TOP_RIGHT,
        duration=duration, parent=widget,
    )


# ═══════════════════════════════════════════════════════════
#  通用组件
# ═══════════════════════════════════════════════════════════

class MetaCard(CardWidget):
    """带标题的卡片容器"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.v_layout = QVBoxLayout(self)
        self.v_layout.setContentsMargins(16, 12, 16, 16)
        self.v_layout.setSpacing(12)
        self.title_label = SubtitleLabel(title, self)
        self.v_layout.addWidget(self.title_label)


class KeyValueRow(QWidget):
    """键值对一行"""

    def __init__(self, key, value="", parent=None):
        super().__init__(parent)
        self._h = QHBoxLayout(self)
        self._h.setContentsMargins(0, 0, 0, 0)
        self._h.setSpacing(8)
        self.key_label = StrongBodyLabel(key, self)
        self.key_label.setFixedWidth(90)
        self._h.addWidget(self.key_label)
        self.value_label = BodyLabel(value, self)
        self.value_label.setWordWrap(True)
        self._h.addWidget(self.value_label, 1)

    def set_value(self, value):
        self.value_label.setText(str(value))


class ResultCard(CardWidget):
    """搜索结果条目卡片"""

    def __init__(self, album, parent=None, on_click=None):
        super().__init__(parent)
        self.album = album
        self.on_click = on_click

        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 12, 16, 12)
        self.v.setSpacing(4)

        album_id = album.get('id', '?')
        title = album.get('title', '未知标题')
        author = album.get('author') or '未知作者'
        tags = album.get('tags') or []
        tag_text = '  '.join(tags[:4]) if tags else '无标签'

        row1 = QHBoxLayout()
        self.id_label = StrongBodyLabel(f'#{album_id}', self)
        self.title_label = SubtitleLabel(title, self)
        self.title_label.setWordWrap(True)
        row1.addWidget(self.id_label)
        row1.addWidget(self.title_label, 1)
        self.v.addLayout(row1)

        self.meta_label = CaptionLabel(f' 作者: {author}', self)
        self.v.addWidget(self.meta_label)

        self.tags_label = CaptionLabel(f' 标签: {tag_text}', self)
        self.tags_label.setWordWrap(True)
        self.v.addWidget(self.tags_label)

        if on_click is not None:
            self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if self.on_click is not None:
            self.on_click(self.album)
        super().mouseReleaseEvent(e)


# ═══════════════════════════════════════════════════════════
#  本子详情对话框
# ═══════════════════════════════════════════════════════════

class AlbumDetailDialog(QDialog):
    """本子详情对话框"""

    def __init__(self, album_id, service, parent=None):
        super().__init__(parent)
        self.album_id = album_id
        self.service = service
        self.detail = None

        self.setWindowTitle(f"本子详情 - {album_id}")
        self.setMinimumWidth(520)
        self.setMinimumHeight(480)
        self._build_content()
        self._load_detail()

    def _build_content(self):
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 20)
        self.root.setSpacing(12)

        self.title_label = TitleLabel("加载中...", self)
        self.title_label.setWordWrap(True)
        self.root.addWidget(self.title_label)

        self.id_label = CaptionLabel(f" ID: {self.album_id}", self)
        self.root.addWidget(self.id_label)

        info_card = MetaCard("详细信息", self)
        self.author_row = KeyValueRow("作者", "未知", info_card)
        self.chapter_row = KeyValueRow("章节数", "-", info_card)
        self.pub_row = KeyValueRow("发布日期", "-", info_card)
        self.update_row = KeyValueRow("更新日期", "-", info_card)
        self.likes_row = KeyValueRow("点赞", "-", info_card)
        self.views_row = KeyValueRow("浏览", "-", info_card)
        for row in (self.author_row, self.chapter_row, self.pub_row,
                    self.update_row, self.likes_row, self.views_row):
            info_card.v_layout.addWidget(row)
        self.root.addWidget(info_card)

        self.tags_label = BodyLabel("", self)
        self.tags_label.setWordWrap(True)
        self.root.addWidget(self.tags_label)

        self.desc_label = BodyLabel("", self)
        self.desc_label.setWordWrap(True)
        self.root.addWidget(self.desc_label)

        self.root.addStretch(1)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addWidget(BodyLabel("章节:", self))
        self.chapter_combo = ComboBox(self)
        self.chapter_combo.addItem("全部章节", userData=0)
        bottom_row.addWidget(self.chapter_combo)
        bottom_row.addStretch(1)

        self.download_btn = PrimaryPushButton(FIF.DOWNLOAD, "下载", self)
        self.download_btn.clicked.connect(self._on_download)
        bottom_row.addWidget(self.download_btn)
        self.root.addLayout(bottom_row)

    def _load_detail(self):
        if not JMCOMIC_AVAILABLE:
            show_error(self, "jmcomic 库未安装", "请先安装 jmcomic 以查看详情")
            self.title_label.setText("无法加载详情")
            return
        self.service.get_detail(
            self.album_id,
            on_done=self._on_detail_loaded,
            on_error=self._on_detail_error,
        )

    def _on_detail_loaded(self, detail):
        if not detail:
            show_error(self, "未找到该本子")
            self.title_label.setText(f"本子 {self.album_id} 不存在")
            return
        self.detail = detail
        self._render_detail(detail)

    def _on_detail_error(self, etype, emsg):
        show_error(self, "获取详情失败", emsg)
        self.title_label.setText("获取详情失败")

    def _render_detail(self, detail):
        self.title_label.setText(detail.get("title", "未知标题"))
        self.id_label.setText(f" ID: {detail.get('id', self.album_id)}")
        self.author_row.set_value(detail.get("author") or "未知")
        photo_count = int(detail.get("photo_count", 0) or 0)
        self.chapter_row.set_value(str(photo_count))
        self.pub_row.set_value(detail.get("pub_date") or "-")
        self.update_row.set_value(detail.get("update_date") or "-")
        self.likes_row.set_value(str(detail.get("likes") or 0))
        self.views_row.set_value(str(detail.get("views") or 0))

        tags = detail.get("tags") or []
        if tags:
            self.tags_label.setText(" " + "  ".join(tags[:8]))

        desc = detail.get("description") or ""
        if desc:
            self.desc_label.setText(desc)

        self.chapter_combo.clear()
        self.chapter_combo.addItem("全部章节 (整本)", userData=0)
        for i in range(1, photo_count + 1):
            self.chapter_combo.addItem(f"第 {i} 章", userData=i)

    def _on_download(self):
        if not self.detail:
            show_error(self, "请先加载详情")
            return
        chapter_idx = self.chapter_combo.currentData() or 0
        self.accept()

        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "switch_to_download"):
                parent.switch_to_download(
                    self.album_id,
                    chapter_idx if chapter_idx > 0 else None,
                )
                return
            parent = parent.parent()


# ═══════════════════════════════════════════════════════════
#  搜索浏览子页面
# ═══════════════════════════════════════════════════════════

class SearchTab(QWidget):
    """搜索与浏览子页面"""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.current_page = 1
        self.current_keyword = ""
        self.current_mode = "site"
        self._current_view = "search"
        self._init_ui()

    def _init_ui(self):
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 16)
        self.root.setSpacing(12)

        # 搜索栏
        search_card = MetaCard("搜索漫画", self)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(BodyLabel("模式:", self))
        self.mode_combo = ComboBox(self)
        for mode_id, mode_name in SEARCH_MODES:
            self.mode_combo.addItem(mode_name, userData=mode_id)
        self.mode_combo.setFixedWidth(100)
        row.addWidget(self.mode_combo)

        self.search_edit = LineEdit(self)
        self.search_edit.setPlaceholderText("输入关键词，支持标签/作者/角色/作品搜索...")
        self.search_edit.returnPressed.connect(self._do_search)
        row.addWidget(self.search_edit, 1)

        self.search_btn = PrimaryPushButton(FIF.SEARCH, "搜索", self)
        self.search_btn.clicked.connect(self._do_search)
        row.addWidget(self.search_btn)
        search_card.v_layout.addLayout(row)
        self.root.addWidget(search_card)

        # 排行榜 / 推荐
        browse_card = MetaCard("排行榜 / 推荐浏览", self)
        brow = QHBoxLayout()
        brow.setSpacing(8)
        brow.addWidget(BodyLabel("榜单:", self))
        self.rank_type_combo = ComboBox(self)
        for rid, rname in RANK_TYPES:
            self.rank_type_combo.addItem(rname, userData=rid)
        brow.addWidget(self.rank_type_combo)

        brow.addWidget(BodyLabel("分类:", self))
        self.rank_cat_combo = ComboBox(self)
        for cid, cname in CATEGORY_LIST:
            self.rank_cat_combo.addItem(cname, userData=cid)
        brow.addWidget(self.rank_cat_combo)

        rank_btn = PushButton(FIF.ALBUM, "查看榜单", self)
        rank_btn.clicked.connect(self._load_ranking)
        brow.addWidget(rank_btn)

        brow.addSpacing(4)
        brow.addWidget(BodyLabel("排序:", self))
        self.order_combo = ComboBox(self)
        for oid, oname in ORDER_LIST:
            self.order_combo.addItem(oname, userData=oid)
        brow.addWidget(self.order_combo)

        brow.addWidget(BodyLabel("时间:", self))
        self.time_combo = ComboBox(self)
        for tid, tname in TIME_LIST:
            self.time_combo.addItem(tname, userData=tid)
        brow.addWidget(self.time_combo)

        rec_btn = PushButton(FIF.ALBUM, "推荐浏览", self)
        rec_btn.clicked.connect(self._load_recommend)
        brow.addWidget(rec_btn)
        brow.addStretch(1)
        browse_card.v_layout.addLayout(brow)
        self.root.addWidget(browse_card)

        # 结果区域
        self.result_header = StrongBodyLabel("🔍 输入关键词搜索，或从上方浏览榜单与推荐", self)
        self.root.addWidget(self.result_header)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.root.addWidget(self.scroll, 1)

        self.scroll_content = QWidget()
        self.result_layout = QVBoxLayout(self.scroll_content)
        self.result_layout.setContentsMargins(0, 0, 8, 0)
        self.result_layout.setSpacing(8)
        self.result_layout.addStretch(1)
        self.scroll.setWidget(self.scroll_content)

        # 分页
        page_row = QHBoxLayout()
        self.prev_btn = PushButton("◀ 上一页", self)
        self.prev_btn.clicked.connect(self._prev_page)
        self.prev_btn.setEnabled(False)
        self.next_btn = PushButton("下一页 ▶", self)
        self.next_btn.clicked.connect(self._next_page)
        self.next_btn.setEnabled(False)
        self.page_label = BodyLabel("第 1 页", self)
        page_row.addStretch(1)
        page_row.addWidget(self.prev_btn)
        page_row.addWidget(self.page_label)
        page_row.addWidget(self.next_btn)
        page_row.addStretch(1)
        self.root.addLayout(page_row)

        self._show_empty_hint("开始搜索吧！")

    # ---------- 结果渲染 ----------
    def _clear_results(self):
        while self.result_layout.count() > 1:
            item = self.result_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _remove_stretch(self):
        while self.result_layout.count():
            item = self.result_layout.takeAt(self.result_layout.count() - 1)
            if item.spacerItem() is not None:
                return
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _show_empty_hint(self, text):
        self._clear_results()
        self._remove_stretch()
        self.result_layout.addStretch(1)
        hint = BodyLabel(text, self)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: #888888; padding: 40px;")
        self.result_layout.insertWidget(0, hint)

    def _render_results(self, results):
        self._clear_results()
        self._remove_stretch()
        if not results:
            self.result_layout.addStretch(1)
            hint = BodyLabel("😅 未找到相关结果", self)
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("color: #888888; padding: 40px;")
            self.result_layout.insertWidget(0, hint)
            return

        for album in results:
            card = ResultCard(album, self, on_click=lambda a: self._show_detail(a))
            self.result_layout.addWidget(card)
        self.result_layout.addStretch(1)

    def _set_result_header(self, text):
        self.result_header.setText(text)

    def _show_detail(self, album):
        dlg = AlbumDetailDialog(album.get("id", ""), self.service, self)
        dlg.exec_()

    # ---------- 搜索 ----------
    def _do_search(self):
        keyword = self.search_edit.text().strip()
        if not keyword:
            show_error(self, "请输入搜索关键词")
            return
        self.current_keyword = keyword
        self.current_mode = self.mode_combo.currentData() or "site"
        self.current_page = 1
        self._current_view = "search"
        self._run_search()

    def _run_search(self):
        if not JMCOMIC_AVAILABLE:
            show_error(self, "jmcomic 库未安装", "请先安装 jmcomic 以使用搜索功能")
            return
        self.search_btn.setEnabled(False)
        self._set_result_header(f"🔍 正在搜索【{self.current_keyword}】第 {self.current_page} 页...")
        self.service.search(
            self.current_keyword, self.current_page, self.current_mode,
            on_done=self._on_search_done, on_error=self._on_search_error,
        )

    def _on_search_done(self, results):
        self.search_btn.setEnabled(True)
        if not results:
            self._set_result_header(f"🔍 搜索【{self.current_keyword}】未找到结果")
            self._show_empty_hint("未找到相关结果")
        else:
            self._set_result_header(
                f"🔍 搜索【{self.current_keyword}】- 共 {len(results)} 个结果 (第 {self.current_page} 页)"
            )
            self._render_results(results)
        self._update_paging(results)

    def _on_search_error(self, etype, emsg):
        self.search_btn.setEnabled(True)
        show_error(self, "搜索失败", emsg)

    # ---------- 排行榜 ----------
    def _load_ranking(self):
        if not JMCOMIC_AVAILABLE:
            show_error(self, "jmcomic 库未安装", "请先安装 jmcomic 以使用排行榜")
            return
        rank_type = self.rank_type_combo.currentData() or "week"
        category = self.rank_cat_combo.currentData() or "all"
        self.current_page = 1
        self._current_view = "rank"
        self._set_result_header(f"🏆 正在获取排行榜 (第 {self.current_page} 页)...")
        self.service.get_ranking(
            rank_type, self.current_page, category,
            on_done=self._on_ranking_done, on_error=self._on_ranking_error,
        )

    def _on_ranking_done(self, results):
        if not results:
            self._set_result_header("🏆 暂无排行榜数据")
            self._show_empty_hint("暂无排行榜数据")
        else:
            self._set_result_header(f"🏆 榜单结果 (第 {self.current_page} 页)")
            self._render_results(results)
        self._update_paging(results)

    def _on_ranking_error(self, etype, emsg):
        show_error(self, "获取排行榜失败", emsg)

    # ---------- 推荐 ----------
    def _load_recommend(self):
        if not JMCOMIC_AVAILABLE:
            show_error(self, "jmcomic 库未安装", "请先安装 jmcomic 以使用推荐浏览")
            return
        category = self.rank_cat_combo.currentData() or "all"
        order_by = self.order_combo.currentData() or "hot"
        time_range = self.time_combo.currentData() or "week"
        self.current_page = 1
        self._current_view = "recommend"
        self._set_result_header(f"🎯 正在获取推荐内容 (第 {self.current_page} 页)...")
        self.service.get_category_albums(
            category, order_by, time_range, self.current_page,
            on_done=self._on_recommend_done, on_error=self._on_recommend_error,
        )

    def _on_recommend_done(self, results):
        if not results:
            self._set_result_header("🎯 暂无推荐内容")
            self._show_empty_hint("暂无推荐内容，可尝试更换分类或扩大时间范围")
        else:
            self._set_result_header(f"🎯 推荐结果 (第 {self.current_page} 页)")
            self._render_results(results)
        self._update_paging(results)

    def _on_recommend_error(self, etype, emsg):
        show_error(self, "获取推荐内容失败", emsg)

    # ---------- 分页 ----------
    def _update_paging(self, results):
        self.page_label.setText(f"第 {self.current_page} 页")
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(bool(results))

    def _prev_page(self):
        if self.current_page <= 1:
            return
        self.current_page -= 1
        self._reload_current()

    def _next_page(self):
        self.current_page += 1
        self._reload_current()

    def _reload_current(self):
        if self._current_view == "search" and self.current_keyword:
            self._run_search()
        elif self._current_view == "rank":
            self._load_ranking()
        elif self._current_view == "recommend":
            self._load_recommend()


# ═══════════════════════════════════════════════════════════
#  下载中心子页面
# ═══════════════════════════════════════════════════════════

class DownloadTab(QWidget):
    """下载中心子页面"""

    pack_finished = pyqtSignal(object, object)
    pack_error = pyqtSignal(str, str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._task = None
        self._init_ui()
        self.pack_finished.connect(self._on_pack_done)
        self.pack_error.connect(self._on_pack_error)

    def _init_ui(self):
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 16)
        self.root.setSpacing(12)

        # 下载输入
        input_card = MetaCard("下载本子", self)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(BodyLabel("本子ID:", self))
        self.album_edit = LineEdit(self)
        self.album_edit.setPlaceholderText("输入本子ID，例如 123456")
        self.album_edit.setFixedWidth(180)
        self.album_edit.returnPressed.connect(self._start_download)
        row.addWidget(self.album_edit)

        row.addWidget(BodyLabel("章节:", self))
        self.chapter_combo = ComboBox(self)
        self.chapter_combo.addItem("全部章节", userData=0)
        row.addWidget(self.chapter_combo)

        self.download_btn = PrimaryPushButton(FIF.DOWNLOAD, "开始下载", self)
        self.download_btn.clicked.connect(self._start_download)
        row.addWidget(self.download_btn)
        row.addStretch(1)
        input_card.v_layout.addLayout(row)
        self.root.addWidget(input_card)

        # 打包设置
        pack_card = MetaCard("打包设置", self)
        pack_row = QHBoxLayout()
        pack_row.setSpacing(8)
        pack_row.addWidget(BodyLabel("打包格式:", self))
        self.pack_combo = ComboBox(self)
        for fmid, fmname in PACK_FORMATS:
            self.pack_combo.addItem(fmname, userData=fmid)
        pack_row.addWidget(self.pack_combo)

        pack_row.addWidget(BodyLabel("密码:", self))
        self.pass_edit = LineEdit(self)
        self.pass_edit.setPlaceholderText("留空不加密")
        self.pass_edit.setFixedWidth(160)
        pack_row.addWidget(self.pass_edit)

        self.show_pw_check = CheckBox("文件名显示密码", self)
        pack_row.addWidget(self.show_pw_check)
        pack_row.addStretch(1)
        pack_card.v_layout.addLayout(pack_row)
        self.root.addWidget(pack_card)

        # 进度区
        self.progress_card = MetaCard("下载进度", self)
        self.status_label = CaptionLabel("等待下载任务", self)
        self.progress_card.v_layout.addWidget(self.status_label)

        self.progress_bar = ProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_card.v_layout.addWidget(self.progress_bar)

        self.progress_text = CaptionLabel("", self)
        self.progress_card.v_layout.addWidget(self.progress_text)
        self.root.addWidget(self.progress_card)

        # 结果区
        self.result_card = MetaCard("下载结果", self)
        self.result_card.v_layout.addWidget(CaptionLabel("暂无下载任务", self))
        self._result_row_host = QWidget(self)
        self._result_row = QVBoxLayout(self._result_row_host)
        self._result_row.setContentsMargins(0, 0, 0, 0)
        self._result_row.setSpacing(4)
        self.result_card.v_layout.addWidget(self._result_row_host)
        self.root.addWidget(self.result_card)

        self.root.addStretch(1)

    # ---------- 对外接口 ----------
    def submit_download(self, album_id, chapter_idx=None):
        """发起下载。chapter_idx 为 None=全部；>0 表示下载指定章节或跳过 N 章"""
        self.album_edit.setText(album_id)
        if chapter_idx is not None and chapter_idx > 0:
            for i in range(self.chapter_combo.count()):
                if self.chapter_combo.itemData(i) == chapter_idx:
                    self.chapter_combo.setCurrentIndex(i)
                    break
        self._start_download()

    # ---------- 下载流程 ----------
    def _start_download(self):
        if self._task is not None:
            try:
                if self._task.isRunning():
                    show_warning(self, "已有下载任务进行中", "请等待当前任务完成")
                    return
            except RuntimeError:
                self._task = None
            except Exception:
                pass

        album_id = self.album_edit.text().strip()
        if not album_id.isdigit():
            show_error(self, "本子ID无效", "请输入正确的数字ID")
            return
        if not JMCOMIC_AVAILABLE:
            show_error(self, "jmcomic 库未安装", "请先安装 jmcomic 以使用下载功能")
            return

        chapter_idx = self.chapter_combo.currentData() or 0
        chapter_idx = chapter_idx if chapter_idx > 0 else None

        self.download_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_text.setText("")
        if chapter_idx:
            self.status_label.setText(f"⏳ 开始下载本子 {album_id} 第 {chapter_idx} 章...")
        else:
            self.status_label.setText(f"⏳ 开始下载本子 {album_id} ...")

        self._task = self.service.download(
            album_id, 0, chapter_idx,
            on_progress=self._on_progress,
            on_done=self._on_download_done,
            on_error=self._on_download_error,
        )

    def _on_progress(self, done, total, unit):
        if total > 0:
            percent = int(done * 100 / total)
            self.progress_bar.setValue(percent)
            self.progress_text.setText(f"{done}/{total} {unit} · {percent}%")
            self.status_label.setText("⏳ 下载中...")

    def _on_download_done(self, result):
        self._task = None
        self.download_btn.setEnabled(True)

        if not result.success:
            self.status_label.setText(f"❌ 下载失败: {result.error_message}")
            show_error(self, "下载失败", result.error_message or "")
            return

        self.status_label.setText("✅ 下载完成，正在打包...")
        self.progress_text.setText(f"章节: {result.photo_count} · 图片: {result.image_count}")

        if not getattr(result, "all_success", True):
            failed = getattr(result, "failed_images", 0)
            show_warning(self, "下载部分失败",
                         f"有 {failed} 张图片/章节下载失败" if failed else "下载可能不完整")

        threading.Thread(target=self._pack_in_thread, args=(result,), daemon=True).start()

    def _on_download_error(self, etype, emsg):
        self._task = None
        self.download_btn.setEnabled(True)
        self.status_label.setText(f"❌ 下载失败: {emsg}")
        show_error(self, "下载失败", emsg)

    # ---------- 打包 ----------
    def _pack_in_thread(self, result):
        try:
            album_id = result.album_id
            pack_format = self.pack_combo.currentData() or "zip"
            password = self.pass_edit.text().strip()
            show_pw = self.show_pw_check.isChecked()
            output_name = self.service.generate_filename(album_id, password, None, show_pw)
            pack_result = self.service.pack(result.save_path, output_name, pack_format, password)
            self.pack_finished.emit(result, pack_result)
        except Exception as e:
            self.pack_error.emit("打包失败", str(e))

    def _on_pack_error(self, title, message):
        self.status_label.setText(f"❌ {title}: {message}")
        show_error(self, title, message)

    def _on_pack_done(self, result, pack_result):
        self.status_label.setText("✅ 打包完成")
        self.progress_bar.setValue(100)
        self._render_result(result, pack_result)

    # ---------- 结果展示 ----------
    def _render_result(self, result, pack_result):
        while self._result_row.count():
            item = self._result_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        info = [
            ("标题", result.title or "未知"),
            ("作者", result.author or "未知"),
            ("章节数", str(result.photo_count)),
            ("图片数", str(result.image_count)),
        ]
        for key, val in info:
            self._result_row.addWidget(KeyValueRow(key, val))

        if pack_result is not None:
            fmt_name = {fid: fname for fid, fname in PACK_FORMATS}.get(pack_result.format, pack_result.format)

            if pack_result.success:
                self._result_row.addWidget(KeyValueRow("打包格式", fmt_name))
                if pack_result.encrypted:
                    self._result_row.addWidget(KeyValueRow("加密", "🔐 已加密"))
                if pack_result.format != "none" and pack_result.output_path:
                    self._result_row.addWidget(KeyValueRow("保存路径", str(pack_result.output_path)))
                    btn_row = QHBoxLayout()
                    open_btn = PushButton("📂 打开所在文件夹", self)
                    output_path = pack_result.output_path
                    open_btn.clicked.connect(lambda _=False, p=output_path: self._open_folder(p))
                    btn_row.addWidget(open_btn)
                    btn_row.addStretch(1)
                    self._result_row.addLayout(btn_row)
            else:
                self._result_row.addWidget(KeyValueRow("打包失败", pack_result.error_message or "未知错误"))
                show_error(self, "打包失败", pack_result.error_message or "")

        show_info(self, "下载完成", "本子下载成功")

    def _open_folder(self, path):
        try:
            import subprocess
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                folder = str(path.parent if path.is_file() else path)
                if sys.platform == "darwin":
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            show_error(self, "无法打开文件夹", str(e))


# ═══════════════════════════════════════════════════════════
#  账号与收藏子页面
# ═══════════════════════════════════════════════════════════

class AccountTab(QWidget):
    """账号与收藏子页面"""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.current_page = 1
        self._init_ui()

    def _init_ui(self):
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 16)
        self.root.setSpacing(12)

        # 登录卡片
        login_card = MetaCard("JM 账号登录", self)
        self.status_row = KeyValueRow("登录状态", "未登录", login_card)
        login_card.v_layout.addWidget(self.status_row)

        self.user_row = KeyValueRow("用户名", "-", login_card)
        self.user_row.setVisible(False)
        login_card.v_layout.addWidget(self.user_row)

        cred_row = QHBoxLayout()
        cred_row.setSpacing(8)
        cred_row.addWidget(BodyLabel("用户名:", self))
        self.username_edit = LineEdit(self)
        self.username_edit.setPlaceholderText("JM 账号")
        self.username_edit.setFixedWidth(180)
        cred_row.addWidget(self.username_edit)

        cred_row.addWidget(BodyLabel("密码:", self))
        self.password_edit = LineEdit(self)
        self.password_edit.setPlaceholderText("JM 密码")
        self.password_edit.setFixedWidth(180)
        self.password_edit.setEchoMode(LineEdit.Password)
        cred_row.addWidget(self.password_edit)

        self.login_btn = PrimaryPushButton(FIF.PEOPLE, "登录", self)
        self.login_btn.clicked.connect(self._do_login)
        cred_row.addWidget(self.login_btn)

        self.logout_btn = PushButton("登出", self)
        self.logout_btn.clicked.connect(self._do_logout)
        cred_row.addWidget(self.logout_btn)

        login_card.v_layout.addLayout(cred_row)
        self.root.addWidget(login_card)

        # 收藏卡片
        fav_card = MetaCard("我的收藏", self)
        fav_row = QHBoxLayout()
        self.refresh_btn = PushButton(FIF.SYNC, "刷新收藏", self)
        self.refresh_btn.clicked.connect(self._load_favorites)
        fav_row.addWidget(self.refresh_btn)
        fav_row.addStretch(1)

        self.prev_btn = PushButton("◀ 上一页", self)
        self.prev_btn.clicked.connect(self._prev_page)
        self.prev_btn.setEnabled(False)
        self.next_btn = PushButton("下一页 ▶", self)
        self.next_btn.clicked.connect(self._next_page)
        self.next_btn.setEnabled(False)
        self.page_label = BodyLabel("第 1 页", self)
        fav_row.addWidget(self.prev_btn)
        fav_row.addWidget(self.page_label)
        fav_row.addWidget(self.next_btn)
        fav_card.v_layout.addLayout(fav_row)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(300)
        fav_card.v_layout.addWidget(self.scroll)

        self.scroll_content = QWidget()
        self.fav_layout = QVBoxLayout(self.scroll_content)
        self.fav_layout.setContentsMargins(0, 0, 8, 0)
        self.fav_layout.setSpacing(6)
        self.fav_layout.addStretch(1)
        self.scroll.setWidget(self.scroll_content)

        self.root.addWidget(fav_card)
        self.root.addStretch(1)

        self._refresh_login_status()

    def _refresh_login_status(self):
        status = self.service.auth.get_login_status()
        if status["logged_in"]:
            self.status_row.set_value("✅ 已登录")
            self.user_row.set_value(status.get("username") or "-")
            self.user_row.setVisible(True)
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
        else:
            self.status_row.set_value("❌ 未登录")
            self.user_row.setVisible(False)
            self.login_btn.setEnabled(True)
            self.logout_btn.setEnabled(False)

    def _do_login(self):
        if not JMCOMIC_AVAILABLE:
            show_error(self, "jmcomic 库未安装", "请先安装 jmcomic 以使用登录功能")
            return
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            show_error(self, "请输入用户名和密码")
            return
        self.login_btn.setEnabled(False)
        self.service.login(username, password,
                           on_done=self._on_login_done, on_error=self._on_login_error)

    def _on_login_done(self, result):
        success, message = result
        self.login_btn.setEnabled(True)
        if success:
            show_info(self, "登录成功", message)
            self._refresh_login_status()
            self._load_favorites()
        else:
            show_error(self, "登录失败", message)

    def _on_login_error(self, etype, emsg):
        self.login_btn.setEnabled(True)
        show_error(self, "登录失败", emsg)

    def _do_logout(self):
        success, message = self.service.auth.logout()
        if success:
            show_info(self, "已登出", message)
        else:
            show_info(self, "提示", message)
        self._refresh_login_status()
        self._clear_favorites()

    def _load_favorites(self):
        """刷新收藏前先验证会话有效性，无效则自动重新登录"""
        status = self.service.auth.get_login_status()
        if not status["logged_in"]:
            show_error(self, "未登录", "请先登录后再查看收藏")
            return

        self.refresh_btn.setEnabled(False)
        self.service.ensure_valid_session(
            on_done=self._on_session_checked,
            on_error=self._on_session_check_error,
        )

    def _on_session_checked(self, result):
        """会话检查完成：成功则继续加载收藏，失败则提示"""
        success, message = result
        if not success:
            self.refresh_btn.setEnabled(True)
            # 刷新登录状态显示
            self._refresh_login_status()
            show_error(self, "登录状态已失效", message)
            return

        # 会话有效，继续加载收藏
        status = self.service.auth.get_login_status()
        client = self.service.auth.get_client()
        username = status.get("username") or ""
        self.service.get_favorites(
            client, self.current_page, "0", username,
            on_done=self._on_favorites_done, on_error=self._on_favorites_error,
        )

    def _on_session_check_error(self, etype, emsg):
        self.refresh_btn.setEnabled(True)
        show_error(self, "会话验证失败", emsg)

    def _on_favorites_done(self, result):
        self.refresh_btn.setEnabled(True)
        albums, folders = result
        self._render_favorites(albums, folders)

    def _on_favorites_error(self, etype, emsg):
        self.refresh_btn.setEnabled(True)
        # 收藏获取失败时检查是否是登录问题
        if "登录" in str(emsg) or "未登录" in str(emsg) or "fav" in str(emsg).lower():
            show_error(self, "收藏获取失败", "登录状态可能已失效，请重新登录")
            self._refresh_login_status()
        else:
            show_error(self, "收藏获取失败", emsg)

    def _render_favorites(self, albums, folders):
        while self.fav_layout.count():
            item = self.fav_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not albums:
            self.fav_layout.addStretch(1)
            hint = BodyLabel("📭 收藏夹为空", self)
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("color: #888888; padding: 20px;")
            self.fav_layout.insertWidget(0, hint)
            self.next_btn.setEnabled(False)
            return

        for album in albums:
            card = ResultCard(album, self, on_click=lambda a: self._show_detail(a))
            self.fav_layout.addWidget(card)

        self.fav_layout.addStretch(1)
        self.page_label.setText(f"第 {self.current_page} 页")
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(bool(albums))

    def _clear_favorites(self):
        while self.fav_layout.count():
            item = self.fav_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.fav_layout.addStretch(1)

    def _show_detail(self, album):
        dlg = AlbumDetailDialog(album.get("id", ""), self.service, self)
        dlg.exec_()

    def _prev_page(self):
        if self.current_page <= 1:
            return
        self.current_page -= 1
        self._load_favorites()

    def _next_page(self):
        self.current_page += 1
        self._load_favorites()


# ═══════════════════════════════════════════════════════════
#  订阅管理子页面
# ═══════════════════════════════════════════════════════════

class SubscriptionCard(MetaCard):
    """单个订阅条目卡片"""

    def __init__(self, sub, parent=None, on_delete=None, on_update=None):
        super().__init__(f"【{sub.get('album_id', '?')}】{sub.get('title') or '未知'}", parent)
        self.sub = sub
        self.on_delete = on_delete
        self.on_update = on_update

        self.count_row = KeyValueRow("已记录章节", str(sub.get("last_count", 0)), self)
        self.v_layout.addWidget(self.count_row)

        btn_row = QHBoxLayout()
        self.update_btn = PushButton(FIF.DOWNLOAD, "下载更新", self)
        self.update_btn.clicked.connect(self._on_update)
        btn_row.addWidget(self.update_btn)

        self.delete_btn = PushButton(FIF.DELETE, "取消订阅", self)
        self.delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self.delete_btn)

        btn_row.addStretch(1)
        self.v_layout.addLayout(btn_row)

    def _on_update(self):
        if self.on_update is not None:
            self.on_update(self.sub)

    def _on_delete(self):
        if self.on_delete is not None:
            self.on_delete(self.sub)


class SubscribeTab(QWidget):
    """订阅管理子页面"""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._init_ui()
        self._refresh()

    def _init_ui(self):
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 16)
        self.root.setSpacing(12)

        add_card = MetaCard("订阅本子", self)
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        add_row.addWidget(BodyLabel("本子ID:", self))
        self.album_edit = LineEdit(self)
        self.album_edit.setPlaceholderText("输入本子ID，例如 123456")
        self.album_edit.setFixedWidth(180)
        self.album_edit.returnPressed.connect(self._do_subscribe)
        add_row.addWidget(self.album_edit)

        self.subscribe_btn = PrimaryPushButton(FIF.BOOK_SHELF, "订阅", self)
        self.subscribe_btn.clicked.connect(self._do_subscribe)
        add_row.addWidget(self.subscribe_btn)

        self.refresh_btn = PushButton(FIF.SYNC, "刷新", self)
        self.refresh_btn.clicked.connect(self._refresh)
        add_row.addWidget(self.refresh_btn)

        add_row.addStretch(1)
        add_card.v_layout.addLayout(add_row)
        self.root.addWidget(add_card)

        self.list_card = MetaCard("当前订阅", self)
        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_card.v_layout.addWidget(self.scroll)

        self.scroll_content = QWidget()
        self.list_layout = QVBoxLayout(self.scroll_content)
        self.list_layout.setContentsMargins(0, 0, 8, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.scroll_content)

        self.root.addWidget(self.list_card, 1)

    def _current_subs(self):
        return self.service.subscribe.list_for("gui:main")

    def _refresh(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        subs = self._current_subs()
        if not subs:
            self.list_layout.addStretch(1)
            hint = BodyLabel("📭 暂无订阅", self)
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("color: #888888; padding: 20px;")
            self.list_layout.insertWidget(0, hint)
            return

        for sub in subs:
            card = SubscriptionCard(sub, self,
                                    on_delete=self._do_unsubscribe,
                                    on_update=self._do_update_download)
            self.list_layout.addWidget(card)
        self.list_layout.addStretch(1)

    def _do_subscribe(self):
        album_id = self.album_edit.text().strip()
        if not album_id.isdigit():
            show_error(self, "本子ID无效", "请输入正确的数字ID")
            return
        if not JMCOMIC_AVAILABLE:
            show_error(self, "jmcomic 库未安装", "请先安装 jmcomic 以使用订阅功能")
            return

        self.subscribe_btn.setEnabled(False)
        self.service.get_detail(
            album_id,
            on_done=lambda detail: self._on_detail_for_sub(detail, album_id),
            on_error=self._on_sub_error,
        )

    def _on_detail_for_sub(self, detail, album_id):
        self.subscribe_btn.setEnabled(True)
        if not detail:
            show_error(self, "未找到该本子", "请检查本子ID是否正确")
            return

        title = detail.get("title", "")
        photo_count = int(detail.get("photo_count", 0) or 0)
        ok = self.service.subscribe.add("gui:main", album_id, "local", title, photo_count)
        if ok:
            show_info(self, "订阅成功", f"已订阅 【{album_id}】{title}")
        else:
            show_error(self, "订阅失败", "请稍后重试")
        self.album_edit.clear()
        self._refresh()

    def _on_sub_error(self, etype, emsg):
        self.subscribe_btn.setEnabled(True)
        show_error(self, "订阅失败", emsg)

    def _do_unsubscribe(self, sub):
        album_id = sub.get("album_id", "")
        if self.service.subscribe.remove("gui:main", album_id):
            show_info(self, "已取消订阅", f"已取消订阅本子 {album_id}")
        else:
            show_info(self, "提示", "该本子未被订阅")
        self._refresh()

    def _do_update_download(self, sub):
        """下载订阅的新章节（跳过已下载章节）"""
        album_id = sub.get("album_id", "")
        last_count = int(sub.get("last_count", 0) or 0)
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "switch_to_download"):
                parent.switch_to_download(album_id, last_count)
                return
            parent = parent.parent()


# ═══════════════════════════════════════════════════════════
#  设置子页面
# ═══════════════════════════════════════════════════════════

class SettingRow(QWidget):
    """单条配置行"""

    def __init__(self, key, title, desc, parent=None):
        super().__init__(parent)
        self.key = key
        self._h = QHBoxLayout(self)
        self._h.setContentsMargins(0, 0, 0, 0)
        self._h.setSpacing(12)

        self.title_label = BodyLabel(title, self)
        self.title_label.setFixedWidth(150)
        self._h.addWidget(self.title_label)

        self.desc_label = CaptionLabel(desc, self)
        self.desc_label.setWordWrap(True)
        self._h.addWidget(self.desc_label, 1)

        self._control_widget = None

    def set_control(self, widget):
        if self._control_widget is not None:
            self._h.removeWidget(self._control_widget)
        self._control_widget = widget
        self._h.addWidget(widget)


class SettingsTab(QWidget):
    """设置子页面"""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._rows = []
        self._init_ui()

    def _init_ui(self):
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 16)
        self.root.setSpacing(12)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.root.addWidget(scroll, 1)

        content = QWidget()
        self.v = QVBoxLayout(content)
        self.v.setContentsMargins(0, 0, 8, 0)
        self.v.setSpacing(12)
        scroll.setWidget(content)

        # 基本设置
        base_card = MetaCard("基本设置", self)
        self._add_text(base_card, "download_dir", "下载目录", "漫画保存路径", browse=True)
        self._add_combo(base_card, "image_suffix", "图片格式", "下载图片的格式", [".jpg", ".png", ".webp"])
        self._add_combo(base_card, "client_type", "客户端类型", "api 兼容性好；html 效率高但限制 IP 地区",
                        ["api", "html"])
        self._add_text(base_card, "client_domain", "自定义域名", "逗号分隔的 JM 域名，留空自动选择")
        self._add_spin(base_card, "retry_times", "请求重试次数", "0 = 使用 jmcomic 默认值(5)", 0, 20)
        self.v.addWidget(base_card)

        # 网络代理
        proxy_card = MetaCard("网络代理", self)
        self._add_bool(proxy_card, "use_proxy", "使用代理", "开启后使用下方代理地址")
        self._add_text(proxy_card, "proxy_url", "代理地址", "格式: http://host:port 或 socks5://host:port")
        self.v.addWidget(proxy_card)

        # 并发与下载
        dl_card = MetaCard("并发与下载", self)
        self._add_spin(dl_card, "max_concurrent_photos", "最大并发章节数", "同时下载的章节数量，建议 3-5", 1, 20)
        self._add_spin(dl_card, "max_concurrent_images", "最大并发图片数", "每章节同时下载的图片数量，建议 5-10", 1, 30)
        self._add_spin(dl_card, "search_page_size", "结果每页数量", "搜索/榜单每页返回数量", 1, 50)
        self._add_spin(dl_card, "daily_download_limit", "每日下载限制", "每用户每日下载次数，0=不限制", 0, 1000)
        self.v.addWidget(dl_card)

        # 打包设置
        pack_card = MetaCard("打包设置", self)
        self._add_combo(pack_card, "pack_format", "打包格式", "下载完成后的打包格式",
                        ["zip", "pdf", "long_img", "none"],
                        labels={"zip": "ZIP 压缩包", "pdf": "PDF 文档",
                                "long_img": "长图", "none": "不打包"})
        self._add_text(pack_card, "pack_password", "打包密码", "ZIP/PDF 加密密码，留空不加密", password=True)
        self._add_bool(pack_card, "filename_show_password", "文件名显示密码", "在文件名末尾添加 #PWxxx 提示")
        self._add_bool(pack_card, "auto_delete_after_send", "下载后自动清理", "打包完成后自动删除本地缓存目录")
        self.v.addWidget(pack_card)

        # JM 账号
        acct_card = MetaCard("JM 账号（用于自动登录）", self)
        self._add_text(acct_card, "jm_username", "用户名", "JM 账号用户名（可选）")
        self._add_text(acct_card, "jm_password", "密码", "JM 账号密码（可选）", password=True)
        self.v.addWidget(acct_card)

        # 订阅与调试
        misc_card = MetaCard("订阅与调试", self)
        self._add_spin(misc_card, "subscribe_check_interval", "订阅检查间隔(秒)", "后台检查订阅更新的间隔，0=关闭", 0, 86400)
        self._add_bool(misc_card, "debug_mode", "调试模式", "输出详细的调试日志")
        self.v.addWidget(misc_card)

        # 操作按钮
        btn_row = QHBoxLayout()
        self.save_btn = PrimaryPushButton("💾 保存设置", self)
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)

        self.reset_btn = PushButton("↺ 恢复默认", self)
        self.reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(self.reset_btn)

        btn_row.addStretch(1)
        self.v.addLayout(btn_row)
        self.v.addStretch(1)

    # ---------- 控件创建 ----------
    def _add_text(self, card, key, title, desc, browse=False, password=False):
        row = SettingRow(key, title, desc, card)
        edit = LineEdit(card)
        if password:
            edit.setEchoMode(LineEdit.Password)
        if browse:
            wrapper = QWidget(card)
            wl = QHBoxLayout(wrapper)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(4)
            edit.setFixedWidth(280)
            wl.addWidget(edit)
            btn = PushButton("浏览...", card)
            btn.setFixedWidth(70)
            btn.clicked.connect(lambda _=False, e=edit: self._browse(e))
            wl.addWidget(btn)
            row.set_control(wrapper)
        else:
            edit.setFixedWidth(280)
            row.set_control(edit)
        card.v_layout.addWidget(row)
        self._rows.append(row)
        row._control = edit
        return row

    def _add_combo(self, card, key, title, desc, options, labels=None):
        row = SettingRow(key, title, desc, card)
        combo = ComboBox(card)
        labels = labels or {o: o for o in options}
        for opt in options:
            combo.addItem(labels.get(opt, opt), userData=opt)
        combo.setFixedWidth(160)
        row.set_control(combo)
        card.v_layout.addWidget(row)
        self._rows.append(row)
        row._control = combo
        return row

    def _add_spin(self, card, key, title, desc, minimum, maximum):
        row = SettingRow(key, title, desc, card)
        spin = SpinBox(card)
        spin.setRange(minimum, maximum)
        spin.setFixedWidth(110)
        row.set_control(spin)
        card.v_layout.addWidget(row)
        self._rows.append(row)
        row._control = spin
        return row

    def _add_bool(self, card, key, title, desc):
        row = SettingRow(key, title, desc, card)
        switch = SwitchButton(card)
        row.set_control(switch)
        card.v_layout.addWidget(row)
        self._rows.append(row)
        row._control = switch
        return row

    # ---------- 加载 / 保存 ----------
    def _load_values(self):
        settings = self.service.config.plugin_config
        for row in self._rows:
            key = row.key
            control = row._control
            value = settings.get(key, JM_DEFAULTS.get(key))

            if isinstance(control, LineEdit):
                control.setText(str(value) if value is not None else "")
            elif isinstance(control, ComboBox):
                idx = control.findData(value)
                if idx >= 0:
                    control.setCurrentIndex(idx)
            elif isinstance(control, SpinBox):
                try:
                    control.setValue(int(value))
                except (TypeError, ValueError):
                    control.setValue(control.minimum())
            elif isinstance(control, SwitchButton):
                control.setChecked(bool(value))

    def _collect_values(self):
        values = {}
        for row in self._rows:
            key = row.key
            control = row._control
            if isinstance(control, LineEdit):
                values[key] = control.text().strip()
            elif isinstance(control, ComboBox):
                values[key] = control.currentData()
            elif isinstance(control, SpinBox):
                values[key] = control.value()
            elif isinstance(control, SwitchButton):
                values[key] = control.isChecked()
        return values

    def _save(self):
        values = self._collect_values()
        self.service.save_settings(values)
        show_info(self, "设置已保存", "所有配置已保存")

    def _reset_defaults(self):
        dlg = MessageBox("恢复默认设置", "确定要恢复所有设置为默认值吗？", self)
        if dlg.exec():
            self.service.save_settings(dict(JM_DEFAULTS))
            self._load_values()
            show_info(self, "已恢复默认", "所有设置已恢复为默认值")

    def _browse(self, edit):
        folder = QFileDialog.getExistingDirectory(self, "选择下载目录", edit.text() or "")
        if folder:
            edit.setText(folder)

    def showEvent(self, e):
        super().showEvent(e)
        self._load_values()


# ═══════════════════════════════════════════════════════════
#  JMComic 主页面（整合所有功能）
# ═══════════════════════════════════════════════════════════

class JmComicPage(QWidget):
    """JMComic 漫画下载主页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("jmcomicPage")

        # 初始化服务
        self.service = JMComicService(parent=self)

        self._init_ui()

    def _init_ui(self):
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)

        # 页面标题
        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 16, 24, 8)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = TitleLabel("JMComic 漫画下载", self)
        title_col.addWidget(title)
        subtitle = CaptionLabel("搜索 · 下载 · 打包 · 订阅 · 账号管理", self)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch(1)
        self.root.addWidget(header)

        # 选项卡
        self.tabs = TabWidget(self)
        self.tabs.setMovable(False)
        self.tabs.setTabsClosable(False)
        self.root.addWidget(self.tabs, 1)

        # 创建子页面
        self.search_tab = SearchTab(self.service, self)
        self.download_tab = DownloadTab(self.service, self)
        self.account_tab = AccountTab(self.service, self)
        self.subscribe_tab = SubscribeTab(self.service, self)
        self.settings_tab = SettingsTab(self.service, self)

        # 添加选项卡
        self.tabs.addTab(self.search_tab, "搜索与浏览", FIF.SEARCH)
        self.tabs.addTab(self.download_tab, "下载中心", FIF.DOWNLOAD)
        self.tabs.addTab(self.account_tab, "账号与收藏", FIF.PEOPLE)
        self.tabs.addTab(self.subscribe_tab, "订阅管理", FIF.BOOK_SHELF)
        self.tabs.addTab(self.settings_tab, "设置", FIF.SETTING)

    # ---------- 对外接口 ----------
    def switch_to_download(self, album_id, chapter_idx=None):
        """切换到下载中心并发起下载

        album_id: 本子ID
        chapter_idx: 为 None 时下载全部；>0 时选择对应章节/跳过N章
        """
        self.download_tab.album_edit.setText(album_id)
        self.download_tab.submit_download(album_id, chapter_idx)

    def closeEvent(self, e):
        """关闭时清理后台任务"""
        try:
            self.service.stop_all_tasks()
        except Exception:
            pass
        super().closeEvent(e)