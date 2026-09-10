# -*- coding: utf-8 -*-
"""阅读器“一直加载中”修复回归测试（离屏，纯本地，不联网/不碰库）。

覆盖三个症状：
1. 快速翻页后部分页被 pool.clear() 丢弃、登记残留 → 永远加载中（ReaderWindow）；
2. 页面异步加载完成但界面不刷新 → 一直停在“加载中”（ReaderWindow pageReady 未连接）；
3. 加载失败无提示、无重试入口 → 默默停在“加载中”（ReaderWindow + ComicReaderPage）。
"""
import os
import sys
import time
import tempfile
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == 'win32':
    site_packages = os.path.join(BASE_DIR, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QColor
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)

# 让测试不污染真实数据目录
_tmp = tempfile.mkdtemp(prefix='ogc_reader_test_')
import ehviewer.ui.reader_window as rwmod
rwmod.PROGRESS_PATH = os.path.join(_tmp, 'progress.json')
rwmod.READER_CACHE_DIR = os.path.join(_tmp, 'reader_cache')


def _mkimg(path, w=360, h=520, rgb=(200, 60, 60), tag=0):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(*rgb))
    # 加点可辨识内容，避免全部纯色
    for y in range(0, h, 24):
        for x in range(0, w, 24):
            img.setPixelColor(x, y, QColor((tag * 37) % 255, 90, (tag * 73) % 255))
    assert img.save(path, 'JPG', 92), 'save fail ' + path
    return path


def _wait(cond, timeout_ms=3000, step=25):
    """等待条件成立（每 25ms 处理一次事件循环）。"""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        QTest.qWait(step)
        if cond():
            return True
    return False


class _Info:
    """ReaderWindow 只用到这几个字段/方法，做鸭子类型即可。"""

    def __init__(self, gid, pages, title='测试漫画'):
        self.gid = gid
        self.token = 'testtoken'
        self.pages = pages
        self.title = title

    def suitable_title(self, show_jpn=False):
        return self.title


_failures = []


def check(name, ok, detail=''):
    print(('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name,
                            ('' if ok else ('  -> ' + str(detail))))))
    if not ok:
        _failures.append(name)


# ════════════════════════════════════════════════════════════════
# 1) ReaderWindow 本地（离线）阅读：快速翻页不残留“加载中”
# ════════════════════════════════════════════════════════════════
print('== 1. ReaderWindow 快速翻页（1 线程 + 慢本地解码 模拟排队被清）==')
dir1 = os.path.join(_tmp, 'g1')
os.makedirs(dir1, exist_ok=True)
files1 = [_mkimg(os.path.join(dir1, 'p%03d.jpg' % i), tag=i) for i in range(16)]

r = rwmod.ReaderWindow(_Info(10001, len(files1)), 0, None, local_files=files1)
r.resize(900, 700)
r.show()
check('1a 首页自动显示（pageReady 已连接并刷新）',
      _wait(lambda: 0 in r._images, timeout_ms=3000))
check('1a2 首页无失败提示', not r._failed_current)

# 构造旧版必现的残留场景：单线程 + 每页解码 120ms
r._pool.setMaxThreadCount(1)
_orig_load_local = rwmod.ReaderWindow._load_local

def _slow_local(self, index):
    time.sleep(0.12)
    return _orig_load_local(self, index)

r._load_local = _slow_local.__get__(r, rwmod.ReaderWindow)

r._show_page(0)
r._on_nav_timeout()            # 请求 0/1/2，0 正在跑（慢）
QTest.qWait(40)
r._show_page(4)
r._on_nav_timeout()            # 旧代码：clear() 会把排队的 1/2 丢掉且登记残留
QTest.qWait(1500)              # 等线程池排空

stuck = []
for i in (1, 2, 3, 4, 5, 6):
    r._show_page(i)
    ok = _wait(lambda i=i: i in r._images, timeout_ms=2500)
    if not ok:
        stuck.append(i)
check('1b 快速翻页后的每一页最终都能显示（不再永久加载中）',
      not stuck, 'stuck pages: %s' % stuck)

# 卷轴模式：图片异步就绪后必须自动刷新滚动条目
r2 = rwmod.ReaderWindow(_Info(10002, len(files1)), 0, None, local_files=files1)
r2.resize(900, 700)
r2.show()
r2._style = 'scroll'
r2._apply_style()
r2._rebuild_scroll()

def _scroll_painted(n=3):
    def _has(lbl):
        p = lbl.pixmap()
        return p is not None and not p.isNull()
    return sum(1 for i, lbl in r2._scroll_items.items() if _has(lbl)) >= n

