# -*- coding: utf-8 -*-
"""Pixiv 专用解析下载页面"""
import os
import re
import threading

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QGridLayout, QFrame, QRadioButton,
)
from qfluentwidgets import (
    CardWidget, FluentIcon as FIF, LineEdit, PrimaryPushButton,
    PushButton, BodyLabel, CaptionLabel, SubtitleLabel,
)
from services.pixiv_service import (
    PixivDownloader, LoginRequiredError,
    get_all_user_illustrations, get_ranking_illustrations,
)
from core.config import config as CFG
from ui.widgets.theme import theme_color
from pages.video.pixiv_dialogs import (
    PixivConfigDialog, PixivFeatureDialog,
    show_error, show_info, show_success,
)


class PixivParseThread(QThread):
    """Pixiv 后台解析线程"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, mode, value, pages, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.value = value
        self.pages = pages
        self._downloader = PixivDownloader()

    def run(self):
        try:
            self._downloader.api
            data_list = []
            if self.mode == 'artist':
                ids = re.split(r'[\s,，]+', self.value.strip())
                ids = [i for i in ids if i]
                if not ids:
                    self.error.emit('请输入画师ID')
                    return
                max_posts = int(CFG.get('pixiv_max_posts', 0) or 0)
                for uid in ids:
                    try:
                        illusts = get_all_user_illustrations(self._downloader, uid)
                        if max_posts and max_posts > 0:
                            illusts = illusts[:max_posts]
                        data_list.extend(illusts)
                    except Exception as e:
                        self.error.emit(f'获取画师 {uid} 作品失败: {e}')
                        continue
            elif self.mode == 'illust':
                ids = re.split(r'[\s,，]+', self.value.strip())
                ids = [i for i in ids if i]
                if not ids:
                    self.error.emit('请输入作品ID')
                    return
                for iid in ids:
                    try:
                        detail = self._downloader._aapi.illust_detail(iid)
                        illust = detail.get('illust')
                        if illust:
                            data_list.append(illust)
                    except Exception as e:
                        self.error.emit(f'获取作品 {iid} 失败: {e}')
                        continue
            elif self.mode == 'tag':
                tag = self.value.strip()
                if not tag:
                    self.error.emit('请输入标签名')
                    return
                page = max(1, min(self.pages, 20))
                offset = 0
                for _ in range(page):
                    try:
                        result = self._downloader._aapi.search_illust(tag, offset=offset)
                        illusts = result.get('illusts') or []
                    except Exception as e:
                        self.error.emit(f'搜索标签 {tag} 失败: {e}')
                        break
                    if not illusts:
                        break
                    data_list.extend(illusts)
                    if not result.get('next_url'):
                        break
                    offset += 30
            elif self.mode == 'ranking':
                page = max(1, min(self.pages, 20))
                data_list = get_ranking_illustrations(self._downloader, total_page=page)
            elif self.mode == 'bookmarks':
                page = max(1, min(self.pages, 50))
                offset = 0
                for _ in range(page):
                    try:
                        result = self._downloader._aapi.user_bookmarks_illust(None, offset=offset)
                        illusts = result.get('illusts') or []
                    except Exception as e:
                        self.error.emit(f'获取收藏失败: {e}')
                        break
                    if not illusts:
                        break
                    data_list.extend(illusts)
                    if not result.get('next_url'):
                        break
                    offset += 30
            elif self.mode == 'history_ranking':
                date = self.value.strip()
                if not re.search(r'^\d{4}-\d{2}-\d{2}$', date):
                    self.error.emit('历史排行榜需输入日期，格式 YYYY-MM-DD')
                    return
                page = max(1, min(self.pages, 20))
                data_list = get_ranking_illustrations(
                    self._downloader, date=date, total_page=page)
            if not data_list:
                self.error.emit('未找到可下载的作品')
                return
            self.finished.emit(data_list)
        except LoginRequiredError as e:
            self.error.emit(f'未登录: {e}')
        except Exception as e:
            self.error.emit(f'解析失败: {e}')


class PixivDownloadThread(QThread):
    """Pixiv 作品下载线程（使用信号跨线程安全回调）"""
    done = pyqtSignal(bool, str)

    def __init__(self, downloader, illust, save_path, add_user_folder=False,
                 add_rank=False, skip_manga=False, max_images=0, parent=None):
        super().__init__(parent)
        self._downloader = downloader
        self.illust = illust
        self.save_path = save_path
        self.add_user_folder = add_user_folder
        self.add_rank = add_rank
        self.skip_manga = skip_manga
        self.max_images = max_images

    def run(self):
        try:
            self._downloader.download_illustrations(
                self._downloader.api,
                [self.illust],
                save_path=self.save_path,
                add_user_folder=self.add_user_folder,
                add_rank=self.add_rank,
                skip_manga=self.skip_manga,
                max_images=self.max_images,
            )
            self.done.emit(True, "")
        except Exception as e:
            self.done.emit(False, str(e))


class PixivPreviewThread(QThread):
    """Pixiv 预览图加载线程"""
    loaded = pyqtSignal(object, object)
    failed = pyqtSignal(object)

    def __init__(self, illust, url, parent=None):
        super().__init__(parent)
        self.illust = illust
        self.url = url

    def run(self):
        try:
            import requests
            headers = {
                'Referer': 'https://www.pixiv.net/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                              '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            }
            resp = requests.get(self.url, headers=headers, timeout=10)
            pix = QPixmap()
            pix.loadFromData(resp.content)
            if not pix.isNull():
                self.loaded.emit(self.illust, pix)
            else:
                self.failed.emit(self.illust)
        except Exception:
            self.failed.emit(self.illust)


def _get_illust_thumb(illust):
    try:
        urls = illust.get('image_urls') or {}
        return urls.get('medium') or urls.get('large') or ''
    except Exception:
        return ''


class PixivCard(CardWidget):
    """Pixiv 作品卡片"""
    downloadRequested = pyqtSignal(object)

    def __init__(self, illust, rank=0, parent=None):
        super().__init__(parent=parent)
        self.illust = illust
        self.rank = rank
        self.name = illust.get('title', '未命名')
        try:
            user = illust.get('user') or {}
            self.user_name = user.get('name', '未知作者')
            self.user_id = str(user.get('id', ''))
        except Exception:
            self.user_name = '未知作者'
            self.user_id = ''
        self.is_manga = illust.get('type') == 'manga'
        self._queued = False
        self._preview_thread = None

        self.setFixedSize(220, 265)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self.previewLabel = QLabel("加载预览...", self)
        self.previewLabel.setAlignment(Qt.AlignCenter)
        self.previewLabel.setFixedSize(196, 130)
        self.previewLabel.setStyleSheet(theme_color(
            "background-color: rgba(0,0,0,0.08); border-radius: 6px;",
            "background-color: rgba(255,255,255,0.08); border-radius: 6px;"))
        layout.addWidget(self.previewLabel, 0, Qt.AlignCenter)

        title = self.name
        if len(title) > 24:
            title = title[:24] + '...'
        self.titleLabel = BodyLabel(title, self)
        self.titleLabel.setStyleSheet(
            "font-size: 12px; color: " + theme_color('#333333', '#E0E0E0') + ";")
        self.titleLabel.setToolTip(self.name)
        layout.addWidget(self.titleLabel)

        type_text = '📔 漫画' if self.is_manga else '🖼 插画'
        if self.rank:
            type_text = f'#{self.rank} ' + type_text
        self.metaLabel = CaptionLabel(
            f"{self.user_name}  |  {type_text}", self)
        self.metaLabel.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + ";")
        self.metaLabel.setToolTip(f"画师ID: {self.user_id}")
        layout.addWidget(self.metaLabel)

        layout.addStretch()

        self.downloadBtn = PrimaryPushButton(FIF.DOWNLOAD, "下载", self)
        self.downloadBtn.clicked.connect(lambda: self.downloadRequested.emit(self))
        layout.addWidget(self.downloadBtn)

        self._load_preview()

    def _load_preview(self):
        thumb = _get_illust_thumb(self.illust)
        if not thumb:
            self.previewLabel.setText("无预览")
            return
        self._preview_thread = PixivPreviewThread(self.illust, thumb, self)
        self._preview_thread.loaded.connect(self._on_preview_loaded)
        self._preview_thread.failed.connect(lambda i: self.previewLabel.setText("预览加载失败"))
        self._preview_thread.start()

    def _on_preview_loaded(self, illust, pixmap):
        try:
            scaled = pixmap.scaled(196, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.previewLabel.setPixmap(scaled)
        except Exception:
            self.previewLabel.setText("预览加载失败")

    def mark_queued(self):
        self._queued = True
        self.downloadBtn.setEnabled(False)
        self.downloadBtn.setText("排队中")
        self.downloadBtn.setIcon(FIF.SYNC)

    def mark_downloading(self):
        self.downloadBtn.setEnabled(False)
        self.downloadBtn.setText("下载中")
        self.downloadBtn.setIcon(FIF.DOWNLOAD)

    def mark_done(self):
        self.downloadBtn.setEnabled(False)
        self.downloadBtn.setText("已下载")
        self.downloadBtn.setIcon(FIF.ACCEPT)
        self.downloadBtn.setStyleSheet(
            "color: #67C23A; border: 1px solid #67C23A; border-radius: 6px;")

    def mark_error(self):
        self.downloadBtn.setEnabled(True)
        self.downloadBtn.setText("下载")
        self.downloadBtn.setIcon(FIF.DOWNLOAD)
        self.downloadBtn.setStyleSheet("")


