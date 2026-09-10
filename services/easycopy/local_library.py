# -*- coding: utf-8 -*-
"""
拷贝漫画本地库扫描（无 GUI 依赖，可独立测试）
============================================
自动检测 easycopy-download 目录下已下载的漫画：
    easycopy-download/{漫画名}/{章节名}/{图片文件}

提供：
- easycopy_root()           —— EasyCopy 下载根目录
- scan_comics()             —— 扫描所有已下载漫画（含章节与图片文件）
- natural sort 工具          —— 按数字自然排序章节/图片
- 完成标记识别               —— 带 .easycopy_done 的章节视为已下载完成
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .downloader import DONE_MARKER


def easycopy_root(output_root: str = "") -> str:
    """EasyCopy 下载根目录：{程序下载目录}/easycopy-download"""
    if not output_root:
        try:
            from services.download_manager import get_download_root
            output_root = get_download_root()
        except Exception:
            output_root = 'data'
    return os.path.join(output_root, 'easycopy-download')


def natural_key(text: str):
    """自然排序键：把 '第12话' 中的数字按数值排序。"""
    parts = re.split(r'(\d+)', text)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def list_image_files(chapter_path: str) -> List[str]:
    """列出章节目录中的图片文件（排除标记与 .part），按自然顺序排序。"""
    files = []
    try:
        for name in os.listdir(chapter_path):
            if name.startswith('.') or name.endswith('.part'):
                continue
            full = os.path.join(chapter_path, name)
            if os.path.isfile(full):
                files.append(full)
    except Exception:
        pass
    files.sort(key=lambda p: natural_key(os.path.basename(p)))
    return files


@dataclass
class LocalChapter:
    """本地章节。"""

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
    cover_url: str = ""            # 第一话第一张图片（本地路径）
    total_chapters: int = 0
    total_images: int = 0


def scan_comics(output_root: str = "") -> List[LocalComic]:
    """扫描 easycopy-download 下所有已下载漫画。

    目录结构：easycopy-download/{漫画名}/{章节名}/{图片}
    返回按漫画名排序的列表；封面取第一话的第一张图片。
    """
    root = easycopy_root(output_root)
    if not os.path.isdir(root):
        return []

    comics: List[LocalComic] = []
    try:
        names = os.listdir(root)
    except Exception:
        return []

    for name in names:
        comic_path = os.path.join(root, name)
        if not os.path.isdir(comic_path) or name.startswith('.'):
            continue

        chapters: List[LocalChapter] = []
        try:
            chapter_names = os.listdir(comic_path)
        except Exception:
            chapter_names = []
        for ch_name in chapter_names:
            ch_path = os.path.join(comic_path, ch_name)
            if not os.path.isdir(ch_path) or ch_name.startswith('.'):
                continue
            images = list_image_files(ch_path)
            if not images:
                continue
            chapters.append(
                LocalChapter(
                    label=ch_name,
                    path=ch_path,
                    images=images,
                    is_done=os.path.isfile(os.path.join(ch_path, DONE_MARKER)),
                )
            )

        if not chapters:
            continue
        chapters.sort(key=lambda c: natural_key(c.label))

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
            )
        )

    comics.sort(key=lambda c: natural_key(c.title))
    return comics
