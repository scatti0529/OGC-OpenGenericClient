# -*- coding: utf-8 -*-
"""
抖音作者订阅页面
================
展示已订阅作者卡片：头像、昵称、签名、作品数量、粉丝数、
是否有更新、上次检查时间；支持取消订阅、打开主页、批量检查更新。
"""
import os

import requests
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl, QSize
from PyQt5.QtGui import QPixmap, QDesktopServices
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QGridLayout, QApplication,
)
from qfluentwidgets import (
    CardWidget, FluentIcon as FIF, PushButton, PrimaryPushButton,
    CaptionLabel, SubtitleLabel, InfoBar, InfoBarPosition, BodyLabel,
    IndeterminateProgressBar, isDarkTheme,
)

from services.douyin_subscription import (
    list_subscriptions, unsubscribe, update_author_status, mark_checked,
    is_subscribed,
)
from ui.widgets.theme import theme_color
from ui.widgets.ui_utils import install_hover_tip


DOUYIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


def load_avatar_pixmap(url: str, size: int = 56) -> QPixmap:
    """加载网络头像并缩放，失败返回空 Pixmap"""
    pix = QPixmap()
    if not url:
        return pix
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": DOUYIN_UA})
        if resp.status_code == 200:
            pix.loadFromData(resp.content)
    except Exception:
        pass
    if not pix.isNull():
        return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pix


