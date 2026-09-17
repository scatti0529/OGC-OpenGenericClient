# -*- coding: utf-8 -*-
"""验证三个模块离线页的索引路径接线。"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == 'win32':
    site_packages = os.path.join(BASE_DIR, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

# 1. JMComic
from services.jmcomic_service import JMComicService
from pages.album.jmcomic_reader import JMComicReaderPage

svc = JMComicService()
p = JMComicReaderPage(svc)
print("[info] JM root:", p.offline_tab.scan_root)
print("[info] JM index:", p.offline_tab.index_path)
# 索引已统一收进 data/offline_index/（旧位置是下载根目录下的 .jmcomic_offline_index.json）
assert p.offline_tab.index_path.endswith('jmcomic_offline_index.json')
assert os.path.join('data', 'offline_index') in p.offline_tab.index_path.replace('/', os.sep)
print("[OK] JMComic 离线页索引接线")

# 2. E-Hentai
from pages.album.ehentai_reader import EhentaiReaderPage

eh = EhentaiReaderPage()
print("[info] EH root:", eh.offline_tab.scan_root)
print("[info] EH index:", eh.offline_tab.index_path)
assert eh.offline_tab.index_path.endswith('ehentai_offline_index.json')
assert os.path.join('data', 'offline_index') in eh.offline_tab.index_path.replace('/', os.sep)
print("[OK] E-Hentai 离线页索引接线")

# 3. EasyCopy
from pages.album.easycopy_offline import OfflineTab as EcTab

ec = EcTab()
print("[info] EC root:", ec._scan_root)
print("[info] EC index:", ec._index_path)
assert 'easycopy' in ec._index_path
print("[OK] EasyCopy 离线页索引接线")

# 4. 索引读写与失效钩子一致性（路径与下载器失效逻辑相同）
from services.comic_library import default_index_path, invalidate_index

dl_root = ec._scan_root
idx = default_index_path(dl_root, 'easycopy')
assert idx == ec._index_path, (idx, ec._index_path)
print("[OK] EasyCopy 索引路径与下载器失效路径一致")

print("\n索引接线验证通过")
