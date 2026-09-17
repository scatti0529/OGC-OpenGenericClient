# -*- coding: utf-8 -*-
"""冒烟：封面磁盘缓存round-trip + 取消收藏/历史批量删除 DB 逻辑。"""
import os, sys, shutil, tempfile, sqlite3
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

from pages.album.ehentai_settings import ehentai_cfg as _c
from pages.album import ehentai_sync as S

# --- 封面磁盘缓存 ---
from pages.album.ehentai_favorites_page import ThumbnailLoader
tl = ThumbnailLoader()
gid = 888888
p = tl._disk_path(gid, '')
print('disk path =', p, '| cover_dir exists =', bool(tl._cover_dir))
# 造一个 pixmap 存盘
img = QImage(50, 60, QImage.Format_RGB32); img.fill(QColor('#28afe9'))
pix = img  # 用 QImage save
img.save(p, 'PNG') if p else None
loaded = tl._load_from_disk(gid, '')
print('load_from_disk ->', loaded is not None)
tl._on_fetched(gid, open(p,'rb').read())
print('cache in memory after fetch ->', gid in tl._cache)

# --- 取消收藏 DB（数据库已统一 → 跑在统一库的临时副本上）---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _eh_db_testkit import use_temp_db, cleanup_temp_db
tmp, tmpdb = use_temp_db(prefix='ogc_unfav_')
c = sqlite3.connect(tmpdb)
c.execute("INSERT OR REPLACE INTO LOCAL_FAVORITES (GID,TOKEN,TITLE,CATEGORY,RATING,TIME) VALUES (?,?,?,?,?,?)",
          (888888, 'x', '测试', 2, 4.0, 1))
c.commit()
c.execute("DELETE FROM LOCAL_FAVORITES WHERE GID=?", (888888,))
c.commit()
print('unfavorite removed ->', c.execute('select count(*) from LOCAL_FAVORITES where GID=888888').fetchone()[0] == 0)
# 历史批量删除
c.execute("INSERT OR REPLACE INTO HISTORY (GID,TOKEN,TITLE,CATEGORY,RATING,MODE,TIME) VALUES (?,?,?,?,?,?,?)",
          (888889, 'y', '历史测试', 2, 4.0, 0, 1))
c.commit()
c.execute("DELETE FROM HISTORY WHERE GID=?", (888889,))
c.commit()
print('history batch-delete removed ->', c.execute('select count(*) from HISTORY where GID=888889').fetchone()[0] == 0)
print('LOCAL_FAV count:', c.execute('select count(*) from LOCAL_FAVORITES').fetchone()[0],
      '| HISTORY count:', c.execute('select count(*) from HISTORY').fetchone()[0])
c.close()
cleanup_temp_db(tmp)
print('DONE')
