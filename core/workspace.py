# -*- coding: utf-8 -*-
"""工作区标记：让「卸载 → 重装 → 选同一个下载目录」能自动恢复

背景
----
程序卸载时只删程序本体（这是刻意的），但 ``%APPDATA%`` 里的用户数据
（索引、配置、账号库）**可能**被用户一并清掉。而下载根目录里的几百 MB
成果与几 MB 索引是用户真正在乎的东西 —— 尤其是「离线索引」和
「缩略图索引」，重建要重新扫描几万个文件、重算几千张缩略图。

做法
----
在下载根目录写这些东西（都以 ``.`` 开头，因此不会出现在文件库列表里）：

    {下载根}/.ogc-workspace.json     标记文件：版本、时间、条目清单与校验值
    {下载根}/.ogc-portable/          可移植副本：索引 JSON + 脱敏配置
    {下载根}/.ogc-portable/userdata/ 用户数据备份（**仅卸载时用户显式选择才写入**）

重装后首次启动时，若本机 ``%APPDATA%`` 还没有用户数据（全新安装），
且下载根目录里存在合法标记，就**自动还原**。

两层设计（安全边界在这里）
--------------------------
======================  ==========================  ===================================
``.ogc-portable/``      程序运行期**自动**维护      只有索引 + 脱敏配置，**绝不含凭据**
``.ogc-portable/userdata/``  仅在卸载时**用户选择**才写  含账号库/权限/全部配置，可完整恢复
======================  ==========================  ===================================

这样"程序自己默默干的"与"用户明确同意的"泾渭分明：账号库只有用户点头才会离开
``%APPDATA%``，而索引（丢了要重扫几万文件、重算几千张缩略图）则默认就有副本。

四条硬约束
----------
1. **自动同步绝不写入凭据**。配置只导出白名单键；``COOKIES``/``HEADERS``/
   ``bili_key`` / 自动登录账号等一律不落盘。导出前后都有断言兜底。
2. **不覆盖正在使用的数据**。只在 ``is_fresh_install()`` 为真时自动还原；
   已有用户数据时只记日志、不擅自动手。
3. **版本要认**。标记来自更高 schema 时拒绝套用（避免新版数据被旧版解释）。
4. **用户数据备份只由卸载流程触发**，运行期不碰。
"""
import hashlib
import json
import os
import shutil
import time

MARKER_NAME = '.ogc-workspace.json'
PORTABLE_DIR = '.ogc-portable'
# 卸载时用户数据的备份子目录（位于 .ogc-portable 下）。
# 只有卸载流程里用户显式选择才会写入 —— 程序运行期绝不碰它。
USERDATA_BACKUP_DIR = 'userdata'
# 备份用户数据时跳过的子目录：日志是噪音、缓存可再生，都没必要跟着备份
_BACKUP_SKIP_DIRS = {'logs', '.cache', '__pycache__', 'temp_videos'}
APP_TAG = 'OGC-OpenGenericClient'
SCHEMA = 1

# 允许导出到下载目录的配置键（白名单）。
# ⚠️ 加键前先问一句：这个值泄露出去有没有风险？凭据类一律不加。
PORTABLE_CONFIG_KEYS = (
    'video_download_root',
    'download_mode', 'download_max_threads',
    'download_parallel_threshold', 'download_retry_times',
    'save_mode', 'xc', 'delay',
)

# 索引类条目：(便携副本里的相对路径, USER_DIR 里的目标相对路径)
_PORTABLE_INDEX_ITEMS = (
    ('thumb_index.json', 'thumb_index.json'),
    ('dir_cache', 'dir_cache'),
    ('offline_index', 'offline_index'),
)


def _log(msg, level='info'):
    try:
        from core.logger import logger
        getattr(logger, level, logger.info)(f'[工作区] {msg}')
    except Exception:
        pass


def marker_path(download_root: str) -> str:
    return os.path.join(download_root, MARKER_NAME)


def portable_dir(download_root: str) -> str:
    return os.path.join(download_root, PORTABLE_DIR)


