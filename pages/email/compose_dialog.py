# -*- coding: utf-8 -*-
"""
邮箱模块 - 写邮件对话框（SMTP 发送）
===================================
收件人 / 抄送 / 主题 / 正文 + 附件。填写信息后点击「发送」，
在后台线程（SendMailWorker）发送，成功/失败弹 InfoBar。
"""
from PyQt5.QtCore import Qt, QThread
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget, QFileDialog,
)

from qfluentwidgets import (
    BodyLabel, CaptionLabel, FluentIcon as FIF, InfoBar, InfoBarPosition,
    LineEdit, PrimaryPushButton, PushButton, StrongBodyLabel, TextEdit,
    ToolButton,
)

from pages.email.email_workers import SendMailWorker


class ComposeDialog(QDialog):
    """写邮件对话框（发送）。"""

    def __init__(self, account, parent=None):
        super().__init__(parent)
        self.account = account
        self._worker = None
        self._attachments = []  # [(filename, bytes, content_type)]
        self.setWindowTitle(f'写邮件 - {account.display_name}')
        self.resize(720, 560)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # 收件人
        to_row = QHBoxLayout()
        to_row.addWidget(CaptionLabel('收件人', self))
        self.to_edit = LineEdit(self)
        self.to_edit.setPlaceholderText('多个收件人用英文逗号分隔')
        to_row.addWidget(self.to_edit, 1)
        root.addLayout(to_row)

        # 抄送
        cc_row = QHBoxLayout()
        cc_row.addWidget(CaptionLabel('抄送', self))
        self.cc_edit = LineEdit(self)
        self.cc_edit.setPlaceholderText('可选')
        cc_row.addWidget(self.cc_edit, 1)
        root.addLayout(cc_row)

        # 主题
        subj_row = QHBoxLayout()
        subj_row.addWidget(CaptionLabel('主题', self))
        self.subject_edit = LineEdit(self)
        self.subject_edit.setPlaceholderText('邮件主题')
        subj_row.addWidget(self.subject_edit, 1)
        root.addLayout(subj_row)

        # 正文
        body_label_row = QHBoxLayout()
        body_label_row.addWidget(StrongBodyLabel('正文', self))
        body_label_row.addStretch(1)
        # 附件按钮
        attach_btn = ToolButton(FIF.DOCUMENT, self)
        attach_btn.setToolTip('添加附件')
        attach_btn.clicked.connect(self._add_attachment)
        body_label_row.addWidget(attach_btn)
        root.addLayout(body_label_row)

        self.body_edit = TextEdit(self)
        self.body_edit.setPlaceholderText('邮件正文…')
        self.body_edit.setFixedHeight(220)
        root.addWidget(self.body_edit, 1)

        # 附件列表
        self.attach_list = QListWidget(self)
        self.attach_list.setFixedHeight(0)  # 初始隐藏（Lazy 显示）
        self.attach_list.setStyleSheet('QListWidget { background: transparent; border: none; }')
        root.addWidget(self.attach_list)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton('取消', self)
        cancel_btn.clicked.connect(self.reject)
        self.send_btn = PrimaryPushButton(FIF.SEND, '发送', self)
        self.send_btn.clicked.connect(self._send)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.send_btn)
        root.addLayout(btn_row)

    # ---------------- 回复/转发预填 ----------------
    def apply_reply_preset(self, preset: dict):
        """按预设预填对话框（to / subject / body）。"""
        if preset.get('to'):
            self.to_edit.setText(preset['to'])
        if preset.get('subject'):
            self.subject_edit.setText(preset['subject'])
        if preset.get('body'):
            self.body_edit.setPlainText(preset['body'])

    # ---------------- 关闭时安全回收后台线程 ----------------
    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(1500)
        super().closeEvent(event)

    # ---------------- 附件 ----------------
    def _add_attachment(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择附件')
        for path in paths:
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                import os
                name = os.path.basename(path)
                ext = os.path.splitext(name)[1].lstrip('.') or 'octet-stream'
                content_type = {
                    'pdf': 'application/pdf',
                    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                    'gif': 'image/gif', 'zip': 'application/zip', 'txt': 'text/plain',
                }.get(ext.lower(), 'application/octet-stream')
                self._attachments.append((name, data, content_type))
                self._refresh_attach_list()
            except Exception as e:
                InfoBar.error('附件失败', f'无法读取：{path}\n{e}',
                              parent=self, position=InfoBarPosition.TOP, duration=4000)

    def _refresh_attach_list(self):
        self.attach_list.clear()
        for name, data, _ct in self._attachments:
            item = QListWidgetItem(f'{name}（{len(data) / 1024:.1f} KB）')
            self.attach_list.addItem(item)
        self.attach_list.setFixedHeight(0 if not self._attachments else 70)

    # ---------------- 发送 ----------------
    def _send(self):
        to = [x.strip() for x in self.to_edit.text().replace('；', ';').replace('，', ',').split(',') if x.strip()]
        if not to:
            InfoBar.warning('提示', '请填写收件人。', parent=self,
                            position=InfoBarPosition.TOP, duration=3000)
            return
        subject = self.subject_edit.text().strip()
        body = self.body_edit.toPlainText()
        cc = [x.strip() for x in self.cc_edit.text().replace('；', ';').replace('，', ',').split(',') if x.strip()]

        self.send_btn.setEnabled(False)
        self.send_btn.setText('发送中…')

        payload = {
            'to': to, 'cc': cc, 'bcc': [],
            'subject': subject, 'body': body,
            'html_body': '', 'attachments': list(self._attachments),
        }
        self._worker = SendMailWorker(self.account, payload, parent=self)
        self._worker.succeeded.connect(self._on_sent)
        self._worker.failed.connect(self._on_send_failed)
        self._worker.start()

    def _on_sent(self, result):
        InfoBar.success('已发送', f'邮件已通过 {self.account.smtp_host} 发送。',
                        parent=self, position=InfoBarPosition.TOP, duration=3000)
        self.accept()

    def _on_send_failed(self, message):
        self.send_btn.setEnabled(True)
        self.send_btn.setText('发送')
        InfoBar.error('发送失败', message, parent=self,
                      position=InfoBarPosition.TOP, duration=5000)