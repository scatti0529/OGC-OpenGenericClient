# -*- coding: utf-8 -*-
"""下载队列编排测试（离屏；用 FakeWorker 模拟下载成功/失败，不联网不碰库）。"""
import os, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
if sys.platform == 'win32':
    sp = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
    pd = os.path.join(sp, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(pd, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', pd)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from types import SimpleNamespace

app = QApplication.instance() or QApplication(sys.argv)

import pages.album.ehentai_page as M

# ---- Fake 下载器 / Worker ----
OUTCOME = {}          # url -> 'ok' | 'fail'
STARTS = []           # 记录启动的 url 顺序
FAILED_URLS = {}


class FakeDL:
    def __init__(self):
        self._failed_tasks = []
        self._title = 'fake'
        self._output_path = ''
    def is_stopping(self):
        return False
    def stop(self):
        pass


class FakeWorker(QObject):
    log_emitted = pyqtSignal(str, str)
    progress_updated = pyqtSignal(object)
    finished_signal = pyqtSignal(object)

    def __init__(self, config, parent=None, retry_failed=False, downloader=None):
        super().__init__(parent)
        self.config = config
        self.downloader = downloader if downloader is not None else FakeDL()
        self._running = False

    def start(self):
        self._running = True
        STARTS.append(self.config.url)
        QTimer.singleShot(60, self._finish)

    def isRunning(self):
        return self._running

    def stop(self):
        pass

    def _finish(self):
        self._running = False
        url = self.config.url
        if OUTCOME.get(url) == 'fail':
            self.downloader._failed_tasks = [('x', 1, url)]
            prog = SimpleNamespace(done=9, total=10, failed=1, finished=True)
        else:
            self.downloader._failed_tasks = []
            prog = SimpleNamespace(done=10, total=10, failed=0, finished=True)
        self.finished_signal.emit(prog)


M.DownloadWorker = FakeWorker
M.DownloadPage._sync_download = lambda self: None
M.DownloadPage._show_failed_fix_dialog = lambda self: None

from pages.album.ehentai_page import DownloadPage

G = 'https://e-hentai.org/g/%s/aabbccddee/'


def wait_until(cond, ms=4000):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QTest.qWait(25)
        if cond():
            return True
    return False


fail = []
def chk(name, cond, extra=''):
    print(('  [%s] %s %s' % ('PASS' if cond else 'FAIL', name, extra)))
    if not cond:
        fail.append(name)


page = DownloadPage()
page.resize(900, 760)
page.show()
app.processEvents()

# 场景：g1 成功、g2 失败、g3 成功 排队
g1, g2, g3 = G % 1, G % 2, G % 3
OUTCOME[g1] = 'ok'
OUTCOME[g2] = 'fail'
OUTCOME[g3] = 'ok'
page._enqueue(g1)
page._enqueue(g1)          # 重复 -> 忽略
page._enqueue(g2)
page._enqueue(g3)

chk('1 g1 立即开始', wait_until(lambda: bool(page.worker and page.worker.isRunning())))
chk('2 重复 URL 未重复入队', page._queue.__len__() == 2, str(len(page._queue)))
chk('3 g1 成功后自动开始 g2', wait_until(lambda: STARTS.count(g2) == 1, 4000))
# g2 失败 -> 停留在该任务，g3 不自动开始
chk('4 g2 失败后停留（task_waiting）',
    wait_until(lambda: page._task_waiting and not (page.worker and page.worker.isRunning())))
chk('4b 队列仍保留 g3 未开始', page._queue.__len__() == 1 and g3 not in STARTS,
    str(page._queue))
chk('5 跳过按钮可用', page.skip_btn.isEnabled())
# 点击跳过 -> 进入 g3
page._skip_current()
chk('6 跳过后自动开始 g3', wait_until(lambda: STARTS.count(g3) == 1, 4000))
chk('7 g3 成功完成且队列清空',
    wait_until(lambda: (not (page.worker and page.worker.isRunning()))
               and not page._task_waiting and not page._queue))
chk('7b 跳过按钮回到禁用', not page.skip_btn.isEnabled())

# 场景2：运行时新增排队，随后自动接续
g4, g5 = G % 4, G % 5
OUTCOME[g4] = 'ok'
OUTCOME[g5] = 'ok'
page._enqueue(g4)
chk('8 g4 开始', wait_until(lambda: page.worker and page.worker.isRunning()))
page._enqueue(g5)
chk('9 g4 成功后自动 g5', wait_until(lambda: STARTS.count(g5) == 1, 4000))
chk('10 全部完成', wait_until(lambda: not (page.worker and page.worker.isRunning())
                              and not page._task_waiting and not page._queue, 4000))
print('STARTS =', [u.rstrip('/').split('/')[-2] for u in STARTS])
page.close()

if fail:
    print('QUEUE TEST FAILED:', fail)
    sys.exit(1)
print('下载队列编排测试全部通过')
