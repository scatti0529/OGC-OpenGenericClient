# -*- coding: utf-8 -*-
"""把历史上"分家"的数据库合并进统一库
================================================

**背景**：全程序现在只有一个 SQLite 文件 ``data/ogc_users.db``（冻结时
``%APPDATA%\\OGC-OpenGenericClient\\ogc_users.db``）。但历史版本里有第二个库：

    data/ehentai/app_db.db      E-Hentai 模块的收藏 / 下载记录 / 历史 / 标签屏蔽
    <程序目录>/app_db.db        更早的 ehviewer 默认位置（__file__ 推导时期）
    <程序目录>/ehviewer/app_db.db

分家的后果：卸载向导只备份得到其中一个，换机只带走一个库就会丢另一半数据。
本模块负责把那些旧库里的数据**一条不落地搬进统一库**，然后把旧文件改名留档
（改成 ``*.merged-<时间戳>``，绝不删除 —— 万一搬错还能找回来）。

设计要点：

* **通用合并**：不写死表名。旧库里有哪些表就建哪些表（用旧库自己的
  ``CREATE TABLE`` 语句），列按两边都有的字段复制，未知的新表也能带过来。
  这样以后旧库多出什么表都不会静默丢失。
* **主键冲突时保留统一库里已有的行**（``INSERT OR IGNORE``）：重复执行安全，
  且不会用旧数据覆盖用户当前正在用的记录。
* **用"改名"当幂等标记**，不再单独维护状态文件：旧文件被改名后下次自然扫不到；
  中途失败则文件还在，下次启动自动重试。
* 整个流程只读旧库、只增统一库，任何异常都只记日志，**绝不影响程序启动**。
"""
import os
import shutil
import sqlite3
import time

from core import paths as _paths
from core.config import config as CFG
from core.logger import logger

#: 旧数据库相对于"用户数据目录 / 程序目录"的候选位置。
LEGACY_DB_RELPATHS = (
    os.path.join('ehentai', 'app_db.db'),   # 最近一个版本用的位置
    'app_db.db',                            # 更早：ehviewer 包内默认
    os.path.join('ehviewer', 'app_db.db'),  # 更早：包内子目录
)

#: 改名后缀（保留原文件，便于回溯）
BACKUP_SUFFIX = '.merged-'


def _iter_legacy_paths():
    """按优先级列出实际存在的旧库文件（去重）。"""
    seen, out = set(), []
    bases = []
    try:
        bases.append(str(CFG.data))
    except Exception:
        pass
    try:
        bases.append(str(_paths.program_dir()))
    except Exception:
        pass
    for base in bases:
        for rel in LEGACY_DB_RELPATHS:
            p = os.path.join(base, rel)
            key = os.path.normcase(os.path.abspath(p))
            if key in seen:
                continue
            seen.add(key)
            if os.path.isfile(p):
                out.append(p)
    # 排除统一库自身（万一它被放在候选位置上）
    try:
        me = os.path.normcase(os.path.abspath(CFG.data / 'ogc_users.db'))
        out = [p for p in out if os.path.normcase(os.path.abspath(p)) != me]
    except Exception:
        pass
    return out


def _snapshot(path: str) -> sqlite3.Connection:
    """把旧库快照到内存连接里再读。

    不直接打开原文件的原因：① 旧库可能处于 WAL 模式，直接拷文件会丢掉
    ``-wal`` 里未合并的数据；② 旧文件可能被其它进程占用。
    ``Connection.backup()`` 是 SQLite 官方的在线备份 API，能拿到一致快照。
    """
    src = sqlite3.connect(path, timeout=10.0)
    mem = sqlite3.connect(':memory:')
    try:
        src.backup(mem)
    finally:
        src.close()
    return mem


def _tables(conn: sqlite3.Connection):
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'").fetchall()
    return [(r[0], r[1]) for r in rows]


def _indexes(conn: sqlite3.Connection):
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' "
        "AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'").fetchall()
    return [(r[0], r[1]) for r in rows]


def _columns(conn: sqlite3.Connection, table: str):
    try:
        return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    except sqlite3.Error:
        return []


