# -*- coding: utf-8 -*-
"""冒烟：downloads 对账 (reconcile) —— 用临时 DB + 临时下载目录，验证清理孤立/补写未分类。"""
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

orig = _c.get(_c.KEY_DB_PATH)
tmp = tempfile.mkdtemp(prefix='ogc_recon_')
tmp_db = os.path.join(tmp, 'app_db.db')
shutil.copy2(os.path.join(BASE, 'data', 'ehentai', 'app_db.db'), tmp_db)
_c.set(_c.KEY_DB_PATH, tmp_db)

# 临时下载目录：comicB 有元数据(gid=999999004)，comicA 无元数据(无gid)
dldir = os.path.join(tmp, 'ExHentai-download')
os.makedirs(os.path.join(dldir, '漫画B目录'), exist_ok=True)
with open(os.path.join(dldir, '漫画B目录', '001.jpg'), 'wb') as f:
    f.write(b'\x89PNG\r\n\x1a\n' + b'\x00'*100)
with open(os.path.join(dldir, '漫画B目录', '.ehentai_info.json'), 'w', encoding='utf-8') as f:
    json.dump({'gid': 999999004, 'token': 'abcdef1234'}, f)
os.makedirs(os.path.join(dldir, '旧漫画A'), exist_ok=True)
with open(os.path.join(dldir, '旧漫画A', '001.jpg'), 'wb') as f:
    f.write(b'\x89PNG\r\n\x1a\n' + b'\x00'*100)

# 预先在临时库放一条"孤儿"(无对应目录)与一条"有对应目录漫画B"
import sqlite3
c = sqlite3.connect(tmp_db)
c.execute("INSERT OR REPLACE INTO DOWNLOADS (GID,TOKEN,TITLE,TITLE_JPN,THUMB,CATEGORY,POSTED,UPLOADER,RATING,SIMPLE_LANGUAGE,STATE,LEGACY,TIME,LABEL) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (999999099, 'deadbeef00', '完全不存在的孤儿', '', '', 0x400, '', '', 0.0, None, 3, 0, 1, None))
c.execute("INSERT OR REPLACE INTO DOWNLOADS (GID,TOKEN,TITLE,TITLE_JPN,THUMB,CATEGORY,POSTED,UPLOADER,RATING,SIMPLE_LANGUAGE,STATE,LEGACY,TIME,LABEL) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (999999004, 'abcdef1234', '漫画B目录', '', '', 0x400, '', '', 0.0, None, 3, 0, 1, '漫画'))
c.commit(); c.close()

r = S.reconcile_downloads(dldir)
print('reconcile result:', r)
c = sqlite3.connect(tmp_db)
print('orphan 999999099 still exists?', c.execute('select count(*) from DOWNLOADS where GID=999999099').fetchone()[0])
print('comicB DOWNLOADS rows:', c.execute('select GID,LABEL,STATE from DOWNLOADS where GID=999999004').fetchall())
print('total DOWNLOADS:', c.execute('select count(*) from DOWNLOADS').fetchone()[0])
c.close()

_c.set(_c.KEY_DB_PATH, orig)
shutil.rmtree(tmp, ignore_errors=True)
print('DONE')
