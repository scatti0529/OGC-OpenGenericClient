# -*- coding: utf-8 -*-
"""冒烟：comic_category / set_comic_category 读/写分类。用临时DB+临时目录。"""
import os, sys, shutil, tempfile, json
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
from pages.album.ehentai_settings import ehentai_cfg as _c
from pages.album import ehentai_sync as S
import sqlite3
orig = _c.get(_c.KEY_DB_PATH)
tmp = tempfile.mkdtemp(prefix='ogc_cat_')
tmp_db = os.path.join(tmp, 'app_db.db')
shutil.copy2(os.path.join(BASE, 'data', 'ehentai', 'app_db.db'), tmp_db)
_c.set(_c.KEY_DB_PATH, tmp_db)
comic_dir = os.path.join(tmp, '某漫画目录')
os.makedirs(comic_dir, exist_ok=True)
with open(os.path.join(comic_dir, '.ehentai_info.json'), 'w', encoding='utf-8') as f:
    json.dump({'gid': 999999005, 'token': 'xx'}, f)
print('gid =', S.comic_gid(comic_dir), '| cat before =', repr(S.comic_category(comic_dir, '某漫画目录')))
print('set category 长篇 =', S.set_comic_category(comic_dir, '某漫画目录', '长篇'))
c = sqlite3.connect(tmp_db)
print('row label after set =', c.execute("SELECT LABEL FROM DOWNLOADS WHERE GID=999999005").fetchone()[0])
c.close()
print('cat after =', repr(S.comic_category(comic_dir, '某漫画目录')))
_c.set(_c.KEY_DB_PATH, orig)
shutil.rmtree(tmp, ignore_errors=True)
print('DONE')
