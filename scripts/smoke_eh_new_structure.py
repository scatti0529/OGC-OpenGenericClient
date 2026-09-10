# -*- coding: utf-8 -*-
"""冒烟：新 E-Hentai 结构（拆散画廊中心 -> 分段页）。验证构建 + 页面切换 + 就地详情。"""
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

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from pages.album.ehentai_page import EhentaiPage
from ehviewer.appctx import ctx
from ehviewer import db as ehdb
from ehviewer.ui.bus import bus
from ehviewer.models import GalleryInfo
from ehviewer import constants as C

p = EhentaiPage()
p.resize(1200, 780)
p.show()
app.processEvents()

print('stacked tab count:', p.stackedWidget.count())
print('pages present:',
      all(hasattr(p, a) for a in
          ['home_page','search_page','download_page','favorites_page',
           'reader_page','history_page','top_page','settings_page']))

# 切换到 OGC tab（不触发网络）
for key, name in [(p.TAB_DOWNLOAD,'下载画廊'),(p.TAB_FAVORITES,'收藏'),
                  (p.TAB_READER,'阅读'),(p.TAB_SETTINGS,'设置')]:
    p.pivot.setCurrentItem(key); app.processEvents()
    print('switch', name, '->', p.stackedWidget.currentWidget().objectName())

# 验证就地详情叠加机制（用一个轻量测试页，避免真实 DetailWindow 网络线程卡住测试）
class _FakeOverlay(QWidget):
    back_requested = pyqtSignal()
    def shutdown(self): pass
fo = _FakeOverlay()
p._push_overlay(fo); app.processEvents()
print('fake overlay count:', len(p._overlays))
p._pop_overlay(); app.processEvents()
print('after pop overlays:', len(p._overlays))

# 详情下载请求 -> 转交下载画廊（只验证切页+URL；patch 掉真正下载避免网络）
try:
    p.download_page._start_download = lambda: None
    gi = GalleryInfo(); gi.gid=123456; gi.token='abcdef0123'; gi.title='dl'; gi.category=C.CAT_MANGA
    p._on_detail_download_requested(gi, '未分类')
    app.processEvents()
    print('detail download routed to 下载画廊:',
          p.stackedWidget.currentWidget() is p.download_page,
          '| url:', p.download_page.download_card.get_url())
except Exception as e:
    import traceback; traceback.print_exc(); print('download route FAIL', repr(e))

print('wired ctx:', ctx.image_loader is not None, ctx.download_manager is not None)
print('DONE construct')
