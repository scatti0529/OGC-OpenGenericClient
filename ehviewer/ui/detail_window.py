# -*- coding: utf-8 -*-
"""画廊详情窗口（仿 e-hentai 官网详情页布局）
左侧封面 + 右上标题/日文标题，下方三列：信息 / 标签(按命名空间彩色) / 操作；
随后是“该画廊有更新版本”、评论、缩略图网格（显示 N张图片中的 X-Y，页码+文件名）。
"""
import re

from PyQt5.QtCore import Qt, QThread, QUrl, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QPixmap, QDesktopServices
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QLabel, QDialog, QListWidget, QListWidgetItem, QGridLayout)

from qfluentwidgets import (CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
                            StrongBodyLabel, PrimaryPushButton, PushButton, ToolButton,
                            InfoBar, InfoBarPosition, FluentIcon, ScrollArea,
                            FlowLayout, CheckBox)

from .. import constants as C
from .. import engine
from .. import db
from ..config import get, is_login
from ..appctx import ctx
from ..models import GalleryInfo, GalleryDetail
from ..session import EhException
from ..tag_translation import tag_translation
from .bus import bus
from .widgets import StarRating

TAG_COLORS = {
    "female": "#CC6699", "male": "#6699CC", "language": "#CC9966",
    "artist": "#CC66CC", "group": "#6699CC", "parody": "#99CC66",
    "character": "#CC9966", "reclass": "#808080", "misc": "#808080",
    "other": "#808080", "mixed": "#808080", "cosplayer": "#CC6699",
}


def _tag_color(ns):
    return TAG_COLORS.get(ns.lower(), "#808080")


_BODY_FONT = None


def _body_label_font():
    """返回与详情“信息”列 BodyLabel(str(v)) 一致的字体的副本（懒创建并缓存）。"""
    global _BODY_FONT
    if _BODY_FONT is None:
        try:
            probe = BodyLabel("")
            _BODY_FONT = QFont(probe.font())
            probe.deleteLater()
        except Exception:
            _BODY_FONT = QFont()
    return QFont(_BODY_FONT)


class DetailWorker(QThread):
    done = pyqtSignal(object, str)

    def __init__(self, gid, token, parent=None):
        super(DetailWorker, self).__init__(parent)
        self.gid = gid
        self.token = token

    def run(self):
        try:
            detail = engine.get_gallery_detail(self.gid, self.token)
            self.done.emit(detail, "")
        except Exception as e:
            self.done.emit(None, str(e))