# ═══════════════════════════════════════════════════════════
#  后台线程：加载头像 / 刷新更新
# ═══════════════════════════════════════════════════════════
class AvatarLoadThread(QThread):
    loaded = pyqtSignal(object, str)   # (pixmap, sec_uid)

    def __init__(self, url: str, sec_uid: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.sec_uid = sec_uid

    def run(self):
        try:
            self.setPriority(QThread.LowPriority)
        except Exception:
            pass
        pix = load_avatar_pixmap(self.url)
        if not pix.isNull():
            self.loaded.emit(pix, self.sec_uid)


class RefreshWorker(QThread):
    """批量检查订阅作者更新（后台线程）"""
    progress = pyqtSignal(int, int, str)   # (done, total, message)
    updated = pyqtSignal(dict)             # 更新后的订阅记录
    done = pyqtSignal(int, int)            # (成功数, 总数)

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.items = items

    def run(self):
        from services.douyin_service import DouyinDownloader
        downloader = DouyinDownloader()
        parser = downloader._get_parser()

        success = 0
        total = len(self.items)
        for i, item in enumerate(self.items, 1):
            sec_uid = item.get('sec_uid', '')
            user_home = item.get('user_home') or f"https://www.douyin.com/user/{sec_uid}"
            self.progress.emit(i, total, f"正在检查 {item.get('nickname') or sec_uid} ...")
            try:
                profile = parser.get_user_profile(user_home)
                last_aweme_id = parser.get_latest_aweme_id(user_home, max_pages=1)
                if profile:
                    update_author_status(sec_uid, profile, last_aweme_id)
                    success += 1
                else:
                    # 无法获取资料时至少尝试获取最新作品 id
                    if last_aweme_id:
                        update_author_status(sec_uid, item, last_aweme_id)
            except Exception:
                pass
            finally:
                # 避免频繁请求
                try:
                    import time
                    time.sleep(1.0)
                except Exception:
                    pass
        self.done.emit(success, total)


# ═══════════════════════════════════════════════════════════
#  订阅作者卡片
# ═══════════════════════════════════════════════════════════
class SubscriptionCard(CardWidget):
    def __init__(self, record: dict, page, parent=None):
        super().__init__(parent=parent)
        self.record = record
        self.page = page
        self.sec_uid = record.get('sec_uid', '')
        self._avatar_thread = None

        self.setFixedHeight(120)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        # 头像
        self.avatar_label = QLabel(self)
        self.avatar_label.setFixedSize(56, 56)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        avatar_url = record.get('avatar_url') or ''
        if not avatar_url:
            self.avatar_label.setText("👤")
        self.avatar_label.setStyleSheet(
            "background-color: rgba(255,255,255,0.08); border-radius: 28px;"
            " color: " + theme_color('#999999', '#888888') + "; font-size: 26px;")
        layout.addWidget(self.avatar_label, 0, Qt.AlignTop)

        # 中间信息
        mid = QVBoxLayout()
        mid.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        nickname = record.get('nickname') or '未知作者'
        if len(nickname) > 18:
            nickname = nickname[:18] + '...'
        name_label = SubtitleLabel(nickname, self)
        name_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        top_row.addWidget(name_label)

        has_update = bool(record.get('has_update'))
        if has_update:
            update_tag = CaptionLabel("● 有更新", self)
            update_tag.setStyleSheet(
                "color: #F56C6C; font-size: 11px; font-weight: bold;")
        else:
            update_tag = CaptionLabel("无更新", self)
            update_tag.setStyleSheet(
                "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 11px;")
        top_row.addWidget(update_tag)
        top_row.addStretch()
        mid.addLayout(top_row)

        signature = record.get('signature') or ''
        if signature:
            if len(signature) > 40:
                signature = signature[:40] + '...'
            sig_label = CaptionLabel(signature, self)
            sig_label.setStyleSheet(
                "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
            sig_label.setWordWrap(True)
            mid.addWidget(sig_label)

        info_label = CaptionLabel(
            f"作品 {record.get('aweme_count') or 0}  ·  粉丝 {record.get('follower_count') or 0}",
            self)
        info_label.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        mid.addWidget(info_label)

        last_checked = record.get('last_checked_at') or ''
        if last_checked:
            checked_label = CaptionLabel(f"上次检查：{last_checked}", self)
            checked_label.setStyleSheet(
                "color: " + theme_color('#C0C0C0', '#666666') + "; font-size: 11px;")
            mid.addWidget(checked_label)

        layout.addLayout(mid, 1)

        # 右侧按钮
        right = QVBoxLayout()
        right.setSpacing(6)

        self.parse_btn = PrimaryPushButton(FIF.SYNC, " 解析主页", self)
        self.parse_btn.setFixedHeight(28)
        self.parse_btn.clicked.connect(self._parse_home)
        right.addWidget(self.parse_btn)

        self.open_btn = PushButton(FIF.LINK, " 主页", self)
        self.open_btn.setFixedHeight(28)
        self.open_btn.clicked.connect(self._open_home)
        right.addWidget(self.open_btn)

        self.unsub_btn = PushButton(FIF.DELETE, " 取消订阅", self)
        self.unsub_btn.setFixedHeight(28)
        self.unsub_btn.clicked.connect(self._unsubscribe)
        right.addWidget(self.unsub_btn)

        right.addStretch()
        layout.addLayout(right)

        # 异步加载头像
        if avatar_url:
            self._avatar_thread = AvatarLoadThread(avatar_url, self.sec_uid, self)
            self._avatar_thread.loaded.connect(self._on_avatar_loaded)
            self._avatar_thread.start()

        install_hover_tip(self.parse_btn, "解析主页", "跳转到抖音页并解析该作者主页全部作品")
        install_hover_tip(self.open_btn, "打开主页", "在浏览器中打开该作者抖音主页")
        install_hover_tip(self.unsub_btn, "取消订阅", "从订阅列表中移除该作者")

    def _on_avatar_loaded(self, pix, sec_uid):
        if sec_uid == self.sec_uid:
            self.avatar_label.setPixmap(pix)

    def _open_home(self):
        url = self.record.get('user_home') or f"https://www.douyin.com/user/{self.sec_uid}"
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _parse_home(self):
        """跳转到抖音解析页并解析该作者主页全部作品"""
        url = self.record.get('user_home') or f"https://www.douyin.com/user/{self.sec_uid}"
        if not url:
            InfoBar.warning("提示", "该作者缺少主页链接", orient=Qt.Horizontal,
                            isClosable=True, position=InfoBarPosition.TOP,
                            duration=3000, parent=self.page.window())
            return

        win = self.page.window()
        douyin_page = getattr(win, 'videoPage_douyin', None) if win is not None else None
        if douyin_page is None:
            InfoBar.error("操作失败", "抖音解析页未就绪", parent=self.page.window())
            return

        # 先切换到抖音页，再触发主页解析
        win.switchTo(douyin_page)
        douyin_page.open_user_home_and_parse(url)

    def _unsubscribe(self):
        if unsubscribe(self.sec_uid):
            InfoBar.success(
                "已取消订阅",
                f"作者「{self.record.get('nickname') or self.sec_uid}」已移除",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self.page.window())
            self.page.reload()
        else:
            InfoBar.error("操作失败", "取消订阅失败", parent=self.page.window())


# ═══════════════════════════════════════════════════════════
#  订阅页面主体
# ═══════════════════════════════════════════════════════════
class DouyinSubscriptionPage(QScrollArea):
    """抖音作者订阅管理页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DouyinSubscriptionPage")
        self._cards = []
        self._refresh_worker = None

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.viewport().setAutoFillBackground(False)

        self.view = QWidget(self)
        self.view.setAutoFillBackground(False)
        self.view.setStyleSheet("background: transparent;")
        self.layout = QVBoxLayout(self.view)
        self.layout.setSpacing(12)
        self.layout.setContentsMargins(24, 24, 24, 24)
        self.setWidget(self.view)

        self._build_header()
        self._build_results_area()

        self.reload()

    def _build_header(self):
        header_card = CardWidget(self.view)
        header_layout = QVBoxLayout(header_card)
        header_layout.setSpacing(10)
        header_layout.setContentsMargins(20, 18, 20, 18)

        top = QHBoxLayout()
        top.setSpacing(12)
        title = SubtitleLabel("⭐ 抖音作者订阅", header_card)
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        top.addWidget(title)

        desc = CaptionLabel("查看已订阅作者的资料、作品数量与更新状态", header_card)
        desc.setStyleSheet(
            "color: " + theme_color('#B0B0B0', '#5A5F6A') + "; font-size: 11px;")
        top.addWidget(desc)
        top.addStretch()

        self.refresh_btn = PrimaryPushButton(FIF.SYNC, " 检查更新", header_card)
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.clicked.connect(self.refresh_all)
        top.addWidget(self.refresh_btn)

        header_layout.addLayout(top)

        self.status_label = CaptionLabel("", header_card)
        self.status_label.setStyleSheet(
            "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 12px;")
        self.status_label.setVisible(False)
        header_layout.addWidget(self.status_label)

        self.loading_bar = IndeterminateProgressBar(header_card)
        self.loading_bar.setFixedHeight(4)
        self.loading_bar.setVisible(False)
        header_layout.addWidget(self.loading_bar)

        self.layout.addWidget(header_card)

    def _build_results_area(self):
        self.empty_label = QLabel("暂无订阅作者\n在抖音解析用户主页后可订阅作者", self.view)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            "color: " + theme_color('#AAAAAA', '#666666') + "; font-size: 14px; padding: 60px 0;")
        self.layout.addWidget(self.empty_label)

        self.cards_widget = QWidget(self.view)
        self.cards_widget.setAutoFillBackground(False)
        self.cards_widget.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setSpacing(10)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setAlignment(Qt.AlignTop)
        self.layout.addWidget(self.cards_widget, 1)

    # ── 加载 / 刷新 ──
    def reload(self):
        """重新加载订阅列表"""
        self._clear_cards()
        records = list_subscriptions()
        if not records:
            self.empty_label.setVisible(True)
            self.cards_widget.setVisible(False)
            return

        self.empty_label.setVisible(False)
        self.cards_widget.setVisible(True)
        for record in records:
            card = SubscriptionCard(record, self, self.cards_widget)
            self.cards_layout.addWidget(card)
            self._cards.append(card)

    def _clear_cards(self):
        for card in list(self._cards):
            try:
                card.deleteLater()
            except Exception:
                pass
        self._cards = []
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh_all(self):
        """批量检查所有订阅作者的更新状态"""
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            InfoBar.info("正在检查", "已有检查任务进行中", parent=self.window())
            return

        records = list_subscriptions()
        if not records:
            InfoBar.info("暂无订阅", "没有需要检查的订阅作者", parent=self.window())
            return

        self.refresh_btn.setEnabled(False)
        self.loading_bar.setVisible(True)
        self.loading_bar.start()
        self.status_label.setVisible(True)
        self.status_label.setText("准备检查更新...")

        self._refresh_worker = RefreshWorker(records, self)
        self._refresh_worker.progress.connect(self._on_refresh_progress)
        self._refresh_worker.done.connect(self._on_refresh_done)
        self._refresh_worker.start()

    def _on_refresh_progress(self, done, total, message):
        self.status_label.setText(f"检查进度 {done}/{total}：{message}")

    def _on_refresh_done(self, success, total):
        self.refresh_btn.setEnabled(True)
        self.loading_bar.setVisible(False)
        self.loading_bar.stop()
        self.status_label.setText(f"检查完成：成功 {success}/{total}")
        self.reload()
        # 汇总查看有更新的作者数量
        updated = sum(1 for r in list_subscriptions() if r.get('has_update'))
        if updated > 0:
            InfoBar.warning(
                "发现更新",
                f"共 {updated} 位作者有新作品",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=5000, parent=self.window())
        else:
            InfoBar.success("检查完成", "所有作者均无更新", parent=self.window())
        self._refresh_worker = None