def _sha256(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 16), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ''


def _dir_stat(path: str) -> dict:
    n = 0
    total = 0
    newest = 0.0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                st = os.stat(os.path.join(root, f))
            except OSError:
                continue
            n += 1
            total += st.st_size
            newest = max(newest, st.st_mtime)
    return {'files': n, 'bytes': total, 'newest': round(newest, 3)}


# ═══════════════════════════════════════════════════════════
#  写标记 / 导出可移植副本
# ═══════════════════════════════════════════════════════════

def read_marker(download_root: str) -> dict:
    """读取标记；不存在或损坏返回 {}。"""
    if not download_root:
        return {}
    p = marker_path(download_root)
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get('app') == APP_TAG:
            return data
    except Exception:
        pass
    return {}


def _portable_config() -> dict:
    """导出可移植配置（白名单 + 兜底断言，绝不带凭据）。"""
    from core.config import config as CFG
    out = {}
    for k in PORTABLE_CONFIG_KEYS:
        v = CFG.get(k)
        if v is not None:
            out[k] = v
    # 双保险：万一白名单被误改，这里挡住明显敏感的值
    blob = json.dumps(out, ensure_ascii=False).lower()
    for bad in ('cookie', 'token', 'password', 'passwd', 'secret',
                'authorization', 'bili_key'):
        if bad in blob:
            _log(f'可移植配置里出现疑似敏感键 "{bad}"，已放弃导出配置', 'warning')
            return {}
    return out


def export_portable(download_root: str = '') -> dict:
    """把索引与脱敏配置复制到 ``{下载根}/.ogc-portable/``。

    用 mtime+大小先做变更判断，避免每次启动都复制 2MB 的索引。
    """
    from core.config import config as CFG
    root = download_root or CFG.download_root
    pdir = portable_dir(root)
    stats = {'copied': [], 'skipped': [], 'bytes': 0}
    try:
        os.makedirs(pdir, exist_ok=True)
    except OSError as e:
        _log(f'创建可移植目录失败: {e}', 'error')
        return stats

    for src_rel, _dst_rel in _PORTABLE_INDEX_ITEMS:
        src = os.path.join(str(CFG.data), *src_rel.split('/'))
        dst = os.path.join(pdir, os.path.basename(src_rel))
        if os.path.isdir(src):
            # 目录：逐文件比对，只搬新增/变了的
            for root_, _dirs, files in os.walk(src):
                rel = os.path.relpath(root_, src)
                target_root = dst if rel == '.' else os.path.join(dst, rel)
                try:
                    os.makedirs(target_root, exist_ok=True)
                except OSError:
                    continue
                for f in files:
                    s = os.path.join(root_, f)
                    d = os.path.join(target_root, f)
                    try:
                        if os.path.exists(d) and os.path.getmtime(d) >= os.path.getmtime(s) \
                                and os.path.getsize(d) == os.path.getsize(s):
                            stats['skipped'].append(f)
                            continue
                        shutil.copy2(s, d)
                        stats['copied'].append(f)
                        stats['bytes'] += os.path.getsize(d)
                    except OSError:
                        pass
        elif os.path.isfile(src):
            try:
                if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src) \
                        and os.path.getmtime(dst) >= os.path.getmtime(src):
                    stats['skipped'].append(os.path.basename(src_rel))
                    continue
                shutil.copy2(src, dst)
                stats['copied'].append(os.path.basename(src_rel))
                stats['bytes'] += os.path.getsize(dst)
            except OSError:
                pass

    # 配置（脱敏）
    cfg_out = _portable_config()
    if cfg_out:
        try:
            p = os.path.join(pdir, 'config.portable.json')
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(cfg_out, f, ensure_ascii=False, indent=2)
            stats['copied'].append('config.portable.json')
        except OSError:
            pass

    # GUI 配置（主题/透明度等，无凭据）
    try:
        from core import paths as _paths
        gp = _paths.gui_config_path()
        if os.path.isfile(gp):
            shutil.copy2(gp, os.path.join(pdir, 'gui-config.json'))
            stats['copied'].append('gui-config.json')
    except Exception:
        pass

    return stats


