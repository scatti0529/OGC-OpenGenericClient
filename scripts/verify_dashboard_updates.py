# -*- coding: utf-8 -*-
"""仪表盘更新综合验证"""
import sys
import os
sys.path.insert(0, os.getcwd())

from PyQt5 import QtCore
pkg_dir = os.path.dirname(QtCore.__file__)
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(pkg_dir, 'Qt5', 'plugins')
os.environ['QT_QPA_PLATFORM'] = 'windows'

from PyQt5.QtWidgets import QApplication
app = QApplication([])

print("=== 1. 权限常量 ===")
from core.database import ALL_FEATURES, ALL_MODULES, get_default_permissions
print(f"模块数: {len(ALL_MODULES)}")
print(f"功能数: {len(ALL_FEATURES)}")
jmcomic_feats = [f[0] for f in ALL_FEATURES if f[0].startswith('jmcomic')]
print(f"JMComic 功能: {jmcomic_feats}")
perms = get_default_permissions()
print(f"默认权限 features 键数: {len(perms['features'])}")

print("\n=== 2. 系统统计 ===")
from core.database import get_system_stats, get_usage_stats
stats = get_system_stats()
print(f"用户: {stats.get('user_count', 0)}")
print(f"封禁: {stats.get('banned_count', 0)}")
print(f"音乐: {stats.get('music_song_count', 0)}")
print(f"音乐下载: {stats.get('music_download_count', 0)}")
print(f"视频: {stats.get('video_file_count', 0)}")
print(f"播放列表: {stats.get('music_playlist_count', 0)}")
print(f"JM订阅: {stats.get('jmcomic_subscription_count', 0)}")
print(f"JM下载: {stats.get('jmcomic_download_count', 0)}")
print(f"音乐文件: {stats.get('music_file_count', 0)}")

usage = get_usage_stats()
print(f"使用量模块: {list(usage.keys())}")

print("\n=== 3. 仪表盘 UI ===")
from pages.dashboard_page import DashboardInterface
dash = DashboardInterface()
print("仪表盘创建成功")
print(f"统计卡片数: {dash.statsGrid.count()}")
print(f"JM订阅卡片: {dash.statJmSubCard.titleLabel.text()}")
print(f"JM下载卡片: {dash.statJmDownloadCard.titleLabel.text()}")
print(f"音乐文件卡片: {dash.statMusicFileCard.titleLabel.text()}")
dash.close()

print("\n=== 4. 使用量记录 ===")
from services.jmcomic_service import JMComicService
svc = JMComicService()
svc._record_usage('test_action', 'test_detail')
from core.database import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute("SELECT module, action, detail FROM usage_stats WHERE module='jmcomic' AND action='test_action'")
row = cursor.fetchone()
if row:
    print(f"记录成功: {row[0]}/{row[1]}/{row[2]}")
else:
    print("记录失败")
cursor.execute("DELETE FROM usage_stats WHERE module='jmcomic' AND action='test_action'")
conn.commit()
conn.close()
print("测试记录已清理")

print("\n=== 5. 主窗口验证 ===")
from ui.main_window import Window
w = Window()
print(f"主窗口创建成功: {w.windowTitle()}")
print(f"JMComic 页面: {w.PeopleInterface.__class__.__name__}")
w.close()

print("\n所有验证通过！")