# -*- coding: utf-8 -*-
"""
抖音配置弹窗（完整移植自 douyin_parse-master/qt_app.py 排版样式）
==============================================================
包含:
- QualitySelectionDialog：视频清晰度选择（目标项目 qt_app.py 样式）
- VideoConfigDialog：视频配置弹窗（Cookie 管理 + 最大页数）
- CookieWorker：Playwright 扫码登录获取 Cookie（完整版）
- DouyinLogDialog：下载日志弹窗
- DouyinFeatureDialog：功能清单
"""
import os
import time

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QWidget, QGroupBox, QFrame, QRadioButton,
    QButtonGroup, QDialogButtonBox, QTextEdit, QApplication,
)
from qfluentwidgets import (
    FluentIcon as FIF, PrimaryPushButton, PushButton,
    InfoBar, InfoBarPosition, CaptionLabel, SubtitleLabel,
    TextEdit as FluentTextEdit, SpinBox,
)

from core.config import config as CFG
from ui.widgets.theme import theme_color
from pages.video.douyin_service_helper import save_cookie_file, load_cookie_file


# ═══════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════
DOUYIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

QR_SELECTORS = [
    ".qrcode-img img",
    "img[aria-label*='二维码']",
    "img.RhjdbXj8",
    "img[src^='data:image/png;base64']",
    "img[src*='qrcode']",
    "img[src*='qr']",
    "img[alt*='二维码']",
    "[class*=qrcode] img",
]

CONTROL_HEIGHT = 32           # 统一控件高度
CONTROL_RADIUS = 6            # 统一圆角


# ═══════════════════════════════════════════════════════════
#  InfoBar 快捷
# ═══════════════════════════════════════════════════════════
def show_info(parent, title, content, duration=3000):
    InfoBar.info(title=title, content=content, orient=Qt.Horizontal,
                 isClosable=True, position=InfoBarPosition.TOP,
                 duration=duration, parent=parent)


def show_success(parent, title, content, duration=3000):
    InfoBar.success(title=title, content=content, orient=Qt.Horizontal,
                    isClosable=True, position=InfoBarPosition.TOP,
                    duration=duration, parent=parent)


def show_error(parent, title, content, duration=5000):
    InfoBar.error(title=title, content=content, orient=Qt.Horizontal,
                  isClosable=True, position=InfoBarPosition.BOTTOM_RIGHT,
                  duration=duration, parent=parent)


# ═══════════════════════════════════════════════════════════
#  Cookie 工具（移植自 qt_app.py / qt_app_fluent.py）
# ═══════════════════════════════════════════════════════════
def _cookies_to_header(cookies: list) -> str:
    parts = []
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _has_sessionid(cookies: list) -> bool:
    for c in cookies:
        if c.get("name") == "sessionid" and c.get("value"):
            return True
    return False


def _is_logged_in(url: str) -> bool:
    lower = (url or "").lower()
    if "douyin.com" not in lower:
        return False
    return not any(x in lower for x in ("passport", "/login", "/auth"))


def _clear_proxy_env():
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "socks_proxy"):
        os.environ.pop(key, None)


def _find_qr(page):
    scopes = [page]
    try:
        scopes.extend(page.frames)
    except Exception:
        pass
    for scope in scopes:
        for sel in QR_SELECTORS:
            try:
                el = scope.query_selector(sel)
                if not el:
                    continue
                box = el.bounding_box()
                if box and box.get("width", 0) >= 100 and box.get("height", 0) >= 100:
                    return el
            except Exception:
                continue
    return None


def _open_login_panel(page):
    clicked = False
    for fn in (
        lambda: page.click("#login-panel-new", timeout=3000),
        lambda: page.locator("[id*='login-panel'], [id*='login-pannel']").first.click(timeout=2000),
        lambda: page.get_by_role("button", name="登录").first.click(timeout=2000),
    ):
        try:
            fn()
            clicked = True
            break
        except Exception:
            continue
    if clicked:
        page.wait_for_timeout(1500)

    for text in ("扫码登录", "二维码登录", "二维码"):
        try:
            page.get_by_text(text, exact=False).first.click(timeout=1500)
            page.wait_for_timeout(800)
            return
        except Exception:
            continue