def write_marker(download_root: str = '', extra: dict = None) -> dict:
    """写出/更新工作区标记。返回标记内容（失败返回 {}）。"""
    from core.config import config as CFG
    from core import paths as _paths

    root = download_root or CFG.download_root
    if not root or not os.path.isdir(root):
        return {}

    old = read_marker(root)
    items = {}
    pdir = portable_dir(root)
    for src_rel, _ in _PORTABLE_INDEX_ITEMS:
        name = os.path.basename(src_rel)
        p = os.path.join(pdir, name)
        if os.path.isdir(p):
            items[name] = _dir_stat(p)
        elif os.path.isfile(p):
            st = os.stat(p)
            items[name] = {'files': 1, 'bytes': st.st_size, 'sha256': _sha256(p)}
    cfgp = os.path.join(pdir, 'config.portable.json')
    if os.path.isfile(cfgp):
        items['config.portable.json'] = {'files': 1, 'bytes': os.path.getsize(cfgp)}

    marker = {
        'schema': SCHEMA,
        'app': APP_TAG,
        'app_version': str(CFG.get('version', '')),
        'frozen': _paths.is_frozen(),
        'created_at': old.get('created_at') or time.strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'download_root': os.path.abspath(root),
        'portable_dir': PORTABLE_DIR,
        'items': items,
        'note': '此文件由程序自动生成，用于重装后识别工作区；删除它不影响已下载的内容。',
    }
    if extra:
        marker.update(extra)
    try:
        p = marker_path(root)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(marker, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except OSError as e:
        _log(f'写标记失败: {e}', 'error')
        return {}
    return marker


def sync_workspace(download_root: str = '') -> dict:
    """启动/设置变更后调用：导出可移植副本 + 更新标记。"""
    try:
        stats = export_portable(download_root)
        marker = write_marker(download_root)
        if stats.get('copied'):
            _log(f"已更新工作区副本（{len(stats['copied'])} 个文件, "
                 f"{stats.get('bytes', 0) / 1024:.0f} KB）")
        return {'stats': stats, 'marker': marker}
    except Exception as e:
        _log(f'同步工作区失败（不影响使用）: {e}', 'error')
        return {}


# ═══════════════════════════════════════════════════════════
#  还原
# ═══════════════════════════════════════════════════════════

def backup_user_data(download_root: str = '') -> dict:
    """把整个用户数据目录备份到 ``{下载根}/.ogc-portable/userdata/``。

    **只在卸载流程里、用户显式选择时才调用。** 与运行期自动同步的区别：
    这里包含 ``ogc_users.db``（账号与密码哈希）、权限、全部配置，
    因此绝不能在程序运行期默默执行。

    跳过 ``logs/`` 与 ``.cache/``：前者是噪音，后者可再生且体积大。

    Returns:
        {'ok': bool, 'files': int, 'bytes': int, 'dest': str, 'reason': str}
    """
    from core.config import config as CFG
    root = download_root or CFG.download_root
    src = str(CFG.data)
    dest = os.path.join(portable_dir(root), USERDATA_BACKUP_DIR)
    out = {'ok': False, 'files': 0, 'bytes': 0, 'dest': dest, 'reason': ''}

    if not os.path.isdir(src):
        out['reason'] = 'no-user-data'
        return out
    if not root or not os.path.isdir(root):
        out['reason'] = 'no-download-root'
        return out
    # 安全底线：绝不把用户数据备份进自己的子目录（会无限递归）
    if os.path.normcase(os.path.abspath(dest)).startswith(
            os.path.normcase(os.path.abspath(src)) + os.sep):
        out['reason'] = 'dest-inside-source'
        return out

    try:
        os.makedirs(dest, exist_ok=True)
        for cur, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in _BACKUP_SKIP_DIRS]
            rel = os.path.relpath(cur, src)
            troot = dest if rel == '.' else os.path.join(dest, rel)
            try:
                os.makedirs(troot, exist_ok=True)
            except OSError:
                continue
            for fn in files:
                s = os.path.join(cur, fn)
                d = os.path.join(troot, fn)
                try:
                    shutil.copy2(s, d)
                    out['files'] += 1
                    out['bytes'] += os.path.getsize(d)
                except OSError:
                    pass
        out['ok'] = out['files'] > 0
    except Exception as e:
        out['reason'] = str(e)
    return out


