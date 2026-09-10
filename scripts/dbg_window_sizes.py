# -*- coding: utf-8 -*-
"""诊断：遍历主窗口，找出尺寸提示异常巨大（会撑爆窗口）的子控件"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication
_APP = QApplication.instance() or QApplication(sys.argv)

import ui.main_window as mw
win = mw.Window()
win.resize(1080, 780)
win.show()
_APP.processEvents()

print('window.size =', win.size())
print('window.minimumSizeHint =', win.minimumSizeHint())
print('window.sizeHint =', win.sizeHint())

print('\n--- 大小可疑的控件 (sizeHint 宽>1200 或 高>1200) ---')
seen = set()
report = []


def walk(w, depth=0):
    try:
        sh = w.sizeHint()
        msh = w.minimumSizeHint()
        if (sh.width() > 1200 or sh.height() > 1200
                or msh.width() > 1200 or msh.height() > 1200):
            cls = w.__class__.__name__
            obj = w.objectName()
            key = (id(w),)
            if key not in seen:
                seen.add(key)
                report.append((depth, cls, obj, sh, msh))
        for c in w.findChildren(type(w)):
            if c is not w:
                walk(c, depth + 1)
    except Exception:
        pass


for c in win.findChildren(object):
    walk(c)

for depth, cls, obj, sh, msh in report:
    print(f'  {"  "*depth}{cls} objectName="{obj}" sizeHint={sh} minSizeHint={msh}')

# 特别检查首页
home = getattr(win, 'homeInterface', None)
if home is not None:
    print('\n--- 首页 homeInterface ---')
    print('  home.size =', home.size(), 'hero:', end=' ')
    hero = getattr(home, 'hero', None)
    if hero is not None:
        print(hero.size(), 'fixedH=', hero.height(), 'sizeHint=', hero.sizeHint())
    print('  home.minimumSizeHint =', home.minimumSizeHint(), 'sizeHint =', home.sizeHint())

win.close()
