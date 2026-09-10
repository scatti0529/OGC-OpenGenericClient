# coding:utf-8
"""渲染 MediaOfflineViewer：确认 图片/视频 分两个列表 + 选中项暗红色。"""
import os, sys, tempfile, time, base64
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.setdefault('QT_LOGGING_RULES', 'default.warning=false')
site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
app = QApplication.instance() or QApplication(sys.argv)

from services import download_manager as dm
import pages.video.media_offline as mo
from pages.video.media_offline import MediaOfflineViewer

PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

real_root = dm.get_download_root
tmp_root = tempfile.mkdtemp(prefix='ogc_view_')
dm.get_download_root = lambda: tmp_root
try:
    base = os.path.join(tmp_root, 'bilibili-download')
    for sub in ('images', 'videos'):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    imgs = ['a_封面.png', 'b_第二张.png']
    vids = ['v_正片.mp4', 'w_预告.mp4']
    for i, f in enumerate(imgs):
        p = os.path.join(base, 'images', f)
        with open(p, 'wb') as fh:
            fh.write(PNG)
        os.utime(p, (time.time() - i * 100, time.time() - i * 100))  # 不同 mtime
    for i, f in enumerate(vids):
        p = os.path.join(base, 'videos', f)
        with open(p, 'wb') as fh:
            fh.write(b'\x00' * 512)
        os.utime(p, (time.time() - i * 50, time.time() - i * 50))

    viewer = MediaOfflineViewer('bilibili', '哔哩哔哩')
    viewer.resize(1000, 700)
    # 选中一条（验证暗红色）
    if viewer.video_list.count():
        it = viewer.video_list.item(0)
        viewer.video_list.setCurrentItem(it)

    # 默认名称排序
    print('default sort_key =', viewer._sort_key)
    img_names = [viewer.image_list.item(i).text() for i in range(viewer.image_list.count())]
    vid_names = [viewer.video_list.item(i).text() for i in range(viewer.video_list.count())]
    print('IMG list:', img_names)
    print('VID list:', vid_names)
    print('image_list.count=', viewer.image_list.count(), 'video_list.count=', viewer.video_list.count())
    pop = viewer.video_list.palette()
    print('video_list has item:selected stylesheet:', '8B0000' in viewer.video_list.styleSheet())

    viewer.show()
    app.processEvents()
    pix = viewer.grab()
    out = os.path.join(os.path.dirname(__file__), '_offline_viewer.png')
    pix.save(out)
    print('saved', out, pix.width(), pix.height())

    # 切到下载时间排序（验证真的重排：应把 v_正片 放前面，因为 mtime 更新）
    viewer.sort_combo.setCurrentIndex(1)
    app.processEvents()
    vid_names2 = [viewer.video_list.item(i).text() for i in range(viewer.video_list.count())]
    print('after time sort sort_key =', viewer._sort_key, 'VID list:', vid_names2)
finally:
    dm.get_download_root = real_root
    import shutil
    shutil.rmtree(tmp_root, ignore_errors=True)