def has_userdata_backup(download_root: str = '') -> bool:
    """下载目录里是否有卸载时留下的用户数据备份。"""
    from core.config import config as CFG
    root = download_root or CFG.download_root
    d = os.path.join(portable_dir(root), USERDATA_BACKUP_DIR)
    try:
        return os.path.isdir(d) and bool(os.listdir(d))
    except OSError:
        return False


def is_fresh_install() -> bool:
    """本机是否还没有用户数据（决定能否自动还原）。"""
    from core.config import config as CFG
    d = str(CFG.data)
    for name in ('ogc_users.db', 'config.json', 'thumb_index.json'):
        if os.path.exists(os.path.join(d, name)):
            return False
    return True


def restore_from_workspace(download_root: str = '', marker: dict = None,
                           overwrite: bool = False) -> dict:
    """把可移植副本还原进 ``data/``（USER_DIR）。

    Args:
        download_root: 下载根目录；默认取当前配置。
        marker: 已读到的标记（省一次 IO）。
        overwrite: 是否覆盖已存在的索引文件。默认 False ——
                   自动还原只在全新安装时发生，不覆盖用户正在用的数据。
    """
    from core.config import config as CFG
    root = download_root or CFG.download_root
    mk = marker if marker is not None else read_marker(root)
    result = {'ok': False, 'restored': [], 'skipped': [], 'reason': ''}
    if not mk:
        result['reason'] = 'no-marker'
        return result
    if int(mk.get('schema', 0)) > SCHEMA:
        result['reason'] = 'newer-schema'
        _log(f"工作区标记版本 {mk.get('schema')} 高于本程序支持的 {SCHEMA}，"
             f"拒绝套用（请升级程序后再试）", 'warning')
        return result

    pdir = os.path.join(root, mk.get('portable_dir') or PORTABLE_DIR)
    if not os.path.isdir(pdir):
        result['reason'] = 'no-portable'
        return result

    old_root = str(mk.get('download_root') or '')
    new_root = os.path.abspath(root)
    root_changed = bool(old_root) and os.path.normcase(os.path.abspath(old_root)) != os.path.normcase(new_root)

    for src_rel, dst_rel in _PORTABLE_INDEX_ITEMS:
        src = os.path.join(pdir, os.path.basename(src_rel))
        dst = os.path.join(str(CFG.data), *dst_rel.split('/'))
        if os.path.isdir(src):
            for r_, _d, files in os.walk(src):
                rel = os.path.relpath(r_, src)
                troot = dst if rel == '.' else os.path.join(dst, rel)
                try:
                    os.makedirs(troot, exist_ok=True)
                except OSError:
                    continue
                for f in files:
                    s = os.path.join(r_, f)
                    d = os.path.join(troot, f)
                    if os.path.exists(d) and not overwrite:
                        result['skipped'].append(f)
                        continue
                    try:
                        shutil.copy2(s, d)
                        result['restored'].append(f)
                    except OSError:
                        pass
        elif os.path.isfile(src):
            if os.path.exists(dst) and not overwrite:
                result['skipped'].append(os.path.basename(src_rel))
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                result['restored'].append(os.path.basename(src_rel))
            except OSError:
                pass

    # 下载盘换过盘符时，缩略图索引里的绝对路径会失效 —— 按前缀改写
    if root_changed:
        n = _rewrite_index_root(os.path.join(str(CFG.data), 'thumb_index.json'),
                                old_root, new_root)
        if n:
            result['rewritten'] = n
            _log(f'下载根目录已从 {old_root} 变为 {new_root}，'
                 f'改写 {n} 条缩略图索引路径')

    # 配置：只补**缺失**的键，不覆盖用户已有的设置
    cfgp = os.path.join(pdir, 'config.portable.json')
    if os.path.isfile(cfgp):
        try:
            with open(cfgp, 'r', encoding='utf-8') as f:
                pc = json.load(f)
            applied = []
            for k, v in (pc or {}).items():
                if k not in PORTABLE_CONFIG_KEYS:
                    continue          # 白名单外一律不认，防止手工塞进来的键
                if overwrite or CFG.get(k) in (None, ''):
                    CFG[k] = v
                    applied.append(k)
            if applied:
                result['config_applied'] = applied
        except Exception as e:
            _log(f'还原可移植配置失败: {e}', 'warning')

    # 卸载时用户选择备份的**用户数据**（账号库/权限/全部配置）——
    # 只有存在该备份时才还原；同样遵循"不覆盖已有数据"。
    ubak = os.path.join(pdir, USERDATA_BACKUP_DIR)
    if os.path.isdir(ubak):
        n_before = len(result['restored'])
        for r_, _d, files in os.walk(ubak):
            rel = os.path.relpath(r_, ubak)
            troot = str(CFG.data) if rel == '.' else os.path.join(str(CFG.data), rel)
            try:
                os.makedirs(troot, exist_ok=True)
            except OSError:
                continue
            for fn in files:
                s = os.path.join(r_, fn)
                d = os.path.join(troot, fn)
                if os.path.exists(d) and not overwrite:
                    result['skipped'].append(fn)
                    continue
                try:
                    shutil.copy2(s, d)
                    result['restored'].append(fn)
                except OSError:
                    pass
        if len(result['restored']) > n_before:
            result['userdata_restored'] = len(result['restored']) - n_before
            _log(f"已还原卸载时备份的用户数据：{result['userdata_restored']} 个文件")

    result['ok'] = bool(result['restored'] or result.get('config_applied'))
    return result


