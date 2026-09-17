# -*- coding: utf-8 -*-
"""存储布局回归测试：data/ 放索引，下载根目录放缓存。

守住的约定（改路径的人请先看这里）：

1. **下载根目录** = 配置里的 ``video_download_root``；配置了就建目录，
   **不因"目录还不存在"而静默回退 data/**（旧行为会让用户配置失效、
   把几百 MB 下载与缓存悄悄塞回项目目录）。
2. **缓存**（缩略图 / 画廊图片 / 预览图 / 阅读器 / easycopy）一律在
   ``{下载根}/.cache/`` 下 —— 大体积、可再生，不占程序目录。
3. **索引 JSON**（缩略图索引 / 目录索引 / 离线索引）一律在 ``data/`` 下 ——
   小体积、不可再生，换下载盘也不能丢。
4. 缓存目录不得出现在文件库的平台列表 / 目录列表里。
5. ``core.storage_migration`` 能把旧布局搬成新布局，且**幂等**。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_storage_layout.py

退出码 0 表示全部通过。
"""
import json
import os
import shutil
import sys
import tempfile
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

FAILURES = []


def step(name, fn):
    try:
        fn()
        print(f'[OK] {name}')
    except Exception:
        FAILURES.append(name)
        print(f'[FAIL] {name}')
        traceback.print_exc()


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def _under(child, parent):
    return _norm(child).startswith(_norm(parent) + os.sep)


# ═══════════════ 1~3. 实际路径归属 ═══════════════

def test_download_root_is_configured_and_exists():
    from core.config import config as CFG
    root = CFG.download_root
    assert os.path.isabs(root), f'下载根目录应为绝对路径: {root}'
    assert os.path.isdir(root), f'下载根目录应被创建: {root}'
    configured = str(CFG.get('video_download_root', '') or '').strip()
    if configured:
        # 配置了就必须以实现为准（这正是旧实现静默回退 data/ 的 bug）
        assert _norm(root) == _norm(configured), \
            f'配置了 {configured} 但解析成了 {root}（不应回退 data/）'


def _download_root_differs_from_data():
    """下载根目录是否真的独立于 data/。

    生产环境（配置了 video_download_root）为 True。
    以脚本方式运行时 root 取自 sys.argv[0] 所在目录，可能落到 scripts/data，
    此时 download_root 与 data 恰好重合 —— "缓存不能在 data 里"这条前提不成立，
    相关断言应跳过，而不是误报失败。
    """
    from core.config import config as CFG
    return _norm(CFG.download_root) != _norm(str(CFG.data))


def test_caches_live_in_download_root():
    from core.config import config as CFG, CACHE_DIR_NAME
    from services import file_library as FL

    cache_root = CFG.cache_dir
    assert _under(cache_root, CFG.download_root), '缓存根目录应在下载根目录下'
    assert os.path.basename(_norm(cache_root)) == CACHE_DIR_NAME

    from ehviewer.image_cache import CACHE_DIR as eh_cache
    from ehviewer.ui.reader_window import READER_CACHE_DIR
    from pages.album.eh_preview import PREVIEW_DIR
    from pages.album.eh_cover import COVER_DIR
    from services.easycopy.app import default_cache_dir

    pairs = [
        ('file_library 缩略图缓存', FL.get_thumb_cache_dir()),
        ('ehviewer 图片缓存', eh_cache),
        ('EH 预览图', PREVIEW_DIR),
        ('EH 封面', COVER_DIR),
        ('easycopy 图片缓存', default_cache_dir()),
        ('阅读临时缓存', READER_CACHE_DIR),
    ]
    for label, path in pairs:
        assert _under(path, cache_root), f'{label} 应在 {cache_root} 下，实际 {path}'
        if _download_root_differs_from_data():
            assert not _under(path, CFG.data), f'{label} 不应留在 data/ 里: {path}'


def test_indexes_live_in_data():
    from core.config import config as CFG
    from services import file_library as FL
    from services.comic_library import default_index_path

    checks = [
        ('缩略图索引', FL._thumb_index_file()),
        ('目录扫描索引', FL.get_dir_cache_dir()),
        ('离线索引(ogc)', default_index_path('/whatever/ogc-download', 'ogc')),
        ('离线索引(easycopy)', default_index_path('/whatever/easycopy-download', 'easycopy')),
    ]
    for label, path in checks:
        assert _under(path, CFG.data), f'{label} 应在 data/ 下，实际 {path}'
        # 关键分离：索引绝不能落在缓存目录里（那会随"清理缓存"一起被删掉）
        assert not _under(path, CFG.cache_dir), \
            f'{label} 不应落在缓存目录里: {path}'
        if _download_root_differs_from_data():
            assert not _under(path, CFG.download_root), \
                f'{label} 不应留在下载根目录里: {path}'


