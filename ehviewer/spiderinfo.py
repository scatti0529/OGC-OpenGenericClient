# -*- coding: utf-8 -*-
"""SpiderInfo：下载目录中的 .ehviewer 文本文件读写（移植自 SpiderInfo.java）"""
import os
import re

SPIDER_INFO_FILENAME = ".ehviewer"
SUPPORTED_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


class SpiderInfo(object):
    """下载/阅读进度元数据"""

    def __init__(self):
        self.start_page = 0          # 阅读进度（页索引）
        self.gid = -1
        self.token = ""
        self.preview_pages = 0
        self.preview_per_page = 40
        self.pages = -1
        self.ptoken_map = {}         # index -> pToken

    def is_valid(self):
        return (self.gid != -1 and bool(self.token) and self.pages != -1
                and self.ptoken_map is not None)

    # ---------- 读写 ----------
    def write(self, path):
        lines = ["VERSION2",
                 "%08x" % self.start_page,
                 str(self.gid),
                 self.token or "",
                 "1",
                 str(self.preview_pages),
                 str(self.preview_per_page),
                 str(self.pages)]
        for idx in sorted(self.ptoken_map):
            pt = self.ptoken_map[idx]
            if pt and pt != "failed":
                lines.append("%d %s" % (idx, pt))
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            os.replace(tmp, path)
        except OSError:
            pass

    @classmethod
    def read(cls, path):
        info = cls()
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
        except OSError:
            return info
        if not lines:
            return info
        try:
            if lines[0] == "VERSION2":
                base = 1
                info.start_page = int(lines[1], 16) if len(lines) > 1 else 0
                if info.start_page < 0:
                    info.start_page = 0
                pos = 2
            else:
                base = 0
                pos = 0
            if len(lines) > pos:
                info.gid = int(lines[pos])
            if len(lines) > pos + 1:
                info.token = lines[pos + 1]
            # pos+2 = 废弃 mode 行
            if base == 1:
                if len(lines) > pos + 3:
                    info.preview_pages = int(lines[pos + 3])
                if len(lines) > pos + 4:
                    info.preview_per_page = int(lines[pos + 4])
                if len(lines) > pos + 5:
                    info.pages = int(lines[pos + 5])
                data_start = pos + 6
            else:
                if len(lines) > pos + 2:
                    info.pages = int(lines[pos + 2])
                data_start = pos + 3
            for line in lines[data_start:]:
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    try:
                        idx = int(parts[0])
                    except ValueError:
                        continue
                    info.ptoken_map[idx] = parts[1].strip()
            if not (0 < info.pages <= 100000):
                info.pages = -1
        except (ValueError, IndexError):
            pass
        return info


def sanitize_filename(name):
    """去掉非法字符，按 UTF-8 截断到 255 字节，去首尾空白"""
    if not name:
        return ""
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "")
    name = name.strip()
    while len(name.encode("utf-8", "ignore")) > 255:
        name = name[:-1]
    return name


def get_download_dirname(info, title):
    """生成下载目录名：{gid}-{suitableTitle}"""
    return "%d-%s" % (info.gid, sanitize_filename(title))


def page_file_name(index, ext):
    """图片文件名：%08d{index+1}{ext}"""
    return "%08d%s" % (index + 1, ext)


def find_gallery_dir(root, gid):
    """在下载根下查找 gid 对应的目录（兼容手动改名）：优先 {gid}- 前缀中最长者"""
    best = None
    try:
        for name in os.listdir(root):
            if name.startswith("%d-" % gid):
                if best is None or len(name) > len(best):
                    best = name
    except OSError:
        pass
    return best
