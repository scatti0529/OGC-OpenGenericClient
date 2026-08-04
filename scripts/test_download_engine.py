# -*- coding: utf-8 -*-
"""测试多模式下载引擎核心功能"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.download_manager import (
    DownloadMode, URLProbe, ParallelDownloader, StreamDownloader,
    AdaptiveDownloader, SmartDownloader,
)


def start_server():
    """本地 HTTP 服务器，支持 Range，5MB 文件"""
    import http.server
    import socketserver
    TEST_SIZE = 5 * 1024 * 1024

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._send(206, 0)
        def do_GET(self):
            range_header = self.headers.get('Range', '')
            start, end = 0, TEST_SIZE - 1
            if range_header.startswith('bytes='):
                parts = range_header[6:].split('-')
                start = int(parts[0])
                if parts[1]:
                    end = int(parts[1])
            self._send(206 if range_header else 200, start, end)
        def _send(self, code, start, end=TEST_SIZE - 1):
            self.send_response(code)
            if code == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{TEST_SIZE}')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            remaining = end - start + 1
            while remaining > 0:
                try:
                    self.wfile.write(b'X' * min(remaining, 32768))
                except Exception:
                    break
                remaining -= min(remaining, 32768)
        def log_message(self, *args):
            pass

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}/test.bin', TEST_SIZE


def check(name, cond):
    print(f"  -> {'PASS' if cond else 'FAIL'}: {name}")
    assert cond, name


def main():
    print("=" * 50)
    print("多模式下载引擎测试")
    print("=" * 50)

    server = None
    tmp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'temp_videos')
    os.makedirs(tmp, exist_ok=True)
    try:
        server, url, total = start_server()
        print(f"测试服务器: {url} ({total} bytes)\n")

        # 1. DownloadMode 枚举
        print("[1] DownloadMode")
        check("AUTO", DownloadMode.AUTO.value == 'auto')
        check("PARALLEL", DownloadMode.PARALLEL.value == 'parallel')
        check("STREAM", DownloadMode.STREAM.value == 'stream')
        check("display_name", DownloadMode.AUTO.display_name == '自动判定')

        # 2. URLProbe
        print("[2] URLProbe")
        probe = URLProbe(url).probe()
        check("ok", probe.ok)
        check("size", probe.total_size == total)
        check("partial", probe.supports_partial)

        # 3. ParallelDownloader
        print("[3] ParallelDownloader")
        p_path = os.path.join(tmp, 'parallel_test.bin')
        dl = ParallelDownloader(url, p_path, total, num_threads=8, retry_times=2)
        check("download", dl.download())
        check("size_ok", os.path.getsize(p_path) == total)

        # 4. StreamDownloader
        print("[4] StreamDownloader")
        s_path = os.path.join(tmp, 'stream_test.bin')
        dl = StreamDownloader(url, s_path, total_size=total, retry_times=2)
        check("download", dl.download())
        check("size_ok", os.path.getsize(s_path) == total)

        # 5. AdaptiveDownloader 自动模式
        print("[5] AdaptiveDownloader (auto)")
        a_path = os.path.join(tmp, 'adaptive_test.bin')
        # 临时降低阈值，确保走并发分块
        from core.config import config as CFG
        old = CFG.get('download_parallel_threshold', 20)
        CFG['download_parallel_threshold'] = 1
        dl = AdaptiveDownloader(url, a_path)
        ok = dl.download()
        check("download", ok)
        check("no_part", not os.path.exists(f"{a_path}.part"))
        check("size_ok", os.path.getsize(a_path) == total)
        print(f"     used_mode={dl.get_used_mode()}")
        CFG['download_parallel_threshold'] = old

        # 6. 强制流式模式
        print("[6] AdaptiveDownloader (stream)")
        f_path = os.path.join(tmp, 'forced_stream.bin')
        dl = AdaptiveDownloader(url, f_path, mode='stream')
        check("download", dl.download())
        check("mode", dl.get_used_mode() == 'stream')
        check("size_ok", os.path.getsize(f_path) == total)

        # 7. 失败清理
        print("[7] 失败清理")
        fail_path = os.path.join(tmp, 'fail_test.bin')
        dl = AdaptiveDownloader('http://127.0.0.1:1/nonexistent.bin', fail_path,
                                retry_times=0)
        check("fail", not dl.download())
        check("no_part", not os.path.exists(f"{fail_path}.part"))
        check("no_file", not os.path.exists(fail_path))

        # 8. SmartDownloader 兼容
        print("[8] SmartDownloader")
        sm = SmartDownloader(url, 'smart_test.bin', tmp, 'video', 'douyin',
                             num_threads=8, is_hls=False)
        check("download", sm.download())
        check("path_exists", os.path.exists(sm.get_downloaded_path()))

        print("\n" + "=" * 50)
        print("全部测试通过 ✓")
        print("=" * 50)
    finally:
        if server:
            server.shutdown()
        for name in os.listdir(tmp):
            if name.startswith(('parallel_test', 'stream_test', 'adaptive_test',
                                'fail_test', 'forced_stream')) \
                    and os.path.isfile(os.path.join(tmp, name)):
                try:
                    os.remove(os.path.join(tmp, name))
                except OSError:
                    pass


if __name__ == '__main__':
    main()