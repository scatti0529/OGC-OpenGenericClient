# -*- coding: utf-8 -*-
"""邮箱模块冒烟测试（离线，不触网）。

验证：
1. 服务层：服务器推断 / modified UTF-7 解码 / MIME 解析（subject、from、to、text、html、附件元数据）
2. UI 层：EmailPage / AccountManagerDialog / ComposeDialog 可实例化
3. 主窗口：'邮箱' 导航项已注册（需要 offscreen 平台插件路径）
"""
import os
import sys
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

try:
    # ---------- 服务层 ----------
    from services.email_service import (
        suggest_servers, _modified_utf7_decode, EmailService, EmailAccount,
    )

    assert suggest_servers('a@gmail.com')['imap_host'] == 'imap.gmail.com'
    assert suggest_servers('a@163.com')['imap_host'] == 'imap.163.com'
    assert suggest_servers('me@mycompany.com')['imap_host'] == 'imap.mycompany.com'
    print('[OK] suggest_servers')

    assert _modified_utf7_decode('INBOX') == 'INBOX'
    assert len(_modified_utf7_decode('&XfJT0ZAB-')) > 0
    print('[OK] modified utf7 decode')

    # 构造带附件的 multipart 邮件
    from email.message import EmailMessage as SM
    m = SM()
    m['From'] = 'sender@example.com'
    m['To'] = 'to@example.com'
    import base64
    m['Subject'] = '=?utf-8?B?' + base64.b64encode('测试邮件'.encode('utf-8')).decode() + '?='
    m.set_content('这是纯文本正文。')
    m.add_alternative('<b>HTML 正文</b>', subtype='html')
    m.add_attachment(b'PDFDATA', maintype='application', subtype='pdf', filename='report.pdf')
    raw = m.as_bytes()

    em = EmailService().parse_message(raw, uid='1')
    assert em.subject == '测试邮件', repr(em.subject)
    assert em.from_email == 'sender@example.com'
    assert em.to == ['to@example.com']
    assert '纯文本正文' in em.text_body
    assert '<b>HTML 正文</b>' in em.html_body
    assert len(em.attachments) == 1 and em.attachments[0].filename == 'report.pdf'
    assert em.raw_bytes == raw
    print('[OK] MIME parse (subject/from/to/text/html/attachment)')

    # 新增方法：build_sent_raw / mark_seen / delete_message 存在且签名正确
    from services.email_service import EmailAccount as _Acc
    _a = _Acc({'email': 'a@qq.com', 'password': 'x',
               'imap_host': 'imap.qq.com', 'smtp_host': 'smtp.qq.com'})
    svc = EmailService()
    assert hasattr(svc, 'build_sent_raw')
    assert hasattr(svc, 'mark_seen')
    assert hasattr(svc, 'delete_message')
    assert hasattr(svc, 'append_sent')
    raw = svc.build_sent_raw(_a, {'to': ['x@y.com'], 'subject': 's', 'body': 'b', 'cc': [], 'bcc': [], 'html_body': '', 'attachments': []})
    assert isinstance(raw, bytes) and len(raw) > 0
    print('[OK] service write ops present & build_sent_raw works')

    print('SERVICE LAYER: PASS')

    # ---------- UI 层 ----------
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from pages.email.email_page import EmailPage
    page = EmailPage()
    assert page is not None
    print('[OK] EmailPage instantiate; account(init)=%s' % bool(page._account))
    assert page.compose_btn.isEnabled() is (bool(page._account))
    print('[OK] EmailPage empty-state buttons consistent')

    from pages.email.account_manager import AccountManagerDialog
    dlg = AccountManagerDialog()
    dlg._collect()
    print('[OK] AccountManagerDialog instantiate + collect')

    from pages.email.compose_dialog import ComposeDialog
    acc = EmailAccount({'email': 'a@qq.com', 'password': 'x',
                        'imap_host': 'imap.qq.com', 'smtp_host': 'smtp.qq.com'})
    cd = ComposeDialog(acc)
    print('[OK] ComposeDialog instantiate')

    # apply_reply_preset
    cd.apply_reply_preset({'to': 'a@b.com', 'subject': 'Re: hi', 'body': 'reply'})
    assert cd.to_edit.text() == 'a@b.com'
    print('[OK] ComposeDialog apply_reply_preset')

    # OperationWorker
    from pages.email.email_workers import OperationWorker, FetchFoldersWorker, FetchHeadersWorker, FetchMessageWorker, SendMailWorker, TestAccountWorker
    for cls in (OperationWorker, FetchFoldersWorker, FetchHeadersWorker, FetchMessageWorker, SendMailWorker, TestAccountWorker):
        assert cls is not None
    opw = OperationWorker(acc, 'mark_seen', folder='INBOX', uid='1', seen=True)
    opw2 = OperationWorker(acc, 'delete', folder='INBOX', uid='1')
    assert opw.op == 'mark_seen' and opw2.op == 'delete'
    print('[OK] OperationWorker + all workers instantiate')

    # ---------- 主窗口导航项 ----------
    import ui.main_window as mw
    win = mw.Window()
    win.resize(1080, 780)
    app.processEvents()
    assert '邮箱' in win._nav_items, 'email nav item missing'
    assert hasattr(win, 'emailPage')
    print('[OK] Window has 邮箱 nav item + emailPage')
    print('navigable nav keys:', '邮箱' in win._nav_items)

    print('EMAIL SMOKE RESULT: ALL PASSED')
    sys.exit(0)
except Exception:
    traceback.print_exc()
    print('EMAIL SMOKE RESULT: FAILED')
    sys.exit(1)