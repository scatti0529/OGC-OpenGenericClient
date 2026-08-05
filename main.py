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
from PyQt5.QtCore import Qt, QLocale
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

app = QApplication(sys.argv)


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

# ── 国际化 ──
translator = FluentTranslator(QLocale())
app.installTranslator(translator)

# ── 启动登录窗口 ──
from ui.login_window import LoginWindow

window = LoginWindow()
window.show()
logger.info("应用程序启动")
app.exec_()
logger.info("应用程序退出")