# -*- coding: utf-8 -*-
"""通用 UI 组件：画廊卡片、星级评分、标签流、占位提示"""
from PyQt5.QtCore import Qt, QRectF, pyqtSignal, QSize
from PyQt5.QtGui import QPainter, QColor, QPixmap, QIcon, QFont, QPen
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QGraphicsDropShadowEffect,
                             QSizePolicy)

from qfluentwidgets import (CardWidget, BodyLabel, CaptionLabel, StrongBodyLabel, SubtitleLabel,
                            ToolButton, FluentIcon, isDarkTheme)

from .. import constants as C
from ..models import GalleryInfo


class StarRating(QWidget):
    """星级显示（0-5，支持半星）"""

    def __init__(self, parent=None):
        super(StarRating, self).__init__(parent)
        self.rating = 0.0
        self.star_color = QColor("#FFB300")
        self.empty_color = QColor(0, 0, 0, 60)
        self.setFixedHeight(16)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_rating(self, r):
        try:
            self.rating = max(0.0, min(5.0, float(r)))
        except (TypeError, ValueError):
            self.rating = 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        star_w = self.height()
        gap = 2
        for i in range(5):
            rect = QRectF(i * (star_w + gap), 0, star_w, star_w)
            p.setPen(Qt.NoPen)
            p.setBrush(self.empty_color)
            self._draw_star(p, rect, 1.0)
            fill = max(0.0, min(1.0, self.rating - i))
            if fill > 0:
                p.setBrush(self.star_color)
                self._draw_star(p, rect, fill)
        p.end()
        self.setFixedWidth(int(5 * (star_w + gap)) - gap)

    def _draw_star(self, p, rect, fill):
        # 用 clip 实现部分填充
        if fill >= 1.0:
            self._star_path(p, rect)
        else:
            p.save()
            p.setClipRect(QRectF(rect.x(), rect.y(), rect.width() * fill, rect.height()))
            self._star_path(p, rect)
            p.restore()

    def _star_path(self, p, rect):
        from PyQt5.QtGui import QPainterPath
        path = QPainterPath()
        cx, cy, r = rect.center().x(), rect.center().y(), rect.width() / 2
        path.moveTo(cx, cy - r)
        for i in range(5):
            a1 = -90 + i * 72
            import math
            x1 = cx + r * math.cos(math.radians(a1 + 36))
            y1 = cy + r * math.sin(math.radians(a1 + 36))
            x2 = cx + r * math.cos(math.radians(a1 + 72))
            y2 = cy + r * math.sin(math.radians(a1 + 72))
            path.lineTo(x1, y1)
            path.lineTo(x2, y2)
        path.closeSubpath()
        p.drawPath(path)


class TagChips(QWidget):
    """标签流（namespace:name 的 chip 显示）"""
    tagClicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super(TagChips, self).__init__(parent)
        self._tags = []
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_tags(self, tags, limit=12):
        """tags: list[(namespace, name)]"""
        self._tags = list(tags)[:limit]
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for ns, name in self._tags:
            chip = _TagChip("%s:%s" % (ns, name))
            chip.clicked.connect(lambda t=ns + ":" + name: self.tagClicked.emit(t))
            self._layout.addWidget(chip)
        self._layout.addStretch(1)


class _TagChip(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, text, parent=None):
        super(_TagChip, self).__init__(parent)
        self.setText(text)
        self.setStyleSheet("""
            _TagChip {
                background: rgba(127, 127, 127, 0.18);
                border-radius: 7px;
                padding: 1px 6px;
                font-size: 11px;
            }
            _TagChip:hover {
                background: rgba(0, 120, 215, 0.25);
            }
        """)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.text())


