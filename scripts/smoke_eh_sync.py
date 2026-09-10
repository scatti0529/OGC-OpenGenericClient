# -*- coding: utf-8 -*-
"""冒烟：下载->分类->数据库同步。测试 ehentai_sync + DownloadPage 分类下拉。"""
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

from pages.album import ehentai_sync as S
print('extract_gid_token:', S.extract_gid_token('https://e-hentai.org/g/4103360/b865187d64/'))
print('labels:', S.read_download_labels())
# 写一条测试记录（假 gid），验证写入 + 清理
url = 'https://e-hentai.org/g/999999003/abc12345/'
print('sync(ok) =', S.sync_download_to_db(url, '同步测试·虚拟', label='', state=3))
print('add_label(测试分类) =', S.add_label('测试分类'))
import sqlite3
c = sqlite3.connect(S.db_path())
row = c.execute("SELECT GID,TOKEN,TITLE,LABEL,STATE FROM DOWNLOADS WHERE GID=?", (999999003,)).fetchone()
print('downloaded row:', row)
c.close()

# DownloadPage 分类下拉
from pages.album.ehentai_page import DownloadPage
dp = DownloadPage()
dp.resize(900, 700); dp.show(); app.processEvents()
print('category_combo count:', dp.category_combo.count())
print('combo items:', [(dp.category_combo.itemText(i), dp.category_combo.itemData(i)) for i in range(dp.category_combo.count())])
dp.set_category('测试分类')
print('set_category(测试分类) -> current_category:', repr(dp.current_category()),
      '| comboData:', repr(dp.category_combo.currentData()))
dp.set_category('')
print('current_category reset:', repr(dp.current_category()))

# 清理
c = sqlite3.connect(S.db_path())
c.execute("DELETE FROM DOWNLOADS WHERE GID=?", (999999003,))
c.execute("DELETE FROM DOWNLOAD_LABELS WHERE LABEL=?", ('测试分类',))
c.commit(); c.close()
print('cleaned; exists:', S.extract_gid_token(url))
print('DONE')
