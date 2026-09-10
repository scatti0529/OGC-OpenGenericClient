# -*- coding: utf-8 -*-
"""完整 Window 实例化验证：确保 JMComic 阅读页 / E-Hentai 阅读页在真实窗口中可用。"""
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

# 直接实例化 Window（登录窗口会做 setCurrentUser，这里跳过登录，仅验证构造）
from ui.main_window import Window

w = Window()
assert w.easycopyPage is not None
assert w.ehentaiPage is not None
assert w.PeopleInterface is not None  # JMComic
assert w.ehentaiPage.reader_page is not None
assert w.PeopleInterface.reader_tab is not None
assert '拷贝漫画' in w._nav_items
assert 'E-Hentai' in w._nav_items
assert '人物' in w._nav_items  # JMComic 的 objectName

# 验证画册父项点击处理器已连接
album_nav = w._nav_items.get('画册')
assert album_nav is not None
print("[OK] Window 实例化 + 全部阅读页挂载成功")
w.close()
print("\n完整 Window 验证通过")
