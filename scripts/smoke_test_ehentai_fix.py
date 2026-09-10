# -*- coding: utf-8 -*-
"""E-Hentai 修复验证：
1. 下载器「停止」快速响应 + 失败任务记入列表 + 「重试失败」续传（本地 HTTP 服务器模拟）
2. 我的收藏卡片网格自适应列数
3. 封面图 requests 加载（不再走 Qt TLS）
"""
import base64
import os
import sys
import threading
import time
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

FAILURES = []


def step(name, fn):
    try:
        fn()
        print(f'[OK] {name}')
    except Exception:
        FAILURES.append(name)
        print(f'[FAIL] {name}')
        traceback.print_exc()


# ---------------------------------------------------------------
# 本地 HTTP 服务器：模拟画廊页面 + 详情页 + 图片
# ---------------------------------------------------------------
PNG_1PX = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)

slow_flag = {'on': False}
server_info = {'port': 0}


class GalleryHandler:
    """用函数式 handler 模拟 E-Hentai 页面结构"""

    @staticmethod
    def _gallery_page(page_url):
        tds = ''.join(
            f'<td onclick="document.location=this.firstChild.href"><a>{i}</a></td>'
            for i in (1, 2)
        )
        # 真实 E-Hentai 的图片详情链接是绝对 URL
        links = ''.join(
            f'<a href="http://127.0.0.1:{server_info["port"]}/g/1/abc/{n}/">&nbsp;</a>'
            for n in (1, 2)
        )
        return (
            '<html><head><title>Test Gallery</title></head><body>'
            f'<table>{tds}</table>'
            f'<div id="gdt" class="gt200">{links}</div>'
            '</body></html>'
        ).encode('utf-8')

    @staticmethod
    def _detail_page():
        # 真实 E-Hentai 详情页里的图片地址是绝对 URL
        img = f'http://127.0.0.1:{server_info["port"]}/img/1.jpg'
        return (f'<html><body><img id="img" src="{img}"></body></html>').encode('utf-8')

    @staticmethod
    def _image_bytes():
        if slow_flag['on']:
            # 模拟慢速图片：分块发送，每块间隔 0.8 秒
            body = PNG_1PX * 20000      # ~1.3MB，分 3 块发
            n = 3
            size = len(body) // n
            return body, size
        return PNG_1PX, len(PNG_1PX)