def _wait_qr(page, status_cb=None, timeout_sec=35):
    deadline = time.time() + timeout_sec
    opened = False
    last_retry = 0.0
    last_emit = 0.0
    while time.time() < deadline:
        el = _find_qr(page)
        if el:
            return el
        now = time.time()
        if not opened:
            _open_login_panel(page)
            opened = True
            last_retry = now
        elif now - last_retry >= 8:
            _open_login_panel(page)
            last_retry = now
        if status_cb and now - last_emit >= 2:
            remain = max(0, int(deadline - now))
            status_cb(f"等待二维码出现...（剩余约 {remain}s）")
            last_emit = now
        page.wait_for_timeout(500)
    return None


def _extract_cookies(context, page, status_cb=None):
    cookies = context.cookies()
    if _has_sessionid(cookies):
        return _cookies_to_header(cookies)
    if status_cb:
        status_cb("登录成功，正在提取 Cookie...")
    try:
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)
    except Exception:
        pass
    cookies = context.cookies()
    if _has_sessionid(cookies):
        return _cookies_to_header(cookies)
    return None


# ═══════════════════════════════════════════════════════════
#  CookieWorker（Playwright 自动获取，移植自 qt_app.py）
# ═══════════════════════════════════════════════════════════
class CookieWorker(QThread):
    """扫码登录获取 Cookie（完整版，支持自动打开登录面板/轮询检测）"""
    qr = pyqtSignal(bytes)
    status = pyqtSignal(str)
    done = pyqtSignal(str)
    error = pyqtSignal(str)

    def run(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            self.error.emit("缺少 playwright，请安装: pip install playwright && playwright install chromium")
            return

        _clear_proxy_env()
        browser = None
        try:
            self.status.emit("启动浏览器...")
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=DOUYIN_UA, locale="zh-CN", timezone_id="Asia/Shanghai")
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: ()=>undefined});")
                page = context.new_page()

                self.status.emit("打开抖音...")
                page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)

                cookies = context.cookies()
                if _has_sessionid(cookies):
                    ck = _extract_cookies(context, page, self.status.emit)
                    if ck:
                        self.done.emit(ck)
                        browser.close()
                        return

                self.status.emit("获取二维码...")
                el = _wait_qr(page, self.status.emit, timeout_sec=35)
                if not el:
                    self.error.emit("未找到二维码，请确认网络正常且页面未被拦截")
                    browser.close()
                    return

                try:
                    self.qr.emit(el.screenshot())
                except Exception:
                    self.error.emit("二维码截图失败")
                    browser.close()
                    return

                self.status.emit("等待扫码，请在手机上确认登录...")
                start_url = page.url

                for i in range(120):
                    cookies = context.cookies()
                    cur = page.url

                    if _has_sessionid(cookies):
                        ck = _extract_cookies(context, page, self.status.emit)
                        if ck:
                            self.done.emit(ck)
                            browser.close()
                            return

                    if _is_logged_in(cur) and cur != start_url:
                        ck = _extract_cookies(context, page, self.status.emit)
                        if ck:
                            self.done.emit(ck)
                            browser.close()
                            return

                    try:
                        text = page.inner_text("body")
                        if "扫码成功" in text:
                            self.status.emit("扫码成功，请在手机上点击确认...")
                        elif any(k in text for k in ("登录成功", "已登录", "登录完成")):
                            ck = _extract_cookies(context, page, self.status.emit)
                            if ck:
                                self.done.emit(ck)
                                browser.close()
                                return
                    except Exception:
                        pass

                    if i % 5 == 0:
                        self.status.emit(f"等待扫码登录... ({i // 5 + 1}/24)")
                    page.wait_for_timeout(1000)

                self.error.emit("登录超时，请重试（扫码后需在手机上确认）")
                browser.close()
        except Exception as e:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            self.error.emit(f"获取失败: {e}")


