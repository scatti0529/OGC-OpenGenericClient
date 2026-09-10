# -*- coding: utf-8 -*-
"""
自动登录（多账号本机存储）工具
==============================
集中管理「设置→自动登录」的账号列表、选中账号与开关状态，
并负责启动时的自动登录校验。

存储位置：data/config.json（core.config.CFG），键：
- auto_login_enabled  : bool  是否开启自动登录
- auto_login_selected : str   当前选中的账号名
- auto_login_accounts : list  [{username, password}, ...]
"""
from core.config import config as CFG
from core.database import verify_login


def is_enabled() -> bool:
    return bool(CFG.get('auto_login_enabled', False))


def set_enabled(value: bool):
    CFG['auto_login_enabled'] = bool(value)


def get_accounts() -> list:
    """返回账号列表（dict 拷贝）。"""
    return list(CFG.get('auto_login_accounts', []) or [])


def get_selected() -> str:
    return str(CFG.get('auto_login_selected', '') or '')


def set_selected(username: str):
    CFG['auto_login_selected'] = username or ''


def find_account(username: str):
    """按账号名查找账号（返回 dict 拷贝或 None）。"""
    username = (username or '').strip()
    for acc in get_accounts():
        if str(acc.get('username', '')).strip() == username:
            return dict(acc)
    return None


def get_selected_account():
    """返回选中账号（dict 或 None）；若无选中则返回空。"""
    sel = get_selected()
    if not sel:
        return None
    return find_account(sel)


def upsert_account(username: str, password: str) -> bool:
    """新增或更新一个账号。成功返回 True。"""
    username = (username or '').strip()
    if not username:
        return False
    accounts = get_accounts()
    for acc in accounts:
        if str(acc.get('username', '')).strip() == username:
            acc['password'] = password  # 更新密码
            CFG['auto_login_accounts'] = accounts
            return True
    accounts.append({'username': username, 'password': password})
    CFG['auto_login_accounts'] = accounts
    return True


def remove_account(username: str) -> bool:
    """删除一个账号。若删除的是选中账号，则清空选中。返回是否发生删除。"""
    username = (username or '').strip()
    accounts = get_accounts()
    new = [a for a in accounts if str(a.get('username', '')).strip() != username]
    if len(new) == len(accounts):
        return False
    CFG['auto_login_accounts'] = new
    if get_selected() == username:
        set_selected('')
    return True


def try_auto_login():
    """启动时的自动登录。

    若未开启或未配置选中账号，返回 (False, 原因)。
    否则用选中账号尝试 verify_login：
      - 成功：返回 (True, 'ok')
      - 失败：回退登录页，返回 (False, 失败消息)
    """
    if not is_enabled():
        return False, 'auto_login_disabled'
    acc = get_selected_account()
    if not acc:
        return False, 'no_selected_account'
    username = acc['username']
    password = acc['password']
    ok, msg = verify_login(username, password)
    if ok:
        return True, 'ok'
    return False, msg
