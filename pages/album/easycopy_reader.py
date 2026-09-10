# -*- coding: utf-8 -*-
"""
拷贝漫画通用阅读器（OGC 集成版）
================================
支持两种阅读模式：

- 整页滚动（VIEW_SCROLL）：
    · 所有图片纵向排列，随滚动逐张显示；
    · 两种图片宽度适配，鼠标悬停图片上按 Ctrl+滚轮 切换：
        - 宽度适配：图片宽度撑满视口（默认）；
        - 整图适配：按视口缩放，保证至少能看到一张完整图片。
- 翻页模式（VIEW_PAGE）：
    · 一次显示一页，从左往右翻页；
    · 鼠标滚轮上下滑动翻页（上滚上一页、下滚下一页）；
    · 键盘 ← → / PageUp PageDown 翻页；支持页码分页跳转。

图片来源可为网络 URL（经 ImageFetcher 异步加载）或本地文件路径（离线阅读）。
线程安全：图片加载使用 QThread + 分代校验，页面切换/关闭时不会崩溃。
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, QThread, QTimer, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import PushButton, TransparentPushButton, BodyLabel

from ui.widgets.theme import text_primary, text_tertiary

from .easycopy_widgets import LoadingLabel


VIEW_SCROLL = "scroll"
VIEW_PAGE = "page"

# 阅读器加载策略（避免一次性加载所有图片导致卡死/闪退）
_PRELOAD_NEXT = 4      # 预载当前之后 4 页（翻页与整页共用）
_PRELOAD_PREV = 1      # 预载当前之前 1 页（便于回退）
_MAX_CONCURRENT = 3    # 最大并发图片加载线程数（防止线程爆炸）
_DEFAULT_ITEM_H = 360  # 整页模式下图片未知高度时的占位高度（估算滚动窗口用）
_CACHE_MARGIN = 40  # 整页模式缓存窗口：当前窗口前后保留的已加载图片数（超出即回收，防内存膨胀）
_POOL_FACTOR = 3     # 整页虚拟化：池标签数 = 可视图片数 * 该系数



class _ImageLoadWorker(QThread):
    """后台图片加载线程（URL 或本地路径）。"""

    done = pyqtSignal(int, object, int)   # index, QPixmap, generation
    failed = pyqtSignal(int, int)          # index, generation（失败也必须上报，避免永久“加载中”）

    def __init__(self, index: int, source: str, is_local: bool, fetcher, generation: int):
        super().__init__()
        self.index = index
        self.source = source
        self.is_local = is_local
        self.fetcher = fetcher
        self.generation = generation

    def run(self):
        try:
            data = None
            if self.is_local:
                with open(self.source, "rb") as f:
                    data = f.read()
            else:
                data = self.fetcher.fetch(self.source)
            if data:
                pix = QPixmap()
                pix.loadFromData(data)
                if not pix.isNull():
                    self.done.emit(self.index, pix, self.generation)
                    return
            self.failed.emit(self.index, self.generation)
        except Exception:
            self.failed.emit(self.index, self.generation)


class _ReaderScrollArea(QScrollArea):
    """阅读滚动区：拦截滚轮事件交给阅读器处理（翻页 / Ctrl+滚轮切换适配）。"""

    def __init__(self, reader: 'ComicReaderPage', parent=None):
        super().__init__(parent)
        self._reader = reader

    def wheelEvent(self, event):
        if self._reader.handle_wheel(event):
            event.accept()
            return
        super().wheelEvent(event)


class _PageRetryLabel(QLabel):
    """翻页模式中央标签：加载失败时点击可重试当前页。"""

    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ComicReaderPage(QWidget):
    """漫画阅读器（滚动 + 翻页双模式）。"""

    prev_chapter_requested = pyqtSignal(str)
    next_chapter_requested = pyqtSignal(str)

    def __init__(self, fetcher, parent=None):
        super().__init__(parent)
        self._fetcher = fetcher
        self._sources: List[str] = []
        self._is_local = False
        self._generation = 0
        self._failed: set = set()   # 已失败（等待重试）的图片索引，避免原地无限重试

        self._view_mode: str = VIEW_SCROLL
        self._scroll_fit_whole: bool = False   # 滚动模式：整图适配（否则宽度适配）
        self._current_index: int = 0
        self._pixmaps: dict = {}
        self._image_labels: List[QLabel] = []
        self._page_label: Optional[QLabel] = None
        self._indicator_label: Optional[QLabel] = None
        self._page_spin: Optional[QSpinBox] = None
        self._workers: List[_ImageLoadWorker] = []
        # 懒加载/预载窗口状态
        self._item_heights: dict = {}      # index -> 整页模式当前缩放高度（用于估算滚到哪一页）
        self._load_batch: int = 0          # 当前预载批次号（防竞态）
        self._preload_timer: Optional[QTimer] = None
        self._layout_timer: Optional[QTimer] = None
        self._resize_timer: Optional[QTimer] = None
        self._prev_href: str = ""
        self._next_href: str = ""
        self._scroll_area: Optional[_ReaderScrollArea] = None
        self._reader_area: Optional[QWidget] = None
        self._reader_layout: Optional[QVBoxLayout] = None
        self._scroll_mode_btn: Optional[PushButton] = None
        self._page_mode_btn: Optional[PushButton] = None
        self._fit_label: Optional[QLabel] = None

        self.setFocusPolicy(Qt.StrongFocus)
        self._build_ui()

    def sizeHint(self) -> QSize:
        # 阅读区内容高度 = 总页数 * 占位高，可能巨大；这里把阅读器的 sizeHint 收敛到
        # 有限值，避免其作为 QStackedWidget 子项时把窗口最小尺寸撑爆（画册阅读窗口高度异常）。
        return QSize(820, 640)

    def minimumSizeHint(self) -> QSize:
        return QSize(420, 480)

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 8, 24, 8)
        root.setSpacing(8)

        # 顶部：模式切换
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.title_label = BodyLabel("阅读", self)
        self.title_label.setStyleSheet(f"color: {text_primary()}; font-size: 15px; font-weight: 600;")
        top.addWidget(self.title_label, 1)

        self._fit_label = QLabel("", self)
        self._fit_label.setStyleSheet(f"color: {text_tertiary()}; font-size: 12px;")
        self._fit_label.setVisible(False)
        top.addWidget(self._fit_label)

        self._scroll_mode_btn = TransparentPushButton("整页", self)
        self._scroll_mode_btn.clicked.connect(lambda: self.set_mode(VIEW_SCROLL))
        top.addWidget(self._scroll_mode_btn)

        self._page_mode_btn = TransparentPushButton("翻页", self)
        self._page_mode_btn.clicked.connect(lambda: self.set_mode(VIEW_PAGE))
        top.addWidget(self._page_mode_btn)
        root.addLayout(top)

        # 阅读区（滚动容器）
        self._scroll_area = _ReaderScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._reader_area = QWidget(self._scroll_area)
        self._reader_layout = QVBoxLayout(self._reader_area)
        self._reader_layout.setContentsMargins(0, 0, 0, 0)
        self._reader_layout.setSpacing(8)
        self._scroll_area.setWidget(self._reader_area)
        # 滚动时按需触发预载窗口（整页模式）
        self._scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        root.addWidget(self._scroll_area, 1)

        # 底部：上一话 / 页码 / 下一话
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(10)

        self._prev_btn = PushButton("上一话", self)
        self._prev_btn.clicked.connect(self._on_prev_chapter)
        bottom.addWidget(self._prev_btn)

        bottom.addStretch(1)

        self._indicator_label = QLabel("", self)
        self._indicator_label.setAlignment(Qt.AlignCenter)
        self._indicator_label.setStyleSheet(f"color: {text_tertiary()}; font-size: 13px;")
        bottom.addWidget(self._indicator_label)

        # 分页跳转（翻页模式可用）
        self._page_spin = QSpinBox(self)
        self._page_spin.setMinimum(1)
        self._page_spin.setMaximum(1)
        self._page_spin.setFixedWidth(64)
        self._page_spin.valueChanged.connect(self._on_spin_changed)
        self._page_spin.setVisible(False)
        bottom.addWidget(self._page_spin)

        bottom.addStretch(1)

        self._next_btn = PushButton("下一话", self)
        self._next_btn.clicked.connect(self._on_next_chapter)
        bottom.addWidget(self._next_btn)

        root.addLayout(bottom)

    # ---------------- 数据加载 ----------------
    def load(self, title: str, sources: List[str], is_local: bool = False,
             prev_href: str = "", next_href: str = ""):
        """加载阅读内容。sources: URL 列表或本地文件路径列表。"""
        self._generation += 1
        self._clear_workers()
        self._sources = list(sources)
        self._is_local = is_local
        self._failed = set()
        self._prev_href = prev_href or ""
        self._next_href = next_href or ""
        self._current_index = 0
        self._pixmaps = {}

        self.title_label.setText(title or "阅读")
        self._prev_btn.setVisible(bool(self._prev_href))
        self._next_btn.setVisible(bool(self._next_href))

        self._rebuild_content()

        self._prev_btn.setEnabled(True)
        self._next_btn.setEnabled(True)

        if self._sources:
            self._start_loaders()
        else:
            self._reader_layout.addWidget(LoadingLabel("加载中…"))

    def _clear_workers(self):
        """停止旧线程并回收（避免 QThread destroyed while running）。"""
        for w in self._workers:
            for sig in (w.done, w.failed):
                try:
                    sig.disconnect()
                except Exception:
                    pass
            try:
                w.wait(100)
            except Exception:
                pass
            w.deleteLater()
        self._workers = []

    def _start_loaders(self):
        """按需启动图片加载（翻页：当前+前后窗口；整页：可见区+预载窗口）。

        只开启有限并发线程（_MAX_CONCURRENT），并按优先级（当前页优先）输出
        待加载队列，避免一次性加载全部图片导致的卡死/闪退；同时回收超出
        缓存窗口的旧 pixmap，防止内存与缩放绘制无限膨胀。
        """
        total = len(self._sources)
        if total == 0:
            return

        self._load_batch += 1
        window = self._window_indices()
        # 已离开当前加载窗口的失败页：解除失败标记，下次回到窗口时自动重试
        win = set(window)
        for k in [k for k in self._failed if k not in win]:
            self._failed.discard(k)
        self._pump_loaders(window)
        self._prune_cache()

    def _window_indices(self) -> list:
        """计算本次应加载/预载的图片索引列表（当前优先，其次前后窗口）。"""
        total = len(self._sources)
        if total == 0:
            return []
        if self._view_mode == VIEW_PAGE:
            lo = max(0, self._current_index - _PRELOAD_PREV)
            hi = min(total, self._current_index + _PRELOAD_NEXT + 1)
            window = list(range(lo, hi))
            # 当前页排最前
            window.sort(key=lambda i: (abs(i - self._current_index)))
            return window

        # VIEW_SCROLL：按可视区估算当前页，加载当前页 + 其后 _PRELOAD_NEXT 页
        offsets = self._compute_offsets()
        vp_top = self._scroll_area.verticalScrollBar().value()
        cur = 0
        for i in range(total):
            y = offsets.get(i, 0)
            h = self._item_heights.get(i, _DEFAULT_ITEM_H)
            if y + h > vp_top:
                cur = i
                break
        window = []
        for i in range(cur, min(total, cur + _PRELOAD_NEXT + 1)):
            window.append(i)
        return window

    def _pump_loaders(self, window: list, allow_failed: bool = False):
        """把 window 中未加载的图片交给有限并发的工作线程。

        allow_failed=True 时允许重试标记为失败的页（点击重试 / 用户主动重试）。
        失败页默认不再原地反复拉起线程（避免缺失文件时的重试风暴），由
        _start_loaders 在离开窗口后解除标记，回到窗口时自动重试一次。
        """
        total = len(self._sources)
        active = [w for w in self._workers if w.isRunning()]
        active_idx = {w.index for w in active}
        loaded = set(self._pixmaps.keys())
        queued = set()
        for idx in window:
            if idx in loaded or idx in active_idx or idx in queued:
                continue
            if not allow_failed and idx in self._failed:
                continue
            if 0 <= idx < total:
                queued.add(idx)

        for idx in list(queued):
            if len(active) >= _MAX_CONCURRENT:
                # 已有足够并发，剩下的在下一次 _pump 时补充（由 _on_image_loaded 再次调起）
                continue
            source = self._sources[idx]
            worker = _ImageLoadWorker(idx, source, self._is_local, self._fetcher, self._generation)
            worker.done.connect(self._on_image_loaded)
            worker.failed.connect(self._on_image_failed)
            self._workers.append(worker)
            worker.start()
            active.append(worker)

    def _on_image_failed(self, index: int, generation: int):
        """图片加载失败：给出明确提示（不再默默停在“加载中…”）。"""
        if generation != self._generation:
            return  # 旧代数据丢弃
        self._failed.add(index)
        try:
            if self._view_mode == VIEW_PAGE:
                if index == self._current_index:
                    self._update_page_label()
            else:
                self._refresh_pool_layout()   # 让可见区的失败占位显示“加载失败”
        except Exception:
            pass

    def _prune_cache(self):
        """回收超出缓存窗口范围的已加载 pixmap（整页滚动模式防内存/绘制膨胀）。"""
        if self._view_mode != VIEW_SCROLL or not self._pixmaps:
            return
        total = len(self._sources)
        if total == 0:
            return
        offsets = self._compute_offsets()
        vp_top = self._scroll_area.verticalScrollBar().value()
        vp_h = self._vp_height()
        center = 0
        for i in range(total):
            y = offsets.get(i, 0)
            h = self._item_heights.get(i, _DEFAULT_ITEM_H)
            if y + h > vp_top + vp_h / 2:
                center = i
                break
        keep_lo = center - _CACHE_MARGIN
        keep_hi = center + _CACHE_MARGIN
        for idx in list(self._pixmaps.keys()):
            if idx < keep_lo or idx > keep_hi:
                self._pixmaps.pop(idx, None)

    def _on_scroll_changed(self, value: int):
        """整页模式滚动时按需渲染可视区并扩展预载窗口（节流）。"""
        if self._view_mode != VIEW_SCROLL:
            return
        if self._layout_timer is None:
            self._layout_timer = QTimer(self)
            self._layout_timer.setSingleShot(True)
            self._layout_timer.setInterval(60)
            self._layout_timer.timeout.connect(self._refresh_pool_layout)
        self._layout_timer.start()
        if self._preload_timer is None:
            self._preload_timer = QTimer(self)
            self._preload_timer.setSingleShot(True)
            self._preload_timer.setInterval(120)
            self._preload_timer.timeout.connect(self._start_loaders)
        self._preload_timer.start()

    def _rebuild_content(self):
        # 清空阅读区
        while self._reader_layout.count():
            item = self._reader_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        # 释放旧池标签
        for lbl in getattr(self, '_pool_labels', []):
            try:
                lbl.deleteLater()
            except Exception:
                pass
        self._pool_labels = []
        self._image_labels = []
        self._page_label = None
        self._item_heights = {}

        if self._view_mode == VIEW_SCROLL:
            # 虚拟化：不按图片数量创建 QLabel，改用池标签绝对定位
            self._setup_scroll_virtual()
        else:
            # 翻页模式：内容区占满视口，恢复 widgetResizable
            self._reader_area.setMinimumHeight(0)
            self._reader_area.setFixedHeight(self._scroll_area.viewport().height())
            self._scroll_area.setWidgetResizable(True)
            self._reader_layout.setSpacing(8)
            self._page_label = _PageRetryLabel("加载中…")
            self._page_label.setAlignment(Qt.AlignCenter)
            self._page_label.setMinimumSize(200, 200)
            self._page_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._page_label.setStyleSheet(f"color: {text_tertiary()}; background: transparent;")
            self._page_label.clicked.connect(self._retry_current_failed)
            self._reader_layout.addWidget(self._page_label, 1)
            self._update_page_label()

        self._refresh_mode_buttons()
        self._update_indicator()
        self._update_fit_label()
        self._page_spin.setVisible(self._view_mode == VIEW_PAGE)
        if self._page_spin.isVisible():
            self._page_spin.setMaximum(max(1, len(self._sources)))
            self._page_spin.blockSignals(True)
            self._page_spin.setValue(min(max(1, self._current_index + 1), max(1, len(self._sources))))
            self._page_spin.blockSignals(False)

    # ---------------- 整页虚拟化 ----------------
    def _vp_height(self) -> int:
        return max(self._scroll_area.viewport().height(), 1)

    def _visible_count(self) -> int:
        """预估当前视口能容纳的图片数量。"""
        return max(1, self._vp_height() // _DEFAULT_ITEM_H)

    def _pool_size(self) -> int:
        """池标签数量：当前视野能容纳 + 前后预载。"""
        return self._visible_count() * _POOL_FACTOR + _PRELOAD_NEXT + 1

    def _setup_scroll_virtual(self):
        """对整页模式建立虚拟滚动：一个无布局的高度画布 + 池标签绝对定位。"""
        # 清空并关闭布局（改用绝对定位，避免成千上万 QLabel / 巨大布局）
        while self._reader_layout.count():
            item = self._reader_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        # 关闭布局维度，启用绝对定位
        self._reader_layout.setSpacing(0)
        self._reader_layout.setContentsMargins(0, 0, 0, 0)

        total = len(self._sources)
        # 建立池标签
        pool = []
        n = self._pool_size()
        for _ in range(n):
            label = QLabel("加载中…", self._reader_area)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"color: {text_tertiary()}; background: transparent;")
            label.setVisible(False)
            label.setMinimumSize(50, 50)
            pool.append(label)
        self._pool_labels = pool
        # 虚拟滚动需关闭 widgetResizable，否则 Qt 会把控件拉回视口大小
        self._scroll_area.setWidgetResizable(False)
        # 用占位高度撑起画布总高度，保证滚动范围
        h = max(total * _DEFAULT_ITEM_H, self._scroll_area.viewport().height())
        self._reader_area.setMinimumHeight(h)
        self._reader_area.setFixedHeight(h)
        self._reader_area.updateGeometry()
        # 建立图片映射：index -> pool
        self._pool_index_map = {}
        self._layout_offsets = {}
        self._refresh_pool_layout()

    def _compute_offsets(self) -> dict:
        """返回 {index: 顶部 y 坐标}，基于当前已知/占位高度。"""
        offsets = {}
        acc = 0
        for i in range(len(self._sources)):
            h = self._item_heights.get(i, _DEFAULT_ITEM_H)
            offsets[i] = acc
            acc += h
        return offsets

    def _refresh_pool_layout(self):
        """根据滚动位置，把当前要显示的图片索引分配给池标签并定位。"""
        total = len(self._sources)
        if total == 0:
            return
        self._layout_offsets = self._compute_offsets()
        vp_top = self._scroll_area.verticalScrollBar().value()
        vp_h = self._vp_height()
        # 找出可视区覆盖到的索引区间
        first = None
        last = None
        for i in range(total):
            y = self._layout_offsets.get(i, 0)
            h = self._item_heights.get(i, _DEFAULT_ITEM_H)
            if y + h > vp_top and y < vp_top + vp_h:
                if first is None:
                    first = i
                last = i
            if y > vp_top + vp_h and first is not None:
                break
        if first is None:
            first = 0
            last = min(total - 1, self._visible_count())

        # 需要渲染的索引 = 可视区 + 后预载
        want = list(range(first, min(total, last + _PRELOAD_NEXT + 1)))
        # 隐藏所有池标签，再按需分配
        for lbl in self._pool_labels:
            lbl.setVisible(False)
        self._pool_index_map = {}
        for k, idx in enumerate(want):
            if k >= len(self._pool_labels):
                break
            self._pool_index_map[idx] = k
            self._pool_labels[k].setVisible(True)
            # 立即尝试填充（已加载的直接画，未加载的显示占位并按需触发加载）
            if idx in self._pixmaps:
                self._apply_scroll_index(idx)
            else:
                # 顺序：先清空 pixmap 再 setText，否则 setPixmap 会清掉文字
                self._pool_labels[k].setPixmap(QPixmap())
                if idx in self._failed:
                    self._pool_labels[k].setText("第 %d 页 加载失败" % (idx + 1))
                else:
                    self._pool_labels[k].setText("加载中…")
                self._pool_labels[k].setGeometry(0, self._layout_offsets.get(idx, 0),
                                                 self._scroll_area.viewport().width() - 20, _DEFAULT_ITEM_H)

    def _pool_index_of(self, idx: int) -> int:
        return self._pool_index_map.get(idx, 0)

    def _pool_y_of(self, idx: int) -> int:
        return self._layout_offsets.get(idx, 0)

    def _set_layout_height(self):
        """（占位）整页高度已由 _setup_scroll_virtual 设置。"""

    def _on_image_loaded(self, index: int, pix, generation: int):
        if generation != self._generation:
            return  # 旧代数据丢弃
        self._pixmaps[index] = pix
        # 记录整页模式该图片当前的缩放高度（用于滚动定位估算）
        try:
            self._item_heights[index] = max(_DEFAULT_ITEM_H, pix.height())
        except Exception:
            self._item_heights[index] = _DEFAULT_ITEM_H
        if self._view_mode == VIEW_SCROLL:
            self._refresh_pool_layout()
        else:
            if index == self._current_index:
                self._update_page_label()
        self._update_indicator()
        # 继续补充预载队列（限额并发）
        self._start_loaders()

    def _apply_scroll_index(self, idx: int):
        """整页模式：把第 idx 张图渲染到对应池标签（绝对定位）。"""
        pix = self._pixmaps.get(idx)
        if pix is None:
            return
        vp = self._scroll_area.viewport()
        if vp is None or vp.width() <= 0:
            return
        if self._scroll_fit_whole:
            w = max(vp.width() - 20, 100)
            h = max(vp.height() - 20, 100)
            scaled = pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            w = max(vp.width() - 20, 300)
            scaled = pix.scaledToWidth(w, Qt.SmoothTransformation)
        self._item_heights[idx] = scaled.height()
        label = self._pool_labels[self._pool_index_of(idx)]
        label.setGeometry(0, self._pool_y_of(idx), scaled.width(), scaled.height())
        label.setText("")
        label.setPixmap(scaled)

    def _update_page_label(self):
        if self._page_label is None:
            return
        if self._current_index in self._failed:
            # 失败提示 + 可点击重试（点击 _PageRetryLabel 触发 _retry_current_failed）
            # 注意顺序：先清空 pixmap 再 setText，否则 setPixmap 会清掉文字
            self._page_label.setPixmap(QPixmap())
            self._page_label.setText("第 %d 页加载失败\n点击页面重试" % (self._current_index + 1))
            return
        pix = self._pixmaps.get(self._current_index)
        if pix is None:
            self._page_label.setPixmap(QPixmap())
            self._page_label.setText("加载中…")
            return
        vp = self._scroll_area.viewport().size()
        w = max(vp.width() - 40, 200)
        h = max(vp.height() - 40, 200)
        scaled = pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._page_label.setText("")
        self._page_label.setPixmap(scaled)

    def _retry_current_failed(self):
        """点击失败提示：重试当前页。"""
        if self._view_mode != VIEW_PAGE or not self._sources:
            return
        if self._current_index not in self._failed:
            return
        self._failed.discard(self._current_index)
        self._page_label.setText("加载中…")
        self._pump_loaders(self._window_indices(), allow_failed=True)

    def _update_indicator(self):
        total = len(self._sources)
        text = f"{self._current_index + 1} / {total}" if total else ""
        if self._indicator_label is not None:
            self._indicator_label.setText(text)
        if self._page_spin is not None and total:
            self._page_spin.blockSignals(True)
            self._page_spin.setMaximum(total)
            self._page_spin.setValue(min(self._current_index + 1, total))
            self._page_spin.blockSignals(False)

    def _update_fit_label(self):
        if self._fit_label is None:
            return
        if self._view_mode == VIEW_SCROLL:
            self._fit_label.setVisible(True)
            self._fit_label.setText("整图适配" if self._scroll_fit_whole else "宽度适配")
        else:
            self._fit_label.setVisible(False)

    def _refresh_mode_buttons(self):
        scroll_active = self._view_mode == VIEW_SCROLL
        base = "color: {c}; border-radius: 12px; padding: 4px 14px; background: rgba(128,128,128,0.10);"
        self._scroll_mode_btn.setStyleSheet(base.format(c='#FFFFFF' if scroll_active else text_primary()))
        self._page_mode_btn.setStyleSheet(base.format(c='#FFFFFF' if not scroll_active else text_primary()))
        self._scroll_mode_btn.setText(f"整页 {'●' if scroll_active else ''}")
        self._page_mode_btn.setText(f"翻页 {'●' if not scroll_active else ''}")

    # ---------------- 滚轮处理 ----------------
    def handle_wheel(self, event) -> bool:
        """返回 True 表示已消费该滚轮事件。

        - Ctrl+滚轮（滚动模式）：切换 宽度适配 / 整图适配；
        - 翻页模式：滚轮上下翻页（下滚下一页，上滚上一页）。
        """
        # Ctrl+滚轮：切换滚动模式的图片适配
        if event.modifiers() & Qt.ControlModifier:
            if self._view_mode == VIEW_SCROLL:
                self._scroll_fit_whole = not self._scroll_fit_whole
                self._rescale_scroll()
                self._update_fit_label()
            return True

        # 翻页模式：滚轮翻页
        if self._view_mode == VIEW_PAGE:
            delta = event.angleDelta().y()
            if delta > 0:
                self._prev_page()
            elif delta < 0:
                self._next_page()
            return True

        # 滚动模式：交给滚动区正常滚动
        return False

    # ---------------- 模式切换与翻页 ----------------
    def set_mode(self, mode: str):
        if mode == self._view_mode:
            return
        self._view_mode = mode
        self._rebuild_content()
        self._start_loaders()
        self._scroll_area.verticalScrollBar().setValue(0)
        self.setFocus()

    def _prev_page(self):
        if self._view_mode != VIEW_PAGE or self._current_index <= 0:
            return
        self._current_index -= 1
        self._failed.discard(self._current_index)   # 翻回时自动重试一次
        self._update_page_label()
        self._update_indicator()
        self._start_loaders()  # 预载新一页

    def _next_page(self):
        if self._view_mode != VIEW_PAGE or self._current_index >= len(self._sources) - 1:
            return
        self._current_index += 1
        self._failed.discard(self._current_index)   # 翻到新页时自动重试一次
        self._update_page_label()
        self._update_indicator()
        self._start_loaders()

    def _on_spin_changed(self, value: int):
        if self._view_mode != VIEW_PAGE or not self._sources:
            return
        idx = max(0, min(value - 1, len(self._sources) - 1))
        if idx == self._current_index:
            return
        self._current_index = idx
        self._failed.discard(idx)   # 跳页到达时自动重试一次
        self._update_page_label()
        self._update_indicator()
        self._start_loaders()

    def keyPressEvent(self, event):
        if self._view_mode == VIEW_PAGE:
            if event.key() in (Qt.Key_Left, Qt.Key_PageUp):
                self._prev_page()
                return
            if event.key() in (Qt.Key_Right, Qt.Key_PageDown):
                self._next_page()
                return
        super().keyPressEvent(event)

    # ---------------- 章节跳转 ----------------
    def _on_prev_chapter(self):
        if self._prev_href:
            self.prev_chapter_requested.emit(self._prev_href)

    def _on_next_chapter(self):
        if self._next_href:
            self.next_chapter_requested.emit(self._next_href)

    # ---------------- 缩放 ----------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._view_mode == VIEW_SCROLL and self._pixmaps:
            if self._resize_timer is None:
                self._resize_timer = QTimer(self)
                self._resize_timer.setSingleShot(True)
                self._resize_timer.setInterval(120)
                self._resize_timer.timeout.connect(self._rescale_scroll)
            self._resize_timer.start()

    def _rescale_scroll(self):
        """窗口尺寸变化后重绘整页（只重算可视区附近，避免全部重缩放卡顿）。"""
        if self._view_mode != VIEW_SCROLL:
            return
        total = len(self._sources)
        if total == 0:
            return
        self._refresh_pool_layout()

    def closeEvent(self, event):
        self._generation += 1
        self._clear_workers()
        super().closeEvent(event)
