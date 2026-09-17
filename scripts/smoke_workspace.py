# -*- coding: utf-8 -*-
"""工作区标记回归测试：重装后能否自动恢复索引与配置

守住 `core/workspace.py` 的几条硬约束：

1. **索引与配置会被复制到下载目录**（`.ogc-portable/`），并写出标记 JSON；
2. **全新安装时自动还原**：索引回到 `data/`，配置只补缺失键、不覆盖用户设置；
3. **绝不导出凭据** —— `COOKIES` / `bili_key` 这类键必须被白名单挡住；
4. **版本要认**：标记 schema 比程序新时拒绝套用，而不是瞎解释新版数据。

全程在临时目录上用桩配置跑，不碰真实 data/ 与真实下载目录。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_workspace.py

退出码 0 表示全部通过。
"""
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

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


class _StubCfg:
    """给 workspace 模块用的最小配置桩。

    只实现 workspace 实际用到的接口：data / download_root / cache_dir /
    get() / __getitem__ / __setitem__。
    """

    def __init__(self, data: str, dl: str):
        self.data = Path(data)
        self.download_root = dl
        self.cache_dir = os.path.join(dl, '.cache')
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cfg = {
            'version': '1.0.0',
            'video_download_root': dl,
            'download_mode': 'auto',
            'download_max_threads': 8,
            # 下面两个是**凭据**，绝不能被导出到下载目录
            'COOKIES': 'SECRET-COOKIE-VALUE',
            'bili_key': 'SECRET-BILI-KEY',
            'HEADERS': {'Authorization': 'SECRET-TOKEN'},
        }

    def get(self, k, d=None):
        return self.cfg.get(k, d)

    def __getitem__(self, k):
        return self.cfg[k]

    def __setitem__(self, k, v):
        self.cfg[k] = v


def _seed_indexes(data_dir: str, dl: str):
    """造出一套"像真的"索引，其中缩略图索引的值指向下载根下的缓存。"""
    os.makedirs(os.path.join(data_dir, 'dir_cache'), exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'offline_index'), exist_ok=True)
    thumbs = os.path.join(dl, '.cache', 'thumbs')
    os.makedirs(thumbs, exist_ok=True)
    thumb_file = os.path.join(thumbs, 'deadbeef_320x180.jpg')
    with open(thumb_file, 'wb') as f:
        f.write(b'THUMB-BYTES')
    with open(os.path.join(data_dir, 'thumb_index.json'), 'w', encoding='utf-8') as f:
        json.dump({'/src/a.jpg': thumb_file, '/src/b.jpg': thumb_file}, f)
    for i in range(3):
        with open(os.path.join(data_dir, 'dir_cache', f'c{i}.json'), 'w', encoding='utf-8') as f:
            json.dump({'mtime': i, 'files': []}, f)
    with open(os.path.join(data_dir, 'offline_index', 'comic_offline_index.json'),
              'w', encoding='utf-8') as f:
        json.dump({'root': dl, 'comics': []}, f)
    # 再放两个"不可再生"的文件：它们是 is_fresh_install() 的判据
    with open(os.path.join(data_dir, 'ogc_users.db'), 'wb') as f:
        f.write(b'SQLITE')
    with open(os.path.join(data_dir, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'xc': 5}, f)


def _with_env(fn):
    """在临时目录 + 桩配置下运行 fn(tmp, data, dl)。"""
    import core.config as config_mod
    from core import workspace as ws

    tmp = tempfile.mkdtemp(prefix='ogc-ws-')
    data = os.path.join(tmp, 'data')
    dl = os.path.join(tmp, 'downloads')
    os.makedirs(data, exist_ok=True)
    os.makedirs(dl, exist_ok=True)
    original = config_mod.config
    config_mod.config = _StubCfg(data, dl)
    try:
        return fn(tmp, data, dl, ws)
    finally:
        config_mod.config = original
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════

