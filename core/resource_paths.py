# -*- coding: utf-8 -*-
"""
统一资源路径管理
================
所有资源文件的路径集中在此处定义，方便统一修改。
每个路径都标注了**使用位置**，便于追踪。

用法::

    from core.resource_paths import APP_ICON
    app.setWindowIcon(QIcon(APP_ICON))

※ 所有路径基于**只读资源根目录**计算（冻结后即 PyInstaller 的 _internal），
  不依赖当前工作目录，也不依赖 exe 所在目录 —— 见 core/paths.py。
※ 新增资源后请跑 ``scripts/smoke_settings_paths.py``：它会校验这里的每个常量
  都指向真实存在的文件（曾出现常量指向已删除图片、界面空白却没人发现）。
"""
import os

from core import paths as _paths

# ─────────────────────────────────────────────
# 只读资源根目录
#   · 源码运行：项目根目录
#   · 冻结运行：sys._MEIPASS（onedir 下为 <安装目录>/_internal）
#     ⚠️ 不能用 exe 所在目录：PyInstaller 6.x 把随包数据放进 _internal/
# ─────────────────────────────────────────────
PROJECT_ROOT = str(_paths.resource_root())


def _res(*parts):
    """拼接 resources 下的资源路径"""
    return os.path.normpath(os.path.join(PROJECT_ROOT, 'resources', *parts))


def _img(*parts):
    """拼接 resources/images 下的资源路径"""
    return _res('images', *parts)


# ═══════════════════════════════════════════
#  ★ 应用图标（全程序唯一的一份）
# ═══════════════════════════════════════════
# 这张图同时决定了三个地方的图标，必须是同一张，否则会出现
# "资源管理器里是 A、任务栏里是 B、标题栏里是 C"的错乱：
#   ① exe 文件图标  —— 打包时 build_exe.make_icon() 由**同一个文件**生成多尺寸
#                      icon.ico，PyInstaller 嵌进 OGC.exe；安装器 SetupIconFile、
#                      开始菜单/桌面快捷方式、卸载器显示图标都取自它；
#   ② 任务栏 / Alt+Tab —— main.py 里 app.setWindowIcon(QIcon(APP_ICON))；
#   ③ 窗口标题栏      —— 登录/主窗口显式 setWindowIcon（见下方 LOGIN_LOGO/MAIN_LOGO）。
# ⚠️ 换图标只需替换这一个 PNG 文件，改完必须**重新打包**（icon.ico 是构建期生成的，
#    不重建的话 exe 文件图标还是旧的，而任务栏图标会立刻变 —— 两边不一致）。
APP_ICON = _img('logo', 'icon.png')


# ═══════════════════════════════════════════
#  登录窗口 (ui/login_window.py)
# ═══════════════════════════════════════════
LOGIN_BACKGROUND = _img('background', 'background.jpg')          # 登录窗口左侧大背景图
# 登录/主窗口标题栏图标统一用 APP_ICON（= logo/icon.png）。
# 注意 logo/logo.png 与它是**同一张图**（字节完全相同），只是 logo.png 还被
# 登录界面的 Qt 资源 :/images/logo.png 用着（见 resources/resource.qrc），
# 所以两个文件都保留；应用图标一律以 APP_ICON 为准。
LOGIN_LOGO = APP_ICON                                            # 登录窗口标题栏图标
LOGIN_USER_ICON3 = _img('logo', 'user_icon3.png')                 # 注册页默认头像
LOGIN_SPLASH_BG = _img('background', 'background-3-4.png')        # 登录成功过渡动画背景图
LOGIN_RESIZE_BG = _img('background', 'background-3-5.png')        # 登录窗口 resizeEvent 时重置背景

# ═══════════════════════════════════════════
#  主窗口导航 (ui/main_window.py)
# ═══════════════════════════════════════════
MAIN_LOGO = APP_ICON                                             # 主窗口标题栏图标 / 窗口图标
MAIN_ABOUT_AVATAR = _img('logo', 'user_icon2.png')                # 主窗口「关于我」导航头像
NAV_DOUYIN = _img('logo', 'StreamlinePlumpColorTiktok.png')       # 视频 → 抖音导航图标
NAV_TWITTER = _img('logo', 'LogosTwitter.png')                    # 视频 → 推特(X) 导航图标
NAV_XVIDEO = _img('logo', 'XvideosLogo.png')                      # 视频 → Xvideo 导航图标
NAV_PIXIV = _img('logo', 'Fa6BrandsPixiv.png')                    # 视频 → Pixiv 导航图标
NAV_YOUTUBE = _img('logo', 'LogosYoutube.png')                    # 视频 → YouTube 导航图标
NAV_BILIBILI = _img('logo', 'StreamlineUltimateBilibiliLogoBold.png')  # 视频 → 哔哩哔哩 导航图标
NAV_PEOPLE_LEVEL = _img('logo', 'user_icon.png')                  # 人物页面等级图标
NAV_EHENTAI = _img('logo', 'EhViewer.png')            # 人物页面等级图标
NAV_JMCOMIC = _img('logo', 'LogoJM.png')            # 人物页面等级图标
MAIN_GLASS_BG = _img('background', 'background-2-2.jpg')          # 主窗口全局磨砂背景层

# ═══════════════════════════════════════════
#  首页 (pages/home_page.py)
# ═══════════════════════════════════════════
# 首页曾经用下面这些素材，但它们要么早已不在仓库里（photos/gif、MJ119_btm.png），
# 要么只被注释引用；2026-09 清理时确认首页代码**完全不引用**它们，
# 于是连同 resources/images/photos/ 一起删掉了（省下约 1.9 MB 安装体积）。
# 如果以后要给首页加回 Banner/轮播，把素材放进 resources/images/ 后
# 在这里加常量即可 —— scripts/smoke_settings_paths.py 会校验常量指向的文件
# 必须真实存在，不会再出现"引用了不存在的图、界面空白却没人发现"。

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
VIDEO_LOGO = APP_ICON                                              # 视频页面应用图标

# ═══════════════════════════════════════════
#  视频 → 单平台 (pages/video/video_page.py)
# ═══════════════════════════════════════════
VIDEO_PAGE_DOUYIN = _img('logo', 'StreamlinePlumpColorTiktok.png')  # 旧单平台视频页 抖音 图标
VIDEO_PAGE_TWITTER = _img('logo', 'LogosTwitter.png')               # 旧单平台视频页 推特(X) 图标
VIDEO_PAGE_BILIBILI = _img('logo', 'StreamlineUltimateBilibiliLogoBold.png')  # 旧单平台视频页 哔哩哔哩 图标
VIDEO_PAGE_APP_ICON = APP_ICON                                     # 旧单平台视频页 应用图标

# ═══════════════════════════════════════════
#  音乐播放器 (pages/music/music_player_ui.py)
# ═══════════════════════════════════════════
MUSIC_PLAYER_BG = _img('background', 'background-3.jpg')           # 音乐播放器页面背景图
