# -*- coding: utf-8 -*-
"""存储布局迁移工具（默认只预览，加 --apply 才真正搬）

把大体积缓存从程序目录搬到下载根目录，把散落在下载目录里的索引收回 data/。
程序启动时也会自动做一次（core/storage_migration），本脚本用于：

* **先看清楚会发生什么**（默认 dry-run，不动任何文件）
* 手动强制执行一次
* 迁移前后对比 data/ 体积

用法::

    .venv\\Scripts\\python.exe scripts\\migrate_storage.py            # 预览
    .venv\\Scripts\\python.exe scripts\\migrate_storage.py --apply    # 执行
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 控制台多为 GBK：不重配编码的话，输出里的非 GBK 字符（emoji/制表符）会直接
# 抛 UnicodeEncodeError 让工具崩在半路。这里统一成 UTF-8 + 容错替换。
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def _dir_stat(path):
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


def _mb(b):
    return f"{b / 1048576:.1f} MB"


def _pending(source_pairs):
    """返回 [(说明, 源, 目标, 文件数, 字节数)]，只含真实存在的源。"""
    out = []
    for label, src, dst in source_pairs:
        if os.path.isdir(src):
            n, size = _dir_stat(src)
            out.append((label, src, dst, n, size))
        elif os.path.isfile(src):
            try:
                size = os.path.getsize(src)
            except OSError:
                size = 0
            out.append((label, src, dst, 1, size))
    return out


def _backup_irreplaceable(data, dl):
    """迁移前备份**不可再生**的小文件（索引 / 数据库 / 配置）。

    那 700MB 缓存丢了还能重新下载或重算，但索引与数据库丢了就是真丢。
    备份落在 ``data/_migration_backup_<时间戳>/``（data/ 不参与文件库扫描，
    也不会被"清理缓存"误删）。
    """
    import shutil
    import time
    from core import storage_migration as SM

    stamp = time.strftime('%Y%m%d_%H%M%S')
    dest = os.path.join(data, f'_migration_backup_{stamp}')
    os.makedirs(dest, exist_ok=True)

    items = [
        os.path.join(data, 'thumb_index.json'),
        os.path.join(data, 'ogc_users.db'),
        os.path.join(data, 'config.json'),
        os.path.join(dl, '.thumb_index.json'),
        os.path.join(dl, '.dir_cache'),
    ]
    for plat in SM.OFFLINE_INDEX_PLATFORMS:
        items.append(os.path.join(dl, f'.{plat}_offline_index.json'))

    copied = []
    for src in items:
        try:
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(dest, os.path.basename(src)),
                                dirs_exist_ok=True)
                copied.append(os.path.basename(src) + '/')
            elif os.path.isfile(src):
                shutil.copy2(src, dest)
                copied.append(os.path.basename(src))
        except Exception as e:
            print(f"  [备份失败] {src}: {e}")
    return dest, copied


def _verify(data, dl, cache):
    """自检：确认新布局生效、索引可用、旧缓存目录已清空。"""
    print()
    print('=' * 74)
    print('布局自检')
    print('=' * 74)

    print('data/ 顶层（应只剩：索引 JSON / 配置 / 数据库 / 7Z / avatars / 备份）')
    for name in sorted(os.listdir(data)):
        full = os.path.join(data, name)
        if os.path.isdir(full):
            n, size = _dir_stat(full)
            print(f"  [DIR ] {name:<30} {n:>6} 文件 {_mb(size):>10}")
        else:
            print(f"  [FILE] {name:<30} {'':>6}      {_mb(os.path.getsize(full)):>10}")

    print()
    print(f'缓存目录顶层: {cache}')
    for name in sorted(os.listdir(cache)):
        full = os.path.join(cache, name)
        n, size = _dir_stat(full) if os.path.isdir(full) else (1, os.path.getsize(full))
        print(f"  - {name:<30} {n:>6} 文件 {_mb(size):>10}")

    print()
    print('残留检查（旧位置上不应再有缓存目录）')
    stale = []
    for rel in ('ehentai/cache', 'ehentai/previews', 'ehentai/reader_cache',
                'easycopy/images', 'thumb_cache', '.thumbs', '.dir_cache'):
        for base in (data, dl):
            p = os.path.join(base, *rel.split('/'))
            if os.path.isdir(p) and os.listdir(p):
                stale.append((p, len(os.listdir(p))))
    if stale:
        print('  [!] 仍有非空旧目录（多为同名不同大小的冲突文件，被保守保留）:')
        for p, n in stale:
            print(f'      {p}  ({n} 个文件)')
        print('      可执行 --cleanup 清掉空目录；非空的请自行确认后删除。')
    else:
        print('  [OK] 旧位置已无残留缓存目录')

    print()
    print('索引完整性（缩略图索引抽样）')
    idx_file = os.path.join(data, 'thumb_index.json')
    try:
        with open(idx_file, 'r', encoding='utf-8') as f:
            idx = json.load(f)
    except Exception as e:
        print(f'  [!] 无法读取索引: {e}')
        return 1
    total = len(idx)
    checked = 0
    missing = 0
    for key, value in list(idx.items())[:200]:
        checked += 1
        if not (isinstance(value, str) and os.path.isfile(value)):
            missing += 1
    print(f"  条目总数 {total}，抽样 {checked}，失效 {missing}")
    if checked and missing == checked:
        print('  [!] 抽样全部失效 —— 索引里的缓存路径可能没被正确重写')
        return 1
    print('  [OK] 索引指向的缓存文件存在')
    return 0


def _cleanup(data, dl):
    """收尾：只保留最新一份迁移备份，并回收旧位置的空目录。"""
    import shutil

    backups = sorted(
        [d for d in os.listdir(data) if d.startswith('_migration_backup_')])
    removed = []
    for name in backups[:-1]:          # 保留最新一份
        try:
            shutil.rmtree(os.path.join(data, name), ignore_errors=True)
            removed.append(name)
        except Exception:
            pass
    print(f"备份清理：保留 {backups[-1] if backups else '(无)'}，"
          f"删除 {len(removed)} 份旧备份")

    for rel in ('thumb_cache', '.thumbs', '.dir_cache', 'ehentai/cache',
                'ehentai/previews', 'easycopy/images', 'download'):
        for base in (data, dl):
            p = os.path.join(base, *rel.split('/'))
            if os.path.isdir(p) and not os.listdir(p):
                try:
                    os.rmdir(p)
                    print(f"  已删除空目录 {p}")
                except OSError:
                    pass
    return 0


def main() -> int:
    apply_now = '--apply' in sys.argv
    verify_only = '--verify' in sys.argv
    cleanup = '--cleanup' in sys.argv

    from core.config import config as CFG, CACHE_DIR_NAME
    from core import storage_migration as SM

    # 关键：本工具必须操作**真实的项目 data/**，而不是 scripts/data。
    # 默认 root 取自 sys.argv[0]（= scripts/xxx.py → scripts/），这是为让冒烟测试
    # 与真实数据隔离而有意为之；维护脚本必须显式改回项目根（见 ConfigManager.set_root）。
    CFG.set_root(BASE)

    data = str(CFG.data)
    dl = CFG.download_root
    cache = CFG.cache_dir

    print('=' * 74)
    print('存储布局迁移工具')
    print('=' * 74)
    print(f"程序数据目录 data/   : {data}")
    print(f"下载根目录           : {dl}")
    print(f"缓存目录             : {cache}   ({CACHE_DIR_NAME})")
    print(f"离线索引目录         : {os.path.join(data, 'offline_index')}")
    print()

    if verify_only:
        return _verify(data, dl, cache)

    if cleanup:
        return _cleanup(data, dl)

    same = os.path.normcase(os.path.abspath(data)) == os.path.normcase(os.path.abspath(dl))
    if same:
        print('[!] 下载根目录与 data/ 是同一个目录 —— 缓存搬过去仍在 data/ 内。')
        print('    要真正给程序目录瘦身，请在「设置」里把下载根目录改到别的盘/目录，')
        print('    或直接修改 data/config.json 的 video_download_root。')
        print()

    pairs = []
    for rel, dst_rel in SM.LEGACY_CACHE_DIRS:
        pairs.append((f'缓存 {rel}',
                      os.path.join(data, *rel.split('/')),
                      os.path.join(cache, *dst_rel.split('/'))))
    for name, dst_rel in SM.DOWNLOAD_ROOT_CACHE_DIRS:
        pairs.append((f'缓存 {name}',
                      os.path.join(dl, name),
                      os.path.join(cache, *dst_rel.split('/'))))
    pairs.append(('目录索引 .dir_cache', os.path.join(dl, '.dir_cache'),
                  os.path.join(data, 'dir_cache')))
    pairs.append(('缩略图索引 .thumb_index.json',
                  os.path.join(dl, '.thumb_index.json'),
                  os.path.join(data, 'thumb_index.json')))
    for platform in SM.OFFLINE_INDEX_PLATFORMS:
        pairs.append((f'离线索引 {platform}',
                      os.path.join(dl, f'.{platform}_offline_index.json'),
                      os.path.join(data, 'offline_index',
                                   f'{platform}_offline_index.json')))

    # 去重（LEGACY_CACHE_DIRS 里有重复项）
    seen = set()
    unique = []
    for item in pairs:
        key = os.path.normcase(os.path.abspath(item[1]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    pending = _pending(unique)
    n_data, size_data = _dir_stat(data)

    if not pending:
        print('[OK] 没有需要迁移的旧布局内容，当前已是新布局。')
        print(f"   data/ 现有 {n_data} 个文件, {_mb(size_data)}")
        return 0

    print(f"待迁移 {len(pending)} 项（data/ 当前 {n_data} 个文件, {_mb(size_data)}）：")
    total_files = 0
    total_bytes = 0
    for label, src, dst, n, size in pending:
        total_files += n
        total_bytes += size
        print(f"  - {label:<28} {n:>6} 个文件 {_mb(size):>12}")
        print(f"      {src}")
        print(f"   -> {dst}")
    print()
    print(f"合计：{total_files} 个文件, {_mb(total_bytes)}")

    if not apply_now:
        print()
        print('这是预览（dry-run），未改动任何文件。')
        print('确认无误后执行：')
        print(f'    {sys.executable} scripts\\migrate_storage.py --apply')
        return 0

    print()
    print('开始迁移...')
    bk, copied = _backup_irreplaceable(data, dl)
    print(f"  已备份不可再生文件到 {bk}")
    print(f"  备份内容: {', '.join(copied) if copied else '(无)'}")
    stats = SM.migrate(force=True)
    print(f"迁移完成，耗时 {stats.get('elapsed')}s")

    n_data2, size_data2 = _dir_stat(data)
    n_cache, size_cache = _dir_stat(cache)
    print()
    print('─' * 74)
    print(f"data/   : {n_data} 个文件 {_mb(size_data)}  ->  "
          f"{n_data2} 个文件 {_mb(size_data2)}")
    print(f"缓存目录: {n_cache} 个文件 {_mb(size_cache)}")
    print('─' * 74)

    # 迁移后做一次自检
    try:
        from core import storage_migration as SM2
        left = SM2.needs_migration()
        print('迁移标记:', '未完成（下次启动会重试）' if left else '已完成')
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
