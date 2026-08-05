# -*- coding: utf-8 -*-
"""抖音模块集成测试"""
import sys, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Qt 插件路径
site_packages = os.path.join(BASE_DIR, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(plugin_dir):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PyQt5.QtWidgets import QApplication
app = QApplication([])

from services.douyin_service import DouyinConfig, DouyinDownloader, DouyinProgressDB
print('1. douyin_service OK')

from pages.video.douyin_page import DouyinPage, extract_urls
print('2. douyin_page OK')

from pages.video.douyin_dialogs import DouyinConfigDialog, DouyinFeatureDialog
print('3. douyin_dialogs OK')

urls = extract_urls('测试 https://v.douyin.com/SlGTwuMq498/ 和 https://www.douyin.com/video/123 分享')
print('4. extract_urls:', urls)

page = DouyinPage()
print('5. DouyinPage OK')
print('   buttons:', page.parseBtn.text(), '|', page.configBtn.text(), '|', page.retryBtn.text())

cfg = DouyinConfig()
print('6. DouyinConfig OK, dir:', cfg.output_dir)

dlg = DouyinConfigDialog()
print('7. DouyinConfigDialog OK')

feat = DouyinFeatureDialog()
print('8. DouyinFeatureDialog OK')

with DouyinProgressDB() as db:
    db._conn.execute("DELETE FROM douyin_downloads WHERE aweme_id='test123'")
    db._conn.commit()
    db.record(
        aweme_id='test123', resource_type='one', resource_id='test123',
        mix_name='', desc='T', file_path='C:/tmp/t.mp4',
        url='https://x.com', meta={'width': 1920}, status='success'
    )
    ok = db.is_success_downloaded('test123')
    cnt = db.count_by_resource('test123')
    print('9. DB insert OK, is_success:', ok, ', count:', cnt)
    db._conn.execute("DELETE FROM douyin_downloads WHERE aweme_id='test123'")
    db._conn.commit()
    print('10. DB cleanup OK')

dl = DouyinDownloader()
print('11. DouyinDownloader OK, out:', dl.output_dir)
print('\nALL TESTS PASSED!')