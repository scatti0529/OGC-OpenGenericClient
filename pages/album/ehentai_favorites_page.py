# -*- coding: utf-8 -*-
"""
E-Hentai 我的收藏页面（OGC 集成版）
==================================
移植自 OGC-E-hentai 独立程序的 favorites.py，卡片显示样式与源码保持一致。

与原始版本的区别：
1. 数据库路径改为动态读取配置桥接（ehentai_cfg.KEY_DB_PATH），
   支持在设置页手动切换数据库文件后刷新数据。
2. 封面图加载改用 requests 后台线程（源码用 QNetworkAccessManager，
   但本项目 PyQt5 内置 OpenSSL 1.1 与 Python OpenSSL 3.0 共存时
   Qt TLS 初始化失败 → qt.network.ssl TLS initialization failed）。
3. 卡片网格随窗口宽度自适应列数（源码固定 3 列，在 OGC 较窄的内容
   区域会被压缩），窄窗口自动降为 2 列 / 1 列。
4. 勾选状态等配置保存在 OGC 的 data/config.json 的 "ehentai" 节点下。
"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PyQt5.QtCore import QObject, Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFontMetrics, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import requests

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    TitleLabel,
    ToolButton,
)

from core.config import config as CFG
from pages.album.ehentai_settings import ehentai_cfg

# ============================================================
# 常量
# ============================================================
# 可显示的数据表定义
TABLE_DEFS = [
    ('LOCAL_FAVORITES', '显示收藏', '收藏'),
    ('DOWNLOADS', '显示下载', '下载记录'),
]

# 类别映射：代码 -> (中文名, 英文名, 主题色)
CATEGORY_MAP = {
    1: ('其他', 'Misc', '#8b949e'),
    2: ('同人志', 'Doujinshi', '#cf222e'),
    4: ('漫画', 'Manga', '#1f6feb'),
    8: ('艺术CG', 'Artist CG', '#9a6700'),
    16: ('游戏CG', 'Game CG', '#8250df'),
    32: ('图像集', 'Image Set', '#0969da'),
    64: ('角色扮演', 'Cosplay', '#bf3989'),
    128: ('亚洲涩情', 'Asian Porn', '#d1242f'),
    256: ('非H', 'Non-H', '#1a7f37'),
    512: ('西方漫画', 'Western', '#57606a'),
}

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0 Safari/537.36'
)


def _format_time(ts) -> str:
    """将数据库中的时间戳格式化为本地时间字符串（兼容毫秒/秒）"""
    if not ts:
        return '-'
    try:
        ts = float(ts)
        if ts > 1e12:              # 毫秒
            ts /= 1000
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
    except (ValueError, OSError, OverflowError):
        return str(ts)


# ============================================================
# 封面图后台获取线程（requests，规避 Qt TLS 初始化失败）
# ============================================================
class ThumbnailFetchThread(QThread):
    """单个封面图的 requests 后台获取线程"""

    fetched = pyqtSignal(int, bytes)      # (gid, 图片字节)
    failed = pyqtSignal(int)              # (gid)

    def __init__(self, gid: int, url: str, proxies, parent=None):
        super().__init__(parent)
        self.gid = gid
        self.url = url
        self.proxies = proxies

    def run(self) -> None:
        try:
            from ehviewer.session import make_image_session
            s = make_image_session()
            if self.proxies:
                try:
                    s.proxies.update(self.proxies)
                except Exception:
                    pass
            data = None
            for _attempt in (1, 2):  # 失败重试一次
                try:
                    resp = s.get(self.url,
                                 headers={'Referer': 'https://e-hentai.org/'},
                                 timeout=12)
                    if resp.status_code == 200 and resp.content:
                        data = resp.content
                        break
                except Exception:
                    data = None
            if data:
                self.fetched.emit(self.gid, data)
            else:
                self.failed.emit(self.gid)
        except Exception:
            self.failed.emit(self.gid)


# ============================================================
# 封面图异步加载器
# ============================================================
class ThumbnailLoader(QObject):
    """封面图异步加载器（requests 后台线程 + 内存缓存，避免重复请求）

    不使用 Qt 自带的 QNetworkAccessManager：本项目环境中 Qt TLS 初始化
    失败（qt.network.ssl: TLS initialization failed），改走 requests
    （Python 自带 OpenSSL，工作正常）。
    """

    loaded = pyqtSignal(int, object)      # (gid, QPixmap | None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = {}                  # gid -> QPixmap
        self._pending = {}                # gid -> ThumbnailFetchThread
        self._proxy = ''
        # 封面磁盘缓存：下载一次后缓存到 {下载根}/.cache/ehentai/cache/covers，后续直接读本地。
        # 必须与 eh_cover.COVER_DIR 指向同一处（否则同一张封面会被缓存两份，而且写回 data/
        # 会让迁移后的 data/ 重新变胖）。
        try:
            self._cover_dir = CFG.cache_path('ehentai', 'cache', 'covers')
            os.makedirs(self._cover_dir, exist_ok=True)
        except Exception:
            self._cover_dir = ''
        self._apply_proxy()

    def _disk_path(self, gid: int, url: str) -> str:
        if not self._cover_dir:
            return ''
        # 以 gid 为稳定键（避免 url 变化导致缓存失效）
        key = hashlib.md5(str(gid).encode('utf-8')).hexdigest()
        return os.path.join(self._cover_dir, key + '.img')

    def _load_from_disk(self, gid: int, url: str):
        """命中磁盘缓存则加载并返回 QPixmap（用于避免重复网络请求）。"""
        p = self._disk_path(gid, url)
        if not p or not os.path.isfile(p):
            return None
        pix = QPixmap()
        if pix.load(p):
            return pix
        return None

    def _apply_proxy(self) -> None:
        """从配置桥接读取代理配置（用于 requests）"""
        self._proxy = ehentai_cfg.get(ehentai_cfg.KEY_PROXY, '') or ''

    def _proxies(self):
        if not self._proxy:
            return None
        return {'http': self._proxy, 'https': self._proxy}

    def load(self, gid: int, url: str) -> None:
        if not url or not gid:
            return
        # 规范化缩略图 URL（用当前可用的预览缩略图形式）
        try:
            from ehviewer.urls import get_fixed_preview_thumb_url
            url = get_fixed_preview_thumb_url(url) or url
        except Exception:
            pass
        if gid in self._cache:
            self.loaded.emit(gid, self._cache[gid])
            return
        if gid in self._pending:
            return
        # 磁盘缓存命中：直接加载，避免重复网络请求
        disk = self._load_from_disk(gid, url)
        if disk is not None:
            self._cache[gid] = disk
            self.loaded.emit(gid, disk)
            return

        thread = ThumbnailFetchThread(gid, url, self._proxies(), self)
        self._pending[gid] = thread
        thread.fetched.connect(self._on_fetched)
        thread.failed.connect(self._on_fetch_failed)
        thread.start()

    def _on_fetched(self, gid: int, data: bytes) -> None:
        self._pending.pop(gid, None)
        pixmap = QPixmap()
        ok = bool(data) and pixmap.loadFromData(data)
        if ok:
            self._cache[gid] = pixmap
            # 写入磁盘缓存（下次直接读本地）
            try:
                dp = self._disk_path(gid, '')
                if self._cover_dir and dp:
                    pixmap.save(dp, 'PNG')
            except Exception:
                pass
        self.loaded.emit(gid, pixmap if ok else None)

    def _on_fetch_failed(self, gid: int) -> None:
        self._pending.pop(gid, None)
        self.loaded.emit(gid, None)

    def shutdown(self) -> None:
        """安全回收：运行中的线程等其结束再销毁（避免 QThread: Destroyed while running）。"""
        for gid, thread in list(self._pending.items()):
            try:
                if thread.isRunning():
                    thread.requestInterruption()
                    thread.finished.connect(lambda th=thread: th.deleteLater())
                else:
                    thread.deleteLater()
            except Exception:
                pass
        self._pending.clear()


# ============================================================
# 自定义分页栏（当前 qfluentwidgets 版本无 Pagination 组件）
# ============================================================
class PaginationBar(QWidget):
    """简化分页条：上一页 / 页码信息 / 下一页"""

    page_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page = 1
        self._page_count = 1

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.prev_btn = PushButton(FluentIcon.LEFT_ARROW, '上一页', self)
        self.prev_btn.setFixedSize(88, 32)
        self.prev_btn.clicked.connect(self._go_prev)

        self.page_label = StrongBodyLabel('第 1 / 1 页', self)
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setStyleSheet('font-size: 13px; color: #57606a;')

        self.next_btn = PushButton(FluentIcon.RIGHT_ARROW, '下一页', self)
        self.next_btn.setFixedSize(88, 32)
        self.next_btn.clicked.connect(self._go_next)

        layout.addStretch(1)
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.page_label)
        layout.addWidget(self.next_btn)
        layout.addStretch(1)

        self._update_buttons()

    def set_page_count(self, count: int) -> None:
        self._page_count = max(1, count)
        if self._page > self._page_count:
            self.set_current_page(self._page_count)
        else:
            self._update_buttons()

    def set_current_page(self, page: int) -> None:
        page = max(1, min(page, self._page_count))
        if page == self._page:
            return
        self._page = page
        self.page_label.setText(f'第 {self._page} / {self._page_count} 页')
        self._update_buttons()
        self.page_changed.emit(self._page)

    def current_page(self) -> int:
        return self._page

    def page_count(self) -> int:
        return self._page_count

    def _go_prev(self) -> None:
        if self._page > 1:
            self.set_current_page(self._page - 1)

    def _go_next(self) -> None:
        if self._page < self._page_count:
            self.set_current_page(self._page + 1)

    def _update_buttons(self) -> None:
        self.prev_btn.setEnabled(self._page > 1)
        self.next_btn.setEnabled(self._page < self._page_count)
        self.page_label.setText(f'第 {self._page} / {self._page_count} 页')


# ============================================================
# 单条收藏卡片（与源码保持一致）
# ============================================================
class FavoriteCard(CardWidget):
    """一条收藏画廊的卡片"""

    open_requested = pyqtSignal(str)       # 画廊 URL
    download_requested = pyqtSignal(str)   # 画廊 URL
    copy_requested = pyqtSignal(str)       # 画廊 URL
    read_requested = pyqtSignal(str)       # 画廊 URL（应用内在线阅读）
    unfavorite_requested = pyqtSignal(int) # gid（取消收藏）
    detail_requested = pyqtSignal(object)  # GalleryInfo（进入就地漫画详情）

    THUMB_W = 150
    THUMB_H = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gid = 0
        self._token = ''
        self._url = ''
        self._title_full = ''
        self._title_jpn_full = ''
        self._build_ui()
        self.setFixedHeight(228)
        # 保证信息区内容完整显示的最小宽度
        self.setMinimumWidth(410)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(16)

        # ---- 封面图 ----
        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setText('暂无封面')
        self.thumb_label.setStyleSheet("""
            QLabel {
                background: #f0f2f5;
                border: 1px solid #e2e4e8;
                border-radius: 8px;
                color: #8c959f;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.thumb_label)

        # ---- 信息区 ----
        info = QVBoxLayout()
        info.setSpacing(5)

        # 中文标题（单行省略）
        self.title_label = StrongBodyLabel(self)
        self.title_label.setFixedHeight(24)
        self.title_label.setStyleSheet('font-size: 15px; font-weight: 600; color: #1f2328;')

        # 日文标题（单行省略）
        self.title_jpn_label = CaptionLabel(self)
        self.title_jpn_label.setFixedHeight(20)
        self.title_jpn_label.setStyleSheet('color: #57606a; font-size: 12px;')

        # 类别标签 + 评分
        meta = QHBoxLayout()
        meta.setSpacing(10)
        self.category_label = QLabel(self)
        self.rating_label = BodyLabel(self)
        self.rating_label.setStyleSheet('color: #e3a008; font-size: 13px; font-weight: 600;')
        meta.addWidget(self.category_label)
        meta.addWidget(self.rating_label)
        meta.addStretch(1)

        # 上传者 / 时间
        self.uploader_label = BodyLabel(self)
        self.posted_label = BodyLabel(self)
        self.saved_label = BodyLabel(self)
        for lbl in (self.uploader_label, self.posted_label, self.saved_label):
            lbl.setStyleSheet('color: #57606a; font-size: 12px;')

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.download_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, '下载', self)
        self.download_btn.setFixedSize(76, 30)
        self.read_btn = PushButton(FluentIcon.VIEW, '阅读', self)
        self.read_btn.setFixedSize(76, 30)
        self.open_btn = PushButton(FluentIcon.LINK, '打开', self)
        self.open_btn.setFixedSize(76, 30)
        self.copy_btn = ToolButton(FluentIcon.COPY, self)
        self.copy_btn.setFixedSize(30, 30)
        self.copy_btn.setToolTip('复制画廊链接')
        self.unfavorite_btn = ToolButton(FluentIcon.HEART_BROKEN if hasattr(FluentIcon, 'HEART_BROKEN') else FluentIcon.CANCEL, self)
        self.unfavorite_btn.setFixedSize(30, 30)
        self.unfavorite_btn.setToolTip('取消收藏')

        self.download_btn.clicked.connect(lambda: self.download_requested.emit(self._url))
        self.read_btn.clicked.connect(lambda: self.read_requested.emit(self._url))
        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self._url))
        self.copy_btn.clicked.connect(lambda: self.copy_requested.emit(self._url))
        self.unfavorite_btn.clicked.connect(lambda: self.unfavorite_requested.emit(self.gid))

        btn_row.addWidget(self.download_btn)
        btn_row.addWidget(self.read_btn)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.unfavorite_btn)
        btn_row.addStretch(1)

        info.addWidget(self.title_label)
        info.addWidget(self.title_jpn_label)
        info.addLayout(meta)
        info.addWidget(self.uploader_label)
        info.addWidget(self.posted_label)
        info.addWidget(self.saved_label)
        info.addStretch(1)
        info.addLayout(btn_row)

        layout.addLayout(info, 1)

    # ------------------------------------------------------------
    def set_downloaded(self, downed: bool) -> None:
        """若漫画已在下载目录，隐藏「下载」按钮（已在本地）。"""
        self.download_btn.setVisible(not downed)

    def set_data(self, item: dict) -> None:
        self.gid = int(item.get('GID') or 0)
        self._token = item.get('TOKEN') or ''
        self._url = f'https://e-hentai.org/g/{self.gid}/{self._token}/'
        self._thumb_url = item.get('THUMB') or ''

        # 中文标题
        title = (item.get('TITLE') or '').strip() or '(无标题)'
        self._title_full = title
        self.title_label.setText(title)

        # 日文标题
        jpn = (item.get('TITLE_JPN') or '').strip()
        self._title_jpn_full = jpn
        self.title_jpn_label.setText(jpn)

        # 类别
        code = int(item.get('CATEGORY') or 0)
        self._category_code = code
        cn, en, color = CATEGORY_MAP.get(code, ('未知', 'Unknown', '#8b949e'))
        self.category_label.setText(f'{cn} {en}')
        bg = QColor(color)
        bg.setAlpha(28)  # 淡色底
        self.category_label.setStyleSheet(
            f'background: {bg.name(QColor.HexArgb)};'
            f'color: {color};'
            'border-radius: 4px;'
            'padding: 2px 8px;'
            'font-size: 12px;'
        )

        # 评分
        try:
            rating = float(item.get('RATING') or 0)
        except (TypeError, ValueError):
            rating = 0.0
        self.rating_label.setText(f'★ {rating:.2f}')

        self.uploader_label.setText(f'上传者：{item.get("UPLOADER") or "-"}')
        self.posted_label.setText(f'发布时间：{item.get("POSTED") or "-"}')
        self.saved_label.setText(f'收藏时间：{_format_time(item.get("TIME"))}')

        # 根据当前卡片宽度省略标题
        self._elide_titles()

    def _elide_titles(self) -> None:
        """根据当前卡片宽度，对标题做单行省略显示"""
        # 信息区可用宽度 = 卡片宽 - 左右边距 - 封面宽 - 间距
        info_w = self.width() - 16 * 2 - self.THUMB_W - 16
        if info_w <= 40:
            return

        fm_title = QFontMetrics(self.title_label.font())
        self.title_label.setText(
            fm_title.elidedText(self._title_full, Qt.ElideRight, info_w - 8))

        fm_jpn = QFontMetrics(self.title_jpn_label.font())
        self.title_jpn_label.setText(
            fm_jpn.elidedText(self._title_jpn_full, Qt.ElideRight, info_w - 8))

    def resizeEvent(self, event) -> None:
        """窗口/卡片尺寸变化时重新省略标题，确保信息区完整显示"""
        super().resizeEvent(event)
        self._elide_titles()

    def set_thumb(self, pixmap) -> None:
        if pixmap is None:
            self.thumb_label.setText('加载失败')
            return
        scaled = pixmap.scaled(
            self.THUMB_W, self.THUMB_H,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.thumb_label.setText('')
        self.thumb_label.setPixmap(scaled)

    def mouseDoubleClickEvent(self, event) -> None:
        """双击卡片进入就地漫画详情"""
        try:
            from ehviewer.models import GalleryInfo
            from ehviewer import constants as EC
            gi = GalleryInfo()
            gi.gid = self.gid
            gi.token = self._token or ''
            gi.title = self._title_full or ''
            gi.title_jpn = self._title_jpn_full or ''
            gi.thumb = getattr(self, '_thumb_url', '') or ''
            gi.category = getattr(self, '_category_code', EC.UNKNOWN_CATEGORY)
            self.detail_requested.emit(gi)
            return
        except Exception:
            pass
        super().mouseDoubleClickEvent(event)


# ============================================================
# 收藏页面
# ============================================================
class FavoritesPage(QWidget):
    """收藏页面：分页卡片展示本地收藏（数据库路径可动态切换，网格自适应列数）"""

    download_requested = pyqtSignal(str)      # 请求用该 URL 开始下载
    read_requested = pyqtSignal(str)          # 请求应用内在线阅读

    PAGE_SIZE = 12
    MAX_COLUMNS = 3          # 最大列数（与源码一致）
    CARD_MIN_W = 410         # 卡片最小宽度（与源码一致）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []          # 全部数据
        self._filtered = []       # 筛选后数据
        self._cards = []          # 当前页卡片
        self._current_page = 1
        self._page_count = 1
        self._source_counts = {}  # 表名 -> 记录数
        self._columns = self.MAX_COLUMNS
        self._downloaded = (set(), set())   # (gid集合, 标题小写集合)，用于隐藏已下载卡片下载按钮

        self.thumbnail_loader = ThumbnailLoader(self)
        self.thumbnail_loader.loaded.connect(self._on_thumb_loaded)

        # 统一封面缓存服务（按 gid）。收藏时自动下载封面入缓存 + 显示进度。
        from pages.album.eh_cover import cover_service
        self.cover_service = cover_service
        self.cover_service.loaded.connect(self._on_cover_loaded)
        self.cover_service.progress.connect(self._on_cover_progress)
        self._gid_to_card = {}
        self._gid_to_url = {}
        self._cover_total = 0

        self._build_ui()
        self._load_table_checks()
        # 延迟加载：首次被激活（切到本 tab）时才读库，避免启动阶段读全量收藏库
        self._lazy_loaded = False

    # ============================================================
    # UI
    # ============================================================
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 14, 24, 24)
        root.setSpacing(16)

        root.addWidget(TitleLabel('我的收藏', self))

        # ---- 工具栏 ----
        toolbar = CardWidget(self)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(16, 14, 16, 14)
        tb.setSpacing(12)

        # 数据表复选框
        self.table_checkboxes = []
        for _table, label, _name in TABLE_DEFS:
            cb = QCheckBox(label, self)
            cb.setStyleSheet('font-size: 13px; color: #1f2328;')
            cb.toggled.connect(self._on_check_changed)
            tb.addWidget(cb)
            self.table_checkboxes.append(cb)

        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText('搜索标题 / 日文名...')
        self.search_edit.setFixedWidth(230)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)

        self.category_combo = ComboBox(self)
        self.category_combo.setFixedWidth(150)
        # 当前版本 qfluentwidgets 的 addItem 不支持 userData 第二参数，
        # 使用索引映射类别代码
        self.category_codes = [0] + list(CATEGORY_MAP.keys())
        self.category_combo.addItem('全部分类')
        for code in self.category_codes[1:]:
            cn, en, _color = CATEGORY_MAP[code]
            self.category_combo.addItem(f'{cn} {en}')
        self.category_combo.currentIndexChanged.connect(self._apply_filter)

        self.sort_combo = ComboBox(self)
        self.sort_combo.setFixedWidth(170)
        self.sort_combo.addItems([
            '收藏时间（新→旧）',
            '收藏时间（旧→新）',
            '评分（高→低）',
            '发布时间（新→旧）',
        ])
        self.sort_combo.currentIndexChanged.connect(self._apply_filter)

        self.count_label = CaptionLabel(self)
        self.count_label.setStyleSheet('color: #57606a;')

        self.refresh_btn = ToolButton(FluentIcon.SYNC, self)
        self.refresh_btn.setToolTip('重新读取数据库并保存勾选配置')
        self.refresh_btn.clicked.connect(self.reload)

        self.tag_fav_btn = PrimaryPushButton(FluentIcon.HEART, '标签收藏', self)
        self.tag_fav_btn.setToolTip('管理/搜索已收藏的标签（快捷搜索）')
        self.tag_fav_btn.clicked.connect(self._open_tag_favorites)

        tb.addWidget(self.search_edit)
        tb.addWidget(self.category_combo)
        tb.addWidget(self.sort_combo)
        tb.addStretch(1)
        tb.addWidget(self.count_label)
        tb.addWidget(self.tag_fav_btn)
        tb.addWidget(self.refresh_btn)
        root.addWidget(toolbar)

        # ---- 滚动卡片网格（列数随窗口宽度自适应） ----
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea { background: transparent; }')
        content = QWidget()
        self.grid = QGridLayout(content)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop)
        self._set_grid_columns(self.MAX_COLUMNS)
        self._update_content_min_width()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # ---- 封面缓存进度（左下角） ----
        self.cover_progress_label = CaptionLabel('', self)
        self.cover_progress_label.setStyleSheet('color: #57606a;')
        root.addWidget(self.cover_progress_label)

        # ---- 分页 ----
        self.pagination = PaginationBar(self)
        self.pagination.page_changed.connect(self._on_page_changed)
        root.addWidget(self.pagination)

    # ============================================================
    # 网格自适应列数
    # ============================================================
    def _calc_columns(self) -> int:
        """根据当前可用宽度计算列数（窄窗口自动减少列数）"""
        usable = max(200, self.width() - 24 * 2)   # 左右各 24 边距
        cols = (usable + 12) // (self.CARD_MIN_W + 12)
        return max(1, min(self.MAX_COLUMNS, cols))

    def _set_grid_columns(self, cols: int) -> None:
        """设置网格列 stretch（多余的旧列清 0）"""
        for c in range(self.MAX_COLUMNS + 1):
            self.grid.setColumnStretch(c, 0)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)

    def _update_content_min_width(self) -> None:
        """内容最小宽度 = 当前列数 * 卡片最小宽度 + 间距，避免横向滚动条"""
        self.grid.parentWidget().setMinimumWidth(
            self._columns * self.CARD_MIN_W + (self._columns - 1) * 12)

    def resizeEvent(self, event) -> None:
        """窗口宽度变化 → 重新计算列数并重排当前页卡片"""
        super().resizeEvent(event)
        new_cols = self._calc_columns()
        if new_cols != self._columns:
            self._columns = new_cols
            self._set_grid_columns(new_cols)
            self._update_content_min_width()
            self._show_page(self._current_page)

    # ============================================================
    # 数据库路径
    # ============================================================
    @staticmethod
    def db_path() -> str:
        """收藏数据所在的数据库 —— 与账号库同一个统一库（不再是独立 app_db.db）。

        取 ``ehviewer.db.get_db_path()``：默认即统一库；测试脚本可用
        ``set_db_path()`` 临时指到副本，应用本身不切换。
        """
        from ehviewer import db as ehdb
        return ehdb.get_db_path()

    def set_db_path(self, path: str) -> None:
        """兼容旧调用：数据库已统一，这里只重新加载界面。

        以前它会把配置里的数据库路径切到另一个文件；现在只有一个库，
        传进来的路径被忽略（``ehentai_bridge.route_to_shared_db`` 会把旧库
        的数据并进统一库，但不会改变"界面从哪读"）。
        """
        # 代理等配置可能变化，重新应用
        self.thumbnail_loader._apply_proxy()
        # 清空封面缓存，重新加载
        self.thumbnail_loader._cache.clear()
        self.reload()

    # ============================================================
    # 数据表勾选配置
    # ============================================================
    def _load_table_checks(self) -> None:
        """从配置桥接读取之前保存的表勾选状态"""
        try:
            data = json.loads(Path(CFG.cfg_file).read_text(encoding='utf-8'))
            sec = data.get('ehentai', {}) or {}
            # 默认两个都勾选（兼容旧配置）
            for i, (table, label, _name) in enumerate(TABLE_DEFS):
                key = 'show_favorites' if table == 'LOCAL_FAVORITES' else 'show_downloads'
                checked = bool(sec.get(key, True))
                if i < len(self.table_checkboxes):
                    # blockSignals：初始 setChecked 不应触发 _on_check_changed 的全量库读取
                    self.table_checkboxes[i].blockSignals(True)
                    self.table_checkboxes[i].setChecked(checked)
                    self.table_checkboxes[i].blockSignals(False)
        except Exception:
            for cb in self.table_checkboxes:
                cb.blockSignals(True)
                cb.setChecked(True)
                cb.blockSignals(False)

    def _save_table_checks(self) -> None:
        """将当前勾选状态保存到配置桥接"""
        try:
            cfg_file = Path(CFG.cfg_file)
            data = {}
            if cfg_file.exists():
                try:
                    data = json.loads(cfg_file.read_text(encoding='utf-8'))
                except (json.JSONDecodeError, OSError):
                    data = {}
            sec = data.get('ehentai', {}) or {}
            for i, (table, label, _name) in enumerate(TABLE_DEFS):
                key = 'show_favorites' if table == 'LOCAL_FAVORITES' else 'show_downloads'
                sec[key] = (i < len(self.table_checkboxes)
                            and self.table_checkboxes[i].isChecked())
            data['ehentai'] = sec
            cfg_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
        except Exception:
            pass

    def _on_check_changed(self, checked: bool) -> None:
        """勾选状态变化时立即刷新列表（不保存配置，保存由刷新按钮完成）"""
        self._refresh_data()

    def _selected_tables(self) -> list:
        """返回勾选的数据表名列表"""
        tables = []
        for i, (table, label, _name) in enumerate(TABLE_DEFS):
            if i < len(self.table_checkboxes) and self.table_checkboxes[i].isChecked():
                tables.append(table)
        return tables

    # ============================================================
    # 数据库读取
    # ============================================================
    # ============================================================
    # 标签收藏
    # ============================================================
    def _open_tag_favorites(self) -> None:
        from PyQt5.QtWidgets import QDialog, QListWidget, QListWidgetItem, QHBoxLayout as _HBox
        from pages.album.ehentai_sync import list_tag_favorites, delete_tag_favorite
        from ehviewer.ui.bus import bus as eh_bus
        from ehviewer import constants as EC

        dlg = QDialog(self)
        dlg.setWindowTitle('标签收藏（快捷搜索）')
        dlg.resize(420, 480)
        lay = QVBoxLayout(dlg)

        top = _HBox()
        add_btn = PrimaryPushButton(FluentIcon.ADD, '添加标签', dlg)
        top.addWidget(add_btn)
        top.addStretch(1)
        lay.addLayout(top)

        lst = QListWidget(dlg)
        lst.setStyleSheet(
            "QListWidget { color: #1f2328; background: #ffffff;"
            " border: 1px solid rgba(128,128,128,0.30); border-radius: 6px; font-size: 14px; }"
            " QListWidget::item { padding: 6px 10px; color: #1f2328; }"
            " QListWidget::item:selected { color: #ffffff; background: #2ea44f; }"
        )
        lay.addWidget(lst, 1)

        def refresh():
            lst.clear()
            for it in list_tag_favorites():
                li = QListWidgetItem(f"{it['tag']}")
                li.setData(Qt.UserRole, it)
                lst.addItem(li)

        def on_add():
            from PyQt5.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(dlg, '添加标签', '输入要收藏的标签（如 language:chinese）:')
            if ok and (text or '').strip():
                from pages.album.ehentai_sync import add_tag_favorite
                add_tag_favorite(text.strip(), text.strip())
                refresh()

        def on_search(li):
            it = li.data(Qt.UserRole)
            if not it:
                return
            eh_bus.doSearch.emit(it['tag'], EC.MODE_TAG)
            dlg.accept()

        def on_remove(li):
            it = li.data(Qt.UserRole)
            if it:
                delete_tag_favorite(it['id'])
                refresh()

        lst.itemDoubleClicked.connect(on_search)
        add_btn.clicked.connect(on_add)
        # 右键删除
        lst.setContextMenuPolicy(Qt.CustomContextMenu)
        from PyQt5.QtWidgets import QMenu
        def ctx(pos):
            li = lst.itemAt(pos)
            if li is None:
                return
            menu = QMenu(dlg)
            a_search = menu.addAction('搜索该标签')
            a_del = menu.addAction('删除该标签')
            act = menu.exec_(lst.mapToGlobal(pos))
            if act == a_search:
                on_search(li)
            elif act == a_del:
                on_remove(li)
        lst.customContextMenuRequested.connect(ctx)

        refresh()
        dlg.exec_()

    def reload(self) -> None:
        """点击刷新按钮 / 切换数据库：保存勾选配置，然后重新读取数据"""
        self._save_table_checks()
        # 扫描下载目录，用于隐藏已下载卡片的下载按钮
        try:
            from pages.album.ehentai_sync import downloaded_set
            self._downloaded = downloaded_set()
        except Exception:
            self._downloaded = (set(), set())
        self._refresh_data()

    def ensure_loaded(self) -> None:
        """首次激活时加载数据（避免启动阶段读全量收藏库）。"""
        if self._lazy_loaded:
            return
        self._lazy_loaded = True
        self.reload()

    def _refresh_data(self) -> None:
        """重新读取数据库并更新列表（不保存配置）"""
        self._items = self._load_from_db()
        self._apply_filter()

    def _load_from_db(self) -> list:
        db_path = self.db_path()
        if not db_path or not Path(db_path).exists():
            InfoBar.error(
                '数据库不存在',
                f'未找到：{db_path or "（未配置数据库文件）"}',
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )
            return []
        try:
            tables = self._selected_tables()
            if not tables:
                # 都没有勾选则不显示任何数据
                self._source_counts = {}
                return []

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            all_rows = []
            self._source_counts = {}
            # 公共字段（两个表都存在）
            sql = (
                'SELECT GID, TOKEN, TITLE, TITLE_JPN, THUMB, CATEGORY, '
                'POSTED, UPLOADER, RATING, TIME FROM {}'
            )
            for table in tables:
                try:
                    cur.execute(sql.format(table))
                    rows = [dict(r) for r in cur.fetchall()]
                except sqlite3.OperationalError:
                    # 该表不存在时跳过（例如纯收藏库没有 DOWNLOADS 表）
                    rows = []
                self._source_counts[table] = len(rows)
                all_rows.extend(rows)

            # 合并去重：以 (GID, TOKEN, CATEGORY) 为唯一键，
            # 保留首次出现的记录（优先级为 TABLE_DEFS 中表的顺序）
            if len(tables) > 1:
                seen = set()
                unique_rows = []
                for row in all_rows:
                    key = (
                        int(row.get('GID') or 0),
                        row.get('TOKEN') or '',
                        int(row.get('CATEGORY') or 0),
                    )
                    if key not in seen:
                        seen.add(key)
                        unique_rows.append(row)
                all_rows = unique_rows

            conn.close()
            return all_rows
        except Exception as e:  # noqa: BLE001
            InfoBar.error(
                '读取失败',
                str(e),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )
            return []

    # ============================================================
    # 筛选 / 排序 / 分页
    # ============================================================
    def _filter_items(self) -> list:
        keyword = self.search_edit.text().strip().lower()
        idx = self.category_combo.currentIndex()
        cat = self.category_codes[idx] if 0 <= idx < len(self.category_codes) else 0
        sort = self.sort_combo.currentIndex()

        items = []
        for it in self._items:
            if cat and int(it.get('CATEGORY') or 0) != cat:
                continue
            if keyword:
                title = (it.get('TITLE') or '').lower()
                jpn = (it.get('TITLE_JPN') or '').lower()
                if keyword not in title and keyword not in jpn:
                    continue
            items.append(it)

        if sort == 1:      # 收藏时间 旧 → 新
            items.sort(key=lambda x: x.get('TIME') or 0)
        elif sort == 2:    # 评分 高 → 低
            items.sort(key=lambda x: x.get('RATING') or 0, reverse=True)
        elif sort == 3:    # 发布时间 新 → 旧
            items.sort(key=lambda x: x.get('POSTED') or '', reverse=True)
        else:              # 收藏时间 新 → 旧
            items.sort(key=lambda x: x.get('TIME') or 0, reverse=True)
        return items

    def _apply_filter(self) -> None:
        self._filtered = self._filter_items()
        total = len(self._filtered)
        # 统计各表记录数
        counts = '  '.join(
            f'{(TABLE_DEFS[i][2] if i < len(TABLE_DEFS) else t)} {n} 条'
            for i, (t, n) in enumerate(self._source_counts.items())
        )
        if counts:
            self.count_label.setText(f'{counts}    共显示 {total} 条')
        else:
            self.count_label.setText(f'共显示 {total} 条')
        self._page_count = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.pagination.set_page_count(self._page_count)
        if self.pagination.current_page() != 1:
            self.pagination.set_current_page(1)   # 会触发 _show_page
        else:
            self._show_page(1)                    # 首次初始化时确保显示

    def _on_page_changed(self, page: int) -> None:
        self._show_page(page)

    def _show_page(self, page: int) -> None:
        self._current_page = page
        self._clear_cards()
        start = (page - 1) * self.PAGE_SIZE
        page_items = self._filtered[start:start + self.PAGE_SIZE]

        for i, item in enumerate(page_items):
            card = FavoriteCard(self)
            card.set_data(item)
            gids, titles = self._downloaded
            downed = (card.gid in gids
                      or (card._title_full or '').strip().lower() in titles)
            card.set_downloaded(downed)
            card.open_requested.connect(self._open_gallery)
            card.download_requested.connect(self.download_requested.emit)
            card.read_requested.connect(self.read_requested.emit)
            card.copy_requested.connect(self._copy_url)
            card.unfavorite_requested.connect(self._unfavorite)
            card.detail_requested.connect(self._open_detail_local)
            self.grid.addWidget(card, i // self._columns, i % self._columns)
            self._cards.append(card)
            self._gid_to_card[card.gid] = card
            # 统一封面：命中缓存直接用；否则标记占位并排队下载封面（显示进度）
            thumb_url = item.get('THUMB') or ''
            token = item.get('TOKEN') or ''
            self._gid_to_url[card.gid] = thumb_url
            pix = self.cover_service.load(card.gid)
            if pix is not None and not pix.isNull():
                card.set_thumb(pix)
            elif thumb_url or token:
                card.set_thumb(None)
                self.cover_service.enqueue(card.gid, thumb_url, token)

        # 一次性：强制重取「新到旧前 10 个」封面的缓存（与排行榜/主页/搜索同源，修复个别错/加载中）
        if page == 1 and not getattr(self, '_refresh_batch_done', False):
            self._refresh_batch_done = True
            for card in self._cards[:10]:
                gid = card.gid
                url = self._gid_to_url.get(gid, '')
                if url or getattr(card, '_token', ''):
                    self.cover_service.invalidate(gid)
                    self.cover_service.enqueue(gid, url, getattr(card, '_token', '') or '')
                    card.set_thumb(None)

    def _clear_cards(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards.clear()
        self._gid_to_card = {}
        self._gid_to_url = {}

    # ============================================================
    # 槽
    # ============================================================
    def _on_thumb_loaded(self, gid: int, pixmap) -> None:
        for card in self._cards:
            if card.gid == gid:
                card.set_thumb(pixmap)
                return

    # ---------- 统一封面缓存槽 ----------
    def _on_cover_loaded(self, gid: int, pixmap) -> None:
        card = self._gid_to_card.get(gid)
        if card is None:
            return
        try:
            card.set_thumb(pixmap)
        except Exception:
            # 卡片已被销毁（如页面刷新），移除引用并忽略本次回调
            self._gid_to_card.pop(gid, None)

    def _on_cover_progress(self, done: int, total: int) -> None:
        if total <= 0:
            return
        try:
            self.cover_progress_label.setText(f'封面缓存 {done}/{total}')
        except Exception:
            pass

    def _open_gallery(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _open_detail_local(self, gi) -> None:
        """双击收藏卡片 -> 进入就地漫画详情页（不弹窗）。"""
        try:
            from ehviewer.ui.bus import bus
            bus.openDetail.emit(gi)
        except Exception:
            pass

    def _copy_url(self, url: str) -> None:
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(url)
        InfoBar.success(
            '已复制',
            '画廊链接已复制到剪贴板。',
            parent=self,
            position=InfoBarPosition.TOP,
            duration=1500,
        )

    def _unfavorite(self, gid: int) -> None:
        """取消收藏：从 LOCAL_FAVORITES 移除（下载记录 DOWNLOADS 保留）。"""
        dbp = self.db_path()
        if not dbp:
            return
        from PyQt5.QtWidgets import QMessageBox
        ret = QMessageBox.question(
            self, '取消收藏', f'确定取消收藏该漫画吗？\n（gid={gid}，仅从收藏移除，下载记录保留）',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        try:
            import sqlite3
            c = sqlite3.connect(dbp)
            c.execute('DELETE FROM LOCAL_FAVORITES WHERE GID=?', (gid,))
            c.commit()
            c.close()
            # 若该 gid 不在 DOWNLOADS 表，也一并清理（避免残留空行）
            try:
                c = sqlite3.connect(dbp)
                if c.execute('SELECT 1 FROM DOWNLOADS WHERE GID=?', (gid,)).fetchone() is None:
                    pass
                c.close()
            except Exception:
                pass
            InfoBar.success('已取消收藏', f'已移除收藏（gid={gid}）。',
                            parent=self, position=InfoBarPosition.TOP, duration=2000)
            self.reload()
        except Exception as e:
            InfoBar.error('取消失败', str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=3000)