# ═══════════════ 4. 缓存不暴露给用户 ═══════════════

def test_cache_hidden_from_listing():
    from core.config import config as CFG, CACHE_DIR_NAME
    from services import file_library as FL

    # 在下载根目录里确保存在缓存目录与一个正常平台目录
    os.makedirs(os.path.join(CFG.download_root, CACHE_DIR_NAME), exist_ok=True)
    probe = os.path.join(CFG.download_root, '_layout_probe_dir')
    os.makedirs(probe, exist_ok=True)
    try:
        names = [e['name'] for e in FL.list_platforms()]
        assert CACHE_DIR_NAME not in names, f'平台列表不应出现 {CACHE_DIR_NAME}: {names}'
        assert '_layout_probe_dir' in names, '正常目录应出现在平台列表里（列表功能未失效）'

        # 目录列表同样不能暴露缓存
        entries = FL.list_directory(CFG.download_root)
        all_names = [e['name'] for e in entries['dirs']] + \
                    [e['name'] for e in entries['files']]
        assert CACHE_DIR_NAME not in all_names, '目录列表不应出现缓存目录'
    finally:
        shutil.rmtree(probe, ignore_errors=True)


# ═══════════════ 5. 迁移演练（幂等 + 真的搬对了） ═══════════════

class _StubCfg:
    """给迁移模块用的最小配置桩（避免动真实 data/）。"""

    def __init__(self, data, dl):
        self.data = data
        self.download_root = dl
        self.cache_dir = os.path.join(dl, '.cache')
        os.makedirs(self.cache_dir, exist_ok=True)


