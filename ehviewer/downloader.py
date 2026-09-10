# -*- coding: utf-8 -*-
"""下载管理器：多画廊并发 + 每画廊页级顺序下载（移植 DownloadManager + SpiderQueen 流程）
设计：每个画廊一个 QThread worker；页级串行（页面请求->showpage API->流式写盘），
支持断点续传（文件存在即跳过）、失败页重试、.ehviewer 进度记录。
"""
import os
import re
import time
import threading
import traceback
from collections import deque

from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer

from . import constants as C
from . import db
from . import engine
from . import urls
from .config import CFG, get
from .models import GalleryInfo
from .session import make_session, EhException, ParseException
from .spiderinfo import (SpiderInfo, sanitize_filename, page_file_name,
                         find_gallery_dir, SPIDER_INFO_FILENAME, SUPPORTED_EXTS)

MIME_EXT = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/gif": ".gif", "image/webp": ".webp",
}
PATTERN_SHOWKEY = re.compile(r'var showkey="([0-9a-z]+)";')
PATTERN_IMAGE_URL = re.compile(r'<img[^>]*src="([^"]+)" style')
PATTERN_NL = re.compile(r"onclick=\"return nl\('([^\)]+)'\)")
PATTERN_FULLIMG = re.compile(r'<a href="([^"]+)fullimg([^"]+)">')
PATTERN_PAGE_TOKEN = re.compile(r"/s/([0-9a-f]{10})/(\d+)-(\d+)")


