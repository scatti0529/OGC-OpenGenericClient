# -*- coding: utf-8 -*-
"""详情页预览缩略图：用下载画廊的下载逻辑解析漫画，下载前若干页，
缩小为缩略图并缓存到专门文件夹（与画廊封面完全分离）。

目录：data/ehentai/previews/{gid}/000001.jpg ...（缩略图）
封面统一走 pages.album.eh_cover（data/ehentai/cache/covers/{gid}.img），两者互不影响。

预览图获取（新版 GdtPreviewWorker）：
    直接抓画廊 HTML（如 https://e-hentai.org/g/{gid}/{token}/），解析其中
    <div id="gdt" class="gt200"> 下的前 20 个条目：
      · 新版页面：每个条目是一张“雪碧图”的背景裁切
        <a href="/s/..."><div style="width:200px;height:292px;background:
        transparent url(https://.../xxx.webp) -200px 0 no-repeat" ...>
        —— 下载该雪碧图后按偏移裁出每页缩略图；
      · 旧版页面：条目内含 <img src="..."> 直链，直接下载。
"""
import io
import os
import re

from PyQt5.QtCore import QThread, pyqtSignal

from core.config import config as CFG

PREVIEW_DIR = str(CFG.data / 'ehentai' / 'previews')


def preview_dir(gid):
    return os.path.join(PREVIEW_DIR, str(gid))


def preview_path(gid, index):
    return os.path.join(preview_dir(gid), "%06d.jpg" % (index + 1))


def cached_count(gid):
    try:
        return len([f for f in os.listdir(preview_dir(gid)) if f.endswith('.jpg')])
    except Exception:
        return 0


# ════════════════════════════════════════════════════════════════════
#  #gdt 预览解析 + 雪碧图裁切（GdtPreviewWorker）
# ════════════════════════════════════════════════════════════════════
def parse_gdt_sources(html, limit=20):
    """从画廊详情页 HTML 的 <div id="gdt"> 中解析前 limit 个预览条目。

    返回 list[dict]：
        {position, page_url, kind('sprite'|'img'), image_url, x, y, w, h}
    kind='sprite' 时 image_url 为雪碧图地址，(x,y,w,h) 为需要裁出的区域；
    kind='img' 时 image_url 即该页缩略图直链，x=y=w=h=0。
    """
    out = []
    if not html:
        return out
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        gdt = soup.find(id='gdt') or soup.find('div', id='gdt')
        anchors = gdt.find_all('a', href=True) if gdt is not None else []
    except Exception:
        anchors = []
    if anchors:
        for a in anchors:
            if len(out) >= limit:
                break
            href = (a.get('href') or '').strip()
            # 旧版：<img src="...">
            img = a.find('img')
            if img is not None and (img.get('src') or img.get('data-src')):
                out.append({
                    'position': len(out), 'page_url': href, 'kind': 'img',
                    'image_url': (img.get('src') or img.get('data-src') or '').strip(),
                    'x': 0, 'y': 0, 'w': 0, 'h': 0,
                })
                continue
            # 新版：<div style="width:..px;height:..px;background:transparent
            #        url(..雪碧图..) -{x}px -{y}px no-repeat" title="Page N: file">
            div = a.find('div')
            style = div.get('style') if div is not None else ''
            m_url = re.search(r'url\(\s*[\'"]?(.+?)[\'"]?\s*\)', style)
            if not m_url:
                continue
            m_off = re.search(r'\)\s*(-?\d+)px\s+(-?\d+)px', style)
            m_wh = re.search(r'width:\s*(\d+)px;\s*height:\s*(\d+)px', style)
            w = int(m_wh.group(1)) if m_wh else 200
            h = int(m_wh.group(2)) if m_wh else 292
            x = abs(int(m_off.group(1))) if m_off else 0
            y = abs(int(m_off.group(2))) if m_off else 0
            out.append({
                'position': len(out), 'page_url': href, 'kind': 'sprite',
                'image_url': m_url.group(1).strip(), 'x': x, 'y': y, 'w': w, 'h': h,
            })
    # 兜底：正则粗提取 gdt 段内所有图片 src
    if not out:
        seg = ''
        m = re.search(r'<div[^>]*id="gdt"[^>]*>(.*?)</div>', html, re.S)
        seg = m.group(1) if m else html
        seen = set()
        for mm in re.finditer(r'<img[^>]+src="([^"]+)"', seg):
            u = mm.group(1)
            if u.startswith(('http://', 'https://')) and u not in seen:
                seen.add(u)
                out.append({'position': len(out), 'page_url': '', 'kind': 'img',
                            'image_url': u, 'x': 0, 'y': 0, 'w': 0, 'h': 0})
                if len(out) >= limit:
                    break
    return out[:limit]


