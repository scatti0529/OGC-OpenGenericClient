# coding:utf-8
"""抓取主窗口/home 页实际布局到 PNG，供人工查看缩放/越界情况。"""
import os, sys
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE)

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.setdefault('QT_LOGGING_RULES', 'default.warning=false')
site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

app = QApplication(sys.argv)

import ui.main_window as mw

win = mw.Window()
win.resize(1080, 780)
win.show()
app.processEvents()
app.processEvents()

# 记录实际几何
from PyQt5.QtCore import QSize
print("window size:", win.size().width(), win.size().height())
home = win.homeInterface
print("home size:", home.size().width(), home.size().height())
print("home view size:", home.view.size().width(), home.view.size().height())
print("home hero size:", home.hero.size().width(), home.hero.size().height())

# 抓主窗口整体
pix = win.grab()
out = os.path.join(os.path.dirname(__file__), '_win_full.png')
pix.save(out)
print("saved", out, pix.width(), pix.height())

# 抓 home 页
pix2 = home.grab()
out2 = os.path.join(os.path.dirname(__file__), '_home.png')
pix2.save(out2)
print("saved", out2, pix2.width(), pix2.height())

# 抓 hero
pix3 = home.hero.grab()
out3 = os.path.join(os.path.dirname(__file__), '_hero.png')
pix3.save(out3)
print("saved", out3, pix3.width(), pix3.height())
