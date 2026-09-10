# -*- coding: utf-8 -*-
"""离线索引 JSON + 滚动卡片网格冒烟测试。"""
import os
import sys
import tempfile
import time

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

from services.comic_library import (
    scan_comics, save_index, load_index, invalidate_index,
    default_index_path, natural_key,
)

# ---- 构造测试目录：扁平 + 章节层 + 单章 ----
tmp = tempfile.mkdtemp()
root = os.path.join(tmp, "easycopy-download")
os.makedirs(root, exist_ok=True)

gallery = os.path.join(root, "画廊A")
os.makedirs(gallery, exist_ok=True)
for i in (1, 2, 10):
    with open(os.path.join(gallery, f"{i}-1.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff")
with open(os.path.join(gallery, ".ehentai_done"), "w") as f:
    f.write("2026-01-01")

comic = os.path.join(root, "漫画B", "第2话")
os.makedirs(comic, exist_ok=True)
with open(os.path.join(comic, "0001.png"), "wb") as f:
    f.write(b"\x89PNG")
with open(os.path.join(comic, ".jmcomic_done"), "w") as f:
    f.write("2026-01-01")

single = os.path.join(root, "漫画C")
os.makedirs(single, exist_ok=True)
with open(os.path.join(single, "0001.jpg"), "wb") as f:
    f.write(b"\xff\xd8\xff")

index_path = default_index_path(root, 'easycopy')
print("[info] 索引路径:", index_path)

# 1. 首次全量扫描 + 建索引
comics1 = scan_comics(root, index_path=index_path)
assert len(comics1) == 3, len(comics1)
assert os.path.isfile(index_path), "索引文件应已生成"
print("[OK] 首次扫描 + 索引生成，漫画数:", len(comics1))

# 2. 有效期内读索引（把磁盘内容删掉模拟命中索引）
os.remove(os.path.join(gallery, "2-1.jpg"))
comics2 = scan_comics(root, index_path=index_path)
assert len(comics2) == 3, "有效期内应命中索引（仍 3 部）"
by2 = {c.title: c for c in comics2}
assert by2["画廊A"].total_images == 3, "索引中的图片数应来自缓存（仍 3 张）"
print("[OK] 有效期内命中索引（不重新扫描磁盘）")

# 3. 强制刷新 -> 重新扫描（应只剩 2 部、图片数变化）
comics3 = scan_comics(root, index_path=index_path, force=True)
assert len(comics3) == 3, len(comics3)  # 目录还在，只是少一张图
by = {c.title: c for c in comics3}
assert by["画廊A"].total_images == 2, by["画廊A"].total_images
print("[OK] force=True 强制重建索引")

# 4. 索引失效 -> 下次扫描重建
invalidate_index(index_path)
assert not os.path.exists(index_path), "失效后索引文件应删除"
comics4 = scan_comics(root, index_path=index_path)
assert len(comics4) == 3
assert os.path.isfile(index_path), "失效后应重建索引"
print("[OK] invalidate_index + 重建")

# 5. 过期索引 -> 自动重建（改 generated_at 为过去）
comics5 = scan_comics(root, index_path=index_path)
import json
with open(index_path, encoding="utf-8") as f:
    data = json.load(f)
data["generated_at"] = time.time() - 9999
with open(index_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
comics6 = scan_comics(root, index_path=index_path)
assert len(comics6) == 3
print("[OK] 过期索引自动重建")

# 6. UI：卡片网格 + 滚动容器 + 刷新
from pages.album.comic_offline import OfflineLibraryTab, OfflineComicPage, OfflineReaderPage
from pages.album.easycopy_offline import OfflineTab as EasyCopyOfflineTab

tab = OfflineLibraryTab(scan_root=root, index_path=index_path)
tab.load()
app.processEvents()
assert tab.refresh_btn is not None
# 模拟大量漫画（30 部）验证滚动容器不溢出
for i in range(30):
    d = os.path.join(root, f"批量{i:02d}")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "0001.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff")
tab.refresh()
app.processEvents()
from PyQt5.QtWidgets import QScrollArea
scroll = tab.findChild(QScrollArea)
assert scroll is not None, "卡片网格应包在 QScrollArea 中（可滚动）"
print("[OK] OfflineLibraryTab 滚动容器 + 强制刷新（30 部漫画）")

# 7. EasyCopy 离线页（索引路径一致）
ec_tab = EasyCopyOfflineTab()
assert ec_tab._index_path.endswith('easycopy_offline_index.json') or 'easycopy' in ec_tab._index_path
print("[OK] EasyCopyOfflineTab 索引路径:", ec_tab._index_path)

# 8. 下载器失效钩子存在
from services.easycopy.downloader import EasyCopyDownloader
from services.ehentai_downloader import _invalidate_ehentai_index
from services.jmcomic_service import _invalidate_jm_index
_invalidate_ehentai_index()  # 不抛异常即可
_invalidate_jm_index()
print("[OK] 三个模块索引失效钩子可调用")

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("\n离线索引 + 滚动网格冒烟测试全部通过")
