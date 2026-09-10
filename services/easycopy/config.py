# -*- coding: utf-8 -*-
"""拷贝漫画全局配置：域名管理、路径、常量（移植自 OGC-EasyCopy）。"""
from __future__ import annotations

import re
from dataclasses import dataclass

APP_NAME = "EasyCopy 拷贝漫画"
APP_VERSION = "1.0.0"

# 桌面 UA（与浏览器一致）
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 默认候选域名（按优先级排序）
DEFAULT_HOSTS = [
    "www.2026copy.com",
    "2026copy.com",
    "www.2025copy.com",
    "2025copy.com",
    "www.mangacopy.com",
    "mangacopy.com",
    "www.copy3000.com",
    "www.2027copy.com",
    "2027copy.com",
]

PROFILE_PATH = "/person/home"

# 路径 -> 标签页索引 映射
TAB_INDEX_MAP = [
    ("/rank", 2),
    ("/web/login", 3),
    ("/person", 3),
    ("/comics", 1),
    ("/comic", 1),
    ("/filter", 1),
    ("/search", 1),
    ("/recommend", 1),
    ("/newest", 1),
    ("/author", 1),
]


@dataclass
class HostProbe:
    """域名探测结果。"""

    host: str
    success: bool
    latency_ms: int
    status_code: int | None = None
    address_signature: str = ""


def normalize_host(host: str) -> str:
    return host.strip().lower()


def normalize_host_input(value: str) -> str:
    """把用户输入（可能带协议/路径/端口）归一成裸域名。"""
    text = value.strip()
    if not text:
        return ""
    # 带协议
    if "://" in text:
        text = text.split("://", 1)[1]
    elif text.startswith("//"):
        text = text[2:]
    # 去掉路径
    text = re.split(r"[/\\?#]", text)[0]
    # 去掉用户信息
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    # 去掉端口（只处理最后一个冒号，排除 IPv6 简化处理）
    if text.count(":") == 1 and "]" not in text:
        text = text.rsplit(":", 1)[0]
    return normalize_host(text)


def is_valid_host_name(host: str) -> bool:
    h = normalize_host(host)
    if not h or len(h) > 253 or ".." in h or " " in h or h.startswith(".") or h.endswith("."):
        return False
    label_pattern = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
    return all(label and len(label) <= 63 and label_pattern.match(label) for label in h.split("."))


def tab_index_for_path(path: str) -> int:
    """根据路径返回底部标签页索引。"""
    p = path.lower()
    for prefix, index in TAB_INDEX_MAP:
        if p.startswith(prefix):
            return index
    return 0
