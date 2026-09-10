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
if sys.platform == 'win32':
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

# ── 初始化数据库 ──
try:
    from core.database import init_db
    init_db()
    logger.info("数据库初始化成功")
except Exception as e:
    logger.error(f"数据库初始化失败: {str(e)}", exc_info=True)
    sys.exit(1)

# ── 自检下载目录结构 ──
try:
    from services.download_manager import ensure_download_dirs
    ensure_download_dirs()
    logger.info("下载目录自检完成")
except Exception as e:
    logger.error(f"下载目录自检失败: {str(e)}")

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

# ── 全局线程看门狗：拦截所有 QThread.start，退出前统一 requestInterruption + wait，防止 QThread destroyed 闪退 ──
try:
    import core.thread_guard as _thread_guard
    _thread_guard_shutdown = _thread_guard.shutdown
    app.aboutToQuit.connect(_thread_guard_shutdown)
except Exception as _e:
    pass


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