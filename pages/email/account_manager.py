# -*- coding: utf-8 -*-
"""
邮箱模块 - 账号管理对话框（多账号）
===================================
左侧账号列表，右侧编辑表单（邮箱/密码/名称 + IMAP/SMTP 服务器）。
支持：
- 新增 / 删除 / 保存账号
- 输入邮箱自动推断常见域名服务器（QQ/163/Gmail/Outlook 等）
- 「测试连接」在后台线程验证 IMAP+SMTP 凭据
账号配置写入 data/config.json 的 "email" 节点。
"""
import uuid

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget, QFormLayout,
)

from qfluentwidgets import (
    CaptionLabel, CheckBox, FluentIcon as FIF, InfoBar, InfoBarPosition,
    LineEdit, PrimaryPushButton, PushButton, SpinBox, StrongBodyLabel,
    ToolButton, ComboBox,
)

from services.email_service import (
    EmailAccount, email_cfg, suggest_servers,
)
from pages.email.email_workers import TestAccountWorker


class AccountManagerDialog(QDialog):
    """邮箱账号管理对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._test_worker = None
        self._accounts = email_cfg.get_accounts()
        self.setWindowTitle('邮箱账号管理')
        self.resize(760, 560)
        self._build_ui()
        self._reload_list()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ===== 左侧账号列表 =====
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(StrongBodyLabel('账号', self))
        self.acc_list = QListWidget(self)
        self.acc_list.setFixedWidth(220)
        self.acc_list.setStyleSheet(
            'QListWidget { background: transparent; border: 1px solid rgba(153,153,153,0.3); border-radius: 8px; }')
        self.acc_list.currentItemChanged.connect(self._on_select)
        left.addWidget(self.acc_list, 1)

        # 新增按钮
        new_btn = PushButton(FIF.ADD, '新增账号', self)
        new_btn.clicked.connect(self._new_account)
        left.addWidget(new_btn)

        del_btn = PushButton(FIF.DELETE, '删除当前', self)
        del_btn.clicked.connect(self._delete_account)
        left.addWidget(del_btn)

        root.addLayout(left)

        # ===== 右侧编辑表单 =====
        right = QVBoxLayout()
        right.setSpacing(10)

        self._form_title = StrongBodyLabel('编辑账号', self)
        right.addWidget(self._form_title)

        # 基本信息
        base_card = QWidget(self)
        form = QFormLayout(base_card)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        self.name_edit = LineEdit(base_card)
        self.name_edit.setPlaceholderText('显示名（可选，如「我的QQ邮箱」）')
        form.addRow('显示名', self.name_edit)

        self.email_edit = LineEdit(base_card)
        self.email_edit.setPlaceholderText('yourname@domain.com')
        self.email_edit.editingFinished.connect(self._on_email_changed)
        form.addRow('邮箱', self.email_edit)

        self.pwd_edit = LineEdit(base_card)
        self.pwd_edit.setPlaceholderText('密码 / 授权码')
        self.pwd_edit.setEchoMode(LineEdit.Password)
        form.addRow('密码', self.pwd_edit)

        # 服务器（自动推断后可手动覆盖）
        self.imap_host_edit = LineEdit(base_card)
        self.imap_host_edit.setPlaceholderText('imap.example.com')
        form.addRow('IMAP 服务器', self.imap_host_edit)

        imap_port_row = QHBoxLayout()
        self.imap_port_spin = SpinBox(base_card)
        self.imap_port_spin.setRange(1, 65535)
        self.imap_port_spin.setValue(993)
        imap_port_row.addWidget(self.imap_port_spin)
        self.imap_ssl_check = CheckBox('IMAP SSL', base_card)
        self.imap_ssl_check.setChecked(True)
        imap_port_row.addWidget(self.imap_ssl_check)
        imap_port_row.addStretch(1)
        form.addRow('IMAP 端口', self._wrap(imap_port_row))

        self.smtp_host_edit = LineEdit(base_card)
        self.smtp_host_edit.setPlaceholderText('smtp.example.com')
        form.addRow('SMTP 服务器', self.smtp_host_edit)

        smtp_port_row = QHBoxLayout()
        self.smtp_port_spin = SpinBox(base_card)
        self.smtp_port_spin.setRange(1, 65535)
        self.smtp_port_spin.setValue(465)
        smtp_port_row.addWidget(self.smtp_port_spin)
        self.smtp_ssl_check = CheckBox('SMTP SSL', base_card)
        self.smtp_ssl_check.setChecked(True)
        smtp_port_row.addWidget(self.smtp_ssl_check)
        smtp_port_row.addStretch(1)
        form.addRow('SMTP 端口', self._wrap(smtp_port_row))

        right.addWidget(base_card)

        right.addStretch(1)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.test_btn = PushButton(FIF.SYNC, '测试连接', self)
        self.test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(self.test_btn)

        self.save_btn = PrimaryPushButton(FIF.SAVE, '保存账号', self)
        self.save_btn.clicked.connect(self._save_account)
        btn_row.addWidget(self.save_btn)
        right.addLayout(btn_row)

        root.addLayout(right, 1)

    def _wrap(self, layout):
        """把 QHBoxLayout 包进一个容器 QWidget，便于放进 QFormLayout。"""
        w = QWidget(self)
        layout.setContentsMargins(0, 0, 0, 0)
        from PyQt5.QtWidgets import QVBoxLayout
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.addLayout(layout)
        return w

    # ---------------- 列表 ----------------
    def _reload_list(self, select_id=None):
        self.acc_list.clear()
        for acc in self._accounts:
            item = QListWidgetItem(acc.get('email', '未命名'))
            item.setData(Qt.UserRole, acc.get('id'))
            self.acc_list.addItem(item)
        if self._accounts:
            target = select_id or self._accounts[0].get('id')
            for i in range(self.acc_list.count()):
                if self.acc_list.item(i).data(Qt.UserRole) == target:
                    self.acc_list.setCurrentRow(i)
                    break

    def _on_select(self, current, previous):
        if current is None:
            self._clear_form()
            return
        acc = email_cfg.get_by_id(current.data(Qt.UserRole))
        if acc:
            self._load_form(acc)

    def _load_form(self, acc: dict):
        self.name_edit.setText(acc.get('name', ''))
        self.email_edit.setText(acc.get('email', ''))
        self.pwd_edit.setText(acc.get('password', ''))
        self.imap_host_edit.setText(acc.get('imap_host', ''))
        self.imap_port_spin.setValue(int(acc.get('imap_port', 993)))
        self.imap_ssl_check.setChecked(bool(acc.get('imap_ssl', True)))
        self.smtp_host_edit.setText(acc.get('smtp_host', ''))
        self.smtp_port_spin.setValue(int(acc.get('smtp_port', 465)))
        self.smtp_ssl_check.setChecked(bool(acc.get('smtp_ssl', True)))

    def _clear_form(self):
        self._form_title.setText('编辑账号')
        for e in (self.name_edit, self.email_edit, self.pwd_edit,
                  self.imap_host_edit, self.smtp_host_edit):
            e.clear()
        self.imap_port_spin.setValue(993)
        self.smtp_port_spin.setValue(465)
        self.imap_ssl_check.setChecked(True)
        self.smtp_ssl_check.setChecked(True)

    # ---------------- 操作 ----------------
    def _current_id(self):
        item = self.acc_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _new_account(self):
        """清空表单准备新增（暂不写入）。"""
        self.acc_list.setCurrentItem(None)
        self._clear_form()
        self._form_title.setText('新增账号')
        self.email_edit.setFocus()
        self._pending_new = True

    def _delete_account(self):
        acc_id = self._current_id()
        if not acc_id:
            return
        email_cfg.remove_account(acc_id)
        self._accounts = email_cfg.get_accounts()
        self._reload_list()
        InfoBar.success('已删除', '账号已移除。', parent=self,
                        position=InfoBarPosition.TOP, duration=2500)

    def _on_email_changed(self):
        """输入邮箱后推断常见服务器的 IMAP/SMTP。"""
        email = self.email_edit.text().strip()
        if not email or '@' not in email:
            return
        # 若当前服务器字段为空，才自动填充
        if not self.imap_host_edit.text().strip() and not self.smtp_host_edit.text().strip():
            srv = suggest_servers(email)
            self.imap_host_edit.setText(srv['imap_host'])
            self.imap_port_spin.setValue(srv['imap_port'])
            self.imap_ssl_check.setChecked(srv['imap_ssl'])
            self.smtp_host_edit.setText(srv['smtp_host'])
            self.smtp_port_spin.setValue(srv['smtp_port'])
            self.smtp_ssl_check.setChecked(srv['smtp_ssl'])

    def _collect(self) -> dict:
        return {
            'name': self.name_edit.text().strip(),
            'email': self.email_edit.text().strip(),
            'password': self.pwd_edit.text(),
            'imap_host': self.imap_host_edit.text().strip(),
            'imap_port': self.imap_port_spin.value(),
            'imap_ssl': self.imap_ssl_check.isChecked(),
            'smtp_host': self.smtp_host_edit.text().strip(),
            'smtp_port': self.smtp_port_spin.value(),
            'smtp_ssl': self.smtp_ssl_check.isChecked(),
        }

    def _save_account(self):
        email = self.email_edit.text().strip()
        if not email or '@' not in email:
            InfoBar.warning('提示', '请填写正确的邮箱地址。', parent=self,
                            position=InfoBarPosition.TOP, duration=3000)
            return
        if not self.imap_host_edit.text().strip() or not self.smtp_host_edit.text().strip():
            InfoBar.warning('提示', '请填写 IMAP 与 SMTP 服务器。', parent=self,
                            position=InfoBarPosition.TOP, duration=3000)
            return
        data = self._collect()
        acc_id = getattr(self, '_pending_new', None) and None or self._current_id()
        data['id'] = acc_id or uuid.uuid4().hex
        email_cfg.upsert_account(data)
        self._pending_new = False
        self._accounts = email_cfg.get_accounts()
        self._reload_list(select_id=data['id'])
        InfoBar.success('已保存', '账号配置已持久化。', parent=self,
                        position=InfoBarPosition.TOP, duration=2500)

    def _test_connection(self):
        email = self.email_edit.text().strip()
        if not email or '@' not in email:
            InfoBar.warning('提示', '请先填写邮箱地址。', parent=self,
                            position=InfoBarPosition.TOP, duration=3000)
            return
        acc = EmailAccount(self._collect())
        self.test_btn.setEnabled(False)
        self.test_btn.setText('测试中…')
        self._test_worker = TestAccountWorker(acc, parent=self)
        self._test_worker.succeeded.connect(self._on_test_ok)
        self._test_worker.failed.connect(self._on_test_fail)
        self._test_worker.start()

    def _on_test_ok(self, message):
        self.test_btn.setEnabled(True)
        self.test_btn.setText('测试连接')
        InfoBar.success('连接成功', message, parent=self,
                        position=InfoBarPosition.TOP, duration=3000)

    def _on_test_fail(self, message):
        self.test_btn.setEnabled(True)
        self.test_btn.setText('测试连接')
        InfoBar.error('连接失败', message, parent=self,
                      position=InfoBarPosition.TOP, duration=5000)