def make_handler():
    def handler():
        from http.server import BaseHTTPRequestHandler

        class H(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = self.path
                if path == '/g/1/abc/':
                    data = GalleryHandler._gallery_page(path)
                    ctype = 'text/html'
                elif path == '/g/1/abc/?p=0':
                    data = GalleryHandler._gallery_page(path)
                    ctype = 'text/html'
                elif path.startswith('/g/1/abc/') and path.endswith('/'):
                    data = GalleryHandler._detail_page()
                    ctype = 'text/html'
                elif path == '/img/1.jpg':
                    body, size = GalleryHandler._image_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    if slow_flag['on']:
                        n = 3
                        chunk = len(body) // n
                        for i in range(n):
                            self.wfile.write(body[i * chunk:(i + 1) * chunk])
                            self.wfile.flush()
                            time.sleep(0.8)
                    else:
                        self.wfile.write(body)
                    return
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return H
    return handler()


class Listener:
    """模拟 GUI 监听器"""
    def __init__(self):
        self.logs = []
        self.progress = []
        self.finished = []
        self.finished_event = threading.Event()

    def on_log(self, msg, level='info'):
        self.logs.append((level, msg))

    def on_progress(self, p):
        self.progress.append(p)

    def on_finished(self, p):
        self.finished.append(p)
        self.finished_event.set()


def test_downloader_stop_and_retry():
    import tempfile
    from http.server import HTTPServer
    from services.ehentai_downloader import EhentaiDownloader, DownloadConfig

    server = HTTPServer(('127.0.0.1', 0), make_handler())
    server_info['port'] = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    out_dir = tempfile.mkdtemp(prefix='ehentai_test_')

    def run():
        slow_flag['on'] = True          # 图片慢速发送
        listener = Listener()
        cfg = DownloadConfig(
            url=f'http://127.0.0.1:{server_info["port"]}/g/1/abc/',
            output_dir=out_dir,
            concurrency=2,
            timeout=10,
            per_file_retries=0,
            retry_delay=0.1,
        )
        dl = EhentaiDownloader(cfg)
        dl.set_listener(listener)
        th = threading.Thread(target=dl.run, daemon=True)
        th.start()

        # 等图片进入流式传输阶段后点击「停止」
        time.sleep(1.6)
        dl.stop()

        start = time.time()
        th.join(timeout=8)
        elapsed = time.time() - start
        assert not th.is_alive(), '停止后下载线程未在限定时间内结束（停止不响应）'
        assert elapsed < 6, f'停止响应过慢：{elapsed:.1f}s'
        listener.finished_event.wait(2)
        assert listener.finished, '未发出 finished 信号'
        assert len(dl._failed_tasks) >= 1, '停止后失败任务未记录（重试失败无内容）'
        print(f'  stop responded in {elapsed:.2f}s, done={listener.finished[-1].done}, '
              f'failed_tasks={len(dl._failed_tasks)}')

        # 服务器恢复正常 → 「重试失败」续传
        slow_flag['on'] = False
        listener2 = Listener()
        dl2 = EhentaiDownloader(cfg)
        dl2.set_listener(listener2)
        dl2._title = 'Test Gallery'
        dl2._failed_tasks = list(dl._failed_tasks)
        th2 = threading.Thread(target=dl2.run_failed, daemon=True)
        th2.start()
        th2.join(timeout=10)
        assert not th2.is_alive(), '重试失败线程未结束'
        listener2.finished_event.wait(2)
        assert listener2.finished, '重试失败未发出 finished'
        # 所有图片应已落地
        saved = []
        for root, _dirs, files in os.walk(out_dir):
            for f in files:
                saved.append(os.path.join(root, f))
        print(f'  retry finished: files on disk = {len(saved)}')
        assert len(saved) >= 2, f'重试失败后文件不全: {saved}'

        return

    try:
        run()
    finally:
        server.shutdown()
        t.join(timeout=3)
        server.server_close()


def test_adaptive_columns():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from pages.album.ehentai_favorites_page import FavoritesPage

    page = FavoritesPage()
    # 直接用假数据，避免依赖数据库文件
    page._items = [{'GID': i, 'TOKEN': 'x', 'TITLE': f't{i}', 'TITLE_JPN': '',
                    'THUMB': '', 'CATEGORY': 2, 'POSTED': '', 'UPLOADER': '',
                    'RATING': 5.0, 'TIME': 0} for i in range(12)]
    page._apply_filter()

    for w, expect in ((600, 1), (900, 2), (1400, 3)):
        page.resize(w, 780)
        app.processEvents()
        cols = page._calc_columns()
        assert cols == expect, f'width={w}: expected {expect} columns, got {cols}'
    print('  columns: 600->1, 900->2, 1400->3 (adaptive OK)')


def test_thumbnail_loader():
    from http.server import HTTPServer
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    server = HTTPServer(('127.0.0.1', 0), make_handler())
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        slow_flag['on'] = False
        from pages.album.ehentai_favorites_page import ThumbnailLoader
        loader = ThumbnailLoader()
        result = {}

        def on_loaded(gid, pixmap):
            result['pixmap'] = pixmap

        loader.loaded.connect(on_loaded)
        loader.load(42, f'http://127.0.0.1:{port}/img/1.jpg')

        deadline = time.time() + 8
        while 'pixmap' not in result and time.time() < deadline:
            app.processEvents()
            time.sleep(0.05)
        assert 'pixmap' in result, '封面未加载成功（超时）'
        assert result['pixmap'] is not None, '封面 QPixmap 为空'
        assert not result['pixmap'].isNull(), '封面 QPixmap 无效'
        print('  thumbnail loaded via requests, pixmap size =',
              result['pixmap'].width(), 'x', result['pixmap'].height())
    finally:
        server.shutdown()
        t.join(timeout=3)
        server.server_close()


if __name__ == '__main__':
    step('downloader_stop_and_retry', test_downloader_stop_and_retry)
    step('adaptive_columns', test_adaptive_columns)
    step('thumbnail_loader', test_thumbnail_loader)

    if FAILURES:
        print('RESULT: FAILED ->', FAILURES)
        sys.exit(1)
    print('RESULT: ALL PASSED')
