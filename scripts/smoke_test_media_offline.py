# -*- coding: utf-8 -*-
"""离线删除/排序 + 视频平台离线查看器 冒烟测试：
1. comic_library 时间/删除辅助函数
2. 离线阅读排序（名称/下载时间）+ 章节/漫画删除结构（按钮与信号）
3. MediaOfflineViewer：本地扫描、列表分组、图片查看、视频加载、删除刷新
4. PlatformPage / DouyinPage / PixivPage 集成（选项卡切换）
"""
import base64
import os
import shutil
import sys
import tempfile
import time
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# ── Qt 环境（模块级，保证 QApplication 不会被 GC 销毁）──
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication
_APP = QApplication.instance() or QApplication(sys.argv)  # 模块级单例，勿删

FAILURES = []


def step(name, fn):
    try:
        fn()
        print(f'[OK] {name}')
    except Exception:
        FAILURES.append(name)
        print(f'[FAIL] {name}')
        traceback.print_exc()


PNG_1PX = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)


def test_comic_library_helpers():
    from services.comic_library import comic_download_time, delete_local_path, LocalComic
    tmp = tempfile.mkdtemp(prefix='ogc_lib_')
    try:
        comic_dir = os.path.join(tmp, '漫画A')
        os.makedirs(os.path.join(comic_dir, '第1话'), exist_ok=True)
        f = os.path.join(comic_dir, '第1话', '001.jpg')
        with open(f, 'wb') as fh:
            fh.write(PNG_1PX)
        comic = LocalComic(title='漫画A', path=comic_dir)
        t = comic_download_time(comic)
        assert t > 0, 'comic_download_time 应为正数'
        assert abs(t - os.path.getmtime(f)) < 2, 'mtime 不一致'
        assert delete_local_path(os.path.join(comic_dir, '第1话')) is True
        assert not os.path.exists(os.path.join(comic_dir, '第1话'))
        assert delete_local_path(comic_dir) is True
        assert not os.path.exists(comic_dir)
        print('  comic_library helpers OK')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_offline_library_sort_and_delete_structure():
    from services.comic_library import scan_comics
    from pages.album.comic_offline import OfflineLibraryTab, OfflineComicPage

    tmp = tempfile.mkdtemp(prefix='ogc_offline_')
    try:
        # 构造 2 部漫画：漫画A 最后写入（mtime 最新）
        for name, delay in (('漫画B', 1.0), ('漫画A', 0.2)):
            d = os.path.join(tmp, name, '第1话')
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, '001.jpg'), 'wb') as fh:
                fh.write(PNG_1PX)
            time.sleep(delay)
        comics = scan_comics(tmp)
        assert len(comics) == 2

        tab = OfflineLibraryTab(scan_root=tmp, index_path='')
        tab.load()
        deadline = time.time() + 8
        while not tab._comics and time.time() < deadline:
            _APP.processEvents()
            time.sleep(0.05)
        assert len(tab._comics) == 2, '扫描结果为空'
        tab._sort_key = 'name'
        names = [c.title for c in tab._apply_sort(list(tab._comics))]
        assert names == ['漫画A', '漫画B'], f'名称排序错误: {names}'
        tab._sort_key = 'time_desc'
        names = [c.title for c in tab._apply_sort(list(tab._comics))]
        assert names == ['漫画A', '漫画B'], f'下载时间（新→旧）排序错误: {names}'
        print('  排序：名称 / 下载时间 OK')

        comic_page = OfflineComicPage()
        assert hasattr(comic_page, 'delete_comic_btn')
        assert hasattr(comic_page, 'chapter_deleted') and hasattr(comic_page, 'comic_deleted')
        comic = comics[0]
        comic_page.load_comic(comic)
        _APP.processEvents()
        from qfluentwidgets import PushButton
        found_del = any(btn.text() == '删除' for btn in comic_page.findChildren(PushButton))
        assert found_del, '章节单元格缺少「删除」按钮'
        print('  离线漫画页：删除漫画按钮 + 章节删除按钮 OK')
        comic_page.deleteLater()
        tab.deleteLater()
        _APP.processEvents()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_media_offline_viewer():
    import services.download_manager as dm
    from pages.video.media_offline import MediaOfflineViewer

    tmp_root = tempfile.mkdtemp(prefix='ogc_media_')
    real_root = dm.get_download_root
    dm.get_download_root = lambda: tmp_root
    try:
        plat_dir = os.path.join(tmp_root, 'bilibili-download')
        img_dir = os.path.join(plat_dir, 'images')
        vid_dir = os.path.join(plat_dir, 'videos')
        os.makedirs(img_dir, exist_ok=True)
        os.makedirs(vid_dir, exist_ok=True)
        with open(os.path.join(img_dir, '封面.png'), 'wb') as fh:
            fh.write(PNG_1PX)
        with open(os.path.join(vid_dir, '正片.mp4'), 'wb') as fh:
            fh.write(b'\x00' * 1024)

        viewer = MediaOfflineViewer('bilibili', '哔哩哔哩')
        viewer.resize(1000, 700)
        viewer.show()
        _APP.processEvents()

        kinds = {e['label']: e['kind'] for e in viewer._offline_entries}
        assert 'images/封面.png' in kinds and kinds['images/封面.png'] == 'image'
        assert 'videos/正片.mp4' in kinds and kinds['videos/正片.mp4'] == 'video'
        assert viewer.image_list.count() >= 1, '图片列表应有文件'
        assert viewer.video_list.count() >= 1, '视频列表应有文件'
        print('  离线扫描 + 图片/视频分列表 OK:', kinds)

        img_item = None
        for i in range(viewer.image_list.count()):
            it = viewer.image_list.item(i)
            data = it.data(0x0100)
            if data and data.get('label') == 'images/封面.png':
                img_item = it
                break
        assert img_item is not None
        viewer._on_item_clicked(img_item)
        _APP.processEvents()
        assert viewer.view_stack.currentIndex() == 1, '图片查看器未切换'
        pix = viewer.image_label.pixmap()
        assert pix is not None and not pix.isNull(), '本地图片未加载'

        vid_item = None
        for i in range(viewer.video_list.count()):
            it = viewer.video_list.item(i)
            data = it.data(0x0100)
            if data and data.get('label') == 'videos/正片.mp4':
                vid_item = it
                break
        assert vid_item is not None
        viewer._on_item_clicked(vid_item)
        _APP.processEvents()
        assert viewer.view_stack.currentIndex() == 2, '播放器未切换'
        if viewer._player is not None:
            viewer._stop_video()

        # 排序切换：选择「下载时间（新→旧）」应切换排序键并重建列表
        viewer.sort_combo.setCurrentIndex(1)
        _APP.processEvents()
        assert viewer._sort_key == 'time_desc', '切换下载时间排序未生效'
        assert viewer.image_list.count() >= 1 and viewer.video_list.count() >= 1
        viewer.sort_combo.setCurrentIndex(0)
        _APP.processEvents()
        assert viewer._sort_key == 'name', '切回名称排序未生效'
        print('  排序切换（名称/下载时间）OK')

        # 删除选中（本地文件）后列表刷新
        os.remove(os.path.join(vid_dir, '正片.mp4'))
        viewer.refresh_offline()
        labels = [e['label'] for e in viewer._offline_entries]
        assert 'videos/正片.mp4' not in labels, '删除后列表未刷新'
        print('  图片查看 / 视频播放 / 删除刷新 OK')
        viewer.deleteLater()
        _APP.processEvents()
    finally:
        dm.get_download_root = real_root
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_platform_pages_integration():
    from pages.video.video_multiplatform_page import PlatformPage
    from pages.video.douyin_page import DouyinPage
    from pages.video.pixiv_page_ui import PixivPage

    for page in (PlatformPage('xvideo', 'Xvideo'),
                 PlatformPage('twitter', '推特(X)'),
                 PlatformPage('bilibili', '哔哩哔哩'),
                 DouyinPage(),
                 PixivPage()):
        page.resize(1000, 700)
        page.show()
        _APP.processEvents()
        assert hasattr(page, '_offline_viewer'), f'{page.__class__.__name__} 缺少离线查看器'
        assert page._root_stack.currentIndex() == 0
        page._set_view(1)
        _APP.processEvents()
        assert page._root_stack.currentIndex() == 1
        page._set_view(0)
        assert page._root_stack.currentIndex() == 0
        print(f'  {page.__class__.__name__} 集成 OK')
        page.close()
        page.deleteLater()
        _APP.processEvents()


if __name__ == '__main__':
    step('comic_library_helpers', test_comic_library_helpers)
    step('offline_sort_and_delete', test_offline_library_sort_and_delete_structure)
    step('media_offline_viewer', test_media_offline_viewer)
    step('platform_pages_integration', test_platform_pages_integration)

    if FAILURES:
        print('RESULT: FAILED ->', FAILURES)
        sys.exit(1)
    print('RESULT: ALL PASSED')