def _merge_into(target: sqlite3.Connection, old: sqlite3.Connection):
    """把 old 的所有表/索引/数据并进 target。返回 {表名: 新增行数}。"""
    stats = {}
    created = []
    for name, ddl in _tables(old):
        if not ddl:
            continue
        have = _columns(target, name)
        if not have:
            # 统一库里还没有这张表 —— 用旧库自己的建表语句原样建出来，
            # 这样即使将来旧库多出未知的表也不会丢数据。
            try:
                target.execute(ddl)
                created.append(name)
            except sqlite3.Error as e:
                logger.warning(f'[DB合并] 建表 {name} 失败（跳过该表）: {e}')
                continue
        old_cols = _columns(old, name)
        cols = [c for c in old_cols if c in set(_columns(target, name))]
        if not cols:
            continue
        collist = ', '.join(f'"{c}"' for c in cols)
        placeholders = ', '.join('?' * len(cols))
        sql = f'INSERT OR IGNORE INTO "{name}" ({collist}) VALUES ({placeholders})'
        moved = 0
        try:
            cur = old.execute(f'SELECT {collist} FROM "{name}"')
            while True:
                batch = cur.fetchmany(500)
                if not batch:
                    break
                before = target.total_changes
                target.executemany(sql, batch)
                moved += target.total_changes - before
        except sqlite3.Error as e:
            logger.warning(f'[DB合并] 复制表 {name} 出错（已复制的部分保留）: {e}')
        stats[name] = moved
    for name, ddl in _indexes(old):
        try:
            target.execute(ddl)
        except sqlite3.Error:
            pass
    target.commit()
    if created:
        logger.info(f'[DB合并] 统一库里新建了这些表: {created}')
    return stats


def merge_database(old_path: str, target_path: str = None,
                   rename_source: bool = False) -> dict:
    """把 ``old_path`` 这个库合并进统一库。

    Args:
        old_path: 旧库文件。
        target_path: 目标库；默认统一库。
        rename_source: 成功后是否把旧文件改名留档（内置的旧库位置用 True，
                       用户在设置里手动选的外部文件用 False —— 不该动别人的文件）。
    """
    from core.database import DB_PATH, init_ehentai_tables, missing_tables

    target_path = target_path or DB_PATH
    result = {'ok': False, 'source': old_path, 'target': target_path,
              'tables': {}, 'moved': 0, 'renamed': '', 'error': ''}
    if not old_path or not os.path.isfile(old_path):
        result['error'] = '源文件不存在'
        return result
    if os.path.normcase(os.path.abspath(old_path)) == \
            os.path.normcase(os.path.abspath(target_path)):
        result['error'] = '源库与目标库是同一个文件'
        return result

    try:
        # 统一库的表先建全，避免"并进来一张孤立表"这种半吊子状态
        try:
            init_ehentai_tables()
        except Exception:
            pass
        old = _snapshot(old_path)
        try:
            target = sqlite3.connect(target_path, timeout=30.0)
            try:
                target.execute('PRAGMA journal_mode=WAL')
                target.execute('PRAGMA busy_timeout=30000')
                result['tables'] = _merge_into(target, old)
            finally:
                target.close()
        finally:
            old.close()
        result['moved'] = sum(result['tables'].values())
        result['ok'] = True
    except Exception as e:
        result['error'] = f'{type(e).__name__}: {e}'
        logger.error(f'[DB合并] {old_path} → {target_path} 失败: {e}', exc_info=True)
        return result

    if rename_source:
        stamp = time.strftime('%Y%m%d-%H%M%S')
        new_path = f'{old_path}{BACKUP_SUFFIX}{stamp}'
        try:
            os.replace(old_path, new_path)
            for suffix in ('-wal', '-shm'):
                side = old_path + suffix
                if os.path.isfile(side):
                    try:
                        os.replace(side, new_path + suffix)
                    except OSError:
                        pass
            result['renamed'] = new_path
        except OSError as e:
            # 改名失败不影响"数据已经并过去"这个事实；下次会重新扫到并再并一遍
            # （INSERT OR IGNORE 保证不会重复插入）
            logger.warning(f'[DB合并] 旧库改名失败（数据已合并，下次会重扫）: {e}')
    logger.info(f"[DB合并] {os.path.basename(old_path)} → 统一库："
                f"搬移 {result['moved']} 行 {result['tables']}"
                + (f"，旧文件留档 {os.path.basename(result['renamed'])}"
                   if result['renamed'] else ''))
    return result


def merge_legacy_databases() -> dict:
    """启动时调用：把所有内置位置的旧库并进统一库。返回汇总统计。"""
    summary = {'files': [], 'moved': 0, 'skipped': 0, 'errors': []}
    for path in _iter_legacy_paths():
        try:
            r = merge_database(path, rename_source=True)
        except Exception as e:      # 绝不影响启动
            logger.error(f'[DB合并] 处理 {path} 异常: {e}', exc_info=True)
            summary['errors'].append(f'{path}: {e}')
            continue
        if r['ok']:
            summary['files'].append({'path': path, 'moved': r['moved'],
                                     'tables': r['tables'], 'renamed': r['renamed']})
            summary['moved'] += r['moved']
        else:
            summary['skipped'] += 1
            summary['errors'].append(f"{path}: {r['error']}")
    return summary


def describe() -> str:
    """一行摘要（日志/设置页用）。"""
    legacy = _iter_legacy_paths()
    from core.database import DB_PATH
    if not legacy:
        return f'数据库已统一：{DB_PATH}'
    return f'数据库已统一：{DB_PATH}（待合并的旧库 {len(legacy)} 个）'
