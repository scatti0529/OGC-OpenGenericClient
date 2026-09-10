# -*- coding: utf-8 -*-
"""
邮箱模块 - 主页面（OGC 集成版）
===============================
原生 IMAP/SMTP 客户端，Roundcube 式三栏布局：
- 左栏：文件夹列表 + 未读数（收件箱 / 草稿箱 / 已发送 / 垃圾邮件 / 已删除…）
- 中栏：邮件列表（发件人 / 主题 / 日期）
- 右栏：阅读窗格（正文 + 附件 + 回复/删除操作）

顶部工具栏：账号选择 / 写邮件 / 刷新 / 账号管理。
所有 imaplib/smtplib 操作在 QThread 后台线程执行；未配置账号时显示引导。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTextBrowser, QScrollArea,
    QLabel, QHeaderView, QAbstractItemView, QMenu, QAction,
)

from qfluentwidgets import (
    CaptionLabel, ComboBox, FluentIcon as FIF, InfoBar, InfoBarPosition,
    PrimaryPushButton, PushButton, StrongBodyLabel, SubtitleLabel,
    ToolButton, isDarkTheme,
)

from services.email_service import EmailAccount, email_cfg
from pages.email.email_workers import (
    FetchFoldersWorker, FetchHeadersWorker, FetchMessageWorker,
    OperationWorker,
)
from pages.email.compose_dialog import ComposeDialog
from pages.email.account_manager import AccountManagerDialog

from ui.widgets.theme import ensure_theme_connected, on_theme_changed, theme_color


_FOLDER_META = [
    ('INBOX',   '收件箱',   FIF.MAIL),
    ('Sent',    '已发送',   FIF.SEND_FILL),
    ('Drafts',  '草稿',     FIF.EDIT),
    ('Trash',   '已删除',   FIF.DELETE),
    ('Junk',    '垃圾邮件', FIF.CLOSE),
    ('Spam',    '垃圾邮件', FIF.CLOSE),
    ('Deleted', '已删除',   FIF.DELETE),
    ('Archive', '归档',     FIF.FOLDER),
    ('All Mail','全部邮件', FIF.LIBRARY),
]


class EmailPage(QWidget):
    """邮箱主页面（Roundcube 式三栏）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('EmailPage')
        self._account = None
        self._folders = []
        self._folder_worker = None
        self._headers_worker = None
        self._message_worker = None
        self._op_worker = None
        self._current_folder = 'INBOX'
        self._current_uid = ''
        self._last_full_bytes = b''

        self._build_ui()
        ensure_theme_connected()
        on_theme_changed(self._apply_theme_style)

        acc = email_cfg.get_current()
        if acc:
            self._set_account(EmailAccount(acc), refresh=True)
        else:
            self.compose_btn.setEnabled(False)
            self.refresh_btn.setEnabled(False)

        # 页面销毁时安全回收所有后台线程
        self.destroyed.connect(self.shutdown)

    # ============================================================
    # UI
    # ============================================================
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 30, 16, 12)
        root.setSpacing(10)

        # ---------- 顶部：标题 + 工具栏 ----------
        header = QHBoxLayout()
        title = SubtitleLabel('邮箱', self)
        title.setStyleSheet('font-size: 22px; font-weight: bold;')
        header.addWidget(title)
        header.addStretch(1)

        self.account_combo = ComboBox(self)
        self.account_combo.setMinimumWidth(180)
        self.account_combo.currentIndexChanged.connect(self._on_account_switched)
        header.addWidget(self.account_combo)

        self.compose_btn = PrimaryPushButton(FIF.SEND, '写邮件', self)
        self.compose_btn.clicked.connect(self._compose)
        header.addWidget(self.compose_btn)

        self.refresh_btn = ToolButton(FIF.SYNC, self)
        self.refresh_btn.setToolTip('刷新')
        self.refresh_btn.clicked.connect(self._refresh)
        header.addWidget(self.refresh_btn)

        self.manage_btn = ToolButton(FIF.PEOPLE, self)
        self.manage_btn.setToolTip('账号管理')
        self.manage_btn.clicked.connect(self._open_account_manager)
        header.addWidget(self.manage_btn)
        root.addLayout(header)

        # ---------- 三栏 ----------
        self.splitter = QSplitter(Qt.Horizontal, self)
        root.addWidget(self.splitter, 1)

        # 左栏：文件夹树
        folder_wrap = QWidget()
        folder_layout = QVBoxLayout(folder_wrap)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.setSpacing(4)
        self.folder_tree = QTreeWidget(folder_wrap)
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setObjectName('folderTree')
        self.folder_tree.setMinimumWidth(150)
        self.folder_tree.setMaximumWidth(220)
        self.folder_tree.currentItemChanged.connect(self._on_folder_selected)
        folder_layout.addWidget(self.folder_tree)
        self.splitter.addWidget(folder_wrap)

        # 中栏：邮件列表
        list_wrap = QWidget()
        list_layout = QVBoxLayout(list_wrap)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(4)
        self.msg_table = QTableWidget(0, 3, list_wrap)
        self.msg_table.setHorizontalHeaderLabels(['发件人', '主题', '日期'])
        self.msg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.msg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.msg_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.msg_table.setShowGrid(False)
        self.msg_table.verticalHeader().setVisible(False)
        hdr = self.msg_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.msg_table.itemSelectionChanged.connect(self._on_message_selected)
        self.msg_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.msg_table.customContextMenuRequested.connect(self._show_list_menu)
        list_layout.addWidget(self.msg_table)
        self.splitter.addWidget(list_wrap)

        # 右栏：阅读窗格
        reader = QWidget()
        reader_layout = QVBoxLayout(reader)
        reader_layout.setContentsMargins(16, 6, 16, 6)
        reader_layout.setSpacing(8)

        # 阅读区工具条
        rtool = QHBoxLayout()
        rtool.setSpacing(6)
        self.reply_btn = ToolButton(FIF.SEND, self)
        self.reply_btn.setToolTip('回复')
        self.reply_btn.clicked.connect(self._reply)
        rtool.addWidget(self.reply_btn)
        self.forward_btn = ToolButton(FIF.RIGHT_ARROW, self)
        self.forward_btn.setToolTip('转发')
        self.forward_btn.clicked.connect(self._forward)
        rtool.addWidget(self.forward_btn)
        self.delete_btn = ToolButton(FIF.DELETE, self)
        self.delete_btn.setToolTip('删除')
        self.delete_btn.clicked.connect(self._delete_current)
        rtool.addWidget(self.delete_btn)
        rtool.addStretch(1)
        reader_layout.addLayout(rtool)

        self.reader_title = StrongBodyLabel('', reader)
        self.reader_title.setWordWrap(True)
        reader_layout.addWidget(self.reader_title)

        self.reader_meta = CaptionLabel('', reader)
        self.reader_meta.setWordWrap(True)
        self.reader_meta.setStyleSheet('color:' + theme_color('#59636d', '#9aa7b5') + ';')
        reader_layout.addWidget(self.reader_meta)

        self.attach_row = QHBoxLayout()
        self.attach_row.setSpacing(6)
        reader_layout.addLayout(self.attach_row)

        self.reader_view = QTextBrowser(reader)
        self.reader_view.setOpenExternalLinks(True)
        self.reader_view.setStyleSheet('QTextBrowser { background: transparent; border: none; }')
        reader_layout.addWidget(self.reader_view, 1)

        self.splitter.addWidget(reader)
        self.splitter.setSizes([180, 380, 560])

        self._show_empty_state()
        self._apply_theme_style()

    # ============================================================
    # 工具
    # ============================================================
    def _clear_attachments(self):
        while self.attach_row.count():
            item = self.attach_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _folder_icon(self, name):
        for key, _label, icon in _FOLDER_META:
            if key == name:
                return icon.icon()
        return FIF.FOLDER.icon()

    def _folder_label(self, name):
        for key, label, _icon in _FOLDER_META:
            if key == name:
                return label
        return name

    # ============================================================
    # 空状态
    # ============================================================
    def _show_empty_state(self, message='尚未配置邮箱账号'):
        self.msg_table.setRowCount(0)
        self.folder_tree.clear()
        self.reader_title.setText('')
        self.reader_meta.setText('')
        self.reader_view.clear()
        self._clear_attachments()
        self.reader_view.setPlainText(
            f'{message}\\n\\n点击右上角「账号管理」新增一个域名邮箱账号，'
            '输入邮箱与密码（授权码）即可登录并收发邮件。')

    # ============================================================
    # 账号
    # ============================================================
    def _reload_account_combo(self):
        accounts = email_cfg.get_accounts()
        current_id = email_cfg.get('current')
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for acc in accounts:
            self.account_combo.addItem(acc.get('email', '未命名'), acc.get('id'))
        if current_id:
            idx = self.account_combo.findData(current_id)
            if idx >= 0:
                self.account_combo.setCurrentIndex(idx)
        self.account_combo.blockSignals(False)

    def _set_account(self, account, refresh=True):
        self._account = account
        self.compose_btn.setEnabled(bool(account and account.email))
        self.refresh_btn.setEnabled(bool(account and account.email))
        if refresh:
            self._refresh()

    def _on_account_switched(self, index):
        acc_id = self.account_combo.itemData(index)
        if not acc_id:
            self._account = None
            self._show_empty_state('尚未配置邮箱账号')
            return
        email_cfg.set_current(acc_id)
        acc = email_cfg.get_by_id(acc_id)
        if acc:
            self._set_account(EmailAccount(acc), refresh=True)

    def _open_account_manager(self):
        dlg = AccountManagerDialog(self)
        dlg.exec_()
        self._reload_account_combo()
        acc = email_cfg.get_current()
        if acc:
            self._set_account(EmailAccount(acc), refresh=True)
        else:
            self._account = None
            self._show_empty_state('尚未配置邮箱账号')

    def _compose(self, preset=None):
        if not self._account:
            InfoBar.warning('提示', '请先配置邮箱账号。', parent=self,
                            position=InfoBarPosition.TOP, duration=3000)
            return
        dlg = ComposeDialog(self._account, self)
        if preset:
            dlg.apply_reply_preset(preset)
        dlg.exec_()

    def _reply(self):
        if not self._current_uid:
            return
        self._compose(preset={'to': self._current_from_email,
                              'subject': 'Re: ' + self._current_subject})

    def _forward(self):
        if not self._current_uid:
            return
        self._compose(preset={'subject': 'Fwd: ' + self._current_subject,
                              'body': self._current_body})

    def _refresh(self):
        if not self._account:
            return
        self.refresh_btn.setEnabled(False)
        self._folder_worker = FetchFoldersWorker(self._account, parent=self)
        self._folder_worker.succeeded.connect(self._on_folders_loaded)
        self._folder_worker.failed.connect(self._on_net_failed)
        self._folder_worker.start()

    # ============================================================
    # 文件夹
    # ============================================================
    def _on_folders_loaded(self, folders):
        self.refresh_btn.setEnabled(True)
        self._folders = folders
        self._rebuild_folder_tree()
        target = self._current_folder if self._current_folder in [f['name'] for f in folders] else 'INBOX'
        if target not in [f['name'] for f in folders]:
            first = next((f['name'] for f in folders), None)
            target = first
        if target:
            self._load_folder(target)
        else:
            self.msg_table.setRowCount(0)

    def _rebuild_folder_tree(self):
        self.folder_tree.clear()
        ranked = sorted(self._folders, key=lambda f: (self._folder_rank(f['name']), f['name']))
        self._folder_items = {}
        seen = set()
        for f in ranked:
            name = f['name']
            if name in seen:
                continue
            seen.add(name)
            unread = f.get('unread')
            label = self._folder_label(name) or name
            text = label if unread is None else f'{label} ({unread})'
            item = QTreeWidgetItem(self.folder_tree)
            item.setText(0, text)
            item.setData(0, Qt.UserRole, name)
            item.setIcon(0, self._folder_icon(name))
            item.setToolTip(0, name)
            if unread and unread > 0:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            self._folder_items[name] = item
        self.folder_tree.expandAll()
        # 默认选中当前位置
        cur = self._folder_items.get(self._current_folder)
        if cur:
            self.folder_tree.setCurrentItem(cur)

    def _folder_rank(self, name):
        order = ['INBOX', 'Sent', 'Drafts', 'Trash', 'Deleted', 'Junk', 'Spam', 'Archive', 'All Mail']
        try:
            return order.index(name)
        except ValueError:
            return 100

    def _on_folder_selected(self, current, previous):
        if current is None:
            return
        name = current.data(0, Qt.UserRole)
        if name:
            self._load_folder(name)

    def _load_folder(self, folder):
        self._current_folder = folder
        self._current_uid = ''
        self.msg_table.setRowCount(0)
        self.reader_title.setText('')
        self.reader_meta.setText('')
        self.reader_view.clear()
        self._clear_attachments()
        if not self._account:
            return
        self._headers_worker = FetchHeadersWorker(self._account, folder, 100, parent=self)
        self._headers_worker.succeeded.connect(self._on_headers_loaded)
        self._headers_worker.failed.connect(self._on_net_failed)
        self._headers_worker.start()

    def _on_headers_loaded(self, headers):
        self.msg_table.setRowCount(0)
        self.msg_table.setRowCount(len(headers))
        for row, h in enumerate(headers):
            from_txt = h.get('from', '')
            fname = from_txt
            if ' <' in from_txt:
                fname = from_txt.split(' <')[0].strip().strip('"')
            from_item = QTableWidgetItem(fname or '(未知)')
            from_item.setData(Qt.UserRole, h.get('uid', ''))
            subj_item = QTableWidgetItem(h.get('subject', '') or '(无主题)')
            date_item = QTableWidgetItem(self._fmt_date(h.get('date_str', '')))
            if not h.get('is_seen', True):
                for it in (from_item, subj_item, date_item):
                    font = it.font()
                    font.setBold(True)
                    it.setFont(font)
            self.msg_table.setItem(row, 0, from_item)
            self.msg_table.setItem(row, 1, subj_item)
            self.msg_table.setItem(row, 2, date_item)
        self.msg_table.resizeRowsToContents()

    def _fmt_date(self, date_str):
        if not date_str:
            return '-'
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.strftime('%m-%d %H:%M')
        except Exception:
            return date_str[:16]

    # ============================================================
    # 邮件详情
    # ============================================================
    def _on_message_selected(self):
        row = self.msg_table.currentRow()
        if row < 0:
            return
        uid_item = self.msg_table.item(row, 0)
        if not uid_item:
            return
        uid = uid_item.data(Qt.UserRole)
        if not uid:
            return
        self._current_uid = uid
        # 记录发件人/主题供回复/转发
        self._current_from_email = self.msg_table.item(row, 0).text()
        self._current_subject = self.msg_table.item(row, 1).text() if self.msg_table.item(row, 1) else ''
        self.reader_view.setPlainText('加载中…')
        self._message_worker = FetchMessageWorker(
            self._account, self._current_folder, uid, parent=self)
        self._message_worker.succeeded.connect(self._on_message_loaded)
        self._message_worker.failed.connect(self._on_net_failed)
        self._message_worker.start()

    def _on_message_loaded(self, msg):
        self._current_subject = msg.subject or '(无主题)'
        self._current_from_email = msg.from_email or ''
        self._current_body = msg.text_body or msg.html_body or ''
        self.reader_title.setText(self._current_subject)
        meta_parts = []
        if msg.from_display:
            meta_parts.append(f'发件人：{msg.from_display}')
        if msg.to:
            meta_parts.append(f'收件人：{", ".join(msg.to)}')
        if msg.date_str:
            meta_parts.append(f'时间：{msg.date_str}')
        self.reader_meta.setText('　|　'.join(meta_parts))
        self._clear_attachments()
        for att in msg.attachments:
            btn = PushButton(FIF.DOCUMENT, att.filename, self)
            btn.setToolTip(f'{att.content_type} · {att.size / 1024:.1f} KB')
            btn.clicked.connect(lambda _c, a=att: self._download_attachment(a))
            self.attach_row.addWidget(btn)
        self._last_full_bytes = msg.raw_bytes
        if msg.text_body:
            self.reader_view.setPlainText(msg.text_body)
        elif msg.html_body:
            self.reader_view.setHtml(self._sanitize_html(msg.html_body))
        else:
            self.reader_view.setPlainText('（此邮件无正文）')

    def _sanitize_html(self, html):
        import re
        return re.sub(r'<img[^>]*>', '', html, flags=re.IGNORECASE)

    # ============================================================
    # 列表右键菜单
    # ============================================================
    def _show_list_menu(self, pos):
        row = self.msg_table.indexAt(pos).row()
        if row < 0:
            return
        self.msg_table.selectRow(row)
        menu = QMenu(self)
        reply = menu.addAction('回复')
        reply.triggered.connect(self._reply)
        forward = menu.addAction('转发')
        forward.triggered.connect(self._forward)
        menu.addSeparator()
        mark_read = menu.addAction('标记为已读')
        mark_read.triggered.connect(lambda: self._mark_current_seen(True))
        mark_unread = menu.addAction('标记为未读')
        mark_unread.triggered.connect(lambda: self._mark_current_seen(False))
        menu.addSeparator()
        delete = menu.addAction('删除')
        delete.triggered.connect(self._delete_current)
        menu.exec_(self.msg_table.viewport().mapToGlobal(pos))

    def _mark_current_seen(self, seen):
        if not self._current_uid or not self._account:
            return
        self._run_op('mark_seen', uid=self._current_uid, seen=seen)

    def _delete_current(self):
        if not self._current_uid or not self._account:
            return
        self._run_op('delete', uid=self._current_uid)

    def _run_op(self, op, **kwargs):
        self._op_worker = OperationWorker(
            self._account, op, folder=self._current_folder, uid=kwargs.get('uid', ''),
            seen=kwargs.get('seen', True), parent=self)
        self._op_worker.succeeded.connect(lambda _r: self._after_op())
        self._op_worker.failed.connect(self._on_net_failed)
        self._op_worker.start()

    def _after_op(self):
        self._refresh()

    # ============================================================
    # 附件下载
    # ============================================================
    def _download_attachment(self, att):
        try:
            if not self._account:
                return
            from PyQt5.QtWidgets import QFileDialog
            from email.parser import BytesParser
            from email import policy
            path, _ = QFileDialog.getSaveFileName(self, '保存附件', att.filename)
            if not path:
                return
            raw = getattr(self, '_last_full_bytes', b'')
            if not raw:
                InfoBar.warning('提示', '请先重新加载邮件正文。', parent=self,
                                position=InfoBarPosition.TOP, duration=3000)
                return
            found = False
            msg = BytesParser(policy=policy.default).parsebytes(raw)
            for part in msg.walk():
                pf = part.get_filename()
                if pf and _decode_filename(pf) == att.filename:
                    data = part.get_payload(decode=True)
                    if data:
                        with open(path, 'wb') as f:
                            f.write(data)
                        found = True
                    break
            InfoBar.success('已保存', f'附件已保存到 {path}' if found else '未找到附件内容',
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
        except Exception as e:
            InfoBar.error('保存失败', str(e), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)

    def _on_net_failed(self, message):
        self.refresh_btn.setEnabled(True)
        self.reader_view.setPlainText(f'操作失败：{message}')
        InfoBar.error('网络错误', message, parent=self,
                      position=InfoBarPosition.TOP, duration=5000)

    # ============================================================
    # 销毁回收
    # ============================================================
    def shutdown(self):
        """回收所有仍在运行的后台线程。"""
        for w in (self._folder_worker, self._headers_worker,
                  self._message_worker, self._op_worker):
            if w is not None and w.isRunning():
                w.stop()
                w.wait(1200)

    def closeEvent(self, event):
        """关闭时精确回收所有后台线程（配合窗口/应用退出）。"""
        try:
            self.shutdown()
        except Exception:
            pass
        super().closeEvent(event)

    # ============================================================
    # 主题
    # ============================================================
    def _apply_theme_style(self):
        self.folder_tree.setStyleSheet(
            'QTreeWidget { background: transparent; border: none; }'
            'QTreeWidget::item { padding: 4px; }'
            'QTreeWidget::item:selected { background: rgba(76,195,247,0.18); border-radius: 6px; }')
        self.msg_table.setStyleSheet(
            'QTableWidget { background: transparent; border: none; }'
            'QTableWidget::item:selected { background: rgba(76,195,247,0.18); }')


def _decode_filename(value):
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)