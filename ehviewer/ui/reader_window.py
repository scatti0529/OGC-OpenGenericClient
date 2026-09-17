# -*- coding: utf-8 -*-
"""阅读器窗口：翻页/卷轴两种模式，在线加载 + 本地已下载优先"""
import json
import os
import re
import threading
from html import unescape

from PyQt5.QtCore import Qt, QThread, QThreadPool, QRunnable, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
                             QSlider)

from qfluentwidgets import (ToolButton, FluentIcon, StrongBodyLabel, CaptionLabel,
                            ComboBox, PushButton)

from core.config import config as CFG

from .. import urls
from ..config import get
from ..session import make_session
from ..spiderinfo import (SpiderInfo, find_gallery_dir, page_file_name,
                         SUPPORTED_EXTS)

# 阅读进度是**可写用户数据**：走 CFG.data（冻结时 = %APPDATA%），
# 不能用 __file__ 推导 —— 那样在 exe 里会写到安装目录的 _internal/data/ 下。
PROGRESS_PATH = os.path.join(str(CFG.data), 'ehentai', 'reading_progress.json')
# 阅读临时缓存：阅读时下载的图片存这里，退出程序后清理。
# 放下载根目录的 .cache/ 下（大体积、可再生），不占程序目录。
READER_CACHE_DIR = CFG.cache_path("ehentai", "reader_cache")


def _reader_cache_path(gid, index):
    return os.path.join(READER_CACHE_DIR, str(gid), "%06d.jpg" % (index + 1))


def load_reader_cache(gid, index):
    try:
        p = _reader_cache_path(gid, index)
        if os.path.isfile(p):
            img = QImage(p)
            if not img.isNull():
                return img
    except Exception:
        pass
    return None


def save_reader_cache(gid, index, img):
    try:
        p = _reader_cache_path(gid, index)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        img.save(p, "JPG", 85)
    except Exception:
        pass


def clear_reader_cache():
    import shutil
    try:
        shutil.rmtree(READER_CACHE_DIR, ignore_errors=True)
    except Exception:
        pass
PATTERN_PAGE_TOKEN = re.compile(r"/s/([0-9a-f]{10})/(\d+)-(\d+)")
PATTERN_SHOWKEY = re.compile(r'var showkey="([0-9a-z]+)";')
PATTERN_IMAGE_URL = re.compile(r'<img[^>]*src="([^"]+)" style')
PATTERN_IMAGE_ID = re.compile(r'<img[^>]+id="img"[^>]+src="([^"]+)"', re.S)
PATTERN_OG_IMAGE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', re.S)
# 页面被反爬/限流拦截的标记（借鉴下载器检测，命中则不再尝试直链下载）
_BLOCK_MARKERS = ("509 bandwidth limit exceeded", "temporarily banned",
                  "sad panda", "bandwidth limit exceeded", "429 too many requests")
_progress_lock = threading.Lock()


def _looks_like_image(data):
    """图片魔数校验：防止反爬返回的错误页 HTML 被当成图片（与下载器一致）。"""
    return (data[:3] == b"\xff\xd8\xff"           # jpg
            or data[:8] == b"\x89PNG\r\n\x1a\n"    # png
            or data[:4] == b"GIF8"                 # gif
            or data[:4] == b"RIFF"                 # webp
            or data[:2] == b"BM")                  # bmp


def _html_blocked(body):
    low = (body or "").lower()
    return any(m in low for m in _BLOCK_MARKERS)


def _extract_full_image_url(html):
    """从详情页/API 片段中提取原图 URL：img#img -> og:image -> 旧式 style。"""
    if not html:
        return None
    for pat in (PATTERN_IMAGE_ID, PATTERN_OG_IMAGE, PATTERN_IMAGE_URL):
        m = pat.search(html)
        if m:
            u = (m.group(1) or "").strip()
            if u:
                return unescape(u)
    return None


def load_progress(gid):
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return int(d.get(str(gid), {}).get("page", 0) or 0)
    except Exception:
        return 0


def save_progress(gid, page):
    try:
        with _progress_lock:
            d = {}
            if os.path.exists(PROGRESS_PATH):
                try:
                    with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
                        d = json.load(f)
                except Exception:
                    d = {}
            d[str(gid)] = {"page": page, "time": 0}
            with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


