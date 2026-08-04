# -*- coding: utf-8 -*-
"""
OGC 程序 - 统一启动入口
========================
从本文件启动整个 OGC 应用程序（登录窗口 → 主窗口）。

用法：::

    python main.py
"""
import sys
import os

# 确保项目根目录在 sys.path 中（便于导入 core / ui / pages / services）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

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