# coding:utf-8
from qfluentwidgets import (SettingCardGroup, SwitchSettingCard, FolderListSettingCard,
                            OptionsSettingCard, PushSettingCard,
                            HyperlinkCard, PrimaryPushSettingCard, ScrollArea,
                            ComboBoxSettingCard, ExpandLayout, Theme, CustomColorSettingCard,
                            setTheme, setThemeColor, RangeSettingCard, isDarkTheme,
                            SettingCard, ComboBox, SwitchButton, LineEdit, PushButton,
                            PrimaryPushButton, Dialog, BodyLabel)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import InfoBar, InfoBarPosition
from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QStandardPaths
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QLabel, QFileDialog, QVBoxLayout, QHBoxLayout, QDialogButtonBox, QDialog
from pathlib import Path
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

        # music folders
        self.musicInThisPCGroup = SettingCardGroup(
            self.tr("音乐"), self.scrollWidget)
        self.musicFolderCard = FolderListSettingCard(
            cfg.musicFolders,
            self.tr("本地音乐库"),
            directory=QStandardPaths.writableLocation(
                QStandardPaths.MusicLocation),
            parent=self.musicInThisPCGroup
        )
        self.downloadFolderCard = PushSettingCard(
            self.tr('选择文件夹'),
            FIF.DOWNLOAD,
            self.tr("下载目录"),
            cfg.get(cfg.downloadFolder),
            self.musicInThisPCGroup
        )
        self.musicCacheFolderCard = PushSettingCard(
            self.tr('选择文件夹'),
            FIF.MUSIC_FOLDER,
            self.tr("音乐缓存目录"),
            str(Path(CFG['save_path']) / 'data' / 'musics'),
            self.musicInThisPCGroup
        )
        self.musicDownloadFolderCard = PushSettingCard(
            self.tr('选择文件夹'),
            FIF.DOWNLOAD,
            self.tr("音乐下载目录"),
            str(Path(CFG['save_path']) / 'data' / 'musics'),
            self.musicInThisPCGroup
        )
        self.videoDownloadRootCard = PushSettingCard(
            self.tr('选择文件夹'),
            FIF.VIDEO,
            self.tr("视频下载根目录"),
            CFG.get('video_download_root', str(Path(CFG['save_path']) / 'data')),
            self.musicInThisPCGroup
        )

        # download optimization
        self.downloadGroup = SettingCardGroup(
            self.tr('下载优化'), self.scrollWidget)
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
        self.musicInThisPCGroup.addSettingCard(self.musicFolderCard)
        self.musicInThisPCGroup.addSettingCard(self.downloadFolderCard)
        self.musicInThisPCGroup.addSettingCard(self.musicCacheFolderCard)
        self.musicInThisPCGroup.addSettingCard(self.musicDownloadFolderCard)
        self.musicInThisPCGroup.addSettingCard(self.videoDownloadRootCard)

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
        self.expandLayout.addWidget(self.musicInThisPCGroup)
        self.expandLayout.addWidget(self.downloadGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.materialGroup)
        self.expandLayout.addWidget(self.logGroup)
        self.expandLayout.addWidget(self.autoLoginGroup)
        self.expandLayout.addWidget(self.updateSoftwareGroup)
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

    def __onDownloadFolderCardClicked(self):
        """ download folder card clicked slot """
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("选择文件夹"), "./")
        if not folder or cfg.get(cfg.downloadFolder) == folder:
            return

        cfg.set(cfg.downloadFolder, folder)
        self.downloadFolderCard.setContent(folder)

    def __onMusicCacheFolderCardClicked(self):
        folder = QFileDialog.getExistingDirectory(self, "选择音乐缓存目录", "./")
        if not folder:
            return
        CFG['music_cache_path'] = folder
        self.musicCacheFolderCard.setContent(folder)

    def __onMusicDownloadFolderCardClicked(self):
        folder = QFileDialog.getExistingDirectory(self, "选择音乐下载目录", "./")
        if not folder:
            return
        CFG['music_download_path'] = folder
        self.musicDownloadFolderCard.setContent(folder)

    def __onVideoDownloadRootCardClicked(self):
        """视频下载根目录选择"""
        folder = QFileDialog.getExistingDirectory(self, "选择视频下载根目录", "./")
        if not folder:
            return
        CFG['video_download_root'] = folder
        self.videoDownloadRootCard.setContent(folder)
        # 重新创建平台子目录
        try:
            from services.download_manager import ensure_download_dirs
            ensure_download_dirs()
            InfoBar.success(
                title="目录已更新",
                content="已在所选目录下创建各平台下载文件夹",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000, parent=self
            )
        except Exception:
            pass

    def __connectSignalToSlot(self):
        """ connect signal to slot """
        cfg.appRestartSig.connect(self.__showRestartTooltip)

        # music in the pc
        self.downloadFolderCard.clicked.connect(
            self.__onDownloadFolderCardClicked)
        self.musicCacheFolderCard.clicked.connect(
            self.__onMusicCacheFolderCardClicked)
        self.musicDownloadFolderCard.clicked.connect(
            self.__onMusicDownloadFolderCardClicked)
        self.videoDownloadRootCard.clicked.connect(
            self.__onVideoDownloadRootCardClicked)

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
        install_hover_tip(self.musicFolderCard, "本地音乐库", "管理本地音乐文件夹，播放器自动扫描并索引其中的音乐文件")
        install_hover_tip(self.downloadFolderCard, "下载目录", "设置音乐等资源的默认下载保存位置")
        install_hover_tip(self.musicCacheFolderCard, "音乐缓存目录", "设置音乐播放缓存的存放位置")
        install_hover_tip(self.musicDownloadFolderCard, "音乐下载目录", "设置音乐下载的保存位置")
        install_hover_tip(self.videoDownloadRootCard, "视频下载根目录", "设置视频下载的根目录，各平台自动创建子文件夹")
        install_hover_tip(self.themeColorCard, "主题颜色", "自定义应用的主题强调色")
        install_hover_tip(self.blurRadiusCard, "云母模糊半径", "调整云母背景的模糊程度，半径越大越模糊")
        install_hover_tip(self.operationLogCard, "操作日志路径", "设置操作日志的保存路径")
        install_hover_tip(self.errorLogCard, "错误日志路径", "设置错误日志的保存路径")
        install_hover_tip(self.updateOnStartUpCard, "启动检查更新", "开启后每次启动应用时自动检查是否有新版本")
        install_hover_tip(self.helpCard, "帮助", "打开帮助页面，学习 PyQt-Fluent-Widgets 的使用技巧")
        install_hover_tip(self.feedbackCard, "提供反馈", "打开反馈页面，帮助我们改进应用程序")
        install_hover_tip(self.aboutCard, "关于", "查看应用版本信息并检查更新")

        # 自动登录
        self.autoLoginSwitch.checkedChanged.connect(self._on_auto_login_switch)
        self.autoAccountCombo.currentTextChanged.connect(self._on_account_selected)
        install_hover_tip(self.autoLoginCard, "开机自动登录", "开启后下次启动跳过登录页，直接用选中账号登录并显示过渡动画")
        install_hover_tip(self.autoAccountCard, "自动登录账号", "选择本次自动登录使用的账号")
        install_hover_tip(self.addAccountBtn, "添加账号", "新增一个用于自动登录的账号（账号名+密码）")
        install_hover_tip(self.delAccountBtn, "删除账号", "删除下拉框中当前选中的账号")
        self.refresh_auto_login()

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
