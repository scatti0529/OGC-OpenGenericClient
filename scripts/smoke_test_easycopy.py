# -*- coding: utf-8 -*-
"""拷贝漫画模块冒烟测试：验证导入、实例化、标签页切换、离线扫描、下载器路径。"""
import os
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Qt 平台插件路径修复（与 main.py 一致）
if sys.platform == 'win32':
    site_packages = os.path.join(BASE_DIR, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)
    os.environ.setdefault('QT_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

# 1. 服务层导入
from services.easycopy.config import DEFAULT_HOSTS, DESKTOP_USER_AGENT
from services.easycopy.parser import SiteHtmlParser, make_soup, to_simplified
from services.easycopy.downloader import (
    EasyCopyDownloadConfig, EasyCopyDownloader, EasyCopyProgress, DONE_MARKER,
)
from services.easycopy.local_library import scan_comics, easycopy_root, natural_key
print("[OK] 服务层导入")

# 2. 繁->简
assert to_simplified("畫冊熱門推薦") == "画册热门推荐"
print("[OK] to_simplified")

# 3. 自然排序
assert natural_key("第2话") < natural_key("第10话")
print("[OK] natural_key 排序")

# 4. 离线扫描（临时目录造数据）
tmp = tempfile.mkdtemp()
comic_dir = os.path.join(tmp, "easycopy-download", "测试漫画", "第1话")
os.makedirs(comic_dir, exist_ok=True)
for i in range(3):
    with open(os.path.join(comic_dir, f"{i+1:04d}.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff" + bytes([i]))
with open(os.path.join(comic_dir, DONE_MARKER), "w") as f:
    f.write("2026-01-01")
ch2 = os.path.join(tmp, "easycopy-download", "测试漫画", "第2话")
os.makedirs(ch2, exist_ok=True)
with open(os.path.join(ch2, "0001.png"), "wb") as f:
    f.write(b"\x89PNG")

from services.download_manager import get_download_root
print(f"[info] 实际下载根目录: {get_download_root()}")

import services.easycopy.local_library as ll
orig = ll.get_download_root if hasattr(ll, 'get_download_root') else None
# 用 monkeypatch 方式让 easycopy_root 指向临时目录
import services.easycopy.downloader as dl_mod

def fake_root():
    return tmp

ll.easycopy_root.__globals__['get_download_root'] = fake_root
# downloader.download_root 使用 config.output_root，这里直接构造 config
cfg = EasyCopyDownloadConfig(comic_title="测试漫画", chapter_label="第1话", chapter_href="/c/1", output_root=tmp)
d = EasyCopyDownloader(cfg)
root = d.download_root()
assert root == os.path.join(tmp, "easycopy-download"), root
assert d.chapter_dir() == os.path.join(tmp, "easycopy-download", "测试漫画", "第1话")
print("[OK] 下载路径:", d.chapter_dir())

comics = ll.scan_comics(tmp)
assert len(comics) == 1, comics
c0 = comics[0]
assert c0.title == "测试漫画"
assert c0.total_chapters == 2, c0.total_chapters
assert c0.total_images == 4, c0.total_images
assert c0.chapters[0].is_done is True
print(f"[OK] 离线扫描: {c0.title} 共{c0.total_chapters}话 {c0.total_images}张")

# 5. 下载器跳过已下载章节
class Listener:
    def __init__(self):
        self.logs = []
        self.progress = []
        self.finished = []
    def on_log(self, msg, level):
        self.logs.append((msg, level))
    def on_progress(self, p):
        self.progress.append(p)
    def on_finished(self, p):
        self.finished.append(p)

lis = Listener()
d2 = EasyCopyDownloader(EasyCopyDownloadConfig(comic_title="测试漫画", chapter_label="第1话",
                                               chapter_href="/c/1", output_root=tmp))
d2.set_listener(lis)
# 模拟 ctx：load_page_sync 直接返回 ReaderPageData（避免网络）
class FakeCtx:
    def load_page_sync(self, href):
        from services.easycopy.models import ReaderPageData
        return ReaderPageData(images=["https://example.com/1.jpg", "https://example.com/2.jpg"])
d2._ctx = FakeCtx()
# 已有完成标记 -> 跳过
p = d2.run()
assert p.skipped is True, p
assert any("[跳过]" in m for m, _ in lis.logs), lis.logs
print("[OK] 下载器跳过已下载章节")

# 6. UI 实例化
from pages.album.easycopy_page import EasyCopyPage

page = EasyCopyPage()
assert page is not None
assert page.pivot is not None
assert page.stackedWidget.count() == 6, page.stackedWidget.count()
assert page.detail_page is not None
assert page.reader_page is not None
assert page.offline_page is not None
assert page.offline_comic_page is not None
assert page.offline_reader_page is not None
# 分段导航项
routes = list(page.pivot.items.keys())
print("[info] 分段项:", routes)
assert 'easycopyOfflineTab' in routes
# 切换到离线标签页（扫描走线程 + 信号回主线程）
page.offline_page.load()
app.processEvents()
print("[OK] EasyCopyPage 实例化（6 个标签页 + 详情 + 阅读器 + 离线）")

# 7. 详情页与阅读器实例化
from pages.album.easycopy_detail import EasyCopyDetailPage, EasyCopyReaderPage
from pages.album.easycopy_offline import OfflineTab, OfflineComicPage, OfflineReaderPage
assert EasyCopyDetailPage(page.ctx)
assert EasyCopyReaderPage(page.ctx)
print("[OK] 详情页 / 阅读器实例化")

# 8. 共享阅读器基本行为（本地图片）
from pages.album.easycopy_reader import ComicReaderPage
reader = ComicReaderPage(page.ctx.image_fetcher)
reader.load("测试章节", [os.path.join(ch2, "0001.png")], is_local=True)
reader.set_mode("page")
reader.set_mode("scroll")
print("[OK] ComicReaderPage 本地图片加载 + 模式切换")

# 清理临时目录
import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("\n冒烟测试全部通过")
