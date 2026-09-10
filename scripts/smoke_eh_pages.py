# -*- coding: utf-8 -*-
"""冒烟：接线 ctx + 共享DB后，离线构造 EhViewer 各页面，验证可嵌入。"""
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
app = QApplication.instance() or QApplication(sys.argv)

# ---- 接线 ctx / 共享 DB ----
from ehviewer import db as ehdb
from ehviewer.config import CFG as eh_cfg
from ehviewer.appctx import ctx
from ehviewer.session import make_session
from ehviewer.image_cache import ImageLoader
from ehviewer.downloader import DownloadManager

ogc_db = os.path.join(BASE, 'data', 'ehentai', 'app_db.db')
ehdb.set_db_path(ogc_db)
print('db path ->', ehdb.get_db_path())
print('local favorites in shared DB:', len(ehdb.list_local_favorites()))

ctx.session_factory = make_session
ctx.image_loader = ImageLoader(make_session)
ctx.download_manager = DownloadManager()

# ---- 构造页面 ----
from ehviewer.ui.home_page import HomePage
from ehviewer.ui.search_page import SearchPage
from ehviewer.ui.gallery_list_page import GalleryListPage
from ehviewer.ui.favorites_page import FavoritesPage
from ehviewer.ui.downloads_page import DownloadsPage
from ehviewer.ui.album_page import AlbumPage
from ehviewer.ui.history_page import HistoryPage
from ehviewer.ui.top_list_page import TopListPage
from ehviewer.ui.image_search_page import ImageSearchPage
from ehviewer.ui.settings_page import SettingsPage

pages = {
    'home': HomePage, 'search': SearchPage, 'favorites': FavoritesPage,
    'downloads': DownloadsPage, 'album': AlbumPage, 'history': HistoryPage,
    'toplist': TopListPage, 'imagesearch': ImageSearchPage, 'settings': SettingsPage,
}
for name, cls in pages.items():
    try:
        p = cls(None)
        p.resize(900, 700)
        print('OK  ', name, '->', cls.__name__)
        p.deleteLater()
    except Exception as e:
        import traceback; traceback.print_exc()
        print('FAIL', name, '->', repr(e))

g = GalleryListPage('测试')
g.resize(900, 700)
print('OK   gallery_list ->', type(g).__name__)
g.deleteLater()

# DetailWindow / ReaderWindow 也能作 QWidget 构造（父为 None 时是独立窗口）
from ehviewer.ui.detail_window import DetailWindow
from ehviewer.ui.reader_window import ReaderWindow
from ehviewer.models import GalleryInfo
info = GalleryInfo()
info.gid = 0; info.token = '0000000000'; info.title = 't'; info.pages = 1
try:
    dw = DetailWindow(info)
    dw.resize(900, 700)
    print('OK   detail_window construct')
    dw.deleteLater()
except Exception as e:
    import traceback; traceback.print_exc(); print('FAIL detail_window', repr(e))

ctx.image_loader.shutdown()
ctx.download_manager.shutdown()
print('DONE')
