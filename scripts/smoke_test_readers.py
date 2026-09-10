# -*- coding: utf-8 -*-
"""拷贝漫画阅读器增强 + JMComic/E-Hentai 阅读模块冒烟测试。"""
import os
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == 'win32':
    site_packages = os.path.join(BASE_DIR, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)


class _FakeFetcher:
    """本地文件 fetcher（测试用）。"""

    def fetch(self, path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            return None

# 1. 通用漫画库扫描
from services.comic_library import scan_comics, natural_key, has_done_marker

tmp = tempfile.mkdtemp()

# 扁平形态（E-Hentai）：root/画廊名/图片
gallery = os.path.join(tmp, "画廊A")
os.makedirs(gallery, exist_ok=True)
for i in (1, 2, 10):
    with open(os.path.join(gallery, f"{i}-1.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff")
with open(os.path.join(gallery, ".ehentai_done"), "w") as f:
    f.write("2026-01-01")

# 章节层形态（JMComic）：root/漫画名/章节名/图片
comic = os.path.join(tmp, "漫画B", "第2话")
os.makedirs(comic, exist_ok=True)
with open(os.path.join(comic, "0001.png"), "wb") as f:
    f.write(b"\x89PNG")
with open(os.path.join(comic, ".jmcomic_done"), "w") as f:
    f.write("2026-01-01")
# 单章漫画：root/漫画名/图片（省略章节层）
single = os.path.join(tmp, "漫画C")
os.makedirs(single, exist_ok=True)
with open(os.path.join(single, "0001.jpg"), "wb") as f:
    f.write(b"\xff\xd8\xff")

comics = scan_comics(tmp)
assert len(comics) == 3, [c.title for c in comics]
by_title = {c.title: c for c in comics}
assert by_title["画廊A"].flat is True
assert by_title["画廊A"].total_images == 3
assert by_title["画廊A"].chapters[0].is_done is True
assert by_title["漫画B"].flat is False
assert by_title["漫画B"].total_chapters == 1
assert by_title["漫画B"].chapters[0].is_done is True
assert by_title["漫画C"].flat is True
assert by_title["漫画C"].total_images == 1
print("[OK] comic_library 扫描（扁平/章节层/单章/完成标记）")

# 2. 阅读器：翻页/滚轮/键盘/Ctrl+滚轮切换适配
from pages.album.easycopy_reader import ComicReaderPage, VIEW_PAGE, VIEW_SCROLL

fetcher = _FakeFetcher()
reader = ComicReaderPage(fetcher)
reader.load("测试", [os.path.join(gallery, "1-1.jpg"), os.path.join(gallery, "2-1.jpg")], is_local=True)

# 滚轮翻页
reader.set_mode(VIEW_PAGE)
assert reader._view_mode == VIEW_PAGE
reader._next_page()
assert reader._current_index == 1
reader._prev_page()
assert reader._current_index == 0

# 键盘翻页
from PyQt5.QtGui import QKeyEvent
def _key(key):
    return QKeyEvent(QKeyEvent.KeyPress, key, Qt.NoModifier)
reader.keyPressEvent(_key(Qt.Key_Right))
assert reader._current_index == 1, reader._current_index
reader.keyPressEvent(_key(Qt.Key_Left))
assert reader._current_index == 0

# Ctrl+滚轮切换适配
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtCore import QPoint, QPointF
def _wheel(ctrl=False):
    mods = Qt.ControlModifier if ctrl else Qt.NoModifier
    return QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, mods, Qt.NoScrollPhase, False)
reader.set_mode(VIEW_SCROLL)
assert reader._scroll_fit_whole is False
reader.handle_wheel(_wheel(ctrl=True))
assert reader._scroll_fit_whole is True
reader.handle_wheel(_wheel(ctrl=True))
assert reader._scroll_fit_whole is False
print("[OK] 阅读器：翻页/滚轮/键盘/Ctrl+滚轮适配切换")

# 3. 离线阅读 UI 复用组件
from pages.album.comic_offline import OfflineLibraryTab, OfflineComicPage, OfflineReaderPage

tab = OfflineLibraryTab(scan_root=tmp)
assert tab is not None
comic_page = OfflineComicPage()
assert comic_page is not None
reader_page = OfflineReaderPage()
reader_page.load_chapter(by_title["画廊A"], by_title["画廊A"].chapters[0])
reader_page.reader.set_mode(VIEW_PAGE)
print("[OK] 通用离线阅读组件实例化 + 本地章节加载")

# 4. JMComic 目录规则（单章省略章节层）
from services.jmcomic_service import _register_ogc_option, _get_ogc_option_class
import jmcomic
_register_ogc_option()
assert jmcomic.JmModuleConfig.CLASS_OPTION is not None
base2 = tempfile.mkdtemp()
opts = {'dir_rule': {'base_dir': base2, 'rule': 'Bd/Atitle/Ptitle'},
        'download': {'image': {'suffix': '.jpg'}, 'threading': {'photo': 1, 'image': 2}},
        'client': {'impl': 'api'}}
o = jmcomic.JmModuleConfig.option_class().construct(opts)
assert type(o.dir_rule).__name__ == 'OgcJmDirRule'

class FakePhoto:
    is_single_album = True
    from_album = None
    title = '单章'
class FakeAlbum:
    title = '单章'
p_single = o.dir_rule.decide_image_save_dir(FakeAlbum(), FakePhoto())
assert os.path.relpath(p_single, base2) == '单章', os.path.relpath(p_single, base2)

class FakePhoto2:
    is_single_album = False
    from_album = object()
    title = '第1话'
p_multi = o.dir_rule.decide_image_save_dir(FakeAlbum(), FakePhoto2())
assert os.path.relpath(p_multi, base2).replace('\\', '/') == '单章/第1话', os.path.relpath(p_multi, base2)
print("[OK] JMComic 目录规则：单章省略章节名")

# 5. UI 实例化：JMComic 阅读页 / E-Hentai 阅读页 / EasyCopyPage
from services.jmcomic_service import JMComicService
from pages.album.jmcomic_reader import JMComicReaderPage, OnlineReadTab, OnlineChapterReader

svc = JMComicService()
jm_reader = JMComicReaderPage(svc)
assert jm_reader.online_tab is not None
assert jm_reader.offline_tab is not None
print("[OK] JMComicReaderPage 实例化")

from pages.album.ehentai_reader import EhentaiReaderPage, OnlineGalleryReader
eh_reader = EhentaiReaderPage()
assert eh_reader.online_tab is not None
assert eh_reader.offline_tab is not None
print("[OK] EhentaiReaderPage 实例化")

from pages.album.easycopy_page import EasyCopyPage
page = EasyCopyPage()
assert 'easycopyOfflineTab' in page.pivot.items
print("[OK] EasyCopyPage 6 标签页实例化")

# 6. main_window 集成
import ui.main_window as mw
print("[OK] main_window 导入")

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("\n阅读器增强 + JM/E-Hentai 阅读模块冒烟测试全部通过")