# ═══════════════════════════════════════════════════════════
#  QualitySelectionDialog（移植自 qt_app.py 质量选择对话框）
# ═══════════════════════════════════════════════════════════
class QualitySelectionDialog(QDialog):
    """视频清晰度选择弹窗（目标项目 qt_app.py 排版样式，主题适配）"""

    def __init__(self, qualities: list, parent=None):
        super().__init__(parent)
        self.qualities = self._dedup(qualities)
        self.selected_quality = None
        self.setWindowTitle("选择视频质量")
        self.setMinimumWidth(500)
        self.setMaximumHeight(600)
        self._build()
        self._style()

    def _dedup(self, qualities):
        seen = set()
        unique = []
        for q in qualities:
            key = (q.get("ratio", ""), q.get("bit_rate", 0))
            if key not in seen:
                seen.add(key)
                unique.append(q)
        return unique

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        title = SubtitleLabel("请选择要下载的视频质量：", self)
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        scroll.setMaximumHeight(400)
        scroll.setStyleSheet("""
            QScrollArea { border: 1px solid #2b3142; border-radius: 8px; }
        """)

        group = QGroupBox()
        g_layout = QVBoxLayout(group)
        g_layout.setSpacing(8)
        self._bg = QButtonGroup(self)

        if not self.qualities:
            no = QLabel("未找到可用的视频质量选项", group)
            no.setStyleSheet(
                "color:" + theme_color("#999", "#666") + ";padding:20px;")
            g_layout.addWidget(no)
        else:
            for idx, q in enumerate(self.qualities):
                ratio = q.get("ratio", "未知")
                bit = q.get("bit_rate", 0)
                label = q.get("quality_label", ratio)
                desc = f"{label}"
                if bit > 0 and f"{bit // 1000}Kbps" not in label:
                    desc += f" - {bit // 1000}Kbps"
                r = QRadioButton(desc, group)
                r.setProperty("quality", q)
                if idx == 0:
                    r.setChecked(True)
                    self.selected_quality = q
                self._bg.addButton(r, idx)
                g_layout.addWidget(r)
                r.toggled.connect(lambda checked, qq=q: self._select(checked, qq))
        g_layout.addStretch()
        scroll.setWidget(group)
        layout.addWidget(scroll)

        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _select(self, checked, q):
        if checked:
            self.selected_quality = q

    def _style(self):
        self.setStyleSheet("""
            QDialog{background:%s;color:%s}
            QGroupBox{border:2px solid %s;border-radius:8px;margin-top:10px;padding-top:15px;background:%s}
            QRadioButton{padding:12px;font-size:14px;border-radius:6px;margin:4px;background:transparent;color:%s}
            QRadioButton:hover{background:%s}
            QScrollArea{border:1px solid %s;border-radius:8px;background:%s}
        """ % (
            theme_color('#fff', '#0f1115'),
            theme_color('#303133', '#e6e6e6'),
            theme_color('#dcdfe6', '#2b3142'),
            theme_color('#fff', '#1b1f2a'),
            theme_color('#303133', '#e6e6e6'),
            theme_color('#f0f2f5', '#2b3142'),
            theme_color('#dcdfe6', '#2b3142'),
            theme_color('#fff', '#1b1f2a'),
        ))

    def get_selected_quality(self):
        return self.selected_quality


# ═══════════════════════════════════════════════════════════
#  VideoConfigDialog（移植自 qt_app.py / qt_app_fluent.py 配置弹窗）
# ═══════════════════════════════════════════════════════════
def _validate_cookie_format(cookie: str) -> bool:
    """检测 Cookie 格式：应包含 key=value 对"""
    if not cookie or not cookie.strip():
        return False
    parts = [p for p in cookie.split(";") if "=" in p]
    return len(parts) >= 1


