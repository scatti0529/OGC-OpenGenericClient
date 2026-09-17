# -*- coding: utf-8 -*-
"""冒烟：验证 DB 驱动的页面（收藏/本地画册/历史）确实渲染共享数据库数据。"""
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

# 接线 ctx + 共享库
from ehviewer import db as ehdb
from ehviewer.config import CFG as eh_cfg
from ehviewer.appctx import ctx
from ehviewer.session import make_session
from ehviewer.image_cache import ImageLoader
from ehviewer.downloader import DownloadManager
# 数据库已统一 → E-Hentai 表就在账号库 ogc_users.db 里；本脚本要构建真实页面，
# 可能触发写操作，因此跑在副本上。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _eh_db_testkit import use_temp_db, cleanup_temp_db
_tmp_dir, ogc_db = use_temp_db(prefix='ogc_eh_dbpages_')
ctx.session_factory = make_session
ctx.image_loader = ImageLoader(make_session)
ctx.download_manager = DownloadManager()

print('local favorites count:', len(ehdb.list_local_favorites()))
print('history count:', len(ehdb.list_history()))
print('downloads count:', len(ehdb.list_downloads()))
print('download labels:', ehdb.list_labels())

from ehviewer.ui.favorites_page import FavoritesPage
from ehviewer.ui.history_page import HistoryPage
from ehviewer.ui.album_page import AlbumPage

# 收藏页（未登录 -> 读 LOCAL_FAVORITES）
fp = FavoritesPage(None)
fp.resize(1000, 700)
fp.show()
app.processEvents()
try:
    fp.reload()
    app.processEvents()
    lp = fp.list_page
    n = len(getattr(lp, '_items', [])) if hasattr(lp, '_items') else getattr(lp, '_items', [])
    print('favorites loaded items:', len(getattr(lp, '_items', [])))
except Exception as e:
    import traceback; traceback.print_exc(); print('favorites reload FAIL', repr(e))

# 历史页
hp = HistoryPage(None)
hp.resize(1000, 700)
hp.show(); app.processEvents()
try:
    hp._reload(); app.processEvents()
    print('history loaded items:', len(getattr(hp.list_page, '_items', [])))
except Exception as e:
    import traceback; traceback.print_exc(); print('history FAIL', repr(e))

# 本地画册页（读 DOWNLOADS + DOWNLOAD_LABELS）
ap = AlbumPage(None)
ap.resize(1000, 700)
ap.show(); app.processEvents()
try:
    ap._refresh(); app.processEvents()
    print('album labels:', ap._labels())
except Exception as e:
    import traceback; traceback.print_exc(); print('album FAIL', repr(e))

ctx.image_loader.shutdown(); ctx.download_manager.shutdown()
print('DONE')
cleanup_temp_db(_tmp_dir)
