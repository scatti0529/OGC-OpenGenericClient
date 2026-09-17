# coding:utf-8
import os
from qfluentwidgets import (SettingCardGroup, SwitchSettingCard,
                            OptionsSettingCard, PushSettingCard,
                            HyperlinkCard, PrimaryPushSettingCard, ScrollArea,
                            ComboBoxSettingCard, ExpandLayout, Theme, CustomColorSettingCard,
                            setTheme, setThemeColor, RangeSettingCard, isDarkTheme,
                            SettingCard, ComboBox, SwitchButton, LineEdit, PushButton,
                            PrimaryPushButton, Dialog, BodyLabel)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import InfoBar, InfoBarPosition
from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QLabel, QFileDialog, QVBoxLayout, QHBoxLayout, QDialogButtonBox, QDialog
from ui.widgets.common import cfg, HELP_URL, FEEDBACK_URL, AUTHOR, VERSION, YEAR, isWin11
from ui.widgets.common import signalBus, log_manager, CFG
from ui.widgets.common import StyleSheet
import core.auto_login as auto_login
from ui.widgets.glass_effect import glass_manager
from ui.widgets.ui_utils import install_hover_tip
from ui.widgets.common import cfg as _cfg


class _AccountEditDialog(QDialog):
    """添加 / 编辑自动登录账号的弹窗（账号名 + 密码）。"""

    def __init__(self, title: str, parent=None, username: str = '', password: str = ''):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(360)

        self.username_edit = LineEdit(self)
        self.username_edit.setPlaceholderText('账号名')
        self.username_edit.setText(username)

        self.password_edit = LineEdit(self)
        self.password_edit.setPlaceholderText('密码')
        self.password_edit.setEchoMode(LineEdit.Password)
        self.password_edit.setText(password)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(BodyLabel('账号名', self))
        layout.addWidget(self.username_edit)
        layout.addWidget(BodyLabel('密码', self))
        layout.addWidget(self.password_edit)
        layout.addStretch(1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_accept(self):
        if not self.username_edit.text().strip():
            self.username_edit.setPlaceholderText('账号名不能为空')
            return
        if not self.password_edit.text():
            self.password_edit.setPlaceholderText('密码不能为空')
            return
        self.accept()

    def get_credentials(self):
        return self.username_edit.text().strip(), self.password_edit.text()


class SettingInterface(ScrollArea):
    """ 设置界面 - 使用 self.tr() 支持多语言切换 """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)

        # setting label
        self.settingLabel = QLabel(self.tr("设置"), self)

        # ── 下载：唯一需要用户选择的目录 + 下载行为调优 ──
        # 刻意**只有一张目录卡片**：过去这里分散着「本地音乐库 / 下载目录 /
        # 音乐缓存目录 / 音乐下载目录 / 视频下载根目录」五项，用户得同时维护
        # 好几个路径，还经常出现"音乐下到 A 盘、缓存留在 C 盘"的混乱。
        # 现在音乐缓存与下载、各平台下载、缓存目录全部从这一个根目录派生
        # （见 core.config 的 download_root / cache_path / music_*_dir），
        # 用户只需要选一次。
        self.downloadGroup = SettingCardGroup(
            self.tr('下载'), self.scrollWidget)
        self.downloadRootCard = PushSettingCard(
            self.tr('选择文件夹'),
            FIF.FOLDER,
            self.tr('下载目录'),
            CFG.download_root,
            self.downloadGroup
        )
        self.downloadModeCard = OptionsSettingCard(
            _cfg.downloadMode,
            FIF.DOWNLOAD,
            self.tr('下载模式'),
            self.tr('自动判定最优模式，失败自动切换重试'),
            texts=[
                self.tr('自动判定'), self.tr('并发分块'),
                self.tr('流式下载'), self.tr('HLS分片')
            ],
            parent=self.downloadGroup
        )
        self.downloadMaxThreadsCard = RangeSettingCard(
            _cfg.downloadMaxThreads,
            FIF.PEOPLE,
            self.tr('并发线程数'),
            self.tr('大文件并发分块下载的线程数（2-16）'),
            self.downloadGroup
        )
        self.downloadThresholdCard = RangeSettingCard(
            _cfg.downloadParallelThreshold,
            FIF.DOCUMENT,
            self.tr('并发分块阈值'),
            self.tr('超过该大小（MB）的文件启用并发分块下载（5-200 MB）'),
            self.downloadGroup
        )
        self.downloadRetryCard = RangeSettingCard(
            _cfg.downloadRetryTimes,
            FIF.SYNC,
            self.tr('重试次数'),
            self.tr('下载失败后的自动重试次数（0-10）'),
            self.downloadGroup
        )

        # personalization
        self.personalGroup = SettingCardGroup(
            self.tr('个性化'), self.scrollWidget)
        self.micaCard = SwitchSettingCard(
            FIF.TRANSPARENT,
            self.tr('云母效果'),
            self.tr('将半透明应用于窗户和表面'),
            cfg.micaEnabled,
            self.personalGroup
        )
        self.splashCard = SwitchSettingCard(
            FIF.ROBOT,
            self.tr('启动过渡动画'),
            self.tr('登录成功后显示启动过渡动画，再进入主界面'),
            cfg.splashEnabled,
            self.personalGroup
        )
        self.themeCard = OptionsSettingCard(
            cfg.themeMode,
            FIF.BRUSH,
            self.tr('应用主题'),
            self.tr("更改应用程序的外观"),
            texts=[
                self.tr('浅色'), self.tr('深色'),
                self.tr('使用系统设置')
            ],
            parent=self.personalGroup
        )
        self.themeColorCard = CustomColorSettingCard(
            cfg.themeColor,
            FIF.PALETTE,
            self.tr('主题颜色'),
            self.tr('更改应用程序的主题颜色'),
            self.personalGroup
        )
        self.zoomCard = OptionsSettingCard(
            cfg.dpiScale,
            FIF.ZOOM,
            self.tr("界面缩放"),
            self.tr("更改小部件和字体的大小"),
            texts=[
                "100%", "125%", "150%", "175%", "200%",
                self.tr("使用系统设置")
            ],
            parent=self.personalGroup
        )
        self.languageCard = ComboBoxSettingCard(
            cfg.language,
            FIF.LANGUAGE,
            self.tr('语言'),
            self.tr('设置您偏好的界面语言'),
            texts=['简体中文', '繁體中文', 'English', self.tr('使用系统设置')],
            parent=self.personalGroup
        )

        # material
        self.materialGroup = SettingCardGroup(
            self.tr('材料'), self.scrollWidget)
        self.blurRadiusCard = RangeSettingCard(
            cfg.blurRadius,
            FIF.ALBUM,
            self.tr('云母模糊半径'),
            self.tr('半径越大，图像越模糊'),
            self.materialGroup
        )

        # glass effect（全局透明度 / 模糊度）
        self.glassOpacityCard = RangeSettingCard(
            cfg.glassOpacity,
            FIF.TRANSPARENT,
            self.tr('界面透明度'),
            self.tr('数值越小越透明（不低于 150，保证文字清晰可读）'),
            self.materialGroup
        )
        self.glassBlurCard = RangeSettingCard(
            cfg.glassBlurRadius,
            FIF.ALBUM,
            self.tr('界面模糊度'),
            self.tr('数值越大磨砂效果越强（0 为不模糊）'),
            self.materialGroup
        )

        # log settings
        self.logGroup = SettingCardGroup(
            self.tr('日志设置'), self.scrollWidget)
        self.operationLogCard = PushSettingCard(
            self.tr('选择日志路径'),
            FIF.DOCUMENT,
            self.tr('操作日志路径'),
            CFG['operation_log_path'],
            self.logGroup
        )
        self.errorLogCard = PushSettingCard(
            self.tr('选择日志路径'),
            FIF.CANCEL,
            self.tr('错误日志路径'),
            CFG['error_log_path'],
            self.logGroup
        )

        # update software
        self.updateSoftwareGroup = SettingCardGroup(
            self.tr("软件更新"), self.scrollWidget)
        self.updateOnStartUpCard = SwitchSettingCard(
            FIF.UPDATE,
            self.tr('在应用程序启动时检查更新'),
            self.tr('新版本将更加稳定，并且拥有更多功能'),
            configItem=cfg.checkUpdateAtStartUp,
            parent=self.updateSoftwareGroup
        )

        # auto login（自动登录：本机多账号，跳过登录页直进主页）
        self.autoLoginGroup = SettingCardGroup(
            self.tr('自动登录'), self.scrollWidget)

        # ========= 卡片1：开机自动登录（沿用SwitchSettingCard，稳定）=========
        self.autoLoginCard = SwitchSettingCard(
            FIF.ROBOT,
            self.tr('开机自动登录'),
            self.tr('开启后跳过登录页，直接用选中账号登录并显示过渡动画'),
            configItem=None,
            parent=self.autoLoginGroup
        )
        self.autoLoginSwitch = self.autoLoginCard.switchButton
        self.autoLoginSwitch.setChecked(auto_login.is_enabled())
        self.autoLoginSwitch.checkedChanged.connect(self._on_auto_login_switch)


        # ========= 卡片2：自动登录账号，改用CardWidget，彻底解决高度塌陷 =========
        from qfluentwidgets import CardWidget, IconWidget, CaptionLabel, BodyLabel
        self.autoAccountCard = CardWidget(self.autoLoginGroup)
        self.autoAccountCard.setMinimumHeight(80)
        cardLayout = QHBoxLayout(self.autoAccountCard)
        cardLayout.setContentsMargins(20,16,20,16)
        cardLayout.setSpacing(16)

        # 左侧图标+文字
        icon = IconWidget(FIF.PEOPLE, self.autoAccountCard)
        icon.setFixedSize(24,24)
        textLayout = QVBoxLayout()
        titleLabel = BodyLabel(self.tr("自动登录账号"))
        descLabel = CaptionLabel(self.tr("选择本次登录要使用的账号"))
        textLayout.addWidget(titleLabel)
        textLayout.addWidget(descLabel)
        cardLayout.addWidget(icon)
        cardLayout.addLayout(textLayout)
        cardLayout.addStretch(1)

        # 右侧控件行
        self.autoAccountRow = QWidget()
        row = QHBoxLayout(self.autoAccountRow)
        row.setContentsMargins(0,0,0,0)
        row.setSpacing(12)
        self.autoAccountCombo = ComboBox()
        self.autoAccountCombo.setFixedWidth(220)
        self.autoAccountCombo.setMinimumHeight(32)
        self.addAccountBtn = PushButton(FIF.ADD, self.tr('添加账号'))
        self.addAccountBtn.setMinimumHeight(32)
        self.delAccountBtn = PushButton(FIF.DELETE, self.tr('删除账号'))
        self.delAccountBtn.setMinimumHeight(32)
        row.addWidget(self.autoAccountCombo)
        row.addWidget(self.addAccountBtn)
        row.addWidget(self.delAccountBtn)
        self.addAccountBtn.clicked.connect(self._on_add_account)
        self.delAccountBtn.clicked.connect(self._on_delete_account)
        cardLayout.addWidget(self.autoAccountRow)

        # 添加到分组
        self.autoLoginGroup.addSettingCard(self.autoLoginCard)
        self.autoLoginGroup.addSettingCard(self.autoAccountCard)



        # ── 维护：工作区状态 / 用户数据 / 卸载 ──
        # 卸载入口放在这里（用户明确要求"加入卸载程序代码以及按钮"）。
        # 注意：按钮是**交互式**启动卸载器，不静默执行 —— 让用户看到卸载器
        # 自己的询问（是否清理 .cache、是否删除用户数据），而不是由程序替他决定。
        self.maintenanceGroup = SettingCardGroup(self.tr('维护'), self.scrollWidget)

        self.workspaceCard = PushSettingCard(
            self.tr('打开'),
            FIF.FOLDER,
            self.tr('下载工作区'),
            self.tr('读取中…'),
            self.maintenanceGroup
        )
        self.userDataCard = PushSettingCard(
            self.tr('打开'),
            FIF.FOLDER,
            self.tr('用户数据目录'),
            self.tr('账号、配置与索引的存放位置（卸载时默认保留）'),
            self.maintenanceGroup
        )
        self.uninstallCard = PushSettingCard(
            self.tr('卸载'),
            FIF.CANCEL,
            self.tr('卸载本程序'),
            self.tr('只卸载程序本体；下载内容与工作区标记始终保留'),
            self.maintenanceGroup
        )

        # ── 工具依赖：ffmpeg 按需获取 ──
        # ffmpeg **不随包内置**（完整构建 150~170 MB，而全项目只拿它抽视频首帧当
        # 封面）。这里给三条路：自动下载 / 手动指定 / 清除重找。
        self.toolGroup = SettingCardGroup(self.tr('工具依赖'), self.scrollWidget)

        self.ffmpegCard = PushSettingCard(
            self.tr('自动下载'),
            FIF.DOWNLOAD,
            self.tr('ffmpeg（视频封面）'),
            self.tr('状态读取中…'),
            self.toolGroup
        )
        self.ffmpegPickCard = PushSettingCard(
            self.tr('选择文件…'),
            FIF.FOLDER,
            self.tr('手动指定 ffmpeg'),
            self.tr('已经装好了？直接选 ffmpeg.exe；下的是压缩包就选 .zip/.7z，会自动解压'),
            self.toolGroup
        )
        self.ffmpegClearCard = PushSettingCard(
            self.tr('清除'),
            FIF.DELETE,
            self.tr('清除 ffmpeg 绑定'),
            self.tr('清除后重新按 内置 → 环境变量 → PATH 的顺序查找'),
            self.toolGroup
        )

        # application
        self.aboutGroup = SettingCardGroup(self.tr('关于'), self.scrollWidget)
        self.helpCard = HyperlinkCard(
            HELP_URL,
            self.tr('打开帮助页面'),
            FIF.HELP,
            self.tr('帮助'),
            self.tr(
                '发现 PyQt-Fluent-Widgets 的新功能并学习实用技巧'),
            self.aboutGroup
        )
        self.feedbackCard = PrimaryPushSettingCard(
            self.tr('提供反馈'),
            FIF.FEEDBACK,
            self.tr('提供反馈'),
            self.tr('通过提供反馈帮助我们改进应用程序'),
            self.aboutGroup
        )
        self.aboutCard = PrimaryPushSettingCard(
            self.tr('检查更新'),
            FIF.INFO,
            self.tr('关于'),
            '© ' + self.tr('Copyright') + f" {YEAR}, {AUTHOR}. " +
            self.tr('版本') + " " + VERSION,
            self.aboutGroup
        )

        self.__initWidget()
        self.refresh_auto_login()

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 80, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName('settingInterface')

        # initialize style sheet
        self.scrollWidget.setObjectName('scrollWidget')
        self.settingLabel.setObjectName('settingLabel')
        StyleSheet.SETTING_INTERFACE.apply(self)

        # ========= 新增这段样式 =========
        self.setStyleSheet("""
            SettingCard {
                min-height: 64px;
            }
            QComboBox, PushButton {
                max-height:32px;
            }
        """)
        # ===============================


        self.micaCard.setEnabled(isWin11())

        # initialize layout
        self.__initLayout()
        self.__connectSignalToSlot()

    def __initLayout(self):
        self.settingLabel.move(36, 30)

        # add cards to group
        self.maintenanceGroup.addSettingCard(self.workspaceCard)
        self.maintenanceGroup.addSettingCard(self.userDataCard)
        self.maintenanceGroup.addSettingCard(self.uninstallCard)
        self.toolGroup.addSettingCard(self.ffmpegCard)
        self.toolGroup.addSettingCard(self.ffmpegPickCard)
        self.toolGroup.addSettingCard(self.ffmpegClearCard)

        self.downloadGroup.addSettingCard(self.downloadRootCard)
        self.downloadGroup.addSettingCard(self.downloadModeCard)
        self.downloadGroup.addSettingCard(self.downloadMaxThreadsCard)
        self.downloadGroup.addSettingCard(self.downloadThresholdCard)
        self.downloadGroup.addSettingCard(self.downloadRetryCard)

        self.personalGroup.addSettingCard(self.micaCard)
        self.personalGroup.addSettingCard(self.splashCard)
        self.personalGroup.addSettingCard(self.themeCard)
        self.personalGroup.addSettingCard(self.themeColorCard)
        self.personalGroup.addSettingCard(self.zoomCard)
        self.personalGroup.addSettingCard(self.languageCard)

        self.materialGroup.addSettingCard(self.blurRadiusCard)
        self.materialGroup.addSettingCard(self.glassOpacityCard)
        self.materialGroup.addSettingCard(self.glassBlurCard)

        self.logGroup.addSettingCard(self.operationLogCard)
        self.logGroup.addSettingCard(self.errorLogCard)

        self.updateSoftwareGroup.addSettingCard(self.updateOnStartUpCard)

        self.aboutGroup.addSettingCard(self.helpCard)
        self.aboutGroup.addSettingCard(self.feedbackCard)
        self.aboutGroup.addSettingCard(self.aboutCard)

        # add setting card group to layout
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 10, 36, 0)
        self.expandLayout.addWidget(self.downloadGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.materialGroup)
        self.expandLayout.addWidget(self.logGroup)
        self.expandLayout.addWidget(self.autoLoginGroup)
        self.expandLayout.addWidget(self.updateSoftwareGroup)
        self.expandLayout.addWidget(self.maintenanceGroup)
        self.expandLayout.addWidget(self.toolGroup)
        self.expandLayout.addWidget(self.aboutGroup)


    def __showRestartTooltip(self):
        """ show restart tooltip """
        InfoBar.success(
            title=self.tr('更新成功'),
            content=self.tr('配置在重启后生效'),
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=5000,
            parent=self
        )

    def __onDownloadRootCardClicked(self):
        """下载目录选择 —— 全程序**唯一**需要用户选的目录。

        各平台下载（``*-download``）、音乐下载（``music-download``）、音乐缓存
        （``.cache/music``）以及所有缩略图/画廊缓存都从这个根目录派生，
        所以改这里等于一次把"东西放哪"全部改好。
        """
        folder = QFileDialog.getExistingDirectory(self, "选择下载目录", "./")
        if not folder:
            return
        if os.path.normcase(os.path.abspath(folder)) == \
                os.path.normcase(os.path.abspath(CFG.download_root)):
            return
        CFG['video_download_root'] = folder
        self.refresh_download_root()
        # 换了下载根目录 → 工作区标记与可移植索引副本要跟着搬到新目录，
        # 否则重装后在新目录里找不到工作区、恢复不了索引。
        # 复制几 MB 索引，放后台线程，别卡住设置页。
        try:
            import threading
            from core import workspace as _ws, shell_integration as _shell

            def _resync():
                try:
                    _ws.sync_workspace()
                    _shell.register_paths()
                except Exception:
                    pass

            threading.Thread(target=_resync, daemon=True,
                             name='OGC-WorkspaceMove').start()
        except Exception:
            pass
        self.refresh_maintenance()
        # 在新目录下重建各平台子目录 + 音乐目录
        try:
            from services.download_manager import ensure_download_dirs
            ensure_download_dirs()
            InfoBar.success(
                title="下载目录已更新",
                content="已在新目录下创建各平台下载文件夹与音乐目录",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
        except Exception:
            pass

    def refresh_download_root(self):
        """刷新「下载目录」卡片：显示解析后的根目录与各类内容的落点。

        异常一律吞掉 —— 显示不出来是小事，设置页打不开是大事。
        """
        try:
            root = CFG.download_root
            try:
                music = CFG.music_download_dir
                cache = CFG.music_cache_dir
                self.downloadRootCard.setContent(
                    f"{root}　·　音乐 → {os.path.basename(music)}，"
                    f"缓存 → {os.path.basename(os.path.dirname(cache))}"
                    f"/{os.path.basename(cache)}")
            except Exception:
                self.downloadRootCard.setContent(root)
        except Exception:
            try:
                self.downloadRootCard.setContent('状态读取失败')
            except Exception:
                pass

    def __connectSignalToSlot(self):
        """ connect signal to slot """
        cfg.appRestartSig.connect(self.__showRestartTooltip)

        # 下载目录（唯一目录设置项）
        self.downloadRootCard.clicked.connect(
            self.__onDownloadRootCardClicked)

        # personalization
        cfg.themeChanged.connect(setTheme)
        self.themeColorCard.colorChanged.connect(lambda c: setThemeColor(c))
        install_hover_tip(self.micaCard, "云母效果", "开启 Windows11 云母半透明背景")
        install_hover_tip(self.splashCard, "启动过渡动画", "登录成功后显示过渡动画")
        install_hover_tip(self.themeCard, "应用主题", "切换浅色/深色/跟随系统")
        install_hover_tip(self.zoomCard, "界面缩放", "调整界面与字体大小")
        install_hover_tip(self.languageCard, "语言", "设置界面语言")
        install_hover_tip(self.glassOpacityCard, "界面透明度", "越小越透明(>=150)")
        install_hover_tip(self.glassBlurCard, "界面模糊度", "越大磨砂越强")
        self.micaCard.checkedChanged.connect(signalBus.micaEnableChanged)

        # download optimization - 同步到 core.config
        # OptionsSettingCard 通过 optionChanged 信号传递 OptionsConfigItem（配置值已自动保存）
        def _sync_download_mode(item):
            CFG['download_mode'] = str(item.value)
        def _sync_max_threads(value: int):
            CFG['download_max_threads'] = value
        def _sync_threshold(value: int):
            CFG['download_parallel_threshold'] = value
        def _sync_retry(value: int):
            CFG['download_retry_times'] = value

        self.downloadModeCard.optionChanged.connect(_sync_download_mode)
        self.downloadMaxThreadsCard.valueChanged.connect(_sync_max_threads)
        self.downloadThresholdCard.valueChanged.connect(_sync_threshold)
        self.downloadRetryCard.valueChanged.connect(_sync_retry)
        install_hover_tip(self.downloadModeCard, "下载模式", "自动判定最优下载模式，失败自动切换其他模式重试")
        install_hover_tip(self.downloadMaxThreadsCard, "并发线程数", "大文件分块并发下载的线程数，越大下载越快")
        install_hover_tip(self.downloadThresholdCard, "并发分块阈值", "超过该大小的文件自动使用并发分块加速")
        install_hover_tip(self.downloadRetryCard, "重试次数", "下载失败后的重试次数，提升下载成功率")

        # glass effect
        self.glassOpacityCard.valueChanged.connect(glass_manager.set_opacity)
        self.glassBlurCard.valueChanged.connect(glass_manager.set_blur_radius)

        # log settings
        self.operationLogCard.clicked.connect(
            self.__onOperationLogCardClicked)
        self.errorLogCard.clicked.connect(
            self.__onErrorLogCardClicked)

        # about
        self.feedbackCard.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))

        # ── 其余设置卡片悬停功能简介 ──
        install_hover_tip(self.downloadRootCard, "下载目录",
                          "全程序唯一需要选的目录：各平台下载、音乐下载与缓存、缩略图缓存都在它下面")
        self.refresh_download_root()
        install_hover_tip(self.themeColorCard, "主题颜色", "自定义应用的主题强调色")
        install_hover_tip(self.blurRadiusCard, "云母模糊半径", "调整云母背景的模糊程度，半径越大越模糊")
        install_hover_tip(self.operationLogCard, "操作日志路径", "设置操作日志的保存路径")
        install_hover_tip(self.errorLogCard, "错误日志路径", "设置错误日志的保存路径")
        install_hover_tip(self.updateOnStartUpCard, "启动检查更新", "开启后每次启动应用时自动检查是否有新版本")
        install_hover_tip(self.helpCard, "帮助", "打开帮助页面，学习 PyQt-Fluent-Widgets 的使用技巧")
        install_hover_tip(self.feedbackCard, "提供反馈", "打开反馈页面，帮助我们改进应用程序")
        install_hover_tip(self.aboutCard, "关于", "查看应用版本信息并检查更新")

        # ── 维护区 ──
        install_hover_tip(self.workspaceCard, "下载工作区",
                          "打开下载根目录。这里保存着工作区标记与可移植索引，重装后能自动恢复")
        install_hover_tip(self.userDataCard, "用户数据目录",
                          "账号、权限、配置与索引的存放位置；卸载时默认保留")
        install_hover_tip(self.uninstallCard, "卸载本程序",
                          "只卸载程序本体。下载内容与服务标记保留，缓存与用户数据会分别询问")
        self.workspaceCard.clicked.connect(self.__onOpenWorkspace)
        self.userDataCard.clicked.connect(self.__onOpenUserData)
        self.uninstallCard.clicked.connect(self.__onUninstall)
        self.refresh_maintenance()

        # ── 工具依赖区（ffmpeg）──
        install_hover_tip(self.ffmpegCard, "自动下载 ffmpeg",
                          "下载到下载根目录并自动解压绑定（约 40 MB）。只用它抽视频首帧当封面")
        install_hover_tip(self.ffmpegPickCard, "手动指定 ffmpeg",
                          "选 ffmpeg.exe 直接绑定；选 .zip/.7z 压缩包会先解压再绑定")
        install_hover_tip(self.ffmpegClearCard, "清除绑定",
                          "清除后重新按 内置 → 环境变量 → PATH 的顺序查找")
        self.ffmpegCard.clicked.connect(self.__onFfmpegDownload)
        self.ffmpegPickCard.clicked.connect(self.__onFfmpegPick)
        self.ffmpegClearCard.clicked.connect(self.__onFfmpegClear)
        self.refresh_ffmpeg()

        # 自动登录
        self.autoLoginSwitch.checkedChanged.connect(self._on_auto_login_switch)
        self.autoAccountCombo.currentTextChanged.connect(self._on_account_selected)
        install_hover_tip(self.autoLoginCard, "开机自动登录", "开启后下次启动跳过登录页，直接用选中账号登录并显示过渡动画")
        install_hover_tip(self.autoAccountCard, "自动登录账号", "选择本次自动登录使用的账号")
        install_hover_tip(self.addAccountBtn, "添加账号", "新增一个用于自动登录的账号（账号名+密码）")
        install_hover_tip(self.delAccountBtn, "删除账号", "删除下拉框中当前选中的账号")
        self.refresh_auto_login()

    # ---------------- 维护（工作区 / 用户数据 / 卸载） ----------------
    def refresh_maintenance(self):
        """刷新维护区显示。

        所有异常都必须吞掉：状态显示不出来是小事，**设置页打不开**是大事。
        """
        try:
            from core import workspace as _ws
            info = _ws.summary(CFG.download_root)
            if info.get('has_workspace'):
                self.workspaceCard.setContent(
                    f"{info['path']}　·　工作区标记更新于 {info.get('updated_at', '')}")
            else:
                self.workspaceCard.setContent(f"{info['path']}　·　尚无工作区标记")
        except Exception:
            try:
                self.workspaceCard.setContent('状态读取失败')
            except Exception:
                pass

        try:
            from core import shell_integration as _shell
            inst = _shell.install_summary()
            if inst.get('installed'):
                self.uninstallCard.setVisible(True)
                self.uninstallCard.setContent(f"安装于 {inst.get('install_dir')}")
            else:
                # 源码运行 / 直接跑 exe：根本没有卸载器。
                # 隐藏入口，而不是留一个点了没反应的按钮。
                self.uninstallCard.setVisible(False)
        except Exception:
            try:
                self.uninstallCard.setVisible(False)
            except Exception:
                pass

    # ---------------- 工具依赖（ffmpeg）----------------
    def refresh_ffmpeg(self):
        """刷新 ffmpeg 卡片状态。

        和 refresh_maintenance 一样：**任何异常都必须吞掉** ——
        状态显示不出来是小事，设置页打不开是大事。
        """
        try:
            from services import file_library as _FL
            from core.config import config as _CFG
            found = _FL.find_ffmpeg()
            bound = str(_CFG.get('ffmpeg_path', '') or '')
            if found:
                source = '已手动指定' if bound and os.path.normcase(bound) == os.path.normcase(found) \
                    else '自动查找到'
                self.ffmpegCard.setContent(f'{source}：{found}')
            else:
                self.ffmpegCard.setContent(
                    '未找到 ffmpeg —— 本地视频会显示不出封面（其他功能不受影响）')
            # 没绑定过就没什么可清除的
            self.ffmpegClearCard.setVisible(bool(bound))
        except Exception:
            try:
                self.ffmpegCard.setContent('状态读取失败')
                self.ffmpegClearCard.setVisible(False)
            except Exception:
                pass

    def __onFfmpegDownload(self):
        """一键下载 ffmpeg（下载 → 解压 → 绑定 → 打开目录）。"""
        try:
            from ui.widgets.ffmpeg_prompt import run_download_dialog
        except Exception as e:
            InfoBar.error('无法加载组件', str(e), position=InfoBarPosition.TOP,
                          duration=4000, parent=self)
            return
        got = run_download_dialog(self)
        self.refresh_ffmpeg()
        if got:
            InfoBar.success(
                title='ffmpeg 已就绪', content=got,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=4000, parent=self)

    def __onFfmpegPick(self):
        """手动指定：ffmpeg.exe 或压缩包（.zip/.7z）。"""
        try:
            from ui.widgets.ffmpeg_prompt import _pick_and_bind
        except Exception as e:
            InfoBar.error('无法加载组件', str(e), position=InfoBarPosition.TOP,
                          duration=4000, parent=self)
            return
        _pick_and_bind(self)
        self.refresh_ffmpeg()

    def __onFfmpegClear(self):
        try:
            from services.ffmpeg_installer import unbind
            unbind()
        except Exception as e:
            InfoBar.error('清除失败', str(e), position=InfoBarPosition.TOP,
                          duration=4000, parent=self)
        self.refresh_ffmpeg()

    def __onOpenWorkspace(self):
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(CFG.download_root))
        except Exception as e:
            InfoBar.error('打开失败', str(e), position=InfoBarPosition.TOP,
                          duration=3000, parent=self)

    def __onOpenUserData(self):
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(CFG.data)))
        except Exception as e:
            InfoBar.error('打开失败', str(e), position=InfoBarPosition.TOP,
                          duration=3000, parent=self)

    def __onUninstall(self):
        """启动卸载程序。

        刻意**交互式**启动（不加 /SILENT）：卸载器自己会问「是否清理 .cache」
        与「是否删除用户数据」，由用户当场决定，程序不替他做主。

        启动后本程序必须退出 —— 否则文件被占用，卸载会半途而废、留下半个程序。
        """
        from PyQt5.QtWidgets import QMessageBox, QApplication
        try:
            from core import shell_integration as _shell
            if not _shell.is_installed_copy():
                QMessageBox.information(
                    self, '无法卸载',
                    '当前不是通过安装程序安装的副本，因此没有卸载程序。\n\n'
                    '如果是从源码运行，直接删除程序目录即可。\n'
                    '用户数据与下载内容不会被自动删除。')
                return
            r = QMessageBox.question(
                self, '确认卸载',
                '即将启动卸载程序。\n\n'
                '· 只卸载程序本体\n'
                '· 下载内容与工作区标记始终保留\n'
                '· 缓存与用户数据由卸载程序分别询问（默认都不删）\n\n'
                '为避免文件被占用，本程序会随即退出。是否继续？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
            ok, msg = _shell.launch_uninstaller()
            if not ok:
                QMessageBox.warning(self, '启动卸载失败', msg)
                return
            app = QApplication.instance()
            if app is not None:
                app.quit()
        except Exception as e:
            QMessageBox.warning(self, '卸载出错', str(e))

    # ---------------- 自动登录 ----------------
    def refresh_auto_login(self):
        """刷新账号下拉框与开关状态（从存储读取）。"""
        try:
            self.autoLoginSwitch.blockSignals(True)
            self.autoLoginSwitch.setChecked(auto_login.is_enabled())
            self.autoLoginSwitch.blockSignals(False)

            self.autoAccountCombo.blockSignals(True)
            self.autoAccountCombo.clear()
            for acc in auto_login.get_accounts():
                self.autoAccountCombo.addItem(acc.get('username', ''))
            sel = auto_login.get_selected()
            if sel:
                idx = self.autoAccountCombo.findText(sel)
                if idx >= 0:
                    self.autoAccountCombo.setCurrentIndex(idx)
            self.autoAccountCombo.blockSignals(False)

            has_acc = self.autoAccountCombo.count() > 0
            self.autoAccountCard.setEnabled(has_acc or auto_login.is_enabled())
            self.delAccountBtn.setEnabled(has_acc and self.autoAccountCombo.currentIndex() >= 0)
        except Exception:
            pass

    def _on_auto_login_switch(self, checked: bool):
        auto_login.set_enabled(checked)
        if checked and self.autoAccountCombo.count() > 0:
            auto_login.set_selected(self.autoAccountCombo.currentText())
        self.refresh_auto_login()

    def _on_account_selected(self, text: str):
        if text:
            auto_login.set_selected(text)

    def _on_add_account(self):
        """弹出对话框新增/更新一个账号。"""
        existing = self.autoAccountCombo.currentText() if self.autoAccountCombo.count() else ''
        dlg = _AccountEditDialog(self.tr('添加自动登录账号'), self,
                                 username=existing, password='')
        if dlg.exec_() == QDialog.Accepted:
            username, password = dlg.get_credentials()
            auto_login.upsert_account(username, password)
            # 新增后默认选中该账号
            auto_login.set_selected(username)
            self.refresh_auto_login()
            InfoBar.success(
                title=self.tr('已保存'),
                content=self.tr(f'账号 {username} 已添加/更新'),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )

    def _on_delete_account(self):
        """删除当前选中的账号。"""
        username = self.autoAccountCombo.currentText()
        if not username:
            InfoBar.warning(
                title=self.tr('提示'), content=self.tr('请先选择要删除的账号'),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
            return
        auto_login.remove_account(username)
        self.refresh_auto_login()
        InfoBar.success(
            title=self.tr('已删除'),
            content=self.tr(f'账号 {username} 已删除'),
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=3000, parent=self
        )

    def __onOperationLogCardClicked(self):
        """操作日志路径选择"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.tr("选择操作日志保存路径"),
            CFG['operation_log_path'],
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*)"
        )
        if not file_path:
            return
        
        # 更新配置和日志管理器
        CFG['operation_log_path'] = file_path
        log_manager.set_op_log_path(file_path)
        self.operationLogCard.setContent(file_path)

    def __onErrorLogCardClicked(self):
        """错误日志路径选择"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.tr("选择错误日志保存路径"),
            CFG['error_log_path'],
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*)"
        )
        if not file_path:
            return
        
        # 更新配置和日志管理器
        CFG['error_log_path'] = file_path
        log_manager.set_err_log_path(file_path)
        self.errorLogCard.setContent(file_path)