class VideoConfigDialog(QDialog):
    """视频配置弹窗（Cookie 管理 + 最大页数）

    移植自 douyin_parse-master/qt_app.py / qt_app_fluent.py
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("视频配置")
        self.setModal(True)
        self.resize(600, 620)
        self.setMinimumSize(560, 560)
        self._cookie_worker = None

        self._setup_font()
        self._build_ui()
        self._apply_styles()

    def _setup_font(self):
        """统一中文字体，修复乱码"""
        family = "Microsoft YaHei UI"
        self.setFont(QFont(family, 10))
        if self.parent():
            self.parent().setFont(QFont(family, 10))

    # ── UI 构建 ──
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 18, 20, 18)

        title_label = SubtitleLabel("⚙️ 视频解析配置", self)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(title_label)

        desc_label = CaptionLabel("配置解析参数，保存后自动生效", self)
        desc_label.setStyleSheet(
            "color: " + theme_color('#C0C0C0', '#909399') + "; font-size: 12px;")
        layout.addWidget(desc_label)

        layout.addSpacing(4)

        # ── 滚动区 ──
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        form_layout = QVBoxLayout(scroll_widget)
        form_layout.setSpacing(14)
        form_layout.setContentsMargins(0, 0, 6, 0)

        # ═══ 下载行为配置 ═══
        behavior_group = self._make_group("║ 下载行为", "配置主页批量解析的翻页数量")
        behavior_layout = behavior_group._inner_layout
        behavior_layout.setContentsMargins(14, 4, 14, 14)

        pages_label = QLabel("最大页数")
        pages_label.setStyleSheet(self._label_style())
        behavior_layout.addWidget(pages_label)

        pages_row = QHBoxLayout()
        pages_row.setSpacing(8)
        self.max_pages_spin = SpinBox(behavior_group)
        self.max_pages_spin.setRange(1, 50)
        self.max_pages_spin.setValue(int(CFG.get('douyin_max_pages', 10) or 10))
        self.max_pages_spin.setSuffix(" 页")
        self.max_pages_spin.setFixedHeight(CONTROL_HEIGHT)
        self.max_pages_spin.setFixedWidth(120)
        pages_row.addWidget(self.max_pages_spin)
        pages_row.addStretch(1)
        behavior_layout.addLayout(pages_row)

        pages_tip = CaptionLabel("💡 用户主页批量解析时，最多翻多少页（1-50）", behavior_group)
        pages_tip.setStyleSheet(self._tip_style())
        behavior_layout.addWidget(pages_tip)

        form_layout.addWidget(behavior_group)

        # ═══ Cookie 管理 ═══
        cookie_group = self._make_group("║ Cookie 管理", "粘贴抖音 Cookie 后，可解析高权限内容")
        cookie_layout = cookie_group._inner_layout
        cookie_layout.setContentsMargins(14, 4, 14, 14)

        cookie_header = QHBoxLayout()
        cookie_header.setSpacing(8)

        status_text = "已加载"
        if not (CFG.get('douyin_cookie', '') or load_cookie_file()):
            status_text = "未设置"
        self.cookie_status = CaptionLabel(f"状态：{status_text}", cookie_group)
        self.cookie_status.setStyleSheet(self._status_style(status_text))
        cookie_header.addWidget(self.cookie_status)

        cookie_header.addSpacing(6)

        help_btn = PushButton("?", cookie_group)
        help_btn.setFixedSize(22, 22)
        help_btn.setToolTip("如何获取抖音 Cookie")
        help_btn.setStyleSheet(self._help_btn_style())
        help_btn.clicked.connect(self._show_cookie_help)
        cookie_header.addWidget(help_btn)

        self.get_cookie_btn = PushButton(FIF.LINK, " 扫码获取", cookie_group)
        self.get_cookie_btn.setFixedHeight(CONTROL_HEIGHT)
        self.get_cookie_btn.clicked.connect(self._on_get_cookie)
        cookie_header.addWidget(self.get_cookie_btn)

        cookie_header.addStretch(1)
        cookie_layout.addLayout(cookie_header)

        # 二维码预览
        self.cookie_qr = QLabel("二维码预览", cookie_group)
        self.cookie_qr.setFixedSize(120, 120)
        self.cookie_qr.setAlignment(Qt.AlignCenter)
        self.cookie_qr.setStyleSheet(
            f"QLabel{{background:{theme_color('#F5F5F5','#1b1f2a')};"
            f"border-radius:8px;border:1px solid {theme_color('#DCDFE6','#2b3142')};"
            f"color:{theme_color('#909399','#8A8A8A')};font-size:12px}}")
        qr_row = QHBoxLayout()
        qr_row.addWidget(self.cookie_qr)
        qr_row.addStretch(1)
        cookie_layout.addLayout(qr_row)

        # Cookie 编辑框
        self.cookie_edit = FluentTextEdit(cookie_group)
        self.cookie_edit.setPlaceholderText("粘贴抖音 Cookie（例如：sessionid=...; ttwid=...）")
        saved = str(CFG.get('douyin_cookie', '') or '')
        if not saved:
            saved = load_cookie_file()
        self.cookie_edit.setPlainText(saved)
        self.cookie_edit.setFixedHeight(80)
        self.cookie_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.cookie_edit.textChanged.connect(self._on_cookie_text_changed)
        cookie_layout.addWidget(self.cookie_edit)

        # Cookie 格式校验提示
        self.cookie_validate_label = CaptionLabel("", cookie_group)
        self.cookie_validate_label.setStyleSheet(self._tip_style())
        self.cookie_validate_label.setWordWrap(True)
        cookie_layout.addWidget(self.cookie_validate_label)
        self._update_cookie_validate()

        # Cookie 操作按钮行：保存 / 复制 / 清空
        cookie_ops = QHBoxLayout()
        cookie_ops.setSpacing(8)

        save_cookie_btn = PushButton(FIF.SAVE, " 保存 Cookie", cookie_group)
        save_cookie_btn.setFixedHeight(CONTROL_HEIGHT)
        save_cookie_btn.clicked.connect(self._on_save_cookie)
        cookie_ops.addWidget(save_cookie_btn)

        copy_btn = PushButton(FIF.COPY, " 复制", cookie_group)
        copy_btn.setFixedHeight(CONTROL_HEIGHT)
        copy_btn.clicked.connect(self._on_copy_cookie)
        cookie_ops.addWidget(copy_btn)

        clear_cookie_btn = PushButton(FIF.DELETE, " 清空", cookie_group)
        clear_cookie_btn.setFixedHeight(CONTROL_HEIGHT)
        clear_cookie_btn.clicked.connect(self._on_clear_cookie)
        cookie_ops.addWidget(clear_cookie_btn)

        cookie_ops.addStretch(1)
        cookie_layout.addLayout(cookie_ops)

        cookie_tip = CaptionLabel("💡 获取方法：浏览器登录抖音 → F12 → Network → 复制请求头 Cookie", cookie_group)
        cookie_tip.setStyleSheet(self._tip_style())
        cookie_tip.setWordWrap(True)
        cookie_layout.addWidget(cookie_tip)

        form_layout.addWidget(cookie_group)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)

        # ═══ 底部按钮 ═══
        layout.addSpacing(6)
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        close_btn = PushButton(FIF.CLOSE, " 关闭", self)
        close_btn.setFixedHeight(CONTROL_HEIGHT + 4)
        close_btn.clicked.connect(self.reject)
        bottom_row.addWidget(close_btn)

        bottom_row.addStretch(1)

        save_btn = PrimaryPushButton(FIF.ACCEPT, " 保存配置", self)
        save_btn.setFixedHeight(CONTROL_HEIGHT + 4)
        save_btn.setMinimumWidth(120)
        save_btn.clicked.connect(self._on_save)
        bottom_row.addWidget(save_btn)

        layout.addLayout(bottom_row)

    def _make_group(self, title: str, desc: str) -> QGroupBox:
        """创建带标题+说明的分组框（浅底色 + 细分割线）"""
        group = QGroupBox(self)
        group.setStyleSheet(
            "QGroupBox { background: rgba(255,255,255,0.04);"
            " border: 1px solid rgba(255,255,255,0.10); border-radius: 8px;"
            " margin-top: 26px; padding-top: 14px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 14px;"
            " padding: 0 6px; font-weight: bold; font-size: 14px; color: "
            + theme_color('#303133', '#E6E6E6') + "; }"
        )
        group.setTitle(f"   {title}")

        g_layout = QVBoxLayout(group)
        g_layout.setSpacing(4)
        g_layout.setContentsMargins(14, 4, 14, 14)
        if desc:
            desc_lbl = CaptionLabel(desc, group)
            desc_lbl.setStyleSheet(self._desc_style())
            g_layout.addWidget(desc_lbl)
            g_layout.addSpacing(4)
        group._inner_layout = g_layout
        return group

    # ── 样式 ──
    def _label_style(self) -> str:
        return (
            "font-size: 13px; font-weight: bold; color: "
            + theme_color('#303133', '#E6E6E6') + ";"
        )

    def _desc_style(self) -> str:
        return "color: " + theme_color('#A0A0A0', '#909399') + "; font-size: 12px;"

    def _tip_style(self) -> str:
        return "color: " + theme_color('#909399', '#8A8A8A') + "; font-size: 11px;"

    def _status_style(self, status: str) -> str:
        color = "#909399"
        if status == "已加载" and _validate_cookie_format(
                str(CFG.get('douyin_cookie', '') or '') or load_cookie_file()):
            color = "#67C23A"
        elif status == "未设置":
            color = "#909399"
        return f"color: {color}; font-size: 12px; font-weight: bold;"

    def _help_btn_style(self) -> str:
        return (
            "QPushButton { background: rgba(255,255,255,0.08); color: "
            + theme_color('#303133', '#E6E6E6') + ";"
            " border: 1px solid rgba(255,255,255,0.15); border-radius: 11px;"
            " font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background: rgba(59,130,246,0.3); }"
        )

    def _apply_styles(self):
        """统一弹窗全局样式"""
        self.setStyleSheet(
            "QDialog { background: " + theme_color('#fff', '#1b1f2a') + "; }"
            "QGroupBox { background: " + theme_color('#fafafa', 'rgba(255,255,255,0.04)') + ";"
            " border: 1px solid " + theme_color('#e4e7ed', 'rgba(255,255,255,0.10)') + ";"
            f" border-radius: {CONTROL_RADIUS}px; }}"
            "QTextEdit { background: " + theme_color('#fff', '#202530') + ";"
            " color: " + theme_color('#303133', '#E6E6E6') + ";"
            " border: 1px solid " + theme_color('#dcdfe6', '#2b3142') + ";"
            f" border-radius: {CONTROL_RADIUS}px; padding: 8px; }}"
        )

    # ── Cookie 格式校验 ──
    def _on_cookie_text_changed(self):
        """Cookie 内容变化时实时校验格式"""
        self._update_cookie_validate()

    def _update_cookie_validate(self):
        """更新 Cookie 格式校验提示"""
        cookie = self.cookie_edit.toPlainText().strip()
        if not cookie:
            self.cookie_validate_label.setText("")
            return
        if _validate_cookie_format(cookie):
            self.cookie_validate_label.setText("✅ Cookie 格式正确")
            self.cookie_validate_label.setStyleSheet(
                "color: #67C23A; font-size: 11px;")
        else:
            self.cookie_validate_label.setText("⚠️ Cookie 格式错误：应包含 name=value 格式的参数对（分号分隔）")
            self.cookie_validate_label.setStyleSheet(
                "color: #F56C6C; font-size: 11px;")

    # ── 交互 ──
    def _show_cookie_help(self):
        from qfluentwidgets import MessageBox
        box = MessageBox(
            "如何获取抖音 Cookie",
            "1. 使用浏览器打开 https://www.douyin.com 并登录账号\n"
            "2. 按 F12 打开开发者工具 → Network 标签\n"
            "3. 刷新页面，点击任意请求\n"
            "4. 复制请求头中的 Cookie 值粘贴到此处",
            self,
        )
        box.exec()

    # ── Cookie 扫码 ──
    def _on_get_cookie(self):
        self.get_cookie_btn.setEnabled(False)
        self.cookie_status.setText("状态：获取中...")
        self.cookie_status.setStyleSheet("color: #f57c00; font-size: 12px; font-weight: bold;")
        self.cookie_qr.clear()
        self.cookie_qr.setText("启动浏览器...")

        self._cookie_worker = CookieWorker()
        self._cookie_worker.qr.connect(self._on_qr)
        self._cookie_worker.status.connect(self._on_status)
        self._cookie_worker.done.connect(self._on_cookie_ok)
        self._cookie_worker.error.connect(self._on_cookie_err)
        self._cookie_worker.start()

    def _on_qr(self, img):
        pix = QPixmap()
        if pix.loadFromData(img):
            self.cookie_qr.setPixmap(
                pix.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.cookie_qr.setStyleSheet("QLabel{border-radius:8px}")

    def _on_status(self, text):
        if len(text) > 30:
            text = text[:27] + "..."
        self.cookie_status.setText(f"状态：{text}")
        if not self.cookie_qr.pixmap():
            self.cookie_qr.setText(text)

    def _on_cookie_ok(self, cookie):
        self.get_cookie_btn.setEnabled(True)
        self.cookie_status.setText("状态：获取成功 ✓")
        self.cookie_status.setStyleSheet("color:#67C23A;font-size:12px;font-weight:bold")
        self.cookie_edit.setPlainText(cookie)
        save_cookie_file(cookie)
        try:
            CFG['douyin_cookie'] = cookie
        except Exception:
            pass
        self._update_cookie_validate()
        show_success(self, "Cookie 获取成功", "已保存到配置文件和 douyin_cookie.txt")

    def _on_cookie_err(self, msg):
        self.get_cookie_btn.setEnabled(True)
        self.cookie_status.setText("状态：获取失败")
        self.cookie_status.setStyleSheet("color:#F56C6C;font-size:12px;font-weight:bold")
        self.cookie_qr.setText("获取失败")
        show_error(self, "Cookie 获取失败", msg[:300])

    # ── Cookie 一键操作 ──
    def _on_copy_cookie(self):
        """一键复制 Cookie"""
        cookie = self.cookie_edit.toPlainText().strip()
        if not cookie:
            show_info(self, "提示", "没有可复制的 Cookie")
            return
        QApplication.clipboard().setText(cookie)
        show_success(self, "已复制", "Cookie 已复制到剪贴板")

    def _on_clear_cookie(self):
        """清空 Cookie 编辑框"""
        self.cookie_edit.clear()
        show_info(self, "已清空", "Cookie 编辑框已清空")

    def _on_save_cookie(self):
        """校验并保存 Cookie（带成功/失败反馈）"""
        cookie = self.cookie_edit.toPlainText().strip()

        if not cookie:
            try:
                CFG['douyin_cookie'] = ""
                save_cookie_file("")
                self.cookie_status.setText("状态：未设置")
                self.cookie_status.setStyleSheet(self._status_style("未设置"))
                self._update_cookie_validate()
                show_success(self, "已清空", "Cookie 已清除并保存")
            except Exception as e:
                show_error(self, "保存失败", f"清除 Cookie 时出错: {str(e)}")
            return

        if not _validate_cookie_format(cookie):
            show_error(self, "Cookie 格式错误", "Cookie 应包含 name=value 格式的参数对（分号分隔）")
            return

        try:
            CFG['douyin_cookie'] = cookie
            save_cookie_file(cookie)
            self.cookie_status.setText("状态：已加载")
            self.cookie_status.setStyleSheet(self._status_style("已加载"))
            self._update_cookie_validate()
            show_success(self, "保存成功", "Cookie 已保存到配置文件和 douyin_cookie.txt")
        except Exception as e:
            show_error(self, "保存失败", f"保存 Cookie 时出错: {str(e)}")

    # ── 保存 ──
    def _on_save(self):
        """校验全部配置并保存"""
        cookie = self.cookie_edit.toPlainText().strip()

        if cookie and not _validate_cookie_format(cookie):
            show_error(self, "Cookie 格式错误", "Cookie 应包含 name=value 格式的参数对")
            return

        max_pages = self.max_pages_spin.value()
        try:
            CFG['douyin_max_pages'] = max_pages
            CFG['douyin_cookie'] = cookie
            save_cookie_file(cookie)
        except Exception:
            pass

        show_success(self, "配置已保存", "所有配置已保存并生效")
        self.accept()

    def get_max_pages(self) -> int:
        return self.max_pages_spin.value()

    def set_max_pages(self, value: int):
        value = max(1, min(50, int(value)))
        self.max_pages_spin.setValue(value)


# ═══════════════════════════════════════════════════════════
#  下载日志弹窗
# ═══════════════════════════════════════════════════════════
class DouyinLogDialog(QDialog):
    """抖音下载日志弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("抖音下载日志")
        self.setModal(False)
        self.resize(640, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(SubtitleLabel("📋 下载日志", self))

        self.logEdit = QTextEdit(self)
        self.logEdit.setReadOnly(True)
        self.logEdit.setPlaceholderText("下载日志将显示在这里...")
        self.logEdit.setStyleSheet(
            "QTextEdit { background-color: " + theme_color('#F5F5F5', '#1E1E1E') +
            "; border: none; border-radius: 6px; font-family: Consolas, monospace; font-size: 12px; }")
        layout.addWidget(self.logEdit, 1)

        btnRow = QHBoxLayout()
        btnRow.addStretch()
        clearBtn = PushButton(FIF.DELETE, "清空日志", self)
        clearBtn.clicked.connect(lambda: self.logEdit.clear())
        btnRow.addWidget(clearBtn)
        closeBtn = PushButton(FIF.CLOSE, "关闭", self)
        closeBtn.clicked.connect(self.close)
        btnRow.addWidget(closeBtn)
        layout.addLayout(btnRow)

    def append_log(self, text):
        self.logEdit.append(text)
        sb = self.logEdit.verticalScrollBar()
        sb.setValue(sb.maximum())


# ═══════════════════════════════════════════════════════════
#  功能清单
# ═══════════════════════════════════════════════════════════
class DouyinFeatureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("抖音功能清单")
        self.setModal(True)
        self.resize(520, 400)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(SubtitleLabel("抖音功能清单", self))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setSpacing(8)

        g = QGroupBox("📋 功能说明", sw)
        gl = QVBoxLayout(g)

        items = [
            ("🔑 Cookie 扫码登录", "Playwright 自动打开浏览器 → 扫码 → 提取 Cookie"),
            ("🎬 单内容解析", "支持单视频 / 图集 / 短链接 / note 等格式，多链接自动并发"),
            ("🖼 图集解析（Live 图）", "自动识别图集，Live 图提取视频"),
            ("📊 多档清晰度", "A-Bogus/X-Bogus 提供 1080p~360p 多档选择"),
            ("👤 用户主页批量", "主页链接 / 视频反查主页，批量解析全部作品"),
            ("🗂 自动分类目录", "视频→videos/ 图片→images/ 音频→audios/ sourcefiles/"),
            ("🔄 断点续传", "已下载自动跳过（DouyinProgressDB 记录）"),
            ("📝 下载队列", "卡片逐个下载，实时进度条显示"),
        ]
        for name, desc in items:
            row = QWidget(g)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            nl = QLabel(name, row)
            nl.setStyleSheet("font-size:13px;font-weight:bold")
            rl.addWidget(nl, 0)
            rl.addSpacing(12)
            dl = QLabel(desc, row)
            dl.setStyleSheet(f"font-size:12px;color:{theme_color('#909399','#8A8A8A')}")
            dl.setWordWrap(True)
            rl.addWidget(dl, 1)
            gl.addWidget(row)
        sl.addWidget(g)
        sl.addWidget(CaptionLabel(
            "💡 使用 A-Bogus/X-Bogus 签名，支持无水印 + 多清晰度。配置 Cookie 可提高解析成功率。", sw))
        scroll.setWidget(sw)
        scroll.setMinimumHeight(280)
        layout.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        cb = PushButton(FIF.CLOSE, "关闭", self)
        cb.clicked.connect(self.close)
        bottom.addWidget(cb)
        layout.addLayout(bottom)