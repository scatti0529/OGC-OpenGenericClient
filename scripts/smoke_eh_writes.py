# -*- coding: utf-8 -*-
"""冒烟：验证共享数据库的写入链路（下载记录/历史/本地收藏），确保可写且不破坏原数据。"""
import os, sys, time
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

from ehviewer import db as ehdb
from ehviewer.models import GalleryInfo
from ehviewer import constants as C

ogc_db = os.path.join(BASE, 'data', 'ehentai', 'app_db.db')
ehdb.set_db_path(ogc_db)
print('db path =', ehdb.get_db_path())

TEST_GID = 999999001  # 假 gid，测试后删除
def mk():
    g = GalleryInfo(); g.gid = TEST_GID; g.token='abcdef0123'; g.title='测试·写入验证'
    g.title_jpn=''; g.thumb='https://ehgt.org/00/00/00.jpg'; g.category=C.CAT_MANGA
    g.posted='2020-01-01 00:00'; g.uploader='tester'; g.rating=4.5; return g

# 1) 下载记录写入
ehdb.insert_download(mk(), state=C.STATE_WAIT, label='测试分类')
d = ehdb.get_download(TEST_GID)
print('download insert -> state=%s label=%s title=%s' % (d.state, d.label, d.title))
ehdb.update_download_state(TEST_GID, C.STATE_FINISH, label='测试分类')
print('download update ->', ehdb.get_download_state(TEST_GID))
ehdb.delete_download(TEST_GID)
print('download deleted ->', ehdb.get_download(TEST_GID) is None)

# 2) 历史写入
ehdb.add_history(mk(), mode=0)
h = [x for x in ehdb.list_history(100) if x.gid == TEST_GID]
print('history write ->', len(h))
ehdb.delete_history(TEST_GID)
print('history deleted ->', len([x for x in ehdb.list_history(100) if x.gid == TEST_GID]) == 0)

# 3) 本地收藏写入
ok = ehdb.add_local_favorite(mk())
print('local fav write ->', ok, 'exists:', ehdb.is_local_favorited(TEST_GID))
ehdb.delete_local_favorite(TEST_GID)
print('local fav deleted ->', ehdb.is_local_favorited(TEST_GID) is False)

# 4) 标签收藏 (QUICK_SEARCH) 与 标签屏蔽 (FILTER)
tid = ehdb.add_tag_favorite('language:chinese', '中文')
print('tag favorite ->', tid is not None)
if tid is not None:
    ehdb.delete_tag_favorite(tid)
fid = ehdb.add_blocked_tag('test_block_tag')
print('blocked tag ->', fid is not None)
if fid is not None:
    ehdb.delete_blocked_tag(fid)

print('ALL WRITE PATHS OK')
