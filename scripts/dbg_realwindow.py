# coding:utf-8
"""在真实显示器上短暂显示主窗口，并抓取【真实屏幕合成输出】到 PNG。

off-screen 的 widget.grab() 走 QPainter 离屏绘制，绕过了 DWM 合成，
无法复现「透明无边框窗口 + 磨砂/Mica」引发的双重合成鬼影。
本脚本用 QScreen.grabWindow(0) 抓整屏真实像素，以确认是否出现重影。
"""
import os, sys, time
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE)
os.environ.setdefault('QT_LOGGING_RULES', 'default.warning=false')
# 使用真实 windows 平台（不使用 offscreen）
site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QScreen, QGuiApplication
from PyQt5.QtCore import QTimer, Qt

app = QApplication(sys.argv)

import ui.main_window as mw

win = mw.Window()
win.resize(1080, 780)
win.move(30, 30)
win.show()
app.processEvents()
app.processEvents()

def grab_and_quit():
    try:
        screen = QGuiApplication.primaryScreen()
        scr = screen.grabWindow(0)   # 抓整屏真实合成输出
        out = os.path.join(os.path.dirname(__file__), '_real_screen.png')
        scr.save(out)
        print("saved", out, scr.width(), scr.height())
    except Exception as e:
        print("grab failed:", repr(e))
    app.quit()

# 等待窗口完全渲染并上屏，再抓屏
QTimer.singleShot(900, grab_and_quit)
QTimer.singleShot(2500, app.quit)   # 兜底退出
app.exec_()
print("done")
