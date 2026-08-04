# -*- coding: utf-8 -*-
"""
全局 UI 提示工具
================
统一的悬停提示（Flyout）与操作反馈封装：

    - install_hover_tip(widget, title, content, icon)
        给任意控件（按钮/开关/卡片等）安装「鼠标悬停显示功能简介，
        移开鼠标自动消失」的 Flyout 提示。

    - show_flyout(icon, title, content, target, parent)
        在指定控件附近弹出一个可关闭的 Flyout 提示（操作中/成功/失败反馈）。

    - show_success / show_info / show_warning / show_error
        常用反馈快捷方式（内部基于 show_flyout）。

用法 ::

    from ui.widgets.ui_utils import install_hover_tip, show_warning

    install_hover_tip(self.login_btn, '登录', '输入账号密码后点击登录')
    show_warning('操作失败', '请检查网络连接', self.search_btn, self)
"""
from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QWidget

from qfluentwidgets import Flyout, InfoBarIcon, FlyoutAnimationType


class HoverFlyoutFilter(QObject):
    """鼠标悬停控件时显示 Flyout，移开鼠标自动消失"""

    def __init__(self, widget: QWidget, title: str, content: str,
                 icon=InfoBarIcon.SUCCESS, parent=None):
        super().__init__(parent)
        self._widget = widget
        self._title = title
        self._content = content
        self._icon = icon
        self._flyout = None
        widget.installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is self._widget:
            if e.type() == QEvent.Enter:
                self._show()
            elif e.type() == QEvent.Leave:
                self._hide()
        return super().eventFilter(obj, e)

    def _show(self):
        """显示 Flyout"""
        if self._flyout is not None:
            return
        try:
            self._flyout = Flyout.create(
                icon=self._icon,
                title=self._title,
                content=self._content,
                target=self._widget,
                parent=self._widget.window() or self._widget,
                isClosable=False,
                aniType=FlyoutAnimationType.FADE_IN,
            )
            self._flyout.closed.connect(self._on_closed)
        except Exception:
            self._flyout = None

    def _hide(self):
        """关闭 Flyout（淡出后销毁）"""
        if self._flyout is not None:
            f = self._flyout
            self._flyout = None
            try:
                f.fadeOut()
            except Exception:
                try:
                    f.close()
                except Exception:
                    pass

    def _on_closed(self):
        self._flyout = None


def install_hover_tip(widget: QWidget, title: str, content: str,
                      icon=InfoBarIcon.SUCCESS):
    """给控件安装「悬停显示简介、移开自动消失」的提示

    Parameters
    ----------
    widget : QWidget
        目标控件（按钮 / 开关 / 卡片等）
    title : str
        Flyout 标题
    content : str
        Flyout 内容（功能简介）
    icon : InfoBarIcon
        图标（INFORMATION / SUCCESS / WARNING / ERROR）
    """
    return HoverFlyoutFilter(widget, title, content, icon)


# ---------- 通用 Flyout 提示 ----------
def show_flyout(icon, title: str, content: str, target: QWidget, parent: QWidget):
    """在目标控件附近弹出一个可关闭的 Flyout 提示"""
    Flyout.create(
        icon=icon,
        title=title,
        content=content,
        target=target,
        parent=parent,
        isClosable=True,
        aniType=FlyoutAnimationType.PULL_UP,
    )


def show_success(title: str, content: str, target: QWidget, parent: QWidget):
    """成功反馈"""
    show_flyout(InfoBarIcon.SUCCESS, title, content, target, parent)


def show_info(title: str, content: str, target: QWidget, parent: QWidget):
    """信息提示（含“执行中”类提示）"""
    show_flyout(InfoBarIcon.INFORMATION, title, content, target, parent)


def show_warning(title: str, content: str, target: QWidget, parent: QWidget):
    """警告提示"""
    show_flyout(InfoBarIcon.WARNING, title, content, target, parent)


def show_error(title: str, content: str, target: QWidget, parent: QWidget):
    """错误提示"""
    show_flyout(InfoBarIcon.ERROR, title, content, target, parent)


# 兼容别名
success_flyout = show_success
info_flyout = show_info
warning_flyout = show_warning
error_flyout = show_error

