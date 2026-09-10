# -*- coding: utf-8 -*-
"""验证 main_window 集成导入 + EasyCopyPage 在画册子模块注册。"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == 'win32':
    site_packages = os.path.join(BASE_DIR, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

# 1. 导入 main_window（会触发所有子模块导入）
import ui.main_window as mw
print("[OK] ui.main_window 导入")

# 2. 验证画册入口卡片配置包含 easycopy
from pages.album.album_interface import AlbumInterface
keys = [k for k, _, _, _ in AlbumInterface.SUBMODULES]
print("[info] 画册子模块:", keys)
assert 'easycopy' in keys
print("[OK] album_interface 已注册拷贝漫画")

# 3. 验证 EasyCopyPage 类可实例化（不连网）
from pages.album.easycopy_page import EasyCopyPage
page = EasyCopyPage()
assert page.ctx is not None
print("[OK] EasyCopyPage 实例化（ctx 数据目录:", page.ctx.data_dir, "）")

print("\nmain_window 集成验证通过")