class FetchTask(QRunnable):
    """单页抓取：本地优先 -> HTML showkey -> API 图片（可取消，取消后不打扰界面）。

    每个任务都是“有主”的：ReaderWindow._tasks[index] 只登记一个在跑/排队任务，
    任务结束（成功/失败/被取消）都会把自己从登记表移除，因此任何被请求过的页面
    最终一定会有结果（显示/失败提示/留待下次翻回时重新请求），绝不会永远停在
    “加载中…”。
    """

    def __init__(self, reader, index):
        super(FetchTask, self).__init__()
        self.reader = reader
        self.index = index
        self._cancel = threading.Event()

    def cancel(self):
        """请求取消：后续网络阶段不再继续；已取消任务结果不上报。"""
        self._cancel.set()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    # ---------- 内部 ----------
    def _remove_self(self):
        """把本任务从 reader 的登记表移除（仅当自己仍是当前任务时）。"""
        try:
            r = self.reader
            with r._state_lock:
                if r._tasks.get(self.index) is self:
                    del r._tasks[self.index]
        except Exception:
            pass

    def _done(self, img):
        """统一收尾：无论成功/失败/取消，都先解除登记，避免页面被永久卡在加载中。"""
        r = self.reader
        if getattr(r, "_closed", False):
            self._remove_self()
            return
        ok = img is not None and not img.isNull()
        if ok:
            try:
                r._images[self.index] = img   # 先入内存缓存，翻回时秒开
                r._trim_cache()
            except Exception:
                pass
        self._remove_self()
        if self.cancelled:
            return   # 已被取消：静默结束，之后翻回该页会重新发起
        try:
            if ok:
                r.pageReady.emit(self.index, img)
            else:
                r.pageFailed.emit(self.index, "加载失败")
        except RuntimeError:
            pass  # 窗口已销毁

    def run(self):
        r = self.reader
        try:
            if getattr(r, "_closed", False):
                return
            img = load_reader_cache(r._gid, self.index)      # 1) 临时缓存（本次会话内秒开）
            if img is None and not self.cancelled:
                img = r._load_local(self.index)              # 2) 本地已下载
            if img is None and not self.cancelled:
                img = r._fetch_network(self.index)           # 3) 网络 + 存入临时缓存
                if img is not None and not img.isNull():
                    save_reader_cache(r._gid, self.index, img)
            self._done(img)
        except RuntimeError:
            self._remove_self()   # 窗口已被删除，静默结束
        except Exception:
            try:
                self._done(None)
            except RuntimeError:
                self._remove_self()


