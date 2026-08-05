# coding:utf-8
import os
import sys
import logging
from datetime import datetime
from PyQt5.QtCore import Qt, QUrl, QLocale, QTranslator, QSize, QEventLoop, QTimer
from PyQt5.QtGui import QIcon, QDesktopServices
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout
from qframelesswindow import FramelessWindow, StandardTitleBar
from qfluentwidgets import (NavigationItemPosition, MessageBox, setTheme, Theme,
                            SplitFluentWindow, NavigationAvatarWidget, SubtitleLabel,
                            setFont, qconfig, FluentTranslator, NavigationWidget,
                            NavigationSeparator, NavigationToolButton, NavigationDisplayMode,
                            NavigationTreeWidget, NavigationPushButton, NavigationItemHeader,
                            NavigationUserCard)
from qfluentwidgets import SplashScreen
from qfluentwidgets import FluentIcon as FIF
from pathlib import Path
import json

# ─────────────── 日志系统 + 配置 ───────────────
from core.logger import logger
from core.config import config as CFG

# ─────────────── 全局玻璃效果 ───────────────
from ui.widgets.glass_effect import glass_manager, FrostedPanel

# ───────────────  引入真正的设置界面  ───────────────
from pages.settings_page import SettingInterface, cfg, signalBus
from pages.about_page import AboutMeInterface
from pages.home_page import Home
from pages.jmcomic_page import JmComicPage
from pages.video.video_multiplatform_page import MultiPlatformVideoInterface, PlatformPage
from pages.video.pixiv_page_ui import PixivPage
from pages.video.douyin_page import DouyinPage
from pages.music.music_page import MusicInterface
from pages.dashboard_page import DashboardInterface

# ─────────────── 权限管理 ───────────────
from core.database import is_admin, get_user_permissions

# ---------- 资源路径（统一资源路径管理）----------
from core.resource_paths import (
    MAIN_LOGO as icon,
    MAIN_ABOUT_AVATAR as user_icon,
    NAV_DOUYIN as douyin_icon,
    NAV_TWITTER as X_icon,
    NAV_XVIDEO as Xvideo_icon,
    NAV_PIXIV as Pixiv_icon,
    NAV_YOUTUBE as Youtube_icon,
    NAV_BILIBILI as bili_icon,
    NAV_PEOPLE_LEVEL as people_icon,
    MAIN_GLASS_BG,
)
from ui.widgets.theme import ensure_theme_connected, on_theme_changed

class Widget(QFrame):
    """占位子界面（除设置外）"""
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.label = SubtitleLabel(text, self)
        self.hBoxLayout = QHBoxLayout(self)
        setFont(self.label, 24)
        self.label.setAlignment(Qt.AlignCenter)
        self.hBoxLayout.addWidget(self.label, 1, Qt.AlignCenter)
        self.setObjectName(text.replace(' ', '-'))
        self.hBoxLayout.setContentsMargins(0, 32, 0, 0)


