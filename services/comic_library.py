# -*- coding: utf-8 -*-
"""
通用本地漫画库扫描 + 离线索引（无 GUI 依赖，可独立测试）
=====================================================
自动检测各平台下载目录下已下载的漫画，兼容两种目录形态：
- 含章节层： {root}/{漫画名}/{章节名}/{图片}
- 扁平（无章节层，如 E-Hentai）：{root}/{画廊名}/{图片}

提供：
- scan_comics(root, index_path=None, force=False) —— 扫描所有已下载漫画；
  传入 index_path 时优先读离线索引 JSON（秒开），过期/强制时才全量扫描并重建索引。
- natural_key / has_done_marker / list_image_files —— 工具函数
- invalidate_index(index_path) —— 下载完成后使索引失效（下次扫描重建）
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional

DONE_MARKERS = ('.done', '.easycopy_done', '.jmcomic_done', '.ehentai_done')

INDEX_MAX_AGE = 60  # 索引有效时长（秒）：此期间直接读索引，不重新扫描


def natural_key(text: str):
    """自然排序键：把 '第12话' 中的数字按数值排序。"""
    parts = re.split(r'(\d+)', text)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def has_done_marker(directory: str) -> bool:
    """目录下是否存在任意完成标记文件。"""
    try:
        for name in os.listdir(directory):
            if name in DONE_MARKERS:
                return True
    except Exception:
        pass
    return False


def list_image_files(directory: str) -> List[str]:
    """列出目录中的图片文件（排除隐藏标记与 .part），按自然顺序排序。"""
    files = []
    try:
        for name in os.listdir(directory):
            if name.startswith('.') or name.endswith('.part'):
                continue
            full = os.path.join(directory, name)
            if os.path.isfile(full):
                files.append(full)
    except Exception:
        pass
    files.sort(key=lambda p: natural_key(os.path.basename(p)))
    return files


def comic_download_time(comic: 'LocalComic') -> float:
    """漫画的下载时间：目录内最新文件的 mtime（没有文件时退回目录 mtime）。"""
    newest = 0.0
    try:
        for root, _dirs, files in os.walk(comic.path):
            for f in files:
                try:
                    m = os.path.getmtime(os.path.join(root, f))
                    if m > newest:
                        newest = m
                except Exception:
                    pass
    except Exception:
        pass
    if not newest:
        try:
            newest = os.path.getmtime(comic.path)
        except Exception:
            newest = 0.0
    return newest


def delete_local_path(path: str) -> bool:
    """递归删除本地文件或目录（用于删除离线章节 / 漫画 / 媒体文件）。"""
    import shutil
    try:
        if not path:
            return False
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            os.remove(path)
        return not os.path.exists(path)
    except Exception:
        return False


@dataclass
class LocalChapter:
    """本地章节（扁平形态时只有一章，label 为漫画名）。"""

    label: str = ""
    path: str = ""
    images: List[str] = field(default_factory=list)
    is_done: bool = False


@dataclass
class LocalComic:
    """本地漫画。"""

    title: str = ""
    path: str = ""
    chapters: List[LocalChapter] = field(default_factory=list)
    cover_url: str = ""            # 第一章节第一张图片（本地路径）
    total_chapters: int = 0
    total_images: int = 0
    flat: bool = False             # True=无章节层（E-Hentai 形态）


# ═══════════════════════════════════════════
#  离线索引 JSON
# ═══════════════════════════════════════════
def default_index_path(root: str, platform: str) -> str:
    """离线索引文件路径（统一放在 ``data/offline_index/`` 内，与下载内容分离）。

    历史：这些索引原先是 ``{下载根}/.{platform}_offline_index.json``，藏在用户的
    下载目录里 —— 索引属于"小体积、不可再生"的数据，必须跟 data/ 走；换下载盘或
    清理下载目录时不该连带把索引弄丢。

    ``root`` 参数保留是为了兼容既有调用点（索引不再由它推导位置）。
    """
    try:
        from core.config import config as CFG
        return CFG.offline_index_path(platform)
    except Exception:
        # 极端情况下（core 不可导入）退回旧位置，保证功能不中断
        base = os.path.dirname(os.path.abspath(root))
        return os.path.join(base, f'.{platform}_offline_index.json')


def load_index(index_path: str, root: str, max_age: int = INDEX_MAX_AGE):
    """读取离线索引。有效且匹配 root 时返回 comics 列表，否则返回 None。"""
    if not index_path or not os.path.isfile(index_path):
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if data.get("root") != os.path.abspath(root):
            return None
        if time.time() - float(data.get("generated_at", 0)) > max_age:
            return None
        return _comics_from_index(data)
    except Exception:
        return None


def save_index(index_path: str, root: str, comics: List[LocalComic]) -> None:
    """把扫描结果写入离线索引 JSON。"""
    if not index_path:
        return
    try:
        data = {
            "root": os.path.abspath(root),
            "generated_at": time.time(),
            "comics": [_comic_to_dict(c) for c in comics],
        }
        os.makedirs(os.path.dirname(index_path) or ".", exist_ok=True)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def invalidate_index(index_path: str) -> None:
    """使索引失效（删除文件），下次扫描重建。"""
    try:
        if index_path and os.path.exists(index_path):
            os.remove(index_path)
    except Exception:
        pass


def _comic_to_dict(c: LocalComic) -> dict:
    return {
        "title": c.title,
        "path": c.path,
        "flat": c.flat,
        "chapters": [
            {
                "label": ch.label,
                "path": ch.path,
                "is_done": ch.is_done,
                "images": ch.images,
            }
            for ch in c.chapters
        ],
    }


def _comics_from_index(data: dict) -> List[LocalComic]:
    root = data.get("root", "")
    comics: List[LocalComic] = []
    for item in data.get("comics", []):
        chapters = []
        for ch_item in item.get("chapters", []):
            chapters.append(
                LocalChapter(
                    label=ch_item.get("label", ""),
                    path=ch_item.get("path", ""),
                    images=list(ch_item.get("images", []) or []),
                    is_done=bool(ch_item.get("is_done", False)),
                )
            )
        comic = LocalComic(
            title=item.get("title", ""),
            path=item.get("path", ""),
            chapters=chapters,
            flat=bool(item.get("flat", False)),
        )
        comic.cover_url = chapters[0].images[0] if chapters and chapters[0].images else ""
        comic.total_chapters = len(chapters)
        comic.total_images = sum(len(c.images) for c in chapters)
        comics.append(comic)
    return comics


def scan_comics(root: str, index_path: str = "", force: bool = False,
                max_age: int = INDEX_MAX_AGE) -> List[LocalComic]:
    """扫描 root 下所有已下载漫画（兼容含章节层与扁平两种形态）。

    传入 index_path 时：有效期内直接读索引（更快）；force=True 强制全量扫描并重建索引。
    """
    if not root or not os.path.isdir(root):
        return []

    if not force and index_path:
        cached = load_index(index_path, root, max_age)
        if cached is not None:
            return cached

    comics = _scan_comics_disk(root)

    if index_path:
        save_index(index_path, root, comics)
    return comics


def _scan_comics_disk(root: str) -> List[LocalComic]:
    """全量磁盘扫描。"""
    comics: List[LocalComic] = []
    try:
        names = os.listdir(root)
    except Exception:
        return []

    for name in names:
        comic_path = os.path.join(root, name)
        if not os.path.isdir(comic_path) or name.startswith('.'):
            continue

        # 判断形态：直接含图片 -> 扁平；含子目录 -> 章节层
        direct_images = list_image_files(comic_path)
        subdirs = []
        try:
            subdirs = [n for n in os.listdir(comic_path)
                       if os.path.isdir(os.path.join(comic_path, n)) and not n.startswith('.')]
        except Exception:
            pass

        chapters: List[LocalChapter] = []
        if direct_images and not subdirs:
            # 扁平：整目录即一章
            chapters.append(
                LocalChapter(
                    label=name,
                    path=comic_path,
                    images=direct_images,
                    is_done=has_done_marker(comic_path),
                )
            )
            flat = True
        else:
            # 章节层
            flat = False
            for ch_name in sorted(subdirs, key=natural_key):
                ch_path = os.path.join(comic_path, ch_name)
                images = list_image_files(ch_path)
                if not images:
                    continue
                chapters.append(
                    LocalChapter(
                        label=ch_name,
                        path=ch_path,
                        images=images,
                        is_done=has_done_marker(ch_path),
                    )
                )

        if not chapters:
            continue

        cover = chapters[0].images[0] if chapters[0].images else ""
        total_images = sum(len(c.images) for c in chapters)
        comics.append(
            LocalComic(
                title=name,
                path=comic_path,
                chapters=chapters,
                cover_url=cover,
                total_chapters=len(chapters),
                total_images=total_images,
                flat=flat,
            )
        )

    comics.sort(key=lambda c: natural_key(c.title))
    return comics
