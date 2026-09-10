# -*- coding: utf-8 -*-
"""验证 DownloadManager 对共享库的簿记：start 写 DOWNLOADS 行, pause/remove 清理,
    不触发真实网络（在 _pump 定时器触发前完成 start/pause/remove）。"""
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
app = QApplication.instance() or QApplication(sys.argv)

from ehviewer import db as ehdb, constants as C
from ehviewer.models import GalleryInfo
ehdb.set_db_path(os.path.join(BASE, 'data', 'ehentai', 'app_db.db'))

g = GalleryInfo(); g.gid = 999999002; g.token='deadbeef00'; g.title='下载簿记测试'; g.category=C.CAT_MANGA
mgr = ehdb  # placeholder
from ehviewer.downloader import DownloadManager
ctx_dm = DownloadManager()
# 同步块内完成, 不 pump (不 processEvents), 避免真实网络
ctx_dm.start_download(g, label='测试')
print('after start_download: exists =', ehdb.get_download(g.gid) is not None,
      '| state =', ehdb.get_download(g.gid).state if ehdb.get_download(g.gid) else None)
# 暂停(排队中) -> STATE_NONE
ctx_dm.pause(g.gid)
print('after pause: state =', ehdb.get_download(g.gid).state if ehdb.get_download(g.gid) else None)
# 移除 -> 清库
ctx_dm.remove(g.gid, delete_files=False)
print('after remove: exists =', ehdb.get_download(g.gid) is not None)
ehdb.delete_history(g.gid)  # 若详情未写历史, 保险清理
print('DONE (gid=%d)' % g.gid)