class GalleryWorker(QThread):
    """单个画廊的下载任务"""
    progress = pyqtSignal(int, int, int, float)   # gid, finished, total, speed
    stateChanged = pyqtSignal(int, int)           # gid, state
    done = pyqtSignal(int, bool, str)             # gid, all_ok, message
    log = pyqtSignal(str)

    def __init__(self, info, label="", parent=None):
        super(GalleryWorker, self).__init__(parent)
        self._info = info          # GalleryInfo
        self._label = label
        self._stop_flag = threading.Event()
        self._speed_win = deque(maxlen=8)
        self.finished_count = 0
        self.total = 0
        self.session = None

    def stop(self):
        self._stop_flag.set()

    # ---------- 目录 ----------
    def _gallery_root(self):
        root = get("download_dir")
        os.makedirs(root, exist_ok=True)
        title = self._info.suitable_title(get("show_jpn_title", False))
        return os.path.join(root, "%d-%s" % (self._info.gid, sanitize_filename(title)))

    # ---------- 主流程 ----------
    def run(self):
        self.session = make_session()
        try:
            self._run_inner()
        except Exception:
            traceback.print_exc()
            self.done.emit(self._info.gid, False, "下载异常：%s" % traceback.format_exc()[-300:])

    def _run_inner(self):
        info = self._info
        gid = info.gid
        root = self._gallery_root()
        os.makedirs(root, exist_ok=True)
        # 读取已有 .ehviewer
        db.put_download_dirname(gid, os.path.basename(root))
        info_path = os.path.join(root, SPIDER_INFO_FILENAME)
        si = SpiderInfo.read(info_path)
        if si.gid != gid or si.token != info.token:
            si = SpiderInfo()
            si.gid = gid
            si.token = info.token
        # 获取总页数
        total = si.pages
        if total <= 0:
            total = self._fetch_page_count()
            if total <= 0:
                self.stateChanged.emit(gid, C.STATE_FAILED)
                self.done.emit(gid, False, "无法获取画廊页数（可能已被移除或需要登录）")
                return
            si.pages = total
        self.total = total
        self.stateChanged.emit(gid, C.STATE_DOWNLOAD)
        db.update_download_state(gid, C.STATE_DOWNLOAD, total=total)

        show_key = None
        failed = []
        start = time.time()
        for index in range(total):
            if self._stop_flag.is_set():
                break
            # 已存在文件 → 跳过
            if self._page_exists(root, index):
                self.finished_count += 1
                self._emit_progress(start)
                continue
            ptoken = si.ptoken_map.get(index)
            if not ptoken or ptoken == "failed":
                ptoken = self._fetch_ptoken(index, total, si)
                if ptoken:
                    si.ptoken_map[index] = ptoken
                else:
                    si.ptoken_map[index] = "failed"
            ok, msg = False, ""
            for attempt in range(5):
                if self._stop_flag.is_set():
                    break
                ok, msg = self._download_page(root, index, ptoken, show_key)
                if ok:
                    break
                if "509" in msg:
                    break
                if "Key mismatch" in msg or "key" in msg.lower():
                    show_key = None
                time.sleep(0.6 * (attempt + 1))
            if self._stop_flag.is_set():
                break
            if ok:
                self.finished_count += 1
                # 更新 showkey 与下一页 ptoken
                if ptoken:
                    si.ptoken_map[index] = ptoken
            else:
                failed.append((index, msg))
                self._remove_partial(root, index)
            si.write(info_path)
            self._emit_progress(start)
        # 完成
        si.write(info_path)
        legacy = total - self.finished_count
        if self._stop_flag.is_set():
            state = C.STATE_NONE
            db.update_download_state(gid, C.STATE_NONE)
        elif legacy == 0:
            state = C.STATE_FINISH
            db.update_download_state(gid, C.STATE_FINISH)
        else:
            state = C.STATE_FAILED
            db.update_download_state(gid, C.STATE_FAILED)
        self.stateChanged.emit(gid, state)
        self.done.emit(gid, legacy == 0, "失败 %d 页" % legacy if legacy else "全部完成")

    def _page_exists(self, root, index):
        for ext in SUPPORTED_EXTS:
            if os.path.exists(os.path.join(root, page_file_name(index, ext))):
                return True
        return False

    def _remove_partial(self, root, index):
        for ext in SUPPORTED_EXTS:
            p = os.path.join(root, page_file_name(index, ext))
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    def _emit_progress(self, start):
        elapsed = time.time() - start
        speed = 0.0
        if elapsed > 1:
            speed = self.finished_count / elapsed
        self.progress.emit(self._info.gid, self.finished_count, self.total, speed)

    # ---------- 网络 ----------
    def _fetch_page_count(self):
        """优先 gdata API 拿 filecount，失败则解析详情页"""
        try:
            items = [self._info]
            engine.fill_gallery_list_by_api(items, urls.get_referer())
            if self._info.pages > 0:
                return self._info.pages
        except Exception:
            pass
        try:
            detail = engine.get_gallery_detail(self._info.gid, self._info.token)
            if detail.pages > 0:
                return detail.pages
        except Exception:
            pass
        return 0

    def _fetch_ptoken(self, index, total, si):
        """从预览页解析页 pToken（每预览页 40 个）"""
        per = si.preview_per_page or 40
        preview_idx = index // per
        try:
            url = urls.get_gallery_detail_url(self._info.gid, self._info.token, preview_idx)
            resp = engine.http_get(self.session, url, referer=urls.get_referer())
            body = resp.text
            found = {}
            for m in PATTERN_PAGE_TOKEN.finditer(body):
                try:
                    idx = int(m.group(3)) - 1
                except ValueError:
                    continue
                if m.group(2) == str(self._info.gid):
                    found[idx] = m.group(1)
            si.preview_per_page = per
            si.preview_pages = (total + per - 1) // per
            for k, v in found.items():
                si.ptoken_map[k] = v
            return found.get(index)
        except Exception:
            return None

    def _download_page(self, root, index, ptoken, show_key):
        """下载单页：HTML 拿 showKey -> showpage API 拿图 -> 写盘"""
        gid = self._info.gid
        token = self._info.token
        referer_detail = urls.get_gallery_detail_url(gid, token)
        # 1. 需要 showKey 时抓页面 HTML
        page_url = urls.get_page_url(gid, index, ptoken) if ptoken else None
        if (show_key is None or "Key mismatch" in (show_key or "")) and page_url:
            try:
                resp = engine.http_get(self.session, page_url, referer=referer_detail)
                body = resp.text
                m = PATTERN_SHOWKEY.search(body)
                if m:
                    show_key = m.group(1)
                # HTML 兜底：直接取图
                im = PATTERN_IMAGE_URL.search(body)
                if im:
                    image_url = im.group(1).strip()
                    if image_url.endswith(("/509.gif", "/509s.gif")):
                        return False, "509 图片配额用尽"
                    self._speed_win.append((time.time(), index))
                    return self._write_image(root, index, image_url, page_url, show_key), ""
            except Exception as e:
                return False, str(e)
        if not ptoken:
            return False, "缺少页面 token"
        # 2. showpage API
        try:
            payload = {"method": "showpage", "gid": gid, "page": index + 1,
                       "imgkey": ptoken, "showkey": show_key or ""}
            referer = None
            if index > 0:
                referer = urls.get_page_url(gid, index - 1, self._info.token and ptoken or ptoken)
            resp = engine.http_post_json(self.session, urls.get_api_url(), payload,
                                         referer=referer, origin=urls.get_origin())
            d = resp.json()
            if "error" in d:
                return False, d["error"]
            i3 = d.get("i3") or ""
            im = re.search(r'<img[^>]*src="([^"]+)" style', i3)
            if not im:
                return False, "响应缺少图片地址"
            image_url = im.group(1).strip()
            if image_url.endswith(("/509.gif", "/509s.gif")):
                return False, "509 图片配额用尽"
            return self._write_image(root, index, image_url, page_url, show_key), ""
        except Exception as e:
            return False, str(e)

    def _write_image(self, root, index, image_url, referer, show_key):
        """流式下载图片并校验，成功返回 True"""
        headers = {"Referer": referer or urls.get_referer()}
        resp = self.session.get(image_url, headers=headers, timeout=60, stream=True)
        if resp.status_code >= 400:
            return False
        ctype = resp.headers.get("Content-Type", "").lower().split(";")[0].strip()
        ext = MIME_EXT.get(ctype, ".jpg")
        path = os.path.join(root, page_file_name(index, ext))
        tmp = path + ".part"
        total_len = 0
        try:
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(64 * 1024):
                    if self._stop_flag.is_set():
                        resp.close()
                        return False
                    if chunk:
                        f.write(chunk)
                        total_len += len(chunk)
            # 校验：纯文本（<=126 字节全部）或截断
            if total_len > 0 and all(b <= 126 for b in _read_tail(tmp, 256)):
                os.remove(tmp)
                return False
            if total_len == 0:
                os.remove(tmp)
                return False
            os.replace(tmp, path)
            return True
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False


