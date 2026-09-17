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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _eh_db_testkit import use_temp_db, cleanup_temp_db

# 数据库已统一（E-Hentai 的表就在账号库 ogc_users.db 里），所以这里改成：
# 拷一份统一库到临时目录、把 ehviewer 指过去 —— 不再有独立的 app_db.db。
tmp, tmp_db = use_temp_db(prefix='ogc_cat_')
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
cleanup_temp_db(tmp)
print('DONE')