class Window(SplitFluentWindow):
    def __init__(self):
        super().__init__()
        self.initWindow()
        self._current_username = None
        self._nav_items = {}  # routeKey -> NavigationTreeWidget

        # 1. 创建子界面
        self.homeInterface       = Home(self)
        self.homeInterface.setObjectName("首页")  # 添加这一行
        
        self.musicInterface      = MusicInterface(self)
        self.musicInterface.setObjectName("音乐")  # 添加这一行
        # ★★★ 多平台视频解析页面（主页 + 六大平台子模块） ★★★
        self.videoInterface      = MultiPlatformVideoInterface(self)
        self.videoInterface.setObjectName("视频")  # 添加这一行
        # 创建六个平台子模块页面
        self.videoPage_douyin    = DouyinPage(self)
        self.videoPage_douyin.setObjectName("抖音")
        self.videoPage_bilibili  = PlatformPage('bilibili', '哔哩哔哩', self)
        self.videoPage_bilibili.setObjectName("哔哩哔哩")
        self.videoPage_twitter   = PlatformPage('twitter', '推特(X)', self)
        self.videoPage_twitter.setObjectName("推特")
        self.videoPage_pixiv     = PixivPage(self)
        self.videoPage_pixiv.setObjectName("Pixiv")
        self.videoPage_xvideo    = PlatformPage('xvideo', 'Xvideo', self)
        self.videoPage_xvideo.setObjectName("Xvideo")
        self.videoPage_youtube   = PlatformPage('youtube', 'YouTube', self)
        self.videoPage_youtube.setObjectName("YouTube")
        # 将子页面引用传递给视频主页，使图标按钮可以跳转
        self.videoInterface.setSubInterfaces({
            'douyin': self.videoPage_douyin,
            'bilibili': self.videoPage_bilibili,
            'twitter': self.videoPage_twitter,
            'pixiv': self.videoPage_pixiv,
            'xvideo': self.videoPage_xvideo,
            'youtube': self.videoPage_youtube,
        })

        self.PeopleInterface     = JmComicPage(self)
        self.PeopleInterface.setObjectName("人物")  # 添加这一行
        self.folderInterface     = Widget('Folder Interface', self)
        self.albumInterface      = Widget('Album Interface', self)
        self.albumInterface1     = Widget('Album 1', self)
        self.albumInterface2     = Widget('Album 2', self)
        self.albumInterface1_1   = Widget('Album 1-1', self)

        # ★★★  真正的设置界面  ★★★
        self.about_me            = AboutMeInterface()
        self.about_me.setObjectName("about_me")  # 添加这一行
        # 退出登录信号 → 返回登录界面（切换账号）
        self.about_me.logoutRequested.connect(self._logout)
        # 用户名修改信号 → 同步主窗口当前用户名
        self.about_me.usernameChanged.connect(self._on_username_changed)
        self.settingInterface    = SettingInterface(self)
        self.settingInterface.setObjectName("Settings")  # 添加这一行
        # ★★★  仪表盘（管理员专用）  ★★★
        self.dashboardInterface  = DashboardInterface(self)
        self.dashboardInterface.setObjectName("仪表盘")  # 添加这一行

        # enable acrylic effect
        self.navigationInterface.setAcrylicEnabled(True)

        self.initNavigation()
        self._applyNavigationWidth()

        # ── 全局共享磨砂背景层 ──
        # 窗口级背景面板：位于整个窗口（含导航栏/标题栏/所有页面）的最底层，
        # 配合窗口透明背景（setCustomBackgroundColor），为所有页面提供统一磨砂背景。
        # 不插入页面容器 -> 页面索引 / 返回键 / 路由完全不受影响。
        from PyQt5.QtGui import QColor as _QColor
        self.setCustomBackgroundColor(_QColor(0, 0, 0, 0), _QColor(0, 0, 0, 0))
        self.setStyleSheet('AcrylicWindow{background:transparent}')
        self._glass_bg_panel = FrostedPanel(
            self, background_img=MAIN_GLASS_BG)
        self._glass_bg_panel.setGeometry(0, 0, self.width(), self.height())
        self._glass_bg_panel.lower()
        # lower 后子控件可能被上层窗口背景遮挡，确保面板在窗口绘制之下
        self._glass_bg_panel.show()
        self._glass_bg_panel.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # 显式切换到 home.py 首页
        self.stackedWidget.setCurrentWidget(self.homeInterface, popOut=False)

        # ── 应用全局玻璃效果（透明度 / 模糊度）──
        try:
            # 从配置加载全局透明度与模糊度
            glass_manager.load(
                opacity=cfg.get(cfg.glassOpacity),
                blur_radius=cfg.get(cfg.glassBlurRadius)
            )
        except Exception as e:
            logger.error(f"加载玻璃效果配置失败: {e}")

        # 应用当前玻璃效果到主窗口（表格边框 / 卡片边框 / 页面背景）
        glass_manager.apply_to_window(self)
        # 监听玻璃效果变化，实时刷新（由设置页滑块触发）
        glass_manager.changed.connect(self._on_glass_changed)
        logger.info(
            f"主窗口玻璃效果已应用: "
            f"opacity={glass_manager.opacity} blur={glass_manager.blur_radius}"
        )

        # ── 全局主题切换自动刷新 ──
        ensure_theme_connected()
        on_theme_changed(self._on_global_theme_changed)
        # 给视频页面注册主题刷新回调
        on_theme_changed(self.videoInterface._apply_theme_style)

    # ---------------- 全局主题刷新 ----------------
    def _on_global_theme_changed(self):
        """全局主题切换后刷新主窗口组件"""
        try:
            glass_manager.apply_to_window(self)
            if hasattr(self, '_glass_bg_panel'):
                self._glass_bg_panel._on_glass_changed()
        except Exception:
            pass

    # ---------------- 玻璃效果 ----------------
    def _on_glass_changed(self):
        """全局透明度 / 模糊度变化时刷新主窗口样式"""
        glass_manager.apply_to_window(self)
        # 同步背景面板尺寸（窗口级，覆盖整个窗口）
        if hasattr(self, '_glass_bg_panel'):
            self._glass_bg_panel.setGeometry(0, 0, self.width(), self.height())

    # ---------------- 导航 ----------------
    def initNavigation(self):
        self.addSubInterface(self.homeInterface,   FIF.HOME,  '首页')
        self.addSubInterface(self.musicInterface,  FIF.MUSIC, '音乐')
        self.addSubInterface(self.videoInterface,  FIF.VIDEO, '视频')
        # 六个平台子模块（嵌套在视频父级下）
        self.addSubInterface(self.videoPage_douyin,    douyin_icon, '抖音', parent=self.videoInterface)
        self.addSubInterface(self.videoPage_bilibili,  bili_icon,   '哔哩哔哩', parent=self.videoInterface)
        self.addSubInterface(self.videoPage_twitter,   X_icon,      '推特', parent=self.videoInterface)
        self.addSubInterface(self.videoPage_pixiv,     Pixiv_icon,   'Pixiv', parent=self.videoInterface)
        self.addSubInterface(self.videoPage_xvideo,    Xvideo_icon,   'Xvideo', parent=self.videoInterface)
        self.addSubInterface(self.videoPage_youtube,   Youtube_icon,    'YouTube', parent=self.videoInterface)
        # 视频父项：点击只展开/收起子模块，不切换页面
        # clicked 信号连接了 [0] panel._onWidgetClicked（展开/收缩 + flyout）
        # 和 [1] addSubInterface 传入的 switchTo（页面切换）。
        # 方案：断开全部后，仅重新连接 _onWidgetClicked，保留 flyout 子菜单
        # 与展开/收缩逻辑，且不连接 switchTo → 点击不切换页面
        video_nav = self._nav_items.get('视频')
        if video_nav is not None and hasattr(video_nav, 'itemWidget'):
            video_nav.itemWidget.isSelectable = False
            try:
                video_nav.clicked.disconnect()
            except Exception:
                pass
            # 重新连接框架内部的 _onWidgetClicked（支持收缩模式 flyout 子菜单）
            panel = self.navigationInterface.panel
            if hasattr(panel, '_onWidgetClicked'):
                video_nav.clicked.connect(panel._onWidgetClicked)
        self.addSubInterface(self.PeopleInterface,  FIF.PEOPLE, 'JMComic')
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.albumInterface,  FIF.ALBUM, 'Albums', NavigationItemPosition.SCROLL)
        self.addSubInterface(self.albumInterface1, FIF.ALBUM, 'Album 1', parent=self.albumInterface)
        self.addSubInterface(self.albumInterface1_1, FIF.ALBUM, 'Album 1.1', parent=self.albumInterface1)
        self.addSubInterface(self.albumInterface2, FIF.ALBUM, 'Album 2', parent=self.albumInterface)
        self.addSubInterface(self.folderInterface, FIF.FOLDER,'Folder library', NavigationItemPosition.SCROLL)

        # 底部头像
        '''
        self.navigationInterface.addWidget(
            routeKey='avatar',
            widget=NavigationAvatarWidget('scatti', user_icon),
            onClick=self.showMessageBox,
            position=NavigationItemPosition.BOTTOM)
        '''
        # ★★★ 设置放到最底部，仪表盘紧随其后（管理员专用，登录后显示） ★★★
        self.addSubInterface(self.about_me, user_icon, "关于我", position = NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.settingInterface, FIF.SETTING, 'Settings', NavigationItemPosition.BOTTOM)
        self._dashboard_nav_item = self.addSubInterface(
            self.dashboardInterface, FIF.HISTORY, '仪表盘', position=NavigationItemPosition.BOTTOM)
        # 初始隐藏，等 setCurrentUser 时决定是否显示
        self._dashboard_nav_item.setVisible(False)

    def addSubInterface(self, interface, icon, text, position=NavigationItemPosition.TOP,
                        parent=None, isTransparent=False):
        """加导航项后自动重新计算导航栏宽度，使其能完整显示新内容"""
        item = super().addSubInterface(interface, icon, text, position, parent, isTransparent)
        # 保存导航项引用
        if interface.objectName() not in self._nav_items:
            self._nav_items[interface.objectName()] = item
        # 内容变化后自动重新计算宽度(宽度未变时内部会直接跳过)
        self._applyNavigationWidth()
        return item

    # ---------------- 权限控制 ----------------
    def setCurrentUser(self, username: str):
        """登录后设置当前用户，传递到各界面，并根据权限控制导航栏显示"""
        self._current_username = username
        # 将用户名传递给 about_me 界面，加载用户资料
        if hasattr(self.about_me, 'loadUserProfile'):
            self.about_me.loadUserProfile(username)

        try:
            # 是否管理员 —— 仅用户名为 admin 时显示仪表盘
            is_admin_user = (username == 'admin')
            if hasattr(self, '_dashboard_nav_item'):
                self._dashboard_nav_item.setVisible(is_admin_user)

            # 根据用户权限控制各导航项显示
            perms = get_user_permissions(username)
            # 导航项 objectName -> 权限模块 key
            module_map = {
                '首页': 'home',
                '音乐': 'music',
                '视频': 'video',
                '人物': 'people',
                'about_me': 'about_me',
                'Settings': 'settings',
            }
            for route_key, mod_key in module_map.items():
                item = self._nav_items.get(route_key)
                if item is not None:
                    allowed = perms.get('modules', {}).get(mod_key, True)
                    item.setVisible(allowed)

            # 六个视频平台子模块根据功能权限显示/隐藏
            # 注意：不能直接对树形子项 setVisible（会破坏布局导致重叠），
            # 必须通过 removeInterface 正确从导航树中移除
            features = perms.get('features', {})
            video_sub_map = {
                'douyin': ('抖音', 'video_douyin'),
                'bilibili': ('哔哩哔哩', 'video_bilibili'),
                'twitter': ('推特', 'video_twitter'),
                'pixiv': ('Pixiv', 'video_pixiv'),
                'xvideo': ('Xvideo', 'video_xvideo'),
                'youtube': ('YouTube', 'video_youtube'),
            }
            # 记录已移除的子模块，供后续按需移除
            if not hasattr(self, '_removed_video_subs'):
                self._removed_video_subs = set()

            allowed_platforms = set()
            for sub_key, (sub_name, feat_key) in video_sub_map.items():
                allowed = features.get(feat_key, True)
                if not allowed and sub_key not in self._removed_video_subs:
                    # 禁用：正确移除子模块
                    sub_interface = getattr(self, f'videoPage_{sub_key}', None)
                    if sub_interface is not None:
                        self.removeInterface(sub_interface, isDelete=False)
                        self._removed_video_subs.add(sub_key)
                        # 清理导航项引用，避免再操作已移除项
                        self._nav_items.pop(sub_name, None)
                if allowed:
                    allowed_platforms.add(sub_key)

            # 同步隐藏视频主页上被禁用的平台图标卡片
            video_ui = getattr(self, 'videoInterface', None)
            if video_ui is not None and hasattr(video_ui, 'setAllowedPlatforms'):
                video_ui.setAllowedPlatforms(allowed_platforms)

            # JMComic 功能权限（people 模块下的子功能）
            jmcomic_features = {
                'jmcomic_search': 'search_tab',
                'jmcomic_download': 'download_tab',
                'jmcomic_account': 'account_tab',
                'jmcomic_subscribe': 'subscribe_tab',
            }
            people_ui = getattr(self, 'PeopleInterface', None)
            if people_ui is not None:
                for feat_key, tab_attr in jmcomic_features.items():
                    allowed = features.get(feat_key, True)
                    tab = getattr(people_ui, tab_attr, None)
                    if tab is not None:
                        tab.setVisible(allowed)

            # ══ 功能级权限控制 ══
            self._apply_feature_permissions(features)

            # 刷新导航栏宽度
            self._applyNavigationWidth()
        except Exception as e:
            logger.error(f"应用用户权限失败: {e}")

    # ---------------- 功能级权限 ----------------
    def _apply_feature_permissions(self, features: dict):
        """根据功能权限控制各页面内的具体功能按钮"""
        try:
            # ── 音乐页面功能 ──
            music_ui = getattr(self, 'musicInterface', None)
            if music_ui is not None:
                # 搜索功能
                search_ok = features.get('music_search', True)
                if hasattr(music_ui, 'searchInterface'):
                    si = music_ui.searchInterface
                    # 搜索输入框/搜索按钮
                    for attr in ('search_input', 'search_btn'):
                        w = getattr(si, attr, None)
                        if w is not None:
                            w.setEnabled(search_ok)

                # 歌单解析功能
                playlist_ok = features.get('music_playlist', True)
                if hasattr(music_ui, 'playlistInterface'):
                    pi = music_ui.playlistInterface
                    for attr in ('url_input', 'parse_btn', 'parse_all_switch'):
                        w = getattr(pi, attr, None)
                        if w is not None:
                            w.setEnabled(playlist_ok)

                # 下载功能（搜索页下载按钮 + 歌单下载全部）
                download_ok = features.get('music_download', True)
                if hasattr(music_ui, 'searchInterface'):
                    si = music_ui.searchInterface
                    for attr in ('download_btn',):
                        w = getattr(si, attr, None)
                        if w is not None:
                            w.setEnabled(download_ok)
                if hasattr(music_ui, 'playlistInterface'):
                    pi = music_ui.playlistInterface
                    for attr in ('download_all_btn',):
                        w = getattr(pi, attr, None)
                        if w is not None:
                            w.setEnabled(download_ok)

                # 播放器功能（底部播放栏 + 播放页面 + 搜索双击播放）
                player_ok = features.get('music_player', True)
                if hasattr(music_ui, 'bottomBar'):
                    music_ui.bottomBar.setVisible(player_ok)

        except Exception as e:
            logger.error(f"应用功能权限失败: {e}")

    # ---------------- 窗口 ----------------
    def initWindow(self):
        self.resize(1080, 780)
        self.setMinimumWidth(760)
        self.setWindowIcon(QIcon(icon))
        self.setWindowTitle('OGC-OpenGenericClient')

        self.setMicaEffectEnabled(cfg.get(cfg.micaEnabled))

        # 注意：
        # 1. 不在构造时 show() / move()——窗口由登录页在过渡动画结束后
        #    显式设置位置并显示，保证与登录窗口同位置出现，避免画面突兀。
        # 2. 初始尺寸与登录窗口一致（1080x780）。
    
    def createSubInterface(self):
        """（已迁移至登录页 splash，保留空实现兼容）"""
        QApplication.processEvents()

    # ---------------- 导航栏宽度自适应 ----------------
    def _calcNavigationWidth(self) -> int:
        """根据导航栏按钮内容计算展开宽度，使内容完整显示"""
        panel = self.navigationInterface.panel
        max_w = 0
        # 遍历所有树形导航项，取适合内容的最大宽度
        for tw in panel.findChildren(NavigationTreeWidget):
            w = tw.suitableWidth()
            if w > max_w:
                max_w = w
        # 加上右侧安全边距，并限制在合理范围 [200, 420]
        return max(200, min(420, max_w + 10))

    def _applyNavigationWidth(self):
        """应用导航栏自适应宽度，并刷新所有导航项"""
        panel = self.navigationInterface.panel
        target = self._calcNavigationWidth()
        if target == getattr(self, '_nav_prev_width', 0):
            return
        self._nav_prev_width = target

        # 1. 更新展开宽度(内部同步 NavigationWidget.EXPAND_WIDTH)
        self.navigationInterface.setExpandWidth(target)

        # 2. 刷新已创建导航项的宽度
        exp_w = NavigationWidget.EXPAND_WIDTH
        for w in panel.findChildren(NavigationWidget):
            if isinstance(w, NavigationToolButton):
                continue  # 工具按钮固定 40px
            if not w.isCompacted:
                if isinstance(w, NavigationSeparator):
                    w.setFixedSize(exp_w + 10, w.height())
                else:
                    w.setFixedWidth(exp_w)

        # 3. 若当前处于展开/菜单显示模式，同步面板实际宽度
        if panel.displayMode in (NavigationDisplayMode.EXPAND, NavigationDisplayMode.MENU):
            panel.resize(target, panel.height())
            self.navigationInterface.setFixedWidth(target)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._applyNavigationWidth()
        # 同步全局磨砂背景层尺寸（窗口级，覆盖整个窗口）
        if hasattr(self, '_glass_bg_panel'):
            self._glass_bg_panel.setGeometry(0, 0, self.width(), self.height())

    # ---------------- 用户名修改 ----------------
    def _on_username_changed(self, new_username: str):
        """用户名修改后同步主窗口当前用户名"""
        try:
            old_name = self._current_username
            self._current_username = new_username
            logger.info(f"用户名已修改: {old_name} -> {new_username}")
            # 若当前登录用户正好被改名，重新应用其权限（导航项基于用户名判断管理员身份）
            # 注意：admin 不可改名（sqlit 已禁止），这里仅刷新权限显示
            if hasattr(self, '_dashboard_nav_item'):
                is_admin_user = (new_username == 'admin')
                self._dashboard_nav_item.setVisible(is_admin_user)
        except Exception as e:
            logger.error(f"同步用户名失败: {e}")

    # ---------------- 退出登录 ----------------
    def _logout(self):
        """退出登录，返回登录界面（切换账号）"""
        try:
            if hasattr(self, '_current_username'):
                logger.info(f"用户退出登录: {self._current_username}")
            # 保存当前窗口位置尺寸，供登录窗口复用
            geo = self.geometry()
            self.close()
            self.deleteLater()

            # 重新创建登录窗口并显示
            from ui.login_window import LoginWindow
            login_window = LoginWindow()
            login_window.resize(geo.width(), geo.height())
            login_window.move(geo.x(), geo.y())
            login_window.show()
            login_window.raise_()
        except Exception as e:
            logger.error(f"退出登录失败: {str(e)}", exc_info=True)
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"退出登录失败：{str(e)}")

    # ---------------- 赞赏 ----------------
    def showMessageBox(self):
        w = MessageBox(
            '支持作者🥰',
            '个人开发不易，如果这个项目帮助到了您，可以考虑请作者喝一瓶快乐水🥤。',
            self)
        w.yesButton.setText('来啦老弟')
        w.cancelButton.setText('下次一定')
        if w.exec():
            QDesktopServices.openUrl(QUrl("https://afdian.net/a/zhiyiYo"))


# =======================  入口  =======================
if __name__ == '__main__':
    # 1. 高分屏适配
    if cfg.get(cfg.dpiScale) == "Auto":
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    else:
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
        os.environ["QT_SCALE_FACTOR"] = str(cfg.get(cfg.dpiScale))
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    # 2. 应用实例
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings)

    # 3. 国际化
    locale = cfg.get(cfg.language).value
    app.installTranslator(FluentTranslator(locale))
    settingTranslator = QTranslator()
    i18n_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'resources', 'i18n')
    settingTranslator.load(locale, "settings", ".", i18n_dir)
    app.installTranslator(settingTranslator)

    # 4. 主题
    setTheme(Theme.DARK if cfg.get(cfg.themeMode) == Theme.DARK else Theme.LIGHT)

    # 5. 启动
    w = Window()
    w.show()
    sys.exit(app.exec_())