def test_export_and_marker():
    """同步后：可移植副本与标记都要出现，且索引确实被复制。"""
    def run(tmp, data, dl, ws):
        _seed_indexes(data, dl)
        res = ws.sync_workspace()
        pdir = ws.portable_dir(dl)
        assert os.path.isdir(pdir), '可移植目录未创建'
        assert os.path.isfile(os.path.join(pdir, 'thumb_index.json')), '缩略图索引未复制'
        assert os.path.isdir(os.path.join(pdir, 'dir_cache')), '目录索引未复制'
        assert os.path.isdir(os.path.join(pdir, 'offline_index')), '离线索引未复制'

        mp = ws.marker_path(dl)
        assert os.path.isfile(mp), '标记文件未写出'
        with open(mp, 'r', encoding='utf-8') as f:
            mk = json.load(f)
        assert mk.get('app'), '标记缺少 app 标识'
        assert mk.get('schema') == ws.SCHEMA
        assert mk.get('download_root'), '标记缺少 download_root'
        assert mk.get('items'), '标记缺少条目清单'
        assert ws.summary(dl).get('has_workspace') is True
    _with_env(run)


def test_no_credentials_exported():
    """凭据绝不能落进下载目录 —— 这是最容易出事的点。"""
    def run(tmp, data, dl, ws):
        _seed_indexes(data, dl)
        ws.sync_workspace()
        pdir = ws.portable_dir(dl)

        # 1) 配置白名单：只允许 PORTABLE_CONFIG_KEYS 里的键
        cfgp = os.path.join(pdir, 'config.portable.json')
        assert os.path.isfile(cfgp), '可移植配置未生成'
        with open(cfgp, 'r', encoding='utf-8') as f:
            pc = json.load(f)
        for bad in ('COOKIES', 'bili_key', 'HEADERS'):
            assert bad not in pc, f'凭据键被导出了: {bad}'

        # 2) 整个下载目录做一次全文扫描，确认敏感值没以任何形式落盘
        blob = ''
        for root, _dirs, files in os.walk(dl):
            for fn in files:
                try:
                    with open(os.path.join(root, fn), 'r', encoding='utf-8', errors='ignore') as fh:
                        blob += fh.read()
                except OSError:
                    pass
        for secret in ('SECRET-COOKIE-VALUE', 'SECRET-BILI-KEY', 'SECRET-TOKEN'):
            assert secret not in blob, f'敏感值出现在下载目录中: {secret}'
    _with_env(run)


def test_restore_on_fresh_install():
    """全新安装（data/ 空）+ 下载目录有标记 → 自动还原索引与配置。"""
    def run(tmp, data, dl, ws):
        _seed_indexes(data, dl)
        ws.sync_workspace()

        # 模拟卸载后重装：清空用户数据目录
        for name in ('thumb_index.json', 'ogc_users.db', 'config.json'):
            p = os.path.join(data, name)
            if os.path.exists(p):
                os.remove(p)
        shutil.rmtree(os.path.join(data, 'dir_cache'), ignore_errors=True)
        shutil.rmtree(os.path.join(data, 'offline_index'), ignore_errors=True)
        assert ws.is_fresh_install() is True, '清空后应被判定为全新安装'

        res = ws.maybe_restore(dl)
        assert res.get('restored'), f'未还原任何文件: {res}'
        assert os.path.isfile(os.path.join(data, 'thumb_index.json')), '缩略图索引未还原'
        assert os.path.isfile(os.path.join(data, 'dir_cache', 'c0.json')), '目录索引未还原'
        assert os.path.isfile(
            os.path.join(data, 'offline_index', 'comic_offline_index.json')), '离线索引未还原'
        # 配置：缺失的键应被补上
        assert 'config_applied' in res or res.get('ok'), f'配置未还原: {res}'
    _with_env(run)


