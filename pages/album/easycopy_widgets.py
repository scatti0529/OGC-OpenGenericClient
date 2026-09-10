# -*- coding: utf-8 -*-
"""
拷贝漫画共享 UI 组件（OGC 集成版）
=================================
封面图片（异步加载）、漫画卡片、流式布局、章节标题、加载/错误/空状态提示。
颜色跟随 OGC 全局主题（ui.widgets.theme）。
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QRect, QRectF, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QPixmap, QFont, QPainter, QPen, QBrush, QPainterPath
from PyQt5.QtWidgets import (
    QFrame,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QHBoxLayout,
)

from qfluentwidgets import CardWidget, BodyLabel

from ui.widgets.theme import text_primary, text_secondary, text_tertiary


# ═══════════════════════════════════════════
#  流式布局（自动换行）
# ═══════════════════════════════════════════
class FlowLayout(QLayout):
    """流式布局，自动换行排列子控件。"""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 12):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_height = 0
        spacing = self._spacing

        for item in self._items:
            widget = item.widget()
            w = item.sizeHint().width()
            h = item.sizeHint().height()

            next_x = x + w + spacing
            if next_x - spacing > rect.right() - m.right() and line_height > 0:
                # 换行
                x = rect.x() + m.left()
                y = y + line_height + spacing
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(x, y, w, h))
            x += w + spacing
            line_height = max(line_height, h)

        return y + line_height + m.bottom() - rect.y()


# ═══════════════════════════════════════════
#  异步图片加载
# ═══════════════════════════════════════════
class _ImageLoadWorker(QThread):
    """后台图片加载线程。"""

    done = pyqtSignal(str, QPixmap)

    def __init__(self, url: str, fetcher):
        super().__init__()
        self.url = url
        self.fetcher = fetcher

    def run(self):
        try:
            data = self.fetcher.fetch(self.url)
            if data:
                pix = QPixmap()
                pix.loadFromData(data)
                if not pix.isNull():
                    self.done.emit(self.url, pix)
        except Exception:
            pass


class CoverImage(QLabel):
    """异步加载的封面图片，带缓存与圆角。"""

    def __init__(
        self,
        url: str,
        fetcher,
        radius: int = 16,
        placeholder_text: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._url = url
        self._fetcher = fetcher
        self._radius = radius
        self._pixmap: Optional[QPixmap] = None
        self._placeholder_text = placeholder_text

        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(80, 110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setWordWrap(True)

        self._show_placeholder()
        self._load()

    def _show_placeholder(self) -> None:
        self.setStyleSheet(
            f"background-color: rgba(128,128,128,0.12); color: {text_tertiary()};"
        )
        self.setText(self._placeholder_text or "加载中")

    def _load(self) -> None:
        if not self._url:
            return
        self._worker = _ImageLoadWorker(self._url, self._fetcher)
        self._worker.done.connect(self._on_loaded)
        self._worker.start()

    def _on_loaded(self, url: str, pix: QPixmap) -> None:
        if url != self._url:
            return
        self._pixmap = pix
        self.setText("")
        self.setStyleSheet("background: transparent;")
        self.update()

    def set_pixmap_image(self, pix: QPixmap) -> None:
        self._pixmap = pix
        self.setText("")
        self.setStyleSheet("background: transparent;")
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        target = self.rect()
        pix = self._pixmap
        scaled = pix.scaled(
            target.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )

        x = (scaled.width() - target.width()) // 2
        y = (scaled.height() - target.height()) // 2

        path = QPainterPath()
        path.addRoundedRect(QRectF(target), self._radius, self._radius)
        painter.setClipPath(path)
        painter.drawPixmap(target.x() - x, target.y() - y, scaled)
        painter.end()


# ═══════════════════════════════════════════
#  漫画卡片
# ═══════════════════════════════════════════
class ComicCard(CardWidget):
    """漫画卡片：封面 + 标题 + 副标题。"""

    clicked = pyqtSignal(str)

    def __init__(self, title: str, cover_url: str, href: str, fetcher, subtitle: str = "", secondary: str = "", parent=None):
        super().__init__(parent)
        self._href = href

        self.setObjectName("easycopyComicCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 8)
        layout.setSpacing(6)

        self.cover = CoverImage(cover_url, fetcher, radius=14)
        self.cover.setFixedWidth(148)
        self.cover.setFixedHeight(205)
        layout.addWidget(self.cover, 0, Qt.AlignHCenter)

        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(40)
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.title_label.setStyleSheet(f"color: {text_primary()};")
        layout.addWidget(self.title_label)

        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setWordWrap(False)
            self.subtitle_label.setMaximumHeight(18)
            self.subtitle_label.setStyleSheet(f"color: {text_tertiary()}; font-size: 12px;")
            layout.addWidget(self.subtitle_label)

        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(
            """
            #easycopyComicCard { background-color: transparent; border-radius: 20px; }
            #easycopyComicCard:hover { background-color: rgba(128,128,128,0.10); }
            QLabel { background: transparent; border: none; }
            """
        )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self._href)
        # 不调用 super().mouseReleaseEvent，避免基类 CardWidget 的无参 clicked
        # 信号与本类带参 clicked 信号冲突


# ═══════════════════════════════════════════
#  板块标题栏
# ═══════════════════════════════════════════
class SectionHeader(QFrame):
    """板块标题栏：竖条 + 标题 + 可选「查看更多」。"""

    def __init__(self, title: str, show_more: bool = False, parent=None, on_more=None):
        super().__init__(parent)
        self.on_more = on_more
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        bar = QFrame()
        bar.setFixedSize(4, 20)
        bar.setStyleSheet("background-color: #28AFE9; border-radius: 2px;")
        layout.addWidget(bar)

        title_label = BodyLabel(title)
        font = QFont("Microsoft YaHei UI", 10)
        font.setWeight(QFont.DemiBold)
        title_label.setFont(font)
        title_label.setStyleSheet(f"color: {text_primary()};")
        layout.addWidget(title_label)

        layout.addStretch(1)

        if show_more:
            more = QLabel("查看更多 >")
            more.setCursor(Qt.PointingHandCursor)
            more.setStyleSheet(f"color: {text_tertiary()};")
            more.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            more.mousePressEvent = lambda e: self.on_more and self.on_more()
            layout.addWidget(more)


# ═══════════════════════════════════════════
#  状态提示
# ═══════════════════════════════════════════
class LoadingLabel(QLabel):
    """加载占位提示。"""

    def __init__(self, text: str = "加载中…", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"color: {text_tertiary()}; padding: 32px; font-size: 14px;")


class ErrorLabel(QLabel):
    """错误提示。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setText(f"⚠ {text}")
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet("color: #B5542F; padding: 24px; font-size: 14px;")


class EmptyLabel(QLabel):
    """空状态提示。"""

    def __init__(self, text: str = "暂时没有可展示的内容。", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"color: {text_tertiary()}; padding: 48px; font-size: 14px;")
