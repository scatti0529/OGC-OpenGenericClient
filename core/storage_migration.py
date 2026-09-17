# -*- coding: utf-8 -*-
"""存储布局迁移（一次性、幂等）
==============================
把历史上散落在各处的**大体积缓存**与**小体积索引**归位到当前约定：

    data/                     索引 JSON、配置、数据库、7Z、avatars   —— 小体积、不可再生
    {下载根目录}/.cache/      缩略图 / 画廊图片 / 预览图 / 阅读临时缓存 —— 大体积、可再生
    data/offline_index/       漫画与画廊的离线索引 JSON

迁移项
------
缓存（搬去下载根目录）::

    data/ehentai/cache          -> {cache}/ehentai/cache
    data/ehentai/previews       -> {cache}/ehentai/previews
    data/ehentai/reader_cache   -> {cache}/ehentai/reader_cache
    data/easycopy/images        -> {cache}/easycopy/images
    data/thumb_cache            -> {cache}/thumbs      （更早的命名）
    {下载根}/.thumbs            -> {cache}/thumbs      （中间命名）

索引（搬回 data/）::

    {下载根}/.thumb_index.json  -> data/thumb_index.json   （值里的缓存路径会一并重写）
    data/thumb_index.json       -> 同上（合并，保留既有条目）
    {下载根}/.dir_cache         -> data/dir_cache
    data/.dir_cache             -> data/dir_cache
    {下载根}/.{平台}_offline_index.json -> data/offline_index/{平台}_offline_index.json

设计约束（改动本模块时务必保留）
--------------------------------
* **幂等**：源不存在就跳过，重复启动不会搬第二遍。
* **不覆盖**：目标已存在时逐文件合并，同名文件保留目标版本，绝不破坏新数据。
* **不误删**：合并后只回收**空目录**，不用 rmtree 强删 —— 万一有文件搬失败，
  它必须原地留着，而不是被连目录一起清掉。
* **不致命**：单项失败只记日志，绝不让程序起不来。
* **不阻塞**：同盘移动走 ``os.rename``（瞬时）；只有跨盘才会真正复制，此时打日志说明。
"""
import json
import os
import shutil
import time

# 从这里搬出去（旧位置）
LEGACY_CACHE_DIRS = (
    ('ehentai/cache', 'ehentai/cache'),
    ('ehentai/previews', 'ehentai/previews'),
    ('ehentai/reader_cache', 'ehentai/reader_cache'),
    ('easycopy/images', 'easycopy/images'),
    ('thumb_cache', 'thumbs'),
    ('ehentai/reader_cache', 'ehentai/reader_cache'),
)

# 下载根目录下需要用到的中间命名缓存目录（旧代码写在这里）
DOWNLOAD_ROOT_CACHE_DIRS = (
    ('.thumbs', 'thumbs'),
)

# 音乐目录的旧位置（相对程序根 / 用户数据目录）。
# 历史上音乐缓存与下载**各有独立配置键**，但默认值都指向同一个 music/：
#   · 源码模式   <项目根>/music
#   · 冻结模式   %APPDATA%\OGC-OpenGenericClient\music
# 现在两者都从 download_root 派生（见 core.config 的 music_*_dir），
# 启动时把旧目录里的歌搬过去，用户不会"下载的音乐凭空消失"。
LEGACY_MUSIC_DIRS = ('music',)

# 离线索引的平台前缀
OFFLINE_INDEX_PLATFORMS = ('easycopy', 'jmcomic', 'ehentai', 'ogc')

# 迁移完成标记：避免每次启动都做一遍全量 os.walk 检查（失败则下次重试）
_STATE_FILE = 'storage_migration.json'
# v3：新增「旧音乐目录 → {下载根}/music-download」这一步
_STATE_VERSION = 3


def _logger():
    try:
        from core.logger import logger
        return logger
    except Exception:
        return None


def _log(msg, level='info'):
    lg = _logger()
    if lg is None:
        return
    try:
        getattr(lg, level, lg.info)(f"[存储迁移] {msg}")
    except Exception:
        pass


def _dir_size(path: str) -> tuple:
    """返回 (文件数, 总字节数)"""
    n = 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            n += 1
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n, total


def _prune_empty_dirs(path: str):
    """自底向上回收空目录（非空目录保持不动，绝不递归强删）。"""
    if not os.path.isdir(path):
        return
    for root, dirs, files in os.walk(path, topdown=False):
        if files:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass


def _merge_move_dir(src: str, dst: str) -> tuple:
    """把 src 目录搬进 dst（目录合并），返回 (移动数, 移动字节数, 去重数, 冲突数)。

    目标不存在时优先整目录 ``os.rename``：同盘是瞬时的元数据操作，
    这是本项目 400MB+ 缓存能"秒搬"的关键；跨盘 rename 会抛 OSError，
    此时退回逐文件 ``shutil.move``（真正的复制，耗时但只发生一次）。

    同名文件策略（踩过坑）：缓存文件名是「源路径 md5 + 尺寸」派生的，**同名即同一份**。
    最初实现遇到同名就跳过并保留源文件，结果旧目录永远清不干净 ——
    实测残留 9448 个重复缩略图，白白占着空间，自检也会报"旧位置仍有残留"。
    现在改为：同名且**大小一致**才认定为重复副本 → 删源留目标；
    大小不一致说明不是同一份东西，一律保留源文件（宁可留垃圾也不误删数据）。
    """
    if not os.path.isdir(src):
        return 0, 0, 0, 0

    if not os.path.exists(dst):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(dst)) or '.', exist_ok=True)
            os.rename(src, dst)
            n, size = _dir_size(dst)
            return n, size, 0, 0
        except OSError:
            pass        # 跨盘/占用：走下面的逐文件合并

    moved = 0
    moved_bytes = 0
    deduped = 0
    conflicts = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == '.' else os.path.join(dst, rel)
        try:
            os.makedirs(target_root, exist_ok=True)
        except OSError:
            continue
        for name in files:
            s = os.path.join(root, name)
            d = os.path.join(target_root, name)
            if os.path.exists(d):
                try:
                    if os.path.getsize(s) == os.path.getsize(d):
                        os.remove(s)        # 同名同大小 → 重复副本，删源留目标
                        deduped += 1
                    else:
                        conflicts += 1      # 同名不同内容 → 不动它，保留源文件
                except OSError:
                    pass
                continue
            try:
                size = os.path.getsize(s)
                shutil.move(s, d)
                moved += 1
                moved_bytes += size
            except Exception:
                pass        # 单个文件失败就留着，绝不影响其它文件
    _prune_empty_dirs(src)
    return moved, moved_bytes, deduped, conflicts


def _move_file(src: str, dst: str) -> bool:
    """移动单个文件；目标已存在则保留目标（返回 False）。"""
    if not os.path.isfile(src):
        return False
    if os.path.exists(dst):
        return False
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dst)) or '.', exist_ok=True)
        shutil.move(src, dst)
        return True
    except Exception:
        return False


