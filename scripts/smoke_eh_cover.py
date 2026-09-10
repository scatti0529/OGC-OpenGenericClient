# -*- coding: utf-8 -*-
"""冒烟：CoverService 统一缓存 load/save/enqueue + 信号。"""
import os, sys
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.setdefault('QT_LOGGING_RULES', 'default.warning=false')
site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)
sys.argv[0] = os.path.join(BASE, 'main.py')
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage, QColor
app = QApplication.instance() or QApplication(sys.argv)

from pages.album.eh_cover import cover_service, cover_path, gid_from_key
print('gid_from_key(thumb:12345) =', gid_from_key('thumb:12345'))
print('gid_from_key(detail:999) =', gid_from_key('detail:999'))

# save/load round-trip
img = QImage(40, 50, QImage.Format_RGB32); img.fill(QColor('#e67e22'))
cov = cover_service
cov.save(777, img)
p = cover_path(777)
print('path exists:', p and os.path.isfile(p))
print('load ->', cov.load(777) is not None, 'has ->', cov.has(777))

# enqueue 一个不存在的网址(离线会失败) -> 应触发 loaded(None) + progress
res = {'loaded': 0}
cov.loaded.connect(lambda g, pm: None)
cov.progress.connect(lambda d, t: None)
cov.enqueue(888, 'https://ehgt.org/0/invalid.png')
# 给后台线程一点时间
import time
time.sleep(1.5)
app.processEvents()
print('enqueue no-crash DONE')

# 清理测试缓存
try: os.remove(cover_path(777))
except Exception: pass
print('DONE')