def test_migration_moves_legacy_layout():
    import core.config as config_mod
    from core import storage_migration as SM

    tmp = tempfile.mkdtemp(prefix='ogc-layout-')
    data = os.path.join(tmp, 'data')
    dl = os.path.join(tmp, 'dl')
    os.makedirs(os.path.join(data, 'ehentai', 'cache', 'ab'), exist_ok=True)
    os.makedirs(os.path.join(data, 'easycopy', 'images'), exist_ok=True)
    os.makedirs(os.path.join(data, 'thumb_cache'), exist_ok=True)
    os.makedirs(dl, exist_ok=True)

    # 旧位置的缓存文件
    old_img = os.path.join(data, 'ehentai', 'cache', 'ab', 'x.img')
    with open(old_img, 'wb') as f:
        f.write(b'IMG')
    old_thumb = os.path.join(data, 'thumb_cache', 'deadbeef_320x180.jpg')
    with open(old_thumb, 'wb') as f:
        f.write(b'THUMB')
    old_easy = os.path.join(data, 'easycopy', 'images', 'pic.bin')
    with open(old_easy, 'wb') as f:
        f.write(b'PIC')

    # 旧缩略图索引（值指向旧缓存目录）
    with open(os.path.join(data, 'thumb_index.json'), 'w', encoding='utf-8') as f:
        json.dump({'/src/a.jpg': old_thumb}, f)
    # 下载根目录里的索引
    with open(os.path.join(dl, '.easycopy_offline_index.json'), 'w', encoding='utf-8') as f:
        json.dump({'root': 'x', 'comics': []}, f)
    os.makedirs(os.path.join(dl, '.dir_cache'), exist_ok=True)
    with open(os.path.join(dl, '.dir_cache', 'abc.json'), 'w', encoding='utf-8') as f:
        json.dump({'mtime': 1}, f)

    original = config_mod.config
    config_mod.config = _StubCfg(data, dl)
    try:
        SM.migrate(force=True)
        cache = os.path.join(dl, '.cache')

        # 缓存搬走了
        assert os.path.isfile(os.path.join(cache, 'ehentai', 'cache', 'ab', 'x.img')), \
            'ehentai 缓存未搬到 .cache'
        assert os.path.isfile(os.path.join(cache, 'easycopy', 'images', 'pic.bin')), \
            'easycopy 缓存未搬到 .cache'
        assert os.path.isfile(os.path.join(cache, 'thumbs', 'deadbeef_320x180.jpg')), \
            '旧 thumb_cache 未搬到 .cache/thumbs'
        assert not os.path.isdir(os.path.join(data, 'ehentai', 'cache')), \
            '旧缓存目录应已被搬空回收'

        # 索引回到 data/
        new_idx = os.path.join(data, 'thumb_index.json')
        assert os.path.isfile(new_idx), '缩略图索引应留在 data/'
        with open(new_idx, 'r', encoding='utf-8') as f:
            idx = json.load(f)
        value = idx.get('/src/a.jpg', '')
        assert _under(value, os.path.join(cache, 'thumbs')), \
            f'索引值应被重写到新缓存目录，实际 {value}'
        assert os.path.isfile(value), f'重写后的缩略图路径应真实存在: {value}'

        assert os.path.isfile(os.path.join(data, 'offline_index',
                                           'easycopy_offline_index.json')), \
            '下载根目录里的离线索引应收进 data/offline_index'
        assert not os.path.exists(os.path.join(dl, '.easycopy_offline_index.json')), \
            '旧离线索引应已移走'
        assert os.path.isfile(os.path.join(data, 'dir_cache', 'abc.json')), \
            '下载根目录里的目录索引应收进 data/dir_cache'

        # 幂等：再跑一次不应报错、也不应产生副作用
        SM.migrate(force=True)
        assert os.path.isfile(os.path.join(cache, 'thumbs', 'deadbeef_320x180.jpg')), \
            '第二次迁移不应破坏已归位的文件'
    finally:
        config_mod.config = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_migration_dedupe_and_conflict_rules():
    """合并同名文件的规则：

    * 同名 + 同大小 → 认定为同一份缓存副本：**保留目标、删除源**（否则旧目录清不干净）
    * 同名 + 不同大小 → 不是同一份东西：**保留目标，且源文件原地不动**（宁可留垃圾也不误删）
    """
    import core.config as config_mod
    from core import storage_migration as SM

    tmp = tempfile.mkdtemp(prefix='ogc-layout-keep-')
    data = os.path.join(tmp, 'data')
    dl = os.path.join(tmp, 'dl')
    os.makedirs(os.path.join(data, 'thumb_cache'), exist_ok=True)
    os.makedirs(dl, exist_ok=True)

    # 同名同大小 → 去重
    with open(os.path.join(data, 'thumb_cache', 'dup.jpg'), 'wb') as f:
        f.write(b'SAME')
    os.makedirs(os.path.join(dl, '.cache', 'thumbs'), exist_ok=True)
    with open(os.path.join(dl, '.cache', 'thumbs', 'dup.jpg'), 'wb') as f:
        f.write(b'NEW!')

    # 同名不同大小 → 冲突，源保留
    with open(os.path.join(data, 'thumb_cache', 'conflict.jpg'), 'wb') as f:
        f.write(b'OLD-CONTENT')
    with open(os.path.join(dl, '.cache', 'thumbs', 'conflict.jpg'), 'wb') as f:
        f.write(b'X')

    original = config_mod.config
    config_mod.config = _StubCfg(data, dl)
    try:
        SM.migrate(force=True)
        with open(os.path.join(dl, '.cache', 'thumbs', 'dup.jpg'), 'rb') as f:
            assert f.read() == b'NEW!', '目标已有文件被旧文件覆盖了'
        assert not os.path.exists(os.path.join(data, 'thumb_cache', 'dup.jpg')), \
            '同名同大小的重复副本应从源位置删除（否则残留清不掉）'
        with open(os.path.join(dl, '.cache', 'thumbs', 'conflict.jpg'), 'rb') as f:
            assert f.read() == b'X', '冲突文件不应覆盖目标'
        assert os.path.exists(os.path.join(data, 'thumb_cache', 'conflict.jpg')), \
            '同名但大小不同的文件必须保留在源位置（不能误删）'
    finally:
        config_mod.config = original
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    print('=== 存储布局回归测试 ===')
    step('下载根目录按配置解析且已创建', test_download_root_is_configured_and_exists)
    step('缓存都在 下载根/.cache 下', test_caches_live_in_download_root)
    step('索引 JSON 都在 data/ 下', test_indexes_live_in_data)
    step('缓存不出现在文件库列表里', test_cache_hidden_from_listing)
    step('迁移演练：旧布局 → 新布局（幂等）', test_migration_moves_legacy_layout)
    step('迁移去重/冲突规则', test_migration_dedupe_and_conflict_rules)
    if FAILURES:
        print('STORAGE LAYOUT RESULT: FAILED ->', FAILURES)
        sys.exit(1)
    print('STORAGE LAYOUT RESULT: ALL PASSED')