def test_restore_does_not_touch_used_data():
    """本机已有用户数据时，不得自动还原（避免覆盖正在用的东西）。"""
    def run(tmp, data, dl, ws):
        _seed_indexes(data, dl)
        ws.sync_workspace()
        # 不清理 data/：此时 is_fresh_install() 为假
        assert ws.is_fresh_install() is False
        res = ws.maybe_restore(dl)
        assert res.get('skipped') == 'has-user-data', f'不该动手，却做了: {res}'
    _with_env(run)


def test_newer_schema_refused():
    """标记 schema 比程序新时必须拒绝，而不是瞎解释。"""
    def run(tmp, data, dl, ws):
        _seed_indexes(data, dl)
        ws.sync_workspace()
        mp = ws.marker_path(dl)
        with open(mp, 'r', encoding='utf-8') as f:
            mk = json.load(f)
        mk['schema'] = ws.SCHEMA + 99
        with open(mp, 'w', encoding='utf-8') as f:
            json.dump(mk, f, ensure_ascii=False)

        # 清空 data/ 让它"看起来是全新安装"
        for name in ('thumb_index.json', 'ogc_users.db', 'config.json'):
            p = os.path.join(data, name)
            if os.path.exists(p):
                os.remove(p)
        res = ws.restore_from_workspace(dl, overwrite=False)
        assert res.get('reason') == 'newer-schema', f'应拒绝更高版本: {res}'
        assert not res.get('restored'), '拒绝了却还是还原了文件'
    _with_env(run)


def test_download_root_change_rewrites_index():
    """下载盘换过（盘符/路径变化）时，缩略图索引里的绝对路径要跟着改写。

    否则索引条目指向不存在的老路径，缩略图会被判定未命中而全部重算。
    """
    def run(tmp, data, dl, ws):
        _seed_indexes(data, dl)
        ws.sync_workspace()

        # 模拟：数据目录还在，但下载根换到了别处；标记里记的是旧路径
        new_dl = os.path.join(tmp, 'downloads2')
        os.makedirs(new_dl, exist_ok=True)
        mp = ws.marker_path(new_dl)
        old_marker = json.load(open(os.path.join(ws.marker_path(dl)), 'r', encoding='utf-8'))
        # 把可移植副本搬到新下载根，并保留旧的 download_root 记录
        shutil.copytree(ws.portable_dir(dl), ws.portable_dir(new_dl), dirs_exist_ok=True)
        with open(mp, 'w', encoding='utf-8') as f:
            json.dump(old_marker, f, ensure_ascii=False)

        # 清掉 data/ 里的缩略图索引，触发还原
        ti = os.path.join(data, 'thumb_index.json')
        if os.path.exists(ti):
            os.remove(ti)

        res = ws.restore_from_workspace(new_dl, overwrite=False)
        assert os.path.isfile(ti), '缩略图索引未还原'
        with open(ti, 'r', encoding='utf-8') as f:
            idx = json.load(f)
        # 原值指向 dl/.cache/thumbs，还原时应被改写到 new_dl 下
        vals = list(idx.values())
        assert vals, '索引为空'
        assert all(os.path.normcase(new_dl) in os.path.normcase(v) for v in vals), \
            f'索引路径未改写到新下载根: {vals[:2]}'
    _with_env(run)


if __name__ == '__main__':
    print('=== 工作区标记回归测试 ===')
    step('同步：生成可移植副本与标记', test_export_and_marker)
    step('安全：凭据绝不落进下载目录', test_no_credentials_exported)
    step('重装：全新安装自动还原索引与配置', test_restore_on_fresh_install)
    step('克制：已有用户数据时不自动还原', test_restore_does_not_touch_used_data)
    step('版本：拒绝更高 schema 的标记', test_newer_schema_refused)
    step('换盘：缩略图索引路径改写', test_download_root_change_rewrites_index)
    if FAILURES:
        print('WORKSPACE RESULT: FAILED ->', FAILURES)
        sys.exit(1)
    print('WORKSPACE RESULT: ALL PASSED')
