# -*- coding: utf-8 -*-
"""E-Hentai 标签中文翻译（数据：EhTagTranslation/Database v7.x，db.raw.json.gz）

结构（v2 格式）：
    { "data": [ {"namespace": "female", "frontMatters": {"name": "女性", ...},
                 "data": { "ahegao": {"name": "阿黑颜", "intro": "..."}, ... } }, ... ] }

用法：
    from ehviewer.tag_translation import tag_translation, namespace_name
    tag_translation("female", "ahegao")   # -> "阿黑颜"（无翻译返回 ""）
    namespace_name("female")              # -> "女性"
"""
import gzip
import json
import os
import re

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "tag_translations.json.gz")

_index = None          # {namespace_lower: {raw_lower: 中文名}}
_ns_names = {}         # {namespace_lower: 命名空间中文名}
_loaded = False


def _clean_text(text):
    """清洗译名：去掉 markdown 图片/链接/HTML 与多余空白。"""
    if not text:
        return ""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)      # ![图标](url)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)   # [文字](url)
    text = re.sub(r"<[^>]+>", "", text)                    # <标签>
    return re.sub(r"\s+", " ", text).strip()


def _load():
    """惰性加载一次，失败时保持空索引（不抛异常，界面照常显示原文）。"""
    global _index, _ns_names, _loaded
    if _loaded:
        return
    _loaded = True
    _index = {}
    _ns_names = {}
    try:
        if not os.path.isfile(_DB_PATH):
            return
        with gzip.open(_DB_PATH, "rt", encoding="utf-8") as f:
            doc = json.load(f)
        for grp in (doc.get("data") or []):
            ns = (grp.get("namespace") or "").strip().lower()
            if not ns:
                continue
            fm = grp.get("frontMatters") or {}
            nn = _clean_text(fm.get("name"))
            if nn:
                _ns_names[ns] = nn
            m = _index.setdefault(ns, {})
            inner = grp.get("data") or {}
            if isinstance(inner, dict):
                for raw, info in inner.items():
                    if isinstance(info, dict):
                        nm = _clean_text(info.get("name"))
                        if nm:
                            m[raw.strip().lower()] = nm
    except Exception:
        _index = {}
        _ns_names = {}


def tag_translation(namespace, tag):
    """返回 (namespace, tag) 的中文翻译；查不到返回 ''。"""
    if not tag:
        return ""
    _load()
    t = tag.strip().lower()
    if not t:
        return ""
    ns = (namespace or "").strip().lower()
    m = _index.get(ns) if ns else None
    if m and t in m:
        return m[t]
    # 兼容：某些数据把整个 "ns:tag" 当作 raw 存（此时 t 已含冒号）
    if ns and ns + ":" in t:
        pass
    # 命名空间名直接命中（标签本身就是一个命名空间词）
    return _ns_names.get(t, "") if t in _ns_names else ""


def namespace_name(namespace):
    """返回命名空间的中文名（female -> 女性）；无则返回 ''。"""
    _load()
    return _ns_names.get((namespace or "").strip().lower(), "")