class FavoriteDialog(QDialog):
    """收藏夹选择：本地收藏 + 云端 10 槽"""

    def __init__(self, parent=None):
        super(FavoriteDialog, self).__init__(parent)
        self.setWindowTitle("添加收藏")
        self.setFixedSize(360, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(SubtitleLabel("选择收藏位置"))
        self.listw = QListWidget(self)
        lay.addWidget(self.listw, 1)
        row = QHBoxLayout()
        ok = PrimaryPushButton("确定", self)
        ok.clicked.connect(self.accept)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def add_option(self, slot, name):
        item = QListWidgetItem(name)
        item.setData(Qt.UserRole, slot)
        self.listw.addItem(item)

    def choice(self):
        cur = self.listw.currentRow()
        if cur < 0:
            return -2
        return self.listw.item(cur).data(Qt.UserRole)


class TagFavoriteDialog(QDialog):
    """把画廊标签加入标签收藏（QUICK_SEARCH）"""

    def __init__(self, detail, parent=None):
        super(TagFavoriteDialog, self).__init__(parent)
        self.setWindowTitle("收藏标签")
        self.setFixedSize(420, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(SubtitleLabel("选择要收藏的标签"))
        self._boxes = []
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        cont = QWidget(scroll)
        cg = QVBoxLayout(cont)
        cg.setContentsMargins(4, 4, 4, 4)
        cg.setSpacing(4)
        for g in detail.tags or []:
            for t in g.tags:
                cb = CheckBox("%s:%s" % (g.group_name, t), cont)
                cg.addWidget(cb)
                self._boxes.append((cb, g.group_name, t))
        cg.addStretch(1)
        scroll.setWidget(cont)
        lay.addWidget(scroll, 1)
        row = QHBoxLayout()
        ok = PrimaryPushButton("收藏所选", self)
        ok.clicked.connect(self.accept)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)


class _TagChip(QLabel):
    """彩色标签 chip（文字后附 [中文翻译]，翻译库缺失时只显示原文）"""

    # 展示的中文名长度上限（太长会被截断并加省略号，防止单 chip 撑爆行宽）
    _ZH_MAX = 20

    def __init__(self, namespace, tag, parent=None):
        super(_TagChip, self).__init__(parent)
        # 字体大小与详情“信息”列的 BodyLabel 一致（不再写死 11px）
        self.setFont(_body_label_font())
        zh = tag_translation(namespace, tag)
        if zh and zh.lower() == (tag or "").strip().lower():
            zh = ""   # 译名与原文相同则不加括号
        if zh and len(zh) > self._ZH_MAX:
            zh = zh[:self._ZH_MAX] + "…"
        shown = tag if not zh else "%s[%s]" % (tag, zh)
        self.setText(shown)
        self.setToolTip("%s:%s" % (namespace, tag))
        color = _tag_color(namespace)
        self.setStyleSheet(
            "background: %s; color: white; border-radius: 8px; padding: 2px 10px;"
            % color)
        self.setCursor(Qt.PointingHandCursor)


class DetailWindow(QWidget):
    # 详情页「下载」请求：转发给宿主（E-Hentai 模块转交 下载画廊），
    # 避免详情页直接使用 ehviewer 下载管理器（与 OGC 下载画廊分离）。
    downloadRequested = pyqtSignal(object, str)   # (GalleryInfo, label)

    def __init__(self, info, parent=None):
        super(DetailWindow, self).__init__(parent)
        self._info = info
        self._detail = None
        self.setWindowTitle("画廊详情")
        self.resize(1020, 860)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        # back = ToolButton(FluentIcon.LEFT_ARROW, self)
        # back.setToolTip("返回")
        # back.clicked.connect(self.close)
        # top.addWidget(back)
        self.title_bar = StrongBodyLabel(info.suitable_title(get("show_jpn_title", False)), self)
        top.addWidget(self.title_bar, 1)
        self.read_btn = PrimaryPushButton("阅读", self)
        self.read_btn.clicked.connect(self._read)
        top.addWidget(self.read_btn)
        root.addLayout(top)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self._container = QWidget(self.scroll)
        self._lay = QVBoxLayout(self._container)
        self._lay.setContentsMargins(8, 8, 8, 8)
        self._lay.setSpacing(10)
        self.scroll.setWidget(self._container)
        root.addWidget(self.scroll, 1)

        self.status = CaptionLabel("加载中…", self)
        self.status.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status)

        db.add_history(info)
        bus.historyChanged.emit()

        self._worker = DetailWorker(info.gid, info.token, self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    # ---------- 数据 ----------
    def _on_done(self, detail, err):
        if err:
            self.status.setText("加载失败：" + err)
            self.status.setStyleSheet("color: #e5484d;")
            return
        self.status.setText("")
        self._detail = detail
        db.add_history(detail)
        bus.historyChanged.emit()
        self._build_content()

    # ---------- 布局 ----------
    def _build_content(self):
        d = self._detail
        self._build_header(d)
        if d.new_versions:
            self._build_versions(d)
        if d.comments and d.comments.comments:
            self._build_comments(d)
        if d.preview_set:
            self._build_previews(d)
        self._lay.addStretch(1)

    def _build_header(self, d):
        head = CardWidget(self._container)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(16)

        # 左：封面
        self.cover = QLabel(head)
        self.cover.setFixedSize(190, 270)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background: rgba(127,127,127,0.15); border-radius: 6px; color: #888;")
        self.cover.setText("封面加载中…")
        hl.addWidget(self.cover, 0, Qt.AlignTop)

        # 右：标题块 + 三列
        right = QVBoxLayout()
        right.setSpacing(8)
        title = StrongBodyLabel(d.title or d.title_jpn or "")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 18px;")
        right.addWidget(title)
        if d.title_jpn and d.title_jpn != d.title:
            jt = CaptionLabel(d.title_jpn)
            jt.setWordWrap(True)
            jt.setStyleSheet("color: #888;")
            right.addWidget(jt)

        cols = QHBoxLayout()
        cols.setSpacing(16)

        # 信息列
        info_col = QVBoxLayout()
        info_col.setSpacing(3)
        info_col.addWidget(SubtitleLabel("信息"))
        rows = []
        if d.uploader:
            rows.append(("上传者", d.uploader))
        if d.posted:
            rows.append(("发布时间", d.posted))
        if d.parent:
            rows.append(("家长", d.parent))
        if d.visible:
            rows.append(("可见", d.visible))
        if d.language:
            rows.append(("语言", d.language))
        if d.size:
            rows.append(("文件大小", d.size))
        if d.pages:
            rows.append(("页数", "%d 页" % d.pages))
        if d.favorite_count:
            rows.append(("收藏", "%d 次" % d.favorite_count))
        for k, v in rows:
            r = QHBoxLayout()
            kk = CaptionLabel(k)
            kk.setStyleSheet("color: #888;")
            kk.setFixedWidth(64)
            vv = BodyLabel(str(v))
            vv.setWordWrap(True)
            r.addWidget(kk)
            r.addWidget(vv, 1)
            info_col.addLayout(r)
        # 评分
        r = QHBoxLayout()
        r.addWidget(CaptionLabel("评分"))
        stars = StarRating()
        stars.set_rating(d.rating)
        r.addWidget(stars)
        info_col.addLayout(r)
        r2 = QHBoxLayout()
        r2.addWidget(CaptionLabel("平均评分 %.2f" % d.rating if d.rating > 0 else "尚未评分"))
        if d.rating_count:
            r2.addWidget(CaptionLabel("(%d 人)" % d.rating_count))
        r2.addStretch(1)
        info_col.addLayout(r2)
        info_col.addStretch(1)
        cols.addLayout(info_col)

        # 标签列
        tag_col = QVBoxLayout()
        tag_col.setSpacing(3)
        tag_col.addWidget(SubtitleLabel("标签"))
        for g in d.tags or []:
            row = QHBoxLayout()
            row.setSpacing(6)
            box = CaptionLabel((g.group_name or "") + ":")
            box.setStyleSheet("color: #888;")
            box.setFixedWidth(64)
            row.addWidget(box, 0, Qt.AlignTop)
            # 流式布局：标签自动换行，保证不超出容器宽度
            flow = FlowLayout(needAni=False)
            flow.setSpacing(4)
            for t in g.tags:
                chip = _TagChip(g.group_name, t, self._container)
                flow.addWidget(chip)
            row.addLayout(flow, 1)
            tag_col.addLayout(row)
        tag_col.addStretch(1)
        cols.addLayout(tag_col, 1)

        # 操作列
        act_col = QVBoxLayout()
        act_col.setSpacing(6)
        act_col.addWidget(SubtitleLabel("操作"))
        actions = [
            ("下载漫画", FluentIcon.DOWNLOAD, self._download),
            ("收藏漫画", FluentIcon.HEART, self._favorite),
            ("收藏标签", FluentIcon.TAG, self._favorite_tags),
            ("查看评论", FluentIcon.CHAT, self._scroll_comments),
            ("评分", FluentIcon.EDIT, self._rate),
            ("打开网页", FluentIcon.LINK, self._open_gallery_page),
            ("相似画廊", FluentIcon.SEARCH, self._similar),
        ]
        for text, icon, fn in actions:
            b = PushButton(text, self)
            b.setIcon(icon.icon(18))
            b.clicked.connect(fn)
            act_col.addWidget(b)
        act_col.addStretch(1)
        cols.addLayout(act_col)

        right.addLayout(cols, 1)
        hl.addLayout(right, 1)
        self._lay.addWidget(head)

        # 封面加载
        thumb = getattr(self._info, 'thumb', '') or d.thumb or ''
        if thumb:
            loader = ctx.image_loader
            if loader is not None:
                key = "detail:%d" % d.gid
                loader.loaded.connect(self._on_cover_loaded, Qt.UniqueConnection)
                # 用规范化的预览缩略图 URL，加载更快
                try:
                    from ..urls import get_fixed_preview_thumb_url
                    thumb_url = get_fixed_preview_thumb_url(thumb) or thumb
                except Exception:
                    thumb_url = thumb
                # 统一封面：命中缓存直接用；未命中走 cover_service（抓第一页缩略图），并兜底拉 thumb
                try:
                    from pages.album.eh_cover import cover_service
                    pix = cover_service.load(d.gid)
                    if pix is not None and not pix.isNull():
                        self._on_cover_loaded(key, thumb_url, pix)
                        return
                    cover_service.loaded.connect(self._on_cover_loaded_gid, Qt.UniqueConnection)
                    cover_service.enqueue(d.gid, thumb_url, getattr(d, 'token', '') or '')
                    if thumb_url:
                        loader.load(key, thumb_url, is_thumb=True)
                    return
                except Exception:
                    loader.load(key, thumb_url, is_thumb=True)

        # 记录封面窗口引用供滚动定位
        self._comments_widget = None

    def _build_versions(self, d):
        card = CardWidget(self._container)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(4)
        lay.addWidget(StrongBodyLabel("该画廊有更新版本"))
        for v in d.new_versions:
            lbl = CaptionLabel(v.version_name or "")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        self._lay.addWidget(card)

    def _build_comments(self, d):
        card = CardWidget(self._container)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 10, 16, 10)
        cl.setSpacing(6)
        cl.addWidget(StrongBodyLabel("评论"))
        for c in d.comments.comments[:3]:
            cb = CardWidget(card)
            cb_lay = QVBoxLayout(cb)
            cb_lay.setContentsMargins(12, 8, 12, 8)
            h = QHBoxLayout()
            h.addWidget(StrongBodyLabel(c.user or "匿名"))
            h.addStretch(1)
            h.addWidget(CaptionLabel("评分 %d" % c.score))
            cb_lay.addLayout(h)
            text = re.sub(r"<[^>]+>", " ", c.comment or "")
            body = CaptionLabel(text.strip()[:200])
            body.setWordWrap(True)
            cb_lay.addWidget(body)
            cl.addWidget(cb)
        if d.comments.has_more:
            cl.addWidget(CaptionLabel("… 还有更多评论"))
        self._comments_widget = card
        self._lay.addWidget(card)

    def _build_previews(self, d):
        import os as _os
        from types import SimpleNamespace
        card = CardWidget(self._container)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(8)
        total = d.pages
        n = 20
        lay.addWidget(StrongBodyLabel("预览 — 前 %d 张（画廊页 #gdt 缩略图）" % n))
        flow = FlowLayout(needAni=False)
        flow.setSpacing(6)
        self._preview_map = {}
        self._preview_cells = []
        for i in range(n):
            item = SimpleNamespace(position=i, image_url='')
            cell = _PreviewCell(item, self._container)
            cell.clicked.connect(self._jump_to)
            flow.addWidget(cell)
            self._preview_cells.append(cell)
        lay.addLayout(flow)
        self._lay.addWidget(card)

        # 已缓存：直接读缩略图文件夹；否则抓画廊页 #gdt 生成前 20 张预览
        try:
            from pages.album.eh_preview import cached_count, preview_path
            gid = d.gid
            if cached_count(gid) >= n:
                for i in range(n):
                    pth = preview_path(gid, i)
                    if _os.path.isfile(pth):
                        pix = QPixmap(pth)
                        if not pix.isNull():
                            self._preview_cells[i].set_pixmap(pix)
                return
            self._start_preview_worker(gid, d.token)
        except Exception:
            pass

    def _start_preview_worker(self, gid, token):
        from pages.album.eh_preview import GdtPreviewWorker
        try:
            self._pv_worker = GdtPreviewWorker(gid, token, n=20, parent=self)
            self._pv_worker.ready.connect(self._on_preview_file_ready)
            self._pv_worker.done.connect(self._on_preview_done)
            self._pv_worker.log.connect(self._on_preview_log)
            self._pv_worker.start()
        except Exception:
            pass

    def _on_preview_done(self, _count):
        pass

    def _on_preview_log(self, msg):
        try:
            InfoBar.warning("预览", msg, position=InfoBarPosition.TOP,
                            duration=3000, parent=self)
        except Exception:
            pass

    def _on_preview_file_ready(self, index, filepath):
        try:
            if 0 <= index < len(self._preview_cells):
                pix = QPixmap(filepath)
                if not pix.isNull():
                    self._preview_cells[index].set_pixmap(pix)
        except Exception:
            pass

    def _on_preview_loaded(self, key, url, pixmap):
        cell = self._preview_map.get(key)
        if cell is not None:
            cell.set_pixmap(pixmap)

    # ---------- 组件回调 ----------
    def _on_cover_loaded(self, key, url, pixmap):
        if key == "detail:%d" % self._info.gid:
            if pixmap is None or pixmap.isNull():
                return
            self.cover.setPixmap(pixmap.scaled(190, 270, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.cover.setText("")
            # 保存到统一封面缓存（供收藏/历史/主页复用同一张）
            try:
                from pages.album.eh_cover import cover_service
                cover_service.save(self._info.gid, pixmap)
            except Exception:
                pass

    def _on_cover_loaded_gid(self, gid, pixmap):
        """cover_service 第一页缩略图下载完成 -> 回填本详情页封面。"""
        if gid != getattr(self._info, 'gid', None):
            return
        if pixmap is None or pixmap.isNull():
            return
        self.cover.setPixmap(pixmap.scaled(190, 270, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.cover.setText("")

    # ---------- 操作 ----------
    def _read(self):
        bus.openReader.emit(self._detail or self._info, 0)

    def _jump_to(self, page):
        bus.openReader.emit(self._detail or self._info, page)

    def _download(self):
        d = self._detail or self._info
        label = self._choose_label()
        if label is None:
            return
        # 通知宿主（E-Hentai 模块）转交下载画廊的 OGC 下载器下载，并同步数据库。
        try:
            self.downloadRequested.emit(d, label or "")
        except Exception:
            pass

    def _choose_label(self):
        from PyQt5.QtWidgets import QInputDialog
        labels = ["未分类"]
        labels += [l["label"] for l in db.list_labels()]
        text, ok = QInputDialog.getItem(self, "选择下载分类",
                                        "选择或输入新的分类：", labels, 0, True)
        if not ok:
            return None
        text = (text or "").strip()
        if text and text != "未分类" and text not in labels:
            db.add_label(text)
        return text if text != "未分类" else ""

    def _favorite_tags(self):
        d = self._detail
        if d is None or not d.tags:
            InfoBar.info("", "该画廊暂无标签", position=InfoBarPosition.TOP_RIGHT,
                         duration=2000, parent=self)
            return
        dlg = TagFavoriteDialog(d, self)
        if dlg.exec_():
            n = 0
            for cb, ns, t in dlg._boxes:
                if cb.isChecked():
                    if db.add_tag_favorite("%s:%s" % (ns, t), name=t):
                        n += 1
            InfoBar.success("", "已收藏 %d 个标签" % n, position=InfoBarPosition.TOP_RIGHT,
                            duration=2500, parent=self)

    def _scroll_comments(self):
        if self._comments_widget is not None:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(self._comments_widget.y())
        elif self._detail is not None and self._detail.comments:
            self._build_comments(self._detail)
            self._scroll_comments()

    def _favorite(self):
        d = self._detail
        if d is None:
            return
        if not is_login():
            if db.is_local_favorited(d.gid):
                db.delete_local_favorite(d.gid)
                InfoBar.info("", "已从本地收藏移除", position=InfoBarPosition.TOP_RIGHT,
                             duration=2000, parent=self)
            else:
                db.add_local_favorite(d)
                InfoBar.success("", "已添加至本地收藏", position=InfoBarPosition.TOP_RIGHT,
                                duration=2000, parent=self)
            bus.favoriteChanged.emit(d.gid, db.is_local_favorited(d.gid))
            return
        dlg = FavoriteDialog(self)
        dlg.add_option(-1, "本地收藏")
        for i in range(10):
            dlg.add_option(i, C.FAVORITE_CAT_NAMES[i])
        if dlg.exec_():
            slot = dlg.choice()
            try:
                engine.add_favorite(d.gid, d.token, slot)
                if slot == -1:
                    db.add_local_favorite(d)
                InfoBar.success("", "已添加至收藏" if slot != -1 else "已添加至本地收藏",
                                position=InfoBarPosition.TOP_RIGHT, duration=2000, parent=self)
                bus.favoriteChanged.emit(d.gid, True)
            except Exception as e:
                InfoBar.error("", "收藏失败：" + str(e), position=InfoBarPosition.TOP_RIGHT,
                              duration=3000, parent=self)

    def _rate(self):
        d = self._detail
        if d is None:
            return
        if not is_login():
            InfoBar.warning("", "请先登录再评分", position=InfoBarPosition.TOP_RIGHT,
                            duration=2500, parent=self)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("评分")
        lay = QVBoxLayout(dlg)
        from qfluentwidgets import Slider
        slider = Slider(Qt.Horizontal)
        slider.setRange(0, 10)
        slider.setValue(9)
        label = CaptionLabel("5.0 星")
        slider.valueChanged.connect(lambda v: label.setText("%.1f 星" % (v / 2.0)))
        lay.addWidget(slider)
        lay.addWidget(label)
        row = QHBoxLayout()
        ok = PrimaryPushButton("提交", dlg)
        cancel = PushButton("取消", dlg)
        cancel.clicked.connect(dlg.reject)
        ok.clicked.connect(dlg.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        if dlg.exec_():
            rating = slider.value() / 2.0
            def _do():
                try:
                    engine.rate_gallery(d.gid, d.token, rating, d.api_uid, d.api_key)
                    bus.notify.emit("success", "评分成功")
                except Exception as e:
                    bus.notify.emit("error", "评分失败：" + str(e))
            import threading
            threading.Thread(target=_do, daemon=True).start()

    def _open_gallery_page(self):
        """在默认浏览器中打开该漫画的网页链接。"""
        d = self._detail or self._info
        if d is None:
            return
        try:
            gid = getattr(d, 'gid', 0) or 0
            token = getattr(d, 'token', '') or ''
            if not gid or not token:
                bus.notify.emit("error", "缺少画廊 gid/token，无法打开网页。")
                return
            url = "https://e-hentai.org/g/%s/%s/" % (gid, token)
            ok = QDesktopServices.openUrl(QUrl(url))
            if not ok:
                bus.notify.emit("error", "打开浏览器失败：%s" % url)
        except Exception as e:
            bus.notify.emit("error", "打开网页失败：" + str(e))

    def _similar(self):
        d = self._detail
        if d is None:
            return
        title = d.title or ""
        keyword = title.split("[")[0].split("(")[0].strip()[:60]
        if keyword:
            bus.doSearch.emit(keyword, C.MODE_NORMAL)
            self.close()

    def closeEvent(self, event):
        # 精确回收本窗口启动的后台线程，避免返回/关闭时 QThread 运行中被销毁
        for _attr in ("_worker", "_pv_worker"):
            w = getattr(self, _attr, None)
            if w is not None:
                try:
                    if w.isRunning():
                        try:
                            stop = getattr(w, "stop", None)
                            if callable(stop):
                                stop()
                        except Exception:
                            pass
                        w.wait(2500)
                except Exception:
                    pass
        super(DetailWindow, self).closeEvent(event)


class _PreviewCell(QWidget):
    """缩略图 + 页码/文件名"""

    clicked = pyqtSignal(int)

    def __init__(self, item, parent=None):
        super(_PreviewCell, self).__init__(parent)
        self._item = item
        self._pixmap = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.img = QLabel(self)
        self.img.setFixedSize(96, 128)
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setStyleSheet("background: rgba(127,127,127,0.12); border-radius: 4px; color:#888;")
        self.img.setText("…")
        lay.addWidget(self.img)
        # 文件名
        name = ""
        if item.image_url:
            name = item.image_url.split("/")[-1].split("?")[0]
        cap = CaptionLabel("第%d页: %s" % (item.position + 1, name))
        cap.setWordWrap(True)
        cap.setStyleSheet("color: #888;")
        lay.addWidget(cap)
        self.setCursor(Qt.PointingHandCursor)

    def set_pixmap(self, pixmap):
        if pixmap is not None and not pixmap.isNull():
            self.img.setPixmap(pixmap.scaled(96, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.img.setText("")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._item.position)
        super(_PreviewCell, self).mouseReleaseEvent(event)