class GalleryCard(CardWidget):
    """画廊卡片：封面 + 标题 + 分类 + 评分 + 信息"""
    cardClicked = pyqtSignal(object)      # GalleryInfo（避免与 CardWidget.clicked 冲突）
    favoriteClicked = pyqtSignal(object)

    COVER_W = 168
    COVER_H = 238

    def __init__(self, parent=None):
        super(GalleryCard, self).__init__(parent)
        self._info = None
        self._pixmap = None
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(12)

        self.cover = QLabel(self)
        self.cover.setFixedSize(self.COVER_W, self.COVER_H)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background: rgba(127,127,127,0.15); border-radius: 6px; color: #888;")
        self.cover.setText("加载中…")
        self._layout.addWidget(self.cover, 0, Qt.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(5)
        self.title = StrongBodyLabel("", self)
        self.title.setWordWrap(True)
        self.title.setMaximumHeight(56)
        right.addWidget(self.title)

        top_row = QHBoxLayout()
        self.cat_label = CaptionLabel("", self)
        self.cat_label.setStyleSheet("padding: 1px 8px; border-radius: 8px; color: white;")
        self.rating = StarRating(self)
        self.rating_text = CaptionLabel("", self)
        top_row.addWidget(self.cat_label)
        top_row.addStretch(1)
        top_row.addWidget(self.rating)
        top_row.addWidget(self.rating_text)
        right.addLayout(top_row)

        self.meta = CaptionLabel("", self)
        self.meta.setStyleSheet("color: #888;")
        right.addWidget(self.meta)

        self.tags = TagChips(self)
        right.addWidget(self.tags)

        bottom_row = QHBoxLayout()
        self.fav_btn = ToolButton(FluentIcon.HEART, self)
        self.fav_btn.setToolTip("收藏")
        self.fav_btn.setFixedSize(26, 26)
        self.fav_btn.clicked.connect(self._on_fav)
        self.page_label = CaptionLabel("", self)
        self.page_label.setStyleSheet("color: #888;")
        bottom_row.addWidget(self.fav_btn)
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.page_label)
        right.addLayout(bottom_row)

        self._layout.addLayout(right, 1)
        self.setFixedHeight(self.COVER_H + 18)

    def _on_fav(self):
        if self._info is not None:
            self.favoriteClicked.emit(self._info)

    def set_info(self, info, show_jpn=False):
        self._info = info
        self.title.setText(info.suitable_title(show_jpn))
        cat_name = C.get_category_name(info.category)
        self.cat_label.setText(" " + cat_name + " ")
        self.cat_label.setStyleSheet(
            "padding: 1px 8px; border-radius: 8px; color: white; background: %s;"
            % C.get_category_color(info.category))
        self.rating.set_rating(info.rating)
        if info.rating > 0:
            self.rating_text.setText("(%.2f)" % info.rating)
        else:
            self.rating_text.setText("")
        parts = []
        if info.uploader:
            parts.append("上传者: " + info.uploader)
        if info.posted:
            parts.append(info.posted)
        if info.simple_language:
            parts.append(info.simple_language)
        self.meta.setText("  ·  ".join(parts))
        tags = []
        if info.simple_tags:
            for t in info.simple_tags:
                if ":" in t:
                    ns, nm = t.split(":", 1)
                    if ns in ("language", "female", "male", "artist", "group", "parody", "character", "reclass"):
                        tags.append((ns, nm))
        self.tags.set_tags(tags[:8])
        self.page_label.setText("%d 页" % info.pages if info.pages else "")
        self._update_fav_icon(info.is_favorited)

    def _update_fav_icon(self, fav):
        icon = FluentIcon.HEART if fav else FluentIcon.HEART
        if fav:
            self.fav_btn.setIcon(FluentIcon.HEART)
        else:
            self.fav_btn.setIcon(FluentIcon.HEART)

    def set_cover_pixmap(self, pixmap):
        if pixmap is None or pixmap.isNull():
            self.cover.setText("无封面")
            return
        self._pixmap = pixmap
        scaled = pixmap.scaled(self.COVER_W, self.COVER_H, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
        self.cover.setPixmap(scaled)
        self.cover.setText("")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._info is not None:
                self.cardClicked.emit(self._info)
        super(GalleryCard, self).mouseReleaseEvent(event)


class EmptyHint(QWidget):
    """空状态提示"""

    def __init__(self, text="暂无内容", parent=None):
        super(EmptyHint, self).__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        self.icon = QLabel(self)
        self.icon.setPixmap(FluentIcon.LIBRARY.icon(64).pixmap(64, 64))
        self.icon.setAlignment(Qt.AlignCenter)
        self.label = BodyLabel(text, self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("color: #888;")
        lay.addWidget(self.icon)
        lay.addWidget(self.label)