def _read_tail(path, n):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - n))
            return f.read()
    except OSError:
        return b""


class DownloadManager(QObject):
    """全局下载管理器：并发调度 + 状态维护"""
    changed = pyqtSignal()
    progress = pyqtSignal(int, int, int, float)
    galleryDone = pyqtSignal(int, bool, str)

    def __init__(self, parent=None):
        super(DownloadManager, self).__init__(parent)
        self._workers = {}
        self._wait = deque()
        self._lock = threading.Lock()
        self._max_concurrent = max(1, get("download_concurrency", 3))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pump)
        self._timer.start(500)

    def set_concurrency(self, n):
        self._max_concurrent = max(1, min(10, n))

    # ---------- 对外操作 ----------
    def start_download(self, info, label=""):
        """加入下载队列（已在列表则置等待）"""
        gid = info.gid
        existing = db.get_download(gid)
        if existing is None:
            db.insert_download(info, C.STATE_WAIT, label=label)
        else:
            db.update_download_state(gid, C.STATE_WAIT)
        with self._lock:
            if gid not in self._workers and gid not in self._wait:
                self._wait.append(gid)
        self.changed.emit()

    def pause(self, gid):
        with self._lock:
            w = self._workers.get(gid)
        if w is not None:
            w.stop()
        else:
            if gid in self._wait:
                self._wait.remove(gid)
            db.update_download_state(gid, C.STATE_NONE)
            self.changed.emit()

    def pause_all(self):
        with self._lock:
            gids = list(self._workers.keys()) + list(self._wait)
        for g in gids:
            self.pause(g)

    def resume(self, gid):
        info = db.get_download(gid)
        if info is None:
            return
        st = info.state
        if st in (C.STATE_NONE, C.STATE_FAILED, C.STATE_FINISH):
            db.update_download_state(gid, C.STATE_WAIT)
            with self._lock:
                if gid not in self._workers and gid not in self._wait:
                    self._wait.append(gid)
            self.changed.emit()

    def retry_failed(self, gids=None):
        """重试失败（含已完成，用于补缺页）"""
        items = gids or [g for g in db.list_downloads() if g.state in (C.STATE_NONE, C.STATE_FAILED, C.STATE_FINISH)]
        for g in items:
            self.resume(g.gid)

    def retry_all(self):
        """全部重试（不含已完成）"""
        for g in db.list_downloads():
            if g.state in (C.STATE_NONE, C.STATE_FAILED):
                self.resume(g.gid)

    def remove(self, gid, delete_files=False):
        with self._lock:
            w = self._workers.get(gid)
        if w is not None:
            w.stop()
            w.wait(3000)
        if gid in self._wait:
            self._wait.remove(gid)
        if delete_files:
            root = get("download_dir")
            d = find_gallery_dir(root, gid)
            if d:
                import shutil
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
        db.delete_download(gid)
        self.changed.emit()

    # ---------- 调度 ----------
    def _pump(self):
        with self._lock:
            running = len(self._workers)
            while self._wait and running < self._max_concurrent:
                gid = self._wait.popleft()
                if gid in self._workers:
                    continue
                info = db.get_download(gid)
                if info is None:
                    continue
                w = GalleryWorker(info, parent=self)
                w.progress.connect(self._on_progress)
                w.stateChanged.connect(self._on_state)
                w.done.connect(self._on_done)
                w.log.connect(self._on_log)
                self._workers[gid] = w
                running += 1
                w.start()

    def _on_progress(self, gid, finished, total, speed):
        self.progress.emit(gid, finished, total, speed)

    def _on_state(self, gid, state):
        self.changed.emit()

    def _on_done(self, gid, ok, msg):
        with self._lock:
            self._workers.pop(gid, None)
        self.galleryDone.emit(gid, ok, msg)
        self.changed.emit()

    def _on_log(self, text):
        pass

    def shutdown(self):
        with self._lock:
            for w in list(self._workers.values()):
                w.stop()
                w.wait(3000)
            self._workers.clear()
            self._wait.clear()
