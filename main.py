# -*- coding: utf-8 -*-
"""
OGC-OpenGenericClient 程序 - 统一启动入口
=========================================
从本文件启动整个 OGC-OpenGenericClient 应用程序（登录窗口 → 主窗口）。

用法：::

    python main.py
"""
import sys
import os

# 确保项目根目录在 sys.path 中（便于导入 core / ui / pages / services）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ── Qt 平台插件路径修复（含中文/非 ASCII 路径时 PyQt5 的 QLibraryInfo 会损坏为 '?'，需在导入 Qt 前用原生 os.path 计算并注入）──
# 冻结（PyInstaller）后不需要也不应该做这件事：插件由 PyInstaller 的 PyQt5 hook
# 一并打进 _internal，Qt 会自己找到；照旧指向 .venv 反而会指向不存在的目录。
if sys.platform == 'win32' and not getattr(sys, 'frozen', False):
    site_packages = os.path.join(BASE_DIR, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

# ── 初始化日志系统 ──
from core.logger import logger
from core.config import config as CFG

logger.initialize(
    op_log_path=CFG['operation_log_path'],
    err_log_path=CFG['error_log_path']
)

# ── 单实例互斥（尽量早，避免白做一遍初始化）──
# 两个用途：
#   1) 安装器/卸载器用 Inno 的 AppMutex 检测"程序是否在运行" —— 没有它，
#      卸载会在文件被占用时进行，留下半个程序；
#   2) 两个实例同时写同一个 SQLite 库与 config.json 会互相覆盖。
# 用原生 MessageBox 提示（此时 Qt 还没初始化）。系统调用失败一律放行启动。
try:
    from core import shell_integration as _shell
    if not _shell.acquire_single_instance():
        _shell.warn_already_running()
        logger.info("检测到已有实例在运行，本次启动退出")
        sys.exit(0)
except SystemExit:
    raise
except Exception as _e:
    logger.error(f"单实例检查失败（继续启动）: {_e}")

# ── 工作区恢复：重装后把索引/配置/用户数据还原回来 ──
# ⚠️ 必须在 init_db() **之前**！否则 init_db 会先把 ogc_users.db 建出来，
#    is_fresh_install() 立刻变假，自动恢复永远不会触发（这个顺序坑踩过一次）。
# 卸载时下载根目录是保留的，所以这里能凭 .ogc-workspace.json 认出旧工作区；
# 若用户在卸载时选择了备份用户数据，连账号库一起还原（见 core/workspace.py）。
try:
    from core import workspace as _workspace
    _restore = _workspace.maybe_restore()
    if _restore.get('restored'):
        logger.info(f"已从下载目录恢复工作区：{len(_restore['restored'])} 个文件")
except Exception as e:
    logger.error(f"工作区恢复失败（不影响启动）: {e}")

# ── 安装全局崩溃兜底（必须尽早，且在任何 Qt 槽函数可能执行之前）──
# 作用：1) PyQt5 槽函数里未捕获的异常默认会走 qFatal()→abort() 直接闪退且无日志，
#       安装 sys.excepthook 后改为"记录日志 + 进程继续"，把闪退降级为可追踪错误；
#       2) threading.Thread 内未捕获异常写入错误日志（否则线程静默死亡→界面卡死）；
#       3) faulthandler 把硬崩溃瞬间的全部线程栈写入 logs/crash.log。
try:
    from core import crash_guard
    crash_guard.install(log_dir=os.path.dirname(CFG['error_log_path']) or None)
except Exception as _e:
    logger.error(f"安装全局异常兜底失败: {_e}")

# ── 初始化数据库 ──
try:
    from core.database import init_db
    init_db()
    logger.info("数据库初始化成功")
except Exception as e:
    logger.error(f"数据库初始化失败: {str(e)}", exc_info=True)
    sys.exit(1)

# ── 存储布局迁移（一次性、幂等）──
# 把历史上的大体积缓存（缩略图 / 画廊图片 / 预览图）从 data/ 搬到下载根目录的
# .cache/，并把散落在下载根目录里的索引 JSON（缩略图索引 / 目录索引 / 离线索引）
# 收回 data/。必须早于任何缓存读取，否则会先按新路径读空、把缓存当成未命中重算。
# 同盘移动走 os.rename，是瞬时的；跨盘才会真正复制（仅一次），失败也绝不影响启动。
try:
    from core import storage_migration
    if storage_migration.needs_migration():
        logger.info("检测到旧存储布局，开始一次性迁移（缓存 → 下载根目录，索引 → data/）")
        storage_migration.migrate()
except Exception as e:
    logger.error(f"存储布局迁移失败（不影响启动）: {e}")

# ── 自检下载目录结构 ──
try:
    from services.download_manager import ensure_download_dirs
    ensure_download_dirs()
    logger.info("下载目录自检完成")
except Exception as e:
    logger.error(f"下载目录自检失败: {str(e)}")

# ── 工作区同步：维护可移植副本与标记 ──
# 必须晚于存储迁移（索引那时才刚归位到 data/），放后台线程避免首次复制几 MB 卡启动。
try:
    from core import paths as _paths
    logger.info(f"路径解析：{_paths.describe()}")
except Exception:
    pass
try:
    from core import workspace as _workspace
    import threading as _threading
    _threading.Thread(target=_workspace.sync_workspace, daemon=True,
                      name='OGC-WorkspaceSync').start()
except Exception as e:
    logger.error(f"工作区同步启动失败（不影响启动）: {e}")

# ── 注册表登记：把安装目录 / 卸载器路径 / 下载根目录写入 HKCU ──
# 卸载器是独立编译的 exe，读不到本项目的 Python 代码，只能靠注册表知道
# "下载根目录在哪"，才能在卸载时询问是否清理 .cache（见 packaging/installer.iss）。
try:
    from core import shell_integration as _shell
    if _shell.register_paths():
        logger.info("已登记安装信息到注册表（供卸载器使用）")
except Exception as e:
    logger.error(f"注册表登记失败（不影响使用）: {e}")

# ── 加载全局玻璃效果配置 ──
try:
    from ui.widgets.glass_effect import glass_manager
    from ui.widgets.common import cfg as app_cfg
    glass_manager.load(
        opacity=app_cfg.get(app_cfg.glassOpacity),
        blur_radius=app_cfg.get(app_cfg.glassBlurRadius)
    )
except Exception as e:
    logger.error(f"加载玻璃效果配置失败: {e}")

# ── Qt 高 DPI 设置 ──
# 静默无害的 Qt「default」分类警告（无类别 qWarning）：
# 1) "OpenType support missing for ..." —— 渲染日文（片假名）/泰卢固文等文字时，
#    系统字体（微软雅黑/宋体/Arial 等）缺少对应 OpenType 表产生的提示，纯属噪音；
# 2) 退出瞬间个别后台线程尚未结束时的 "QThread: Destroyed while thread is still running"，
#    线程对象已在各模块 closeEvent 中安全回收，退出期残留属正常收尾。
# 仅关闭 default 分类的 warning 级别，不影响其他 Qt 输出。
os.environ.setdefault('QT_LOGGING_RULES', 'default.warning=false')

from PyQt5.QtCore import Qt, QLocale
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

app = QApplication(sys.argv)

# ── 应用图标：所有窗口 / 对话框 / 任务栏都用同一张图 ──
# 只给登录窗口和主窗口 setWindowIcon 是不够的：其它窗口（各功能页弹出的对话框、
# EhViewer 子窗口、启动过渡动画、消息框）没有父窗口图标可用时会退回 Qt 默认的空图标
# —— 表现为任务栏里出现一个白板图标、Alt+Tab 缩略图没图。
# 这里设应用级图标，Qt 会自动把它作为所有窗口的默认图标。
# 图片就是 resources/images/logo/icon.png —— 与 exe 文件图标（build_exe.make_icon()
# 由同一张 PNG 生成的 icon.ico）是**同一张图**，所以资源管理器里的 exe 图标、
# 任务栏图标、窗口标题栏图标三处必然一致。
try:
    from PyQt5.QtGui import QIcon
    from core.resource_paths import APP_ICON
    if APP_ICON and os.path.isfile(APP_ICON):
        app.setWindowIcon(QIcon(APP_ICON))
    else:
        logger.warning(f"应用图标不存在，跳过设置: {APP_ICON}")
except Exception as _e:
    logger.error(f"设置应用图标失败（不影响使用）: {_e}")

# ── 全局线程看门狗：拦截所有 QThread.start，退出前统一 requestInterruption + wait，防止 QThread destroyed 闪退 ──
try:
    import core.thread_guard as _thread_guard
    _thread_guard_shutdown = _thread_guard.shutdown
    app.aboutToQuit.connect(_thread_guard_shutdown)
except Exception as _e:
    pass

# ── GUI 主线程看门狗：心跳超时即转储全部线程栈，把"界面卡死"变成有现场可查 ──
# 必须在 QApplication 之后、事件循环之前安装（心跳依赖主线程事件循环）。
try:
    from core import watchdog as _watchdog
    _watchdog.install()
except Exception as _e:
    logger.error(f"启动主线程看门狗失败: {_e}")


# ── 修复 qfluentwidgets InfoBar 动画警告 ──────────────────────────────
def _patch_qfluent_infobar_drop_animation():
    """修复 qfluentwidgets 1.11.3 的 InfoBarManager 动画警告。

    原问题：InfoBarManager.add() 在父窗口已有 InfoBar 时创建的 dropAni
    只设置了 duration 而未设置 start/end value。当该动画随动画组启动时，
    Qt 会警告：
        QPropertyAnimation::updateState (pos, InfoBar, ): starting an animation without end value
    推特等平台在解析/下载完成时连续弹出多个 InfoBar，最易触发。
    """
    try:
        from qfluentwidgets.components.widgets.info_bar import InfoBarManager
        from PyQt5.QtCore import QPropertyAnimation, QParallelAnimationGroup

        def _patched_add(self, infoBar):
            """与原始 add 逻辑一致，仅修复 dropAni 缺少 start/end value 的问题"""
            p = infoBar.parent()
            if not p:
                return

            if p not in self.infoBars:
                p.installEventFilter(self)
                self.infoBars[p] = []
                self.aniGroups[p] = QParallelAnimationGroup(self)

            if infoBar in self.infoBars[p]:
                return

            # add drop animation（补上 start/end value 避免 without end value 警告）
            if self.infoBars[p]:
                dropAni = QPropertyAnimation(infoBar, b'pos')
                dropAni.setDuration(200)
                dropAni.setStartValue(infoBar.pos())
                dropAni.setEndValue(infoBar.pos())

                self.aniGroups[p].addAnimation(dropAni)
                self.dropAnis.append(dropAni)

                infoBar.setProperty('dropAni', dropAni)

            # add slide animation
            self.infoBars[p].append(infoBar)
            slideAni = self._createSlideAni(infoBar)
            self.slideAnis.append(slideAni)

            infoBar.setProperty('slideAni', slideAni)
            infoBar.closedSignal.connect(lambda: self.remove(infoBar))

            slideAni.start()

        InfoBarManager.add = _patched_add
        logger.info("已应用 InfoBar 动画补丁（修复 dropAni 缺少 end value 警告）")
    except Exception as e:
        logger.warning(f"InfoBar 动画补丁应用失败: {e}")


_patch_qfluent_infobar_drop_animation()


# ── 过滤 qfluentwidgets 动画目标已销毁的良性警告 ──────────────────────
def _install_animation_warning_filter():
    """过滤 QPropertyAnimation 目标已销毁时的 Qt 警告。

    qfluentwidgets 的 Flyout / InfoBar / Menu 等组件在动画进行中，
    目标控件可能因页面切换 / 窗口关闭而被销毁，Qt 会打印：
        QPropertyAnimation::updateState (pos): Changing state of an animation without target
        QPropertyAnimation::updateState (windowOpacity): Changing state of an animation without target
    这类警告无害（动画自然中止），但会刷屏；这里安装 Qt 消息处理器将其静默，
    其余消息按默认方式输出（PyQt5 未暴露 qDefaultMessageHandler，用 qFormatLogMessage 格式化后写 stderr）。
    """
    import sys as _sys

    try:
        from PyQt5.QtCore import (
            QtMsgType, qInstallMessageHandler, qFormatLogMessage,
        )

        def _handler(msgType, context, message):
            text = message if isinstance(message, str) else str(message)
            if 'QPropertyAnimation::updateState' in text and \
                    'Changing state of an animation without target' in text:
                return  # 静默：动画目标已销毁属预期行为
            try:
                formatted = qFormatLogMessage(msgType, context, message)
                _sys.stderr.write(formatted)
                _sys.stderr.flush()
            except Exception:
                _sys.stderr.write(text + "\n")

        qInstallMessageHandler(_handler)
        logger.info("已应用动画警告过滤器（静默 QPropertyAnimation without target）")
    except Exception as e:
        logger.warning(f"动画警告过滤器应用失败: {e}")


_install_animation_warning_filter()

# ── 国际化 ──
translator = FluentTranslator(QLocale())
app.installTranslator(translator)

# ── 启动登录窗口 ──
from ui.login_window import LoginWindow

window = LoginWindow()

# 若开启自动登录且账号校验通过：直接显示过渡动画→主窗口，跳过登录界面
try:
    if window.auto_login_if_enabled():
        # 已接管：窗口未显示登录表单，由 _login_success 显示过渡动画并构造主窗口
        window.show()
        logger.info("应用程序启动（自动登录）")
        app.exec_()
        logger.info("应用程序退出")
    else:
        # 未开启自动登录或校验失败：显示普通登录页
        window.show()
        logger.info("应用程序启动")
        app.exec_()
        logger.info("应用程序退出")
except Exception as e:
    logger.error(f"启动异常：{e}", exc_info=True)