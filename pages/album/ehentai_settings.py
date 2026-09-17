# -*- coding: utf-8 -*-
"""
E-Hentai 设置模块（OGC 集成版）
==============================
包含两部分：
1. EhentaiConfig —— 配置桥接：所有 ehentai_* 配置统一保存在 OGC 的 data/config.json
   的 "ehentai" 节点下（避免与主程序 qconfig 冲突）。
2. SettingPage —— 设置标签页 UI：网络 / 下载 / 认证 / 数据库文件选择。

新增功能：可手动选择本地收藏数据库文件（*.db），应用后立即刷新「我的收藏」页面数据。
"""
import json
import os
from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TextEdit,
    TitleLabel,
    ToolButton,
)

from core.config import config as CFG


# ============================================================
# 配置桥接（data/config.json 的 "ehentai" 节点）
# ============================================================
class EhentaiConfig:
    """E-Hentai 配置桥接：读写 data/config.json 中的 "ehentai" 节点"""

    SECTION = 'ehentai'

    # 键名
    KEY_PROXY = 'proxy'
    KEY_IGNORE_ENV_PROXY = 'ignore_env_proxy'
    KEY_TIMEOUT = 'timeout'
    KEY_OUTPUT_DIR = 'output_dir'
    KEY_CONCURRENCY = 'concurrency'
    KEY_IMAGE_FORMAT = 'image_format'
    KEY_PER_FILE_RETRIES = 'per_file_retries'
    KEY_COOKIES = 'cookies'
    KEY_HEADERS = 'headers'
    KEY_LAST_URL = 'last_url'
    # ⚠️ 已废弃：数据库已统一为 data/ogc_users.db（见 core/database.py 的
    # EHENTAI_DDL 与 core/db_unify.py）。这个键只为兼容老配置文件而保留 ——
    # 读到它也不会切换数据库，只会在启动时把该文件的数据合并进统一库。
    KEY_DB_PATH = 'db_path'

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        # 默认值
        # 注意：这里**没有** db_path 的默认值 —— 数据库已统一，默认值再指向
        # data/ehentai/app_db.db 会让人以为还有第二个库。
        default_out = str(CFG.data / 'ehentai' / 'galleries')
        self._defaults = {
            self.KEY_PROXY: '',
            self.KEY_IGNORE_ENV_PROXY: True,
            self.KEY_TIMEOUT: 30,
            self.KEY_OUTPUT_DIR: default_out,
            self.KEY_CONCURRENCY: 4,
            self.KEY_IMAGE_FORMAT: '原始格式',
            self.KEY_PER_FILE_RETRIES: 3,
            self.KEY_COOKIES: '',
            self.KEY_HEADERS: '',
            self.KEY_LAST_URL: '',
        }
        self._section = {}
        self._load()

    # ---------------- 读写 ----------------
    def _load(self) -> None:
        try:
            cfg_file = Path(CFG.cfg_file)
            if cfg_file.exists():
                data = json.loads(cfg_file.read_text(encoding='utf-8'))
                sec = data.get(self.SECTION)
                if isinstance(sec, dict):
                    self._section = sec
        except Exception:
            self._section = {}

    def save(self) -> None:
        """将 ehentai 节点写回 data/config.json（不破坏其他配置）"""
        try:
            cfg_file = Path(CFG.cfg_file)
            data = {}
            if cfg_file.exists():
                try:
                    data = json.loads(cfg_file.read_text(encoding='utf-8'))
                except (json.JSONDecodeError, OSError):
                    data = {}
            data[self.SECTION] = self._section
            cfg_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
        except Exception:
            pass

    def get(self, key: str, default=None):
        """读取配置项（缺失时返回默认值）"""
        if key in self._section:
            return self._section[key]
        return self._defaults.get(key, default)

    def set(self, key: str, value) -> None:
        """写入配置项并保存"""
        self._section[key] = value
        self.save()


# 全局单例
ehentai_cfg = EhentaiConfig()


# 图片格式：GUI 显示名 -> downloader 格式值
IMAGE_FORMAT_MAP = {
    '原始格式': '',
    'JPG': 'jpg',
    'PNG': 'png',
    'WEBP': 'webp',
}