check('1c 卷轴条目自动刷出图片（pageReady 连接修复）',
      _wait(_scroll_painted, timeout_ms=3000))
QTest.qWait(150)
r2.close()
r.close()

# ════════════════════════════════════════════════════════════════
# 2) ReaderWindow：页面失败有提示，且可点击重试
# ════════════════════════════════════════════════════════════════
print('== 2. ReaderWindow 缺页失败提示 + 点击重试 ==')
dir2 = os.path.join(_tmp, 'g2')
os.makedirs(dir2, exist_ok=True)
good0 = _mkimg(os.path.join(dir2, 'p000.jpg'), tag=0)
bad1 = os.path.join(dir2, 'p001.jpg')
with open(bad1, 'wb') as f:          # 损坏/非图片 → QImage 解码失败
    f.write(b'\x00\x01\x02 broken' * 50)
good2 = _mkimg(os.path.join(dir2, 'p002.jpg'), tag=2)

files2 = [good0, bad1, good2]
r3 = rwmod.ReaderWindow(_Info(10003, len(files2)), 0, None, local_files=files2)
r3.resize(900, 700)
r3.show()
QTest.qWait(150)
r3._show_page(1)
r3._on_nav_timeout()
check('2a 缺页显示“加载失败”提示（不永远加载中）',
      _wait(lambda: r3._failed_current and '加载失败' in r3._page_view.text(),
            timeout_ms=2500),
      repr(r3._page_view.text()))
# “修复”缺页文件后点击重试
os.replace(good0, good0)  # no-op keep
r3._local_files[1] = _mkimg(os.path.join(dir2, 'p001_ok.jpg'), tag=5)
r3._retry_current()
check('2b 点击重试后缺页被加载显示',
      _wait(lambda: 1 in r3._images, timeout_ms=2500),
      repr(r3._page_view.text()))
r3.close()

# ════════════════════════════════════════════════════════════════
# 3) ComicReaderPage（拷贝/JM 通用阅读器）失败提示 + 重试
# ════════════════════════════════════════════════════════════════
print('== 3. ComicReaderPage 失败提示 + 点击重试 ==')
from pages.album.easycopy_reader import ComicReaderPage, VIEW_PAGE


class _LocalFetcher:
    def fetch(self, path):
        try:
            with open(path, 'rb') as f:
                return f.read()
        except Exception:
            return None


dir3 = os.path.join(_tmp, 'g3')
os.makedirs(dir3, exist_ok=True)
c0 = _mkimg(os.path.join(dir3, 'c000.jpg'), tag=1)
c_missing = os.path.join(dir3, 'c_missing.jpg')   # 不存在
c2 = _mkimg(os.path.join(dir3, 'c002.jpg'), tag=2)

cr = ComicReaderPage(_LocalFetcher())
cr.resize(900, 700)
cr.show()
cr.load('本地章节', [c0, c_missing, c2], is_local=True)
cr.set_mode(VIEW_PAGE)
check('3a 首页正常加载', _wait(lambda: 0 in cr._pixmaps, timeout_ms=2500))
cr._next_page()   # 到缺页
check('3b 缺页显示“加载失败”提示',
      _wait(lambda: '加载失败' in (cr._page_label.text() or ''), timeout_ms=2500),
      repr(cr._page_label.text()))
# 点击重试（此时文件仍缺失 → 仍失败但有提示；不无限刷线程）
cr._retry_current_failed()
ok2 = _wait(lambda: 1 in cr._pixmaps, timeout_ms=800)
check('3c 文件仍缺时重试不崩溃、提示保持',
      not ok2 and '加载失败' in (cr._page_label.text() or ''),
      repr(cr._page_label.text()))
# 补齐文件后重试成功
c_missing2 = _mkimg(os.path.join(dir3, 'c_missing2.jpg'), tag=9)
cr._sources[1] = c_missing2
cr._retry_current_failed()
check('3d 补齐文件后点击重试成功显示',
      _wait(lambda: 1 in cr._pixmaps and not (cr._page_label.text() or ''), timeout_ms=2500),
      repr(cr._page_label.text()))
# 翻页到 2 正常
cr._next_page()
check('3e 后续页翻页正常', _wait(lambda: 2 in cr._pixmaps, timeout_ms=2500))
cr.close()

print()
if _failures:
    print('FAILED: %d 项 -> %s' % (len(_failures), _failures))
    sys.exit(1)
print('阅读器修复回归测试全部通过')
shutil.rmtree(_tmp, ignore_errors=True)
