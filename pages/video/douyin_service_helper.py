# -*- coding: utf-8 -*-
"""
抖音 Cookie 文件读写辅助（独立模块避免循环导入）
"""
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def save_cookie_file(cookie: str):
    """保存 Cookie 到 douyin_cookie.txt"""
    try:
        with open(os.path.join(_PROJECT_ROOT, "douyin_cookie.txt"), "w", encoding="utf-8") as f:
            f.write(cookie or "")
    except Exception:
        pass


def load_cookie_file() -> str:
    """从 douyin_cookie.txt 读取 Cookie"""
    try:
        path = os.path.join(_PROJECT_ROOT, "douyin_cookie.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().lstrip("\ufeff").strip()
    except Exception:
        pass
    return ""