def _load_json(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _migrate_thumb_index(cfg) -> int:
    """把缩略图索引合并到 data/thumb_index.json，并重写其中的缓存路径。

    索引值是「缩略图文件的绝对路径」。缓存目录从 data/thumb_cache、
    {下载根}/.thumbs 统一搬到 {cache}/thumbs 之后，旧值会全部失效
    （``get_cached_thumb`` 会因文件不存在而丢弃条目 → 缩略图全部重算）。
    所以这里按前缀把值改写到新目录，保住已有缩略图。
    """
    new_index_file = os.path.join(str(cfg.data), 'thumb_index.json')
    new_thumbs = os.path.abspath(os.path.join(cfg.cache_dir, 'thumbs'))

    legacy_files = [
        new_index_file,                                       # 可能已存在的正式索引
        os.path.join(str(cfg.data), 'thumb_cache', 'index.json'),
        os.path.join(cfg.download_root, '.thumb_index.json'),
        os.path.join(str(cfg.data), '.thumb_index.json'),
    ]
    old_prefixes = [
        os.path.abspath(os.path.join(str(cfg.data), 'thumb_cache')),
        os.path.abspath(os.path.join(cfg.download_root, '.thumbs')),
        os.path.abspath(os.path.join(str(cfg.data), '.thumbs')),
    ]

    merged = {}
    for f in legacy_files:
        if os.path.isfile(f):
            merged.update(_load_json(f))
    if not merged:
        return 0

    fixed = {}
    rewritten = 0
    for key, value in merged.items():
        if isinstance(value, str) and value:
            for pref in old_prefixes:
                if value.startswith(pref):
                    value = os.path.join(new_thumbs, os.path.relpath(value, pref))
                    rewritten += 1
                    break
        fixed[key] = value

    try:
        os.makedirs(os.path.dirname(new_index_file), exist_ok=True)
        with open(new_index_file, 'w', encoding='utf-8') as fp:
            json.dump(fixed, fp, ensure_ascii=False)
    except Exception as e:
        _log(f"写入缩略图索引失败: {e}", 'error')
        return 0

    # 清掉已合并完的旧索引文件（避免下次重复合并出歧义）
    for f in legacy_files[1:]:
        if os.path.isfile(f):
            try:
                os.remove(f)
            except OSError:
                pass
    return rewritten


def _migrate_offline_indexes(cfg) -> int:
    """把 {下载根}/.{平台}_offline_index.json 收进 data/offline_index/"""
    moved = 0
    for platform in OFFLINE_INDEX_PLATFORMS:
        src = os.path.join(cfg.download_root, f'.{platform}_offline_index.json')
        dst = os.path.join(str(cfg.data), 'offline_index',
                           f'{platform}_offline_index.json')
        if _move_file(src, dst):
            moved += 1
    return moved


def _cleanup_empty_legacy_dirs(cfg):
    """回收迁移后剩下的空目录（如 data/download、data/temp_videos 之类的历史残留）。"""
    for name in ('download',):
        _prune_empty_dirs(os.path.join(str(cfg.data), name))


def _migrate_music_dirs(cfg) -> int:
    """把旧音乐目录里的文件搬进**由下载根目录派生**的新位置。

    背景：音乐过去有 ``music_cache_path`` / ``music_download_path`` 两个独立配置键，
    默认都指向同一个 ``music/``（源码模式在项目根，冻结模式在 %APPDATA%）。
    现在设置里只剩一个「下载目录」，两个键不再被读取 —— 但用户可能已经在里面
    存了歌，不能就这么丢下：

        {下载根}/music-download/      ← 旧 music/ 里的内容（下载的歌）
        {下载根}/.cache/music/        ← 显式配置过的 music_cache_path

    规则：
      * 两个旧键指向**不同**目录时各归各位；
      * 指向同一个目录（历史默认）时按"下载的音乐"处理，搬进 music-download；
      * 已经是新位置就跳过（幂等）；
      * 同名文件用 _merge_move_dir 的规则：同大小视为重复→删源，不同大小→保留源。

    返回搬移的文件数。
    """
    moved = 0
    try:
        new_cache = os.path.normcase(os.path.abspath(cfg.music_cache_dir))
        new_down = os.path.normcase(os.path.abspath(cfg.music_download_dir))
    except Exception:
        return 0

    def _move(src: str, dst: str, label: str):
        nonlocal moved
        if not src or not os.path.isdir(src):
            return
        try:
            s = os.path.normcase(os.path.abspath(src))
            d = os.path.normcase(os.path.abspath(dst))
        except Exception:
            return
        # 源就在新位置里（或源=目标）→ 没什么可搬的
        if s == d or s in (new_cache, new_down):
            return
        n, size, dedup, conflict = _merge_move_dir(src, dst)
        if n or dedup:
            moved += n
            _log(f"音乐{label}迁移 {src} -> {dst}"
                 f"（搬移 {n} 个, 去重 {dedup} 个, 冲突保留 {conflict} 个, "
                 f"{size / 1048576:.1f} MB）")

    cfg_dict = getattr(cfg, 'cfg', None) or {}
    old_cache = str(cfg_dict.get('music_cache_path', '') or '')
    old_down = str(cfg_dict.get('music_download_path', '') or '')

    try:
        different = bool(old_cache) and (
            not old_down or os.path.normcase(os.path.abspath(old_cache)) !=
            os.path.normcase(os.path.abspath(old_down)))
    except Exception:
        different = False

    # ① 用户显式配过、且两个键指向不同目录 → 各归各位
    if different:
        _move(old_cache, cfg.music_cache_dir, '缓存')
    if old_down:
        _move(old_down, cfg.music_download_dir, '下载')

    # ② 历史默认目录（两键相同 / 从未配置）：按下载的音乐处理
    for base in (getattr(cfg, 'root', None), getattr(cfg, 'data', None)):
        if not base:
            continue
        for name in LEGACY_MUSIC_DIRS:
            _move(os.path.join(str(base), name), cfg.music_download_dir, '旧目录')
    return moved


def migrate(force: bool = False) -> dict:
    """执行迁移。幂等；返回统计信息（供日志/测试断言）。

    Args:
        force: 忽略「已完成」标记，强制再走一遍（测试与排障用）。
    """
    from core.config import config as cfg

    state_file = os.path.join(str(cfg.data), _STATE_FILE)
    if not force:
        state = _load_json(state_file)
        if state.get('version') == _STATE_VERSION and state.get('ok'):
            return {'skipped': True}

    started = time.monotonic()
    stats = {'cache_dirs': {}, 'offline_indexes': 0, 'thumb_index_rewritten': 0,
             'music_moved': 0, 'skipped': False}

    # 1) 缓存目录 → 下载根目录/.cache
    for src_rel, dst_rel in LEGACY_CACHE_DIRS:
        src = os.path.join(str(cfg.data), *src_rel.split('/'))
        dst = os.path.join(cfg.cache_dir, *dst_rel.split('/'))
        if not os.path.isdir(src):
            continue
        n, size, dedup, conflict = _merge_move_dir(src, dst)
        if n or dedup or os.path.isdir(dst):
            stats['cache_dirs'][src_rel] = n
            stats['deduped'] = stats.get('deduped', 0) + dedup
            stats['conflicts'] = stats.get('conflicts', 0) + conflict
            _log(f"缓存迁移 {src_rel} -> .cache/{dst_rel}（搬移 {n} 个, "
                 f"去重 {dedup} 个, 冲突保留 {conflict} 个, {size / 1048576:.1f} MB）")

    # 1b) 下载根目录下的中间命名缓存
    for src_name, dst_rel in DOWNLOAD_ROOT_CACHE_DIRS:
        src = os.path.join(cfg.download_root, src_name)
        dst = os.path.join(cfg.cache_dir, *dst_rel.split('/'))
        if not os.path.isdir(src):
            continue
        n, size, dedup, conflict = _merge_move_dir(src, dst)
        stats['cache_dirs'][src_name] = n
        stats['deduped'] = stats.get('deduped', 0) + dedup
        stats['conflicts'] = stats.get('conflicts', 0) + conflict
        _log(f"缓存迁移 {src_name} -> .cache/{dst_rel}（搬移 {n} 个, "
             f"去重 {dedup} 个, 冲突保留 {conflict} 个, {size / 1048576:.1f} MB）")

    # 2) 索引 → data/
    try:
        stats['thumb_index_rewritten'] = _migrate_thumb_index(cfg)
    except Exception as e:
        _log(f"缩略图索引迁移失败: {e}", 'error')

    for src_name in ('.dir_cache',):
        for base in (cfg.download_root, str(cfg.data)):
            src = os.path.join(base, src_name)
            dst = os.path.join(str(cfg.data), 'dir_cache')
            if os.path.isdir(src):
                n, _size, dedup, _conflict = _merge_move_dir(src, dst)
                stats['cache_dirs'].setdefault('dir_cache', n)
                stats['deduped'] = stats.get('deduped', 0) + dedup

    try:
        stats['offline_indexes'] = _migrate_offline_indexes(cfg)
    except Exception as e:
        _log(f"离线索引迁移失败: {e}", 'error')

    # 3) 旧音乐目录 → 由下载根目录派生的新位置（音乐不再单独配置目录）
    try:
        stats['music_moved'] = _migrate_music_dirs(cfg)
    except Exception as e:
        _log(f"音乐目录迁移失败: {e}", 'error')

    _cleanup_empty_legacy_dirs(cfg)

    elapsed = time.monotonic() - started
    stats['elapsed'] = round(elapsed, 2)

    try:
        with open(state_file, 'w', encoding='utf-8') as fp:
            json.dump({'version': _STATE_VERSION, 'ok': True,
                       'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                       'elapsed': stats['elapsed']}, fp, ensure_ascii=False)
    except Exception:
        pass

    moved_total = sum(stats['cache_dirs'].values())
    if moved_total or stats['offline_indexes'] or stats['thumb_index_rewritten'] \
            or stats.get('music_moved'):
        _log(f"存储迁移完成：搬移 {moved_total} 个缓存文件、"
             f"{stats['offline_indexes']} 个离线索引、"
             f"{stats.get('music_moved', 0)} 个音乐文件、"
             f"重写 {stats['thumb_index_rewritten']} 条缩略图索引，"
             f"耗时 {elapsed:.2f}s")
    return stats


def needs_migration() -> bool:
    """是否需要迁移（未完成过才返回 True）——供 UI/日志提前提示用。"""
    from core.config import config as cfg
    state_file = os.path.join(str(cfg.data), _STATE_FILE)
    state = _load_json(state_file)
    return not (state.get('version') == _STATE_VERSION and state.get('ok'))