class ReaderWindow(QWidget):
    pageReady = pyqtSignal(int, object)
    pageFailed = pyqtSignal(int, str)

    def __init__(self, info, start_page=0, parent=None, local_files=None):
        super(ReaderWindow, self).__init__(parent)
        self._info = info
        self._gid = info.gid
        self._token = info.token
        self._local_files = local_files or None   # 本地文件列表模式：直接读下载目录图片，不走网络
        self._pages = int(info.pages or 0)
        self._ptokens = {}          # index -> page token（惰性按画廊分页补齐）
        self._ptoken_chunks = {}    # 画廊分页号 -> {index: token}
        self._ptoken_per = 0        # 每个画廊分页实际容纳的图片数（实测首分页得出）
        self._ptoken_lock = threading.Lock()
        self._show_key = None
        self._images = {}
        self._tasks = {}          # index -> FetchTask（正在排队/运行的页任务登记表）
        self._state_lock = threading.Lock()
        self._current = 0
        self._dir = None
        self._style = get("read_style", "page")
        self._fit = get("reader_fit", "width")
        self._session = make_session()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        # 关键：页任务完成/失败后必须刷新界面，否则会一直停留在“加载中…”
        self.pageReady.connect(self._on_page_ready)
        self.pageFailed.connect(self._on_page_failed)

        self.setWindowTitle("阅读器 — " + (info.suitable_title(get("show_jpn_title", False)) or "")[:40])
        self.resize(1100, 800)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 顶栏
        top = QHBoxLayout()
        # back = ToolButton(FluentIcon.LEFT_ARROW, self)
        #  back.setToolTip("返回")
        #  back.clicked.connect(self.close)
        # top.addWidget(back)
        self.title_label = StrongBodyLabel((info.suitable_title(get("show_jpn_title", False)) or "")[:60], self)
        top.addWidget(self.title_label, 1)
        self.page_label = CaptionLabel("—", self)
        top.addWidget(self.page_label)
        # 加载进度（已加载页/总页）
        self.load_label = CaptionLabel("", self)
        top.addWidget(self.load_label)
        self.style_combo = ComboBox(self)
        self.style_combo.addItem("翻页", userData="page")
        self.style_combo.addItem("卷轴", userData="scroll")
        si = self.style_combo.findData(self._style)
        self.style_combo.setCurrentIndex(max(0, si))
        self.style_combo.currentIndexChanged.connect(self._on_style)
        top.addWidget(self.style_combo)
        self.fit_btn = PushButton("宽度适配", self)
        self.fit_btn.clicked.connect(self._toggle_fit)
        top.addWidget(self.fit_btn)
        root.addLayout(top)

        # 进度条
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, max(1, self._pages - 1))
        self.slider.valueChanged.connect(self._on_slider)
        root.addWidget(self.slider)

        # 阅读区
        self._paged_scroll = QScrollArea(self)
        self._paged_scroll.setWidgetResizable(True)
        self._paged_scroll.setAlignment(Qt.AlignCenter)
        self._paged_scroll.setStyleSheet("background: #1b1b1b;")
        self._page_view = QLabel(self._paged_scroll)
        self._page_view.setAlignment(Qt.AlignCenter)
        self._page_view.setStyleSheet("background: transparent; color: #888;")
        self._page_view.setText("加载中…")
        self._paged_scroll.setWidget(self._page_view)
        root.addWidget(self._paged_scroll, 1)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setStyleSheet("background: #1b1b1b;")
        self._scroll_container = QWidget(self._scroll_area)
        self._scroll_lay = QVBoxLayout(self._scroll_container)
        self._scroll_lay.setContentsMargins(0, 0, 0, 0)
        self._scroll_lay.setSpacing(2)
        self._scroll_lay.addStretch(1)
        self._scroll_area.setWidget(self._scroll_container)
        self._scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        root.addWidget(self._scroll_area, 1)

        self._scroll_items = {}
        self._scroll_fail_ts = {}      # 卷轴条目最近一次失败时间（自动重试冷却用）
        self._closed = False
        self._loaded_count = 0
        self._failed_current = False   # 当前页是否处于“加载失败待重试”
        self._pending_page = 0
        # 快速翻页防抖：避免刷爆线程池导致卡住/回不去
        self._nav_timer = QTimer(self)
        self._nav_timer.setSingleShot(True)
        self._nav_timer.setInterval(150)
        self._nav_timer.timeout.connect(self._on_nav_timeout)
        self._apply_style()

        # 本地目录
        if self._local_files is None:
            d = find_gallery_dir(get("download_dir"), self._gid)
            if d:
                self._dir = os.path.join(get("download_dir"), d)
        else:
            self._dir = None
            self._pages = len(self._local_files)

        self._count_worker = None
        if self._local_files is None and self._pages <= 0:
            self.page_label.setText("正在获取页数…")
            self._count_worker = PageCountWorker(info, self)
            self._count_worker.done.connect(self._on_pages_fetched)
            self._count_worker.start()
        sp = start_page
        if sp <= 0 and self._dir is not None:
            try:
                sp = SpiderInfo.read(os.path.join(self._dir, ".ehviewer")).start_page
            except Exception:
                sp = 0
        if sp <= 0:
            sp = load_progress(self._gid)
        self._current = sp
        if self._pages > 0:
            self._current = max(0, min(sp, self._pages - 1))
            self._show_page(self._current)

    # ---------- 模式 ----------
    def _apply_style(self):
        if self._style == "scroll":
            self._paged_scroll.hide()
            self._scroll_area.show()
        else:
            self._paged_scroll.show()
            self._scroll_area.hide()

    def _on_style(self, _i):
        self._style = self.style_combo.currentData()
        self._apply_style()
        if self._style == "scroll":
            self._rebuild_scroll()
        else:
            self._show_page(self._current)

    def _toggle_fit(self):
        self._fit = "whole" if self._fit == "width" else "width"
        self.fit_btn.setText("整图适配" if self._fit == "whole" else "宽度适配")
        self._show_page(self._current)

    # ---------- 页面调度 ----------
    def _request(self, index):
        if index < 0 or index >= self._pages:
            return
        if index in self._images:
            return
        with self._state_lock:
            t = self._tasks.get(index)
            if t is not None:
                if not t.cancelled:
                    return              # 该页已有任务在排队/运行
                self._tasks.pop(index, None)   # 已被取消的旧任务：丢弃并重建
            task = FetchTask(self, index)
            self._tasks[index] = task
        try:
            self._pool.start(task)
        except RuntimeError:
            # 线程池已销毁（窗口关闭中）：把登记清掉，避免残留
            with self._state_lock:
                if self._tasks.get(index) is task:
                    self._tasks.pop(index, None)

    def _local_available(self):
        """是否可本地出图（离线章节列表 / 已下载目录）。"""
        return self._local_files is not None or self._dir is not None

    def _local_image(self, index):
        """本地同步取图：先临时缓存，再读本地文件（离线阅读不闪“加载中”）。"""
        try:
            img = load_reader_cache(self._gid, index)
            if img is not None and not img.isNull():
                return img
            img = self._load_local(index)
            return img if (img is not None and not img.isNull()) else None
        except Exception:
            return None

    def _show_page(self, index):
        if self._pages <= 0:
            self.page_label.setText("未知页数")
            return
        prev = self._current
        self._current = max(0, min(index, self._pages - 1))
        self.slider.setValue(self._current)
        self.page_label.setText("%d / %d" % (self._current + 1, self._pages))
        save_progress(self._gid, self._current)
        # 已加载则立即显示；本地模式相邻翻页（键盘/滚轮/点按）时同步出图，
        # 保证离线翻页不闪“加载中”。大跨度跳页交给防抖+异步，避免拖拽卡顿。
        if self._current in self._images:
            self._display(self._current)
        elif (self._local_available()
              and abs(self._current - prev) <= 2
              and self._current not in self._tasks
              and not self._failed_current):
            img = self._local_image(self._current)
            if img is not None:
                self._images[self._current] = img
                self._display(self._current)
        self._pending_page = self._current
        self._nav_timer.start()

    def _on_nav_timeout(self):
        """防抖到期：加载最终页及相邻页（优先当前页）。

        不再使用 QThreadPool.clear() 丢弃排队任务——那会把任务从线程池丢掉但
        登记表里仍保留该页，导致页面永远卡在“加载中”。改为“取消远离当前页的
        任务”：任务取消后会自行从登记表移除，翻回时能重新发起。
        """
        idx = self._pending_page
        if idx in self._images:
            self._display(idx)
        else:
            self._show_page_msg("加载中… %d/%d" % (idx + 1, self._pages))
            # 本地模式：当前页若有本地文件，同步读出来立即显示
            if (self._local_available() and idx not in self._tasks
                    and not self._failed_current):
                img = self._local_image(idx)
                if img is not None:
                    self._images[idx] = img
                    self._display(idx)
        if self._style == "scroll":
            # 卷轴模式：只补足可视窗口之后的预载页，不取消任何任务（避免回翻空白）
            self._request(idx)
            max_idx = max(self._scroll_items) if self._scroll_items else idx
            for i in range(max_idx + 1, min(self._pages, max_idx + 7)):
                self._add_scroll_item(i)
            return
        # 翻页模式：取消远离当前页的排队任务（防线程池被旧页占满），再请求当前窗口
        wanted = set()
        for off in (0, 1, 2, -1):
            j = idx + off
            if 0 <= j < self._pages:
                wanted.add(j)
        with self._state_lock:
            for i, t in list(self._tasks.items()):
                if i not in wanted:
                    t.cancel()
        for i in wanted:
            self._request(i)
        if idx in self._images:
            self._display(idx)

    def _show_page_msg(self, text):
        """在页面上显示文字（先清空旧 pixmap，避免上一页残留图盖住提示）。"""
        try:
            self._page_view.setPixmap(QPixmap())
        except Exception:
            pass
        self._page_view.setText(text)

    def _update_load_label(self):
        try:
            self.load_label.setText("已加载 %d/%d" % (self._loaded_count, self._pages))
        except Exception:
            pass

    def _on_page_ready(self, index, img):
        if getattr(self, "_closed", False):
            return
        try:
            if index not in self._images:
                self._images[index] = img
                self._trim_cache()
        except Exception:
            pass
        self._loaded_count += 1
        self._update_load_label()
        if index == self._current:
            self._failed_current = False
            self._display(index)
        if self._style == "scroll":
            try:
                self._scroll_fail_ts.pop(index, None)
            except Exception:
                pass
            self._update_scroll_item(index)

    def _on_page_failed(self, index, msg):
        if getattr(self, "_closed", False):
            return
        self._update_load_label()
        if index == self._current:
            self._failed_current = True
            self._show_page_msg("第 %d 页加载失败（%s）\n点击页面任意位置重试"
                                % (index + 1, msg))
        if self._style == "scroll":
            try:
                self._scroll_fail_ts[index] = time.monotonic()
            except Exception:
                pass
            self._update_scroll_item(index)

    def _retry_current(self):
        """重新加载当前页（失败后点击页面触发）。"""
        idx = self._current
        self._failed_current = False
        if idx in self._images:
            self._display(idx)
            return
        if 0 <= idx < self._pages:
            self._show_page_msg("加载中… %d/%d" % (idx + 1, self._pages))
            self._request(idx)

    def _display(self, index):
        img = self._images.get(index)
        if img is None or img.isNull():
            return
        self._failed_current = False
        w, h = img.width(), img.height()
        view_w = max(200, self._paged_scroll.viewport().width() - 20)
        view_h = max(200, self._paged_scroll.viewport().height() - 20)
        if self._fit == "width" or (self._fit == "whole" and w / max(1, h) < view_w / view_h):
            sw, sh = view_w, int(h * view_w / max(1, w))
        else:
            sh, sw = view_h, int(w * view_h / max(1, h))
        pix = QPixmap.fromImage(img).scaled(sw, sh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._page_view.setPixmap(pix)
        self._page_view.setText("")

    def _trim_cache(self):
        keep = {self._current + i for i in range(-3, 5)}
        for k in [k for k in list(self._images) if k not in keep]:
            del self._images[k]

    # ---------- 本地优先 ----------
    def _load_local(self, index):
        # 本地文件列表模式：直接读下载目录的图片路径
        if self._local_files is not None:
            try:
                if 0 <= index < len(self._local_files):
                    img = QImage(self._local_files[index])
                    if not img.isNull():
                        return img
            except Exception:
                return None
            return None
        if self._dir is None:
            return None
        for ext in SUPPORTED_EXTS:
            p = os.path.join(self._dir, page_file_name(index, ext))
            if os.path.exists(p):
                img = QImage(p)
                if not img.isNull():
                    return img
        return None

    # ---------- 网络抓取 ----------
    # 注意：ReaderWindow 自身没有 cancelled 状态（那是 FetchTask 的属性）。
    # 单页“已取消”由 FetchTask 在进入这些方法前拦截；方法内部只关心窗口是否已关闭。
    def _load_ptoken_chunk(self, chunk):
        """抓取并解析画廊某一分页下的所有页 token；返回该分页的图片数。

        表站画廊每一分页实际约 20 张缩略图（历史上曾为 40），这里动态探测
        （首页的实际数量 _ptoken_per），避免按固定 40 分块导致后半段永远
        拿不到 ptoken 而“加载失败”。
        """
        if self._closed:
            return 0
        try:
            url = urls.get_gallery_detail_url(self._gid, self._token, chunk)
            resp = self._session.get(url, headers={"Referer": urls.get_referer()},
                                     timeout=30)
            if self._closed:
                return 0
            body = resp.text
            if _html_blocked(body):
                return 0
            toks = {}
            for m in PATTERN_PAGE_TOKEN.finditer(body):
                if m.group(2) == str(self._gid):
                    toks[max(0, int(m.group(3)) - 1)] = m.group(1)
            if not toks:
                return 0
            self._ptoken_chunks[chunk] = toks
            self._ptokens.update(toks)
            if chunk == 0 and self._ptoken_per <= 0:
                self._ptoken_per = max(toks) + 1
            return max(toks) + 1
        except Exception:
            return 0

    def _ensure_ptoken(self, index):
        pt = self._ptokens.get(index)
        if pt and pt != "failed":
            return pt
        with self._ptoken_lock:
            pt = self._ptokens.get(index)
            if pt and pt != "failed":
                return pt
            per = self._ptoken_per
            if per <= 0:
                per = self._load_ptoken_chunk(0)          # 首分页探测分页容量
            if per <= 0:
                per = self._load_ptoken_chunk(index // 40)  # 兼容：容量探测失败时按旧式
            if per <= 0:
                return None
            chunk = index // per
            if chunk not in self._ptoken_chunks:
                self._load_ptoken_chunk(chunk)
            pt = self._ptokens.get(index)
            return pt if pt and pt != "failed" else None

    def _fetch_network(self, index):
        if self._closed:
            return None
        if self._local_files is not None:
            return None   # 本地文件列表模式：不联网
        ptoken = self._ensure_ptoken(index)
        if not ptoken:
            return None
        # 1) 详情页直连（img#img / og:image / style 兼容解析，下载前做图片校验）
        img = self._fetch_page_direct(index, ptoken)
        if img is not None or self._closed:
            return img
        # 2) 直连被限流/失败：改用 api showpage 备用通道
        if self._show_key:
            try:
                img = self._api_image(index, ptoken)
                if img is not None:
                    return img
            except Exception:
                pass
        return None

    def _fetch_page_direct(self, index, ptoken):
        """详情页 -> 原图 URL -> 下载（返回 QImage 或 None）。"""
        if self._closed:
            return None
        try:
            page_url = urls.get_page_url(self._gid, index, ptoken)
            resp = self._session.get(page_url, headers={
                "Referer": urls.get_gallery_detail_url(self._gid, self._token)}, timeout=30)
            if self._closed:
                return None
            body = resp.text
            if _html_blocked(body):
                return None
            m = PATTERN_SHOWKEY.search(body)
            if m:
                self._show_key = m.group(1)
            url = _extract_full_image_url(body)
            if not url:
                return None
            return self._download_image(url, page_url)
        except Exception:
            return None

    def _api_image(self, index, ptoken):
        if self._closed:
            return None
        payload = {"method": "showpage", "gid": self._gid, "page": index + 1,
                   "imgkey": ptoken, "showkey": self._show_key}
        headers = {"Origin": urls.get_origin()}
        if index > 0:
            prev = self._ptokens.get(index - 1)
            if prev:
                headers["Referer"] = urls.get_page_url(self._gid, index - 1, prev)
        resp = self._session.post(urls.get_api_url(), json=payload, headers=headers, timeout=30)
        if self._closed:
            return None
        d = resp.json()
        if "error" in d:
            self._show_key = None
            return None
        url = _extract_full_image_url(d.get("i3") or "")
        if not url:
            return None
        return self._download_image(url, urls.get_page_url(self._gid, index, ptoken))

    def _download_image(self, url, referer):
        if self._closed:
            return None
        try:
            resp = self._session.get(url, headers={"Referer": referer}, timeout=60)
            if self._closed:
                return None
            if resp.status_code >= 400:
                return None
            data = resp.content
            # 内容校验：太短 / 非图片（反爬 HTML）都视为失败
            if len(data) < 200 or not _looks_like_image(data):
                return None
            img = QImage.fromData(data)
            return img if not img.isNull() else None
        except Exception:
            return None

    # ---------- 卷轴模式 ----------
    def _rebuild_scroll(self):
        for i, lbl in list(self._scroll_items.items()):
            self._scroll_lay.removeWidget(lbl)
            lbl.deleteLater()
        self._scroll_items = {}
        for i in range(max(0, self._current - 2), min(self._pages, self._current + 20)):
            self._add_scroll_item(i)
        QTimer.singleShot(150, self._scroll_to_current)

    def _add_scroll_item(self, index):
        if index in self._scroll_items:
            return
        lbl = QLabel(self._scroll_container)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setMinimumHeight(140)
        lbl.setStyleSheet("color: #666;")
        lbl.setText("第 %d 页 加载中…" % (index + 1))
        lbl._index = index
        self._scroll_lay.insertWidget(self._scroll_lay.count() - 1, lbl)
        self._scroll_items[index] = lbl
        self._request(index)

    def _update_scroll_item(self, index):
        lbl = self._scroll_items.get(index)
        if lbl is None:
            return
        img = self._images.get(index)
        if img is None or img.isNull():
            lbl.setText("第 %d 页 加载失败" % (index + 1))
            return
        w = max(200, lbl.width() or (self._scroll_area.viewport().width() - 24))
        h = max(40, int(img.height() * w / max(1, img.width())))
        lbl.setFixedHeight(h)
        lbl.setPixmap(QPixmap.fromImage(img).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lbl.setText("")

    def _on_scroll_changed(self, value):
        if self._style != "scroll":
            return
        # 根据滚动位置估算当前页
        total_h = 0
        cur = 0
        for i in sorted(self._scroll_items):
            lbl = self._scroll_items[i]
            total_h += lbl.height() + 2
            if total_h > value + 100:
                cur = i
                break
        self._current = cur
        self.page_label.setText("%d / %d" % (self._current + 1, self._pages))
        save_progress(self._gid, self._current)
        # 追加后续页
        max_idx = max(self._scroll_items) if self._scroll_items else 0
        for i in range(max_idx + 1, min(self._pages, max_idx + 6)):
            self._add_scroll_item(i)
        # 可视区附近缺图条目自动补请求（失败/暂缺的页翻回可见时自动重试，带冷却）
        now = time.monotonic()
        for i in range(max(0, self._current - 2), min(self._pages, self._current + 6)):
            if i in self._images or i in self._tasks:
                continue
            if now - self._scroll_fail_ts.get(i, 0) < 2.0:
                continue
            self._request(i)

    def _scroll_to_current(self):
        total_h = 0
        for i in sorted(self._scroll_items):
            if i >= self._current:
                break
            total_h += self._scroll_items[i].height() + 2
        self._scroll_area.verticalScrollBar().setValue(total_h)

    def _on_pages_fetched(self, pages):
        self._pages = max(0, pages)
        if self._pages <= 0:
            self.page_label.setText("无法获取页数")
            self._page_view.setText("无法获取页数，请检查网络后返回重试")
            return
        self.slider.setRange(0, max(1, self._pages - 1))
        self._current = max(0, min(self._current, self._pages - 1))
        self._show_page(self._current)

    def _on_slider(self, v):
        self._show_page(v)

    # ---------- 键盘 / 滚轮 ----------
    def keyPressEvent(self, event):
        k = event.key()
        if self._style != "page":
            super(ReaderWindow, self).keyPressEvent(event)
            return
        if k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_PageDown, Qt.Key_Space):
            self._show_page(self._current + 1)
        elif k in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp):
            self._show_page(self._current - 1)
        elif k == Qt.Key_Home:
            self._show_page(0)
        elif k == Qt.Key_End:
            self._show_page(self._pages - 1)
        else:
            super(ReaderWindow, self).keyPressEvent(event)

    def wheelEvent(self, event):
        if self._style == "scroll":
            super(ReaderWindow, self).wheelEvent(event)
            return
        if event.angleDelta().y() > 0:
            self._show_page(self._current - 1)
        else:
            self._show_page(self._current + 1)
        event.accept()

    def mousePressEvent(self, event):
        if self._style != "page":
            super(ReaderWindow, self).mousePressEvent(event)
            return
        if self._failed_current and event.button() == Qt.LeftButton:
            # 当前页加载失败：点击页面任意位置 = 重试当前页
            self._retry_current()
            event.accept()
            return
        w = self.width()
        if event.x() < w / 3:
            self._show_page(self._current - 1)
        elif event.x() > w * 2 / 3:
            self._show_page(self._current + 1)
        else:
            super(ReaderWindow, self).mousePressEvent(event)

    def closeEvent(self, event):
        self._closed = True
        save_progress(self._gid, self._current)
        # 取消所有在跑/排队任务，让它们尽快退出，避免关闭时卡住
        with self._state_lock:
            for t in list(self._tasks.values()):
                t.cancel()
        self._pool.waitForDone(4000)
        if getattr(self, "_count_worker", None) is not None and self._count_worker.isRunning():
            self._count_worker.wait(3000)
        try:
            self._session.close()
        except Exception:
            pass
        super(ReaderWindow, self).closeEvent(event)

class PageCountWorker(QThread):
    done = pyqtSignal(int)

    def __init__(self, info, parent=None):
        super(PageCountWorker, self).__init__(parent)
        self.info = info

    def run(self):
        try:
            from .. import engine
            items = [self.info]
            engine.fill_gallery_list_by_api(items, urls.get_referer())
            self.done.emit(int(self.info.pages or 0))
            return
        except Exception:
            pass
        try:
            from .. import engine
            d = engine.get_gallery_detail(self.info.gid, self.info.token)
            self.done.emit(int(d.pages or 0))
            return
        except Exception:
            pass
        self.done.emit(0)