def _rewrite_index_root(index_file: str, old_root: str, new_root: str) -> int:
    """把缩略图索引里指向旧下载根的路径改写到新根（值 = 缩略图绝对路径）。"""
    if not os.path.isfile(index_file):
        return 0
    old_pref = os.path.abspath(old_root)
    new_pref = os.path.abspath(new_root)
    try:
        with open(index_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return 0
        n = 0
        for k, v in list(data.items()):
            if isinstance(v, str) and v.startswith(old_pref):
                data[k] = os.path.join(new_pref, os.path.relpath(v, old_pref))
                n += 1
        if n:
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        return n
    except Exception:
        return 0


def maybe_restore(download_root: str = '') -> dict:
    """启动时调用：全新安装 + 下载根有工作区 → 自动还原。

    已有用户数据时只记日志不动手，避免覆盖用户正在用的东西。
    """
    from core.config import config as CFG
    root = download_root or CFG.download_root
    mk = read_marker(root)
    if not mk:
        return {'skipped': 'no-marker'}
    if not is_fresh_install():
        _log(f'检测到下载目录里有工作区标记（{mk.get("updated_at")}），'
             f'但本机已有用户数据，跳过自动还原')
        return {'skipped': 'has-user-data'}
    res = restore_from_workspace(root, marker=mk, overwrite=False)
    if res.get('restored'):
        _log(f"已从下载目录的工作区恢复 {len(res['restored'])} 个索引文件"
             f"（{mk.get('updated_at')} 的快照）")
    return res


def summary(download_root: str = '') -> dict:
    """给设置页/日志用的一行摘要。"""
    from core.config import config as CFG
    root = download_root or CFG.download_root
    mk = read_marker(root)
    if not mk:
        return {'has_workspace': False, 'path': root}
    return {
        'has_workspace': True,
        'path': root,
        'updated_at': mk.get('updated_at', ''),
        'schema': mk.get('schema'),
        'items': mk.get('items', {}),
        'portable_dir': os.path.join(root, mk.get('portable_dir') or PORTABLE_DIR),
    }
