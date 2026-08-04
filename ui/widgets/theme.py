# -*- coding: utf-8 -*-
"""
主题辅助工具：根据深浅色主题自动切换颜色
支持监听主题切换信号，自动重新应用样式
"""
from qfluentwidgets import isDarkTheme


def theme_color(light: str, dark: str) -> str:
    """根据当前主题返回颜色 (light=浅色主题, dark=深色主题)"""
    return dark if isDarkTheme() else light


def text_primary() -> str:
    """主要文字色"""
    return theme_color('#333333', '#E0E0E0')


def text_secondary() -> str:
    """次要文字色"""
    return theme_color('#606060', '#AAAAAA')


def text_tertiary() -> str:
    """弱提示文字色"""
    return theme_color('#909399', '#8A8A8A')


def text_placeholder() -> str:
    """占位提示文字"""
    return theme_color('#AAAAAA', '#666666')


def text_link() -> str:
    """链接色"""
    return theme_color('#0078D4', '#4FC3F7')


def text_accent() -> str:
    """强调色"""
    return theme_color('#28AFE9', '#4FC3F7')


def card_bg() -> str:
    """卡片背景色"""
    return theme_color('rgba(255,255,255,0.92)', 'rgba(35,35,37,0.92)')


def card_border() -> str:
    """卡片边框色"""
    return theme_color('rgba(0,0,0,0.08)', 'rgba(255,255,255,0.12)')


def panel_bg() -> str:
    """面板/内容背景（浅色/深色均保持半透明）"""
    return theme_color('rgba(255,255,255,0.85)', 'rgba(40,40,42,0.85)')


# ═══════════════════════════════════════
#  主题切换监听
# ═══════════════════════════════════════
_theme_callbacks = []


def on_theme_changed(callback):
    """注册主题切换回调，主题变化时自动调用

    用法::

        from ui.widgets.theme import on_theme_changed

        def _apply_style(self):
            self.label.setStyleSheet(f"color: {text_primary()};")

        on_theme_changed(self._apply_style)
    """
    if callback not in _theme_callbacks:
        _theme_callbacks.append(callback)


def _notify_theme_changed():
    """通知所有注册的回调主题已变化"""
    for cb in list(_theme_callbacks):
        try:
            cb()
        except Exception:
            pass


_theme_connected = False


def ensure_theme_connected():
    """确保配置文件变更信号已连接到通知函数（幂等）"""
    global _theme_connected
    if _theme_connected:
        return
    _theme_connected = True
    try:
        from ui.widgets.common import cfg
        cfg.themeChanged.connect(_notify_theme_changed)
    except Exception:
        pass