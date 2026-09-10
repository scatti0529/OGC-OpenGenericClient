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


# ═══════════════════════════════════════
#  设计 token：品牌色 / 圆角 / 字体
#  集中定义视觉规范，避免各处硬编码，保证界面统一
# ═══════════════════════════════════════
BRAND_PRIMARY = '#28AFE9'          # 品牌主色（与 setThemeColor 保持一致）
BRAND_PRIMARY_DEEP = '#0E8CC0'     # 品牌深色（浅色主题 hover / 强调）
BRAND_LIGHT = '#4FC3F7'            # 品牌浅色（深色主题强调 / 链接）


def brand_primary() -> str:
    """品牌主色"""
    return BRAND_PRIMARY


def brand_primary_deep() -> str:
    """品牌强调色（浅色主题使用更深变体保证对比度）"""
    return theme_color(BRAND_PRIMARY_DEEP, BRAND_LIGHT)


def radius_card() -> str:
    """卡片标准圆角"""
    return '10px'


def radius_lg() -> str:
    """大圆角（卡片/面板）"""
    return '14px'


def font_display() -> str:
    """展示型字体（标题 / 数字，字重更重）"""
    return "'Segoe UI Semibold', 'Microsoft YaHei Semibold', 'PingFang SC'"


def font_body() -> str:
    """正文字体"""
    return "'Segoe UI', 'Microsoft YaHei', 'PingFang SC'"


def font_ui() -> str:
    """界面/数据字体"""
    return "'Segoe UI', 'Microsoft YaHei', 'PingFang SC'"


def card_bg() -> str:
    """卡片背景色（冷蓝玻璃调，与全局磨砂背景一致）"""
    return theme_color('rgba(250,252,254,0.92)', 'rgba(34,40,50,0.92)')


def card_border() -> str:
    """卡片边框色（冷色系细边框）"""
    return theme_color('rgba(40,90,130,0.14)', 'rgba(180,210,235,0.16)')


def panel_bg() -> str:
    """面板/内容背景（浅色玻璃白 / 深色冷蓝黑）"""
    return theme_color('rgba(250,252,254,0.85)', 'rgba(34,40,50,0.85)')


def card_hover_border() -> str:
    """卡片悬停边框——品牌蓝光晕（签名式交互识别）"""
    return theme_color('rgba(40,175,233,0.55)', 'rgba(79,195,247,0.50)')


def card_hover_bg() -> str:
    """卡片悬停背景微光"""
    return theme_color('rgba(40,175,233,0.08)', 'rgba(79,195,247,0.10)')


def divider_color() -> str:
    """分隔线/细边框色"""
    return theme_color('rgba(0,0,0,0.06)', 'rgba(255,255,255,0.08)')


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