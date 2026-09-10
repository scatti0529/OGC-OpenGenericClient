# -*- coding: utf-8 -*-
"""先备份 app_db.db，再按 DOWNLOAD_DIRNAME 清理真正孤儿（目录已不存在的 DOWNLOADS/DOWNLOAD_DIRNAME 记录）。"""
import os, sys, sqlite3, time, shutil
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE)
os.environ.setdefault('QT_LOGGING_RULES', 'default.warning=false')
sys.argv[0] = os.path.join(BASE, 'main.py')
from pages.album.ehentai_settings import ehentai_cfg as c
from pages.album import ehentai_sync as S
from ehviewer.config import get as _get

p = S.db_path()
print('db_path =', p)
# 1) 备份（含 -wal/-shm）
stamp = time.strftime('%Y%m%d_%H%M%S')
bak = p + '.bak_' + stamp
shutil.copy2(p, bak)
for sf in ('-wal', '-shm', '-journal'):
    if os.path.isfile(p + sf):
        shutil.copy2(p + sf, bak + sf)
print('backup =', bak, os.path.getsize(bak))

dldir = _get('download_dir', '')
print('dirname 参照目录 =', dldir, '(存在? %s)' % os.path.isdir(dldir))

conn = sqlite3.connect(p)
# 2) 统计孤儿：DOWNLOADS 行若有 DOWNLOAD_DIRNAME 且目录不存在
rows = conn.execute("SELECT GID FROM DOWNLOADS").fetchall()
dl_gids = {r[0] for r in rows}
dirname_map = {r[0]: r[1] for r in conn.execute("SELECT GID, DIRNAME FROM DOWNLOAD_DIRNAME").fetchall()}
orphan_dl = []
for gid in dl_gids:
    d = dirname_map.get(gid)
    if d:
        full = os.path.join(dldir or '', d or '')
        if not os.path.isdir(full):
            orphan_dl.append(gid)
    # 无 DIRNAME 记录 -> 视为无法判定，保留
print('DOWNLOADS 总 =', len(dl_gids), '| 真正孤儿(目录不存在) =', len(orphan_dl))

# 3) 删除孤儿 DOWNLOADS 行 + 其 DOWNLOAD_DIRNAME 行
if orphan_dl:
    placeholders = ','.join('?' * len(orphan_dl))
    conn.execute('DELETE FROM DOWNLOADS WHERE GID IN (%s)' % placeholders, orphan_dl)
    conn.execute('DELETE FROM DOWNLOAD_DIRNAME WHERE GID IN (%s)' % placeholders, orphan_dl)
    conn.commit()
    print('已删除 DOWNLOADS 孤儿 =', len(orphan_dl))

# 4) 清理 DOWNLOAD_DIRNAME 中目录不存在的记录
dd_orphans = conn.execute("SELECT GID, DIRNAME FROM DOWNLOAD_DIRNAME").fetchall()
del_dd = [(g, d) for g, d in dd_orphans if d and not os.path.isdir(os.path.join(dldir or '', d or ''))]
if del_dd:
    tmp = [g for g, _d in del_dd]
    ph = ','.join('?' * len(tmp))
    conn.execute('DELETE FROM DOWNLOAD_DIRNAME WHERE GID IN (%s)' % ph, tmp)
    conn.commit()
    print('清理 DOWNLOAD_DIRNAME 孤儿 =', len(del_dd))

print('最终: DOWNLOADS =', conn.execute('SELECT count(*) FROM DOWNLOADS').fetchone()[0],
      '| DOWNLOAD_DIRNAME =', conn.execute('SELECT count(*) FROM DOWNLOAD_DIRNAME').fetchone()[0],
      '| LOCAL_FAV =', conn.execute('SELECT count(*) FROM LOCAL_FAVORITES').fetchone()[0],
      '| HISTORY =', conn.execute('SELECT count(*) FROM HISTORY').fetchone()[0])
conn.close()
print('DONE (备份: %s)' % bak)