class GdtPreviewWorker(QThread):
    """抓画廊页 #gdt 缩略图 -> 生成前 N 张预览（雪碧图裁切 / 直链下载）。

    信号与旧 PreviewWorker 完全一致：ready(index, filepath) / done(count) / log(msg)。
    """

    ready = pyqtSignal(int, str)      # (index, filepath)
    done = pyqtSignal(int)            # 成功张数
    log = pyqtSignal(str)

    def __init__(self, gid, token, n=20, parent=None):
        super(GdtPreviewWorker, self).__init__(parent)
        self.gid = gid
        self.token = token
        self.n = n
        self._stop = False

    def stop(self):
        self._stop = True

    def _fetch(self, session, url, referer='https://e-hentai.org/'):
        """下载二进制内容并做图片魔数校验。"""
        if self._stop:
            return None
        r = session.get(url, headers={'Referer': referer}, timeout=30)
        if r.status_code >= 400:
            return None
        data = r.content
        if len(data) < 200:
            return None
        ok = (data[:3] == b'\xff\xd8\xff' or data[:8] == b'\x89PNG\r\n\x1a\n'
              or data[:4] == b'GIF8' or data[:4] == b'RIFF')
        return data if ok else None

    def run(self):
        from PIL import Image
        from ehviewer.session import make_session
        try:
            url = 'https://e-hentai.org/g/%s/%s/' % (self.gid, self.token)
            # 与详情页/封面等其余网络请求保持一致：用 ehviewer 会话（配置代理 +
            # 环境代理），不要用下载器那种 trust_env=False 的会话（会绕过系统代理）。
            s = make_session()
            try:
                if not s.cookies.get('nw'):
                    s.cookies.set('nw', '1', domain='e-hentai.org', path='/')
            except Exception:
                pass

            resp = s.get(url, headers={'Referer': 'https://e-hentai.org/'}, timeout=30)
            if resp.status_code >= 400:
                self.log.emit('获取画廊页失败：HTTP %d' % resp.status_code)
                self.done.emit(0)
                return
            sources = parse_gdt_sources(resp.text, limit=self.n)
            if not sources:
                self.log.emit('未能从 #gdt 解析到预览图（可能需登录 Cookies）')
                self.done.emit(0)
                return

            os.makedirs(preview_dir(self.gid), exist_ok=True)
            sprite_cache = {}
            count = 0
            for src in sources:
                if self._stop:
                    break
                try:
                    if src['kind'] == 'sprite':
                        img = sprite_cache.get(src['image_url'])
                        if img is None:
                            data = self._fetch(s, src['image_url'])
                            if not data:
                                continue
                            img = Image.open(io.BytesIO(data))
                            sprite_cache[src['image_url']] = img
                        w = max(1, src['w'] or 200)
                        h = max(1, src['h'] or 292)
                        box = (src['x'], src['y'], min(src['x'] + w, img.width),
                               min(src['y'] + h, img.height))
                        im = img.crop(box)
                    else:
                        data = self._fetch(s, src['image_url'])
                        if not data:
                            continue
                        im = Image.open(io.BytesIO(data))
                    out = preview_path(self.gid, count)
                    im.convert('RGB').save(out, 'JPEG', quality=82)
                    self.ready.emit(count, out)
                    count += 1
                    if count >= self.n:
                        break
                except Exception:
                    continue
            self.done.emit(count)
        except Exception as e:
            self.log.emit('预览生成失败：%s' % e)
            try:
                self.done.emit(0)
            except Exception:
                pass


class PreviewWorker(QThread):
    """下载画廊前 N 张页图 -> 缩小为缩略图 -> 缓存到专门文件夹。"""

    ready = pyqtSignal(int, str)      # (index, filepath)
    done = pyqtSignal(int)            # 成功张数
    log = pyqtSignal(str)

    def __init__(self, gid, token, n=10, parent=None):
        super().__init__(parent)
        self.gid = gid
        self.token = token
        self.n = n
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            from services.ehentai_downloader import EhentaiDownloader, DownloadConfig
            from pages.album.ehentai_settings import ehentai_cfg as _c
            from ehviewer.session import make_image_session
            from PIL import Image

            url = 'https://e-hentai.org/g/%s/%s/' % (self.gid, self.token)
            cfg = DownloadConfig(
                url=url,
                cookies=_c.get(_c.KEY_COOKIES, ''),
                headers=_c.get(_c.KEY_HEADERS, ''),
                proxy=_c.get(_c.KEY_PROXY, ''),
                ignore_env_proxy=bool(_c.get(_c.KEY_IGNORE_ENV_PROXY, True)),
                output_dir=preview_dir(self.gid),
                concurrency=1, timeout=30, image_format='', per_file_retries=2,
            )
            dl = EhentaiDownloader(cfg)
            dl.session = dl._build_session()

            # 解析画廊，取每页第一个详情，再解析出直链
            try:
                _title, page_total = dl._parse_gallery()
            except Exception:
                page_total = 0
            max_pages = min(self.n, page_total or self.n)

            # 用轻量会话下载直链图片
            img_s = make_image_session()
            os.makedirs(preview_dir(self.gid), exist_ok=True)
            count = 0
            for p in range(max_pages):
                if self._stop:
                    break
                try:
                    detail_urls = dl._get_page_image_urls(p)
                    if not detail_urls:
                        continue
                    direct = dl._resolve_image_url(detail_urls[0])
                    if not direct:
                        continue
                    r = img_s.get(direct, headers={'Referer': 'https://e-hentai.org/'}, timeout=12)
                    if r.status_code != 200 or not r.content:
                        continue
                    im = Image.open(io.BytesIO(r.content))
                    im.thumbnail((320, 460))
                    out = preview_path(self.gid, count)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    im.convert('RGB').save(out, 'JPEG', quality=82)
                    self.ready.emit(count, out)
                    count += 1
                    if count >= self.n:
                        break
                except Exception:
                    continue
            self.done.emit(count)
        except Exception as e:
            self.log.emit('预览生成失败：%s' % e)
