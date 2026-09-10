# -*- coding: utf-8 -*-
"""验证：阅读器 sizeHint 有界（避免画册阅读窗口高度异常 / 主窗口布局被撑爆）"""
import os
import sys
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtWidgets import QApplication, QWidget
_APP = QApplication.instance() or QApplication(sys.argv)


def step(name, fn):
    try:
        fn()
        print(f'[OK] {name}')
    except Exception:
        print(f'[FAIL] {name}')
        traceback.print_exc()
        sys.exit(1)


def test_reader_sizehint_bounded():
    from pages.album.easycopy_reader import ComicReaderPage
    from PyQt5.QtCore import QSize

    class Fetcher:
        def fetch(self, url):
            import base64
            return base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

    reader = ComicReaderPage(Fetcher())
    sources = [f'/tmp/fake_{i:04d}.jpg' for i in range(200)]  # 200 页大漫画
    reader.load('大漫画', sources, is_local=True)
    reader.resize(1000, 700)
    reader.show()
    _APP.processEvents()

    sh = reader.sizeHint()
    msh = reader.minimumSizeHint()
    print('  reader sizeHint =', sh, 'minimumSizeHint =', msh)
    assert sh.width() <= 900 and sh.height() <= 800, f'sizeHint 过大（会撑爆窗口）: {sh}'
    assert msh.height() <= 600, f'minimumSizeHint 过大: {msh}'

    # 包裹在一个容器里，模拟阅读器作为模块页子项，检查容器不会因此要求巨大高度
    wrap = QWidget()
    wrap.setObjectName('readerWrap')
    from PyQt5.QtWidgets import QVBoxLayout
    lay = QVBoxLayout(wrap)
    lay.addWidget(reader, 1)
    wrap.resize(1000, 700)
    wrap.show()
    _APP.processEvents()
    wsh = wrap.sizeHint()
    print('  wrap sizeHint =', wsh)
    assert wsh.height() <= 900, f'容器 sizeHint 过大: {wsh}'
    reader.close()
    wrap.close()


def test_main_window_not_bloated():
    # 主窗口构建后，minimumSizeHint / sizeHint 高度不应异常（阅读器等子项被收敛）
    import ui.main_window as mw
    win = mw.Window()
    win.resize(1080, 780)
    win.show()
    _APP.processEvents()
    msh = win.minimumSizeHint()
    sh = win.sizeHint()
    print('  main window minimumSizeHint =', msh, ' sizeHint =', sh)
    assert msh.width() <= 1400 and msh.height() <= 1400, f'主窗口最小尺寸过大: {msh}'
    win.close()


if __name__ == '__main__':
    step('reader_sizehint_bounded', test_reader_sizehint_bounded)
    step('main_window_not_bloated', test_main_window_not_bloated)
    print('RESULT: ALL PASSED')
