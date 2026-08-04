# -*- coding: utf-8 -*-
"""
统一资源路径管理
================
所有资源文件的路径集中在此处定义，方便统一修改。
每个路径都标注了**使用位置**，便于追踪。

用法::

    from core.resource_paths import LOGO_ICON, LOGO_USER_ICON2
    icon = QIcon(LOGO_ICON)

※ 所有路径基于项目根目录计算，不依赖当前工作目录。
"""
import os

# ─────────────────────────────────────────────
# 项目根目录
# ─────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _res(*parts):
    """拼接 resources 下的资源路径"""
    return os.path.normpath(os.path.join(PROJECT_ROOT, 'resources', *parts))


def _img(*parts):
    """拼接 resources/images 下的资源路径"""
    return _res('images', *parts)


# ═══════════════════════════════════════════
#  登录窗口 (ui/login_window.py)
# ═══════════════════════════════════════════
LOGIN_BACKGROUND = _img('background', 'background.jpg')          # 登录窗口左侧大背景图
LOGIN_LOGO = _img('logo', 'logo2.png')                            # 登录窗口标题栏图标
LOGIN_USER_ICON3 = _img('logo', 'user_icon3.png')                 # 注册页默认头像
LOGIN_SPLASH_BG = _img('background', 'background-3-4.png')        # 登录成功过渡动画背景图
LOGIN_RESIZE_BG = _img('background', 'background-3-5.png')        # 登录窗口 resizeEvent 时重置背景

# ═══════════════════════════════════════════
#  主窗口导航 (ui/main_window.py)
# ═══════════════════════════════════════════
MAIN_LOGO = _img('logo', 'logo2.png')                             # 主窗口标题栏图标 / 窗口图标
MAIN_ABOUT_AVATAR = _img('logo', 'user_icon2.png')                # 主窗口「关于我」导航头像
NAV_DOUYIN = _img('logo', 'StreamlinePlumpColorTiktok.png')       # 视频 → 抖音导航图标
NAV_TWITTER = _img('logo', 'LogosTwitter.png')                    # 视频 → 推特(X) 导航图标
NAV_XVIDEO = _img('logo', 'XvideosLogo.png')                      # 视频 → Xvideo 导航图标
NAV_PIXIV = _img('logo', 'Fa6BrandsPixiv.png')                    # 视频 → Pixiv 导航图标
NAV_YOUTUBE = _img('logo', 'LogosYoutube.png')                    # 视频 → YouTube 导航图标
NAV_BILIBILI = _img('logo', 'StreamlineUltimateBilibiliLogoBold.png')  # 视频 → 哔哩哔哩 导航图标
NAV_PEOPLE_LEVEL = _img('logo', 'zs_common_level.png')            # 人物页面等级图标
MAIN_GLASS_BG = _img('background', 'background-2-2.jpg')          # 主窗口全局磨砂背景层

# ═══════════════════════════════════════════
#  首页 (pages/home_page.py)
# ═══════════════════════════════════════════
HOME_ACHIEVEMENT_149 = _img('logo', 'achievement_icon149.png')    # 首页「成就卡片 1」图标
HOME_ACHIEVEMENT_150 = _img('logo', 'achievement_icon150.png')    # 首页「成就卡片 2」图标
HOME_ACHIEVEMENT_244 = _img('logo', 'achievement_icon244.png')    # 首页「成就卡片 3」图标
HOME_ACHIEVEMENT_245 = _img('logo', 'achievement_icon245.png')    # 首页「成就卡片 4」图标
HOME_BANNER = _img('photos', 'images', 'header1.png')             # 首页顶部 Banner 横幅图
HOME_DOWN_BTN = _img('photos', 'images', 'MJ119_btm.png')         # 首页「下载」装饰按钮图
HOME_GIF_1 = _img('photos', 'gif', '1635502638.gif')              # 首页 GIF 轮播图 1
HOME_GIF_FOLDER = _img('photos', 'images', 'HOME')                # 首页轮播图文件夹（内含 01.jpg ~ 34.jpg）

# ═══════════════════════════════════════════
#  关于我 (pages/about_page.py)
# ═══════════════════════════════════════════
ABOUT_DEFAULT_AVATAR = _img('logo', 'user_icon3.png')             # 「关于我」页面默认头像

# ═══════════════════════════════════════════
#  仪表盘 (pages/dashboard_page.py)
# ═══════════════════════════════════════════
DASHBOARD_DEFAULT_AVATAR = _img('logo', 'user_icon3.png')         # 「仪表盘」用户列表默认头像

# ═══════════════════════════════════════════
#  视频 → 多平台 (pages/video/video_multiplatform_page.py)
# ═══════════════════════════════════════════
VIDEO_DOUYIN_ICON = _img('logo', 'StreamlinePlumpColorTiktok.png')  # 视频主页 抖音 平台卡片图标
VIDEO_TWITTER_ICON = _img('logo', 'LogosTwitter.png')               # 视频主页 推特(X) 平台卡片图标
VIDEO_BILIBILI_ICON = _img('logo', 'StreamlineUltimateBilibiliLogoBold.png')  # 视频主页 哔哩哔哩 平台卡片图标
VIDEO_XVIDEO_ICON = _img('logo', 'XvideosLogo.png')                 # 视频主页 Xvideo 平台卡片图标
VIDEO_PIXIV_ICON = _img('logo', 'Fa6BrandsPixiv.png')               # 视频主页 Pixiv 平台卡片图标
VIDEO_YOUTUBE_ICON = _img('logo', 'LogosYoutube.png')               # 视频主页 YouTube 平台卡片图标
VIDEO_LOGO = _img('logo', 'logo2.png')                              # 视频页面应用图标

# ═══════════════════════════════════════════
#  视频 → 单平台 (pages/video/video_page.py)
# ═══════════════════════════════════════════
VIDEO_PAGE_DOUYIN = _img('logo', 'StreamlinePlumpColorTiktok.png')  # 旧单平台视频页 抖音 图标
VIDEO_PAGE_TWITTER = _img('logo', 'LogosTwitter.png')               # 旧单平台视频页 推特(X) 图标
VIDEO_PAGE_BILIBILI = _img('logo', 'StreamlineUltimateBilibiliLogoBold.png')  # 旧单平台视频页 哔哩哔哩 图标
VIDEO_PAGE_APP_ICON = _img('logo', 'logo2.png')                     # 旧单平台视频页 应用图标

# ═══════════════════════════════════════════
#  音乐播放器 (pages/music/music_player_ui.py)
# ═══════════════════════════════════════════
MUSIC_PLAYER_BG = _img('background', 'music_list1.png')            # 音乐播放器页面背景图