# ============================================================
# 设置页面（标签页）
# ============================================================
class SettingPage(QWidget):
    """E-Hentai 设置页：网络 / 下载 / 认证 / 数据库文件"""

    settings_saved = pyqtSignal()          # 保存设置后发出（用于刷新收藏等）
    db_file_changed = pyqtSignal(str)      # 应用了新的数据库文件后发出（携带路径）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        root.addWidget(TitleLabel('设置', self))

        # 滚动区域：窗口缩小时可滚动查看全部设置
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet('QScrollArea { background: transparent; }')
        container = QWidget()
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(16)

        # ===== 数据库卡片（与账号库统一：只读展示 + 导入旧库） =====
        # 以前这里是"选择另一个收藏数据库"：选个 .db 就整站换库，于是账号库与
        # 收藏库分家。现在全程序只有一个库，这张卡片只负责**告诉用户库在哪**、
        # 以及把外部旧库的数据**合并**进来。
        db_card = CardWidget(self)
        db_layout = QVBoxLayout(db_card)
        db_layout.setContentsMargins(20, 16, 20, 16)
        db_layout.setSpacing(12)

        db_layout.addWidget(SubtitleLabel('数据库', db_card))

        db_desc = CaptionLabel(
            '收藏、下载记录、浏览历史与账号信息现在都保存在**同一个**数据库里'
            '（不再有独立的 app_db.db）。这样「备份用户数据」一次就能带全，'
            '换机也不会只丢一半。\n'
            '手里如果有旧版 EhViewer / 早期版本的 .db 文件，可以点「导入外部数据库」'
            '把里面的记录合并进来 —— 外部文件本身不会被修改或删除。',
            db_card,
        )
        db_desc.setWordWrap(True)
        db_desc.setStyleSheet('color: #57606a;')
        db_layout.addWidget(db_desc)

        db_row = QHBoxLayout()
        db_row.setSpacing(10)
        self.db_path_edit = LineEdit(db_card)
        self.db_path_edit.setReadOnly(True)
        self.db_path_edit.setPlaceholderText('统一数据库路径')
        db_row.addWidget(self.db_path_edit, 1)
        locate_btn = ToolButton(FluentIcon.FOLDER, db_card)
        locate_btn.setToolTip('在资源管理器中定位数据库文件')
        locate_btn.clicked.connect(self._open_unified_db_folder)
        db_row.addWidget(locate_btn)
        db_layout.addLayout(db_row)

        apply_row = QHBoxLayout()
        apply_row.addStretch(1)
        self.import_db_btn = PrimaryPushButton(FluentIcon.SYNC, '导入外部数据库…', db_card)
        self.import_db_btn.setToolTip(
            '把另一个 .db 文件里的收藏/下载记录/历史合并进统一数据库（不修改该文件）')
        self.import_db_btn.clicked.connect(self._import_db_file)
        apply_row.addWidget(self.import_db_btn)
        db_layout.addLayout(apply_row)

        root_layout.addWidget(db_card)

        # ===== 浏览 / 阅读（EhViewer 显示/阅读设置，写入 ehviewer 子系统配置） =====
        self._build_browse_read_card(root_layout)

        # ===== 网络设置卡片 =====
        network_card = CardWidget(self)
        net_layout = QVBoxLayout(network_card)
        net_layout.setContentsMargins(20, 16, 20, 16)
        net_layout.setSpacing(12)

        net_layout.addWidget(SubtitleLabel('网络设置', network_card))

        # 代理
        proxy_row = QHBoxLayout()
        proxy_row.addWidget(StrongBodyLabel('代理地址', network_card))
        proxy_row.addStretch(1)
        self.proxy_edit = LineEdit(network_card)
        self.proxy_edit.setPlaceholderText('例如 http://127.0.0.1:7890（留空则直连）')
        self.proxy_edit.setFixedWidth(320)
        proxy_row.addWidget(self.proxy_edit)
        net_layout.addLayout(proxy_row)

        # 忽略系统代理
        ignore_row = QHBoxLayout()
        ignore_row.addWidget(StrongBodyLabel('忽略系统环境代理', network_card))
        ignore_row.addStretch(1)
        self.ignore_env_switch = SwitchButton(network_card)
        ignore_row.addWidget(self.ignore_env_switch)
        net_layout.addLayout(ignore_row)

        # 超时
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(StrongBodyLabel('请求超时（秒）', network_card))
        timeout_row.addStretch(1)
        self.timeout_spin = SpinBox(network_card)
        self.timeout_spin.setRange(5, 120)
        self.timeout_spin.setValue(30)
        timeout_row.addWidget(self.timeout_spin)
        net_layout.addLayout(timeout_row)

        root_layout.addWidget(network_card)

        # ===== 下载设置卡片 =====
        dl_card = CardWidget(self)
        dl_layout = QVBoxLayout(dl_card)
        dl_layout.setContentsMargins(20, 16, 20, 16)
        dl_layout.setSpacing(12)

        dl_layout.addWidget(SubtitleLabel('下载设置', dl_card))

        # 输出目录
        out_row = QHBoxLayout()
        out_row.addWidget(StrongBodyLabel('保存目录', dl_card))
        out_row.addStretch(1)
        self.output_edit = LineEdit(dl_card)
        self.output_edit.setPlaceholderText('默认 data/ehentai/galleries')
        self.output_edit.setFixedWidth(320)
        out_row.addWidget(self.output_edit)
        out_browse_btn = ToolButton(FluentIcon.FOLDER, dl_card)
        out_browse_btn.setToolTip('选择目录')
        out_browse_btn.clicked.connect(self._choose_output_dir)
        out_row.addWidget(out_browse_btn)
        dl_layout.addLayout(out_row)

        # 并发数
        conc_row = QHBoxLayout()
        conc_row.addWidget(StrongBodyLabel('并发下载数', dl_card))
        conc_row.addStretch(1)
        self.concurrent_spin = SpinBox(dl_card)
        self.concurrent_spin.setRange(1, 32)
        self.concurrent_spin.setValue(4)
        conc_row.addWidget(self.concurrent_spin)
        dl_layout.addLayout(conc_row)

        # 图片格式
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(StrongBodyLabel('图片格式', dl_card))
        fmt_row.addStretch(1)
        self.format_combo = ComboBox(dl_card)
        self.format_combo.addItems(['原始格式', 'JPG', 'PNG', 'WEBP'])
        self.format_combo.setFixedWidth(140)
        fmt_row.addWidget(self.format_combo)
        dl_layout.addLayout(fmt_row)

        # 失败重试次数
        retry_row = QHBoxLayout()
        retry_row.addWidget(StrongBodyLabel('失败重试次数', dl_card))
        retry_row.addStretch(1)
        self.retry_spin = SpinBox(dl_card)
        self.retry_spin.setRange(0, 10)
        self.retry_spin.setValue(3)
        retry_row.addWidget(self.retry_spin)
        dl_layout.addLayout(retry_row)

        root_layout.addWidget(dl_card)

        # ===== 认证设置卡片 =====
        auth_card = CardWidget(self)
        auth_layout = QVBoxLayout(auth_card)
        auth_layout.setContentsMargins(20, 16, 20, 16)
        auth_layout.setSpacing(12)

        auth_layout.addWidget(SubtitleLabel('认证设置（可选）', auth_card))

        # Cookies
        auth_layout.addWidget(StrongBodyLabel('Cookies', auth_card))
        self.cookies_edit = TextEdit(auth_card)
        self.cookies_edit.setPlaceholderText(
            '浏览器开发者工具中复制的 Cookie 字符串，例如：\n'
            'nw=1; sk=abc123xyz; ...\n'
            '或 Python 字典格式：{"nw": "1", "sk": "abc123xyz"}'
        )
        self.cookies_edit.setFixedHeight(80)
        auth_layout.addWidget(self.cookies_edit)

        # Headers
        auth_layout.addWidget(StrongBodyLabel('Headers', auth_card))
        self.headers_edit = TextEdit(auth_card)
        self.headers_edit.setPlaceholderText(
            'Python 字典格式，例如：\n'
            '{"User-Agent": "Mozilla/5.0 ...", "Referer": "https://e-hentai.org/"}'
        )
        self.headers_edit.setFixedHeight(80)
        auth_layout.addWidget(self.headers_edit)

        root_layout.addWidget(auth_card)

        # ===== 保存按钮 =====
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_btn = PrimaryPushButton(FluentIcon.UPDATE, '保存设置', self)
        self.save_btn.setFixedWidth(140)
        self.save_btn.clicked.connect(self._save_settings)
        save_row.addWidget(self.save_btn)
        root_layout.addLayout(save_row)

        root_layout.addStretch(1)

        # 载入已保存的配置
        self._load_settings()

    # ------------------------------------------------------------------
    # 数据库（已与账号库统一，不再可切换）
    # ------------------------------------------------------------------
    def _unified_db_path(self) -> str:
        try:
            from core.database import get_db_path
            return get_db_path()
        except Exception:
            return str(CFG.data / 'ogc_users.db')

    def _import_db_file(self) -> None:
        """把外部数据库（如 EhViewer_PC 的 app_db.db）里的数据并进统一库。

        以前这里是"切换收藏数据库"：选另一个 .db 就整站换库。数据库统一后不再
        切换 —— 而是把外部库里的收藏/下载记录/历史**合并**进唯一的那一个库，
        外部文件本身不动（不删不改名，那是用户自己的文件）。
        """
        dbp = self._unified_db_path()
        start_dir = str(Path(dbp).parent) if dbp else str(CFG.data)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            '选择要导入的数据库文件',
            start_dir,
            'SQLite 数据库 (*.db);;所有文件 (*)',
        )
        if not file_path:
            return
        if not Path(file_path).is_file():
            InfoBar.error('文件不存在', f'未找到：{file_path}', parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
            return
        try:
            from core import db_unify
            r = db_unify.merge_database(file_path, target_path=dbp,
                                       rename_source=False)
        except Exception as e:
            r = {'ok': False, 'error': str(e), 'moved': 0, 'tables': {}}
        if r.get('ok'):
            detail = '、'.join(f'{k} {v} 行' for k, v in (r.get('tables') or {}).items()
                               if v) or '没有新增记录（数据已存在）'
            InfoBar.success(
                '导入完成',
                f'共合并 {r.get("moved", 0)} 行到统一数据库：{detail}',
                parent=self, position=InfoBarPosition.TOP, duration=5000)
            self.db_file_changed.emit(dbp)
        else:
            InfoBar.error('导入失败', str(r.get('error') or '未知错误'), parent=self,
                          position=InfoBarPosition.TOP, duration=5000)

    def _open_unified_db_folder(self) -> None:
        """在资源管理器里定位统一数据库文件。"""
        try:
            import subprocess
            path = self._unified_db_path()
            if os.path.isfile(path):
                subprocess.Popen(['explorer', '/select,', path])
            else:
                os.startfile(os.path.dirname(path))
        except Exception as e:
            InfoBar.error('打开失败', str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=3000)

    # ------------------------------------------------------------------
    # 常规设置
    # ------------------------------------------------------------------
    def _build_browse_read_card(self, root_layout) -> None:
        """浏览/阅读：把 EhViewer 的显示/阅读设置集成到 OGC 设置页，写入 ehviewer 子系统配置。"""
        try:
            from ehviewer import config as _eh
            _eh_set = _eh.set
        except Exception:
            return
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        lay.addWidget(SubtitleLabel('浏览 / 阅读', card))

        def _switch(key, label):
            row = QHBoxLayout()
            row.addWidget(StrongBodyLabel(label, card))
            row.addStretch(1)
            sw = SwitchButton(card)
            try:
                sw.setChecked(bool(_eh.get(key, False)))
            except Exception:
                pass
            sw.checkedChanged.connect(lambda on, k=key: _eh_set(k, on))
            row.addWidget(sw)
            lay.addLayout(row)
            return sw

        def _combo(key, label, items):
            row = QHBoxLayout()
            row.addWidget(StrongBodyLabel(label, card))
            row.addStretch(1)
            cb = ComboBox(card)
            for text, data in items:
                cb.addItem(text, data)
            try:
                cur = _eh.get(key)
                idx = cb.findData(cur)
                if idx >= 0:
                    cb.setCurrentIndex(idx)
            except Exception:
                pass
            cb.currentIndexChanged.connect(lambda _i, k=key, c=cb: _eh_set(k, c.currentData()))
            row.addWidget(cb)
            lay.addLayout(row)
            return cb

        _switch('show_jpn_title', '优先显示日文标题')
        _switch('show_gallery_pages', '列表显示页数')
        _combo('image_size', '图片分辨率',
               [('自动', 'a'), ('780x', '780'), ('980x', '980'), ('1280x', '1280'),
                ('1600x', '1600'), ('2400x', '2400')])
        _combo('read_style', '阅读模式', [('翻页', 'page'), ('卷轴', 'scroll')])
        _combo('reader_fit', '阅读适配', [('宽度适配', 'width'), ('整图适配', 'whole')])
        _switch('sync_download_on_read', '阅读时同步下载')
        root_layout.addWidget(card)

    def _load_settings(self) -> None:
        self.db_path_edit.setText(self._unified_db_path())
        self.proxy_edit.setText(ehentai_cfg.get(ehentai_cfg.KEY_PROXY, ''))
        self.ignore_env_switch.setChecked(
            bool(ehentai_cfg.get(ehentai_cfg.KEY_IGNORE_ENV_PROXY, True)))
        self.timeout_spin.setValue(int(ehentai_cfg.get(ehentai_cfg.KEY_TIMEOUT, 30)))
        self.output_edit.setText(ehentai_cfg.get(ehentai_cfg.KEY_OUTPUT_DIR, ''))
        self.concurrent_spin.setValue(int(ehentai_cfg.get(ehentai_cfg.KEY_CONCURRENCY, 4)))

        saved_fmt = ehentai_cfg.get(ehentai_cfg.KEY_IMAGE_FORMAT, '原始格式')
        fmt_index = self.format_combo.findText(saved_fmt)
        if fmt_index >= 0:
            self.format_combo.setCurrentIndex(fmt_index)
        else:
            self.format_combo.setCurrentIndex(0)

        self.retry_spin.setValue(int(ehentai_cfg.get(ehentai_cfg.KEY_PER_FILE_RETRIES, 3)))
        self.cookies_edit.setPlainText(ehentai_cfg.get(ehentai_cfg.KEY_COOKIES, ''))
        self.headers_edit.setPlainText(ehentai_cfg.get(ehentai_cfg.KEY_HEADERS, ''))

    def _save_settings(self) -> None:
        ehentai_cfg.set(ehentai_cfg.KEY_PROXY, self.proxy_edit.text().strip())
        ehentai_cfg.set(ehentai_cfg.KEY_IGNORE_ENV_PROXY,
                        self.ignore_env_switch.isChecked())
        ehentai_cfg.set(ehentai_cfg.KEY_TIMEOUT, self.timeout_spin.value())
        ehentai_cfg.set(ehentai_cfg.KEY_OUTPUT_DIR,
                        self.output_edit.text().strip() or str(CFG.data / 'ehentai' / 'galleries'))
        ehentai_cfg.set(ehentai_cfg.KEY_CONCURRENCY, self.concurrent_spin.value())
        ehentai_cfg.set(ehentai_cfg.KEY_IMAGE_FORMAT, self.format_combo.currentText())
        ehentai_cfg.set(ehentai_cfg.KEY_PER_FILE_RETRIES, self.retry_spin.value())
        ehentai_cfg.set(ehentai_cfg.KEY_COOKIES, self.cookies_edit.toPlainText().strip())
        ehentai_cfg.set(ehentai_cfg.KEY_HEADERS, self.headers_edit.toPlainText().strip())
        ehentai_cfg.save()

        # 数据库已统一：路径只读展示，不随保存变化
        self.db_path_edit.setText(self._unified_db_path())

        self.settings_saved.emit()

        InfoBar.success(
            '设置已保存',
            '所有配置已持久化到本地。',
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )

    def _choose_output_dir(self) -> None:
        current = self.output_edit.text().strip() or str(CFG.data)
        selected = QFileDialog.getExistingDirectory(self, '选择保存目录', current)
        if selected:
            self.output_edit.setText(selected)
