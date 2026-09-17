# -*- coding: utf-8 -*-
"""设置模块 & 资源引用回归测试

两件事合在一个脚本里，因为它们都是"改了路径/资源之后最容易悄悄坏掉"的地方。

## 1. 设置里只留**一个**目录需要用户选

用户明确要求：取消「本地音乐库」与「视频下载根目录」，把「音乐缓存目录」「音乐
下载目录」合并进下载目录 —— 只选一个下载目录就够了。这条链路一旦回退，用户就又
得同时维护好几个路径。所以这里直接断言：

* 设置页**不存在**那 5 张旧卡片（`musicFolderCard` / `downloadFolderCard` /
  `musicCacheFolderCard` / `musicDownloadFolderCard` / `videoDownloadRootCard`）
  与旧的「文件目录」分组；
* 存在**唯一**的下载目录卡片 `downloadRootCard`，且它显示的就是 `CFG.download_root`；
* qfluentwidgets 的 `Config` 里不再有 `musicFolders` / `downloadFolder`
  （路径类配置只留 `core.config` 一个真源）；
* 音乐缓存/下载目录都从下载根派生，`music_cache_path` / `music_download_path`
  不再是配置项。

## 2. 资源常量指向的文件必须真的存在

`core/resource_paths.py` 里每个 `_img()` / `_res()` 常量都必须命中文件。
这条测试是**补写的**：曾经 `NAV_PEOPLE_LEVEL`（人物导航图标）指向
`logo/zs_common_level.png`、`MUSIC_PLAYER_BG` 指向 `background/music_list1.png`，
两个文件早就不在了，而没有任何测试发现 —— 表现是导航图标空白、音乐播放器没背景。
纯靠人眼看界面很难发现，所以交给测试。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_settings_paths.py

退出码 0 表示全部通过。
"""
import os
import sys
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# ⚠️ 必须在导入 Qt 之前注入插件路径（AGENTS.md §7 第 8 条）：项目路径含中文时
# PyQt5 5.15 会把插件目录损坏成 '?'，不注入就直接 abort。
_PLUGIN_DIR = os.path.join(BASE, '.venv', 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(_PLUGIN_DIR, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', _PLUGIN_DIR)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

FAILURES = []
#: 构建出来的页面必须留强引用，否则函数返回时被 GC，连带销毁仍在跑的 QThread
#: → 进程级 abort（详见 AGENTS.md §7 第 25、26 条）。
_ALIVE = []
_APP = None


def step(name, fn):
    try:
        fn()
        print(f'[OK] {name}')
    except Exception:
        FAILURES.append(name)
        print(f'[FAIL] {name}')
        traceback.print_exc()


def _qapp():
    """建 QApplication 并**持有引用**（裸调用会让它被 GC，随后建控件直接 abort）。"""
    global _APP
    from PyQt5.QtWidgets import QApplication
    if _APP is None:
        _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def _under(child, parent):
    c = os.path.normcase(os.path.abspath(child))
    p = os.path.normcase(os.path.abspath(parent))
    return c.startswith(p + os.sep)


# ═══════════════ 1. 设置页只有一张目录卡片 ═══════════════

def test_no_legacy_directory_cards():
    _qapp()
    from PyQt5.QtWidgets import QWidget
    from pages.settings_page import SettingInterface

    host = QWidget()
    host.resize(1200, 800)
    page = SettingInterface(host)
    _ALIVE.append(page)

    removed = ('musicInThisPCGroup', 'musicFolderCard', 'downloadFolderCard',
               'musicCacheFolderCard', 'musicDownloadFolderCard',
               'videoDownloadRootCard')
    present = [n for n in removed if hasattr(page, n)]
    assert not present, f'这些旧的目录设置项应当已被删除，但仍存在：{present}'

    assert hasattr(page, 'downloadRootCard'), '缺少唯一的「下载目录」卡片'
    assert hasattr(page, 'refresh_download_root'), '缺少 refresh_download_root()'

    # 卡片上显示的就是解析后的下载根目录
    from core.config import config as CFG
    text = page.downloadRootCard.contentLabel.text()
    assert CFG.download_root in text, \
        f'「下载目录」卡片应显示 {CFG.download_root}，实际显示 {text!r}'
    # 顺带确认它确实在「下载」组里（而不是被漏加到布局外的孤儿控件）
    titles = [g.titleLabel.text() for g in (page.downloadGroup,)]
    assert '下载' in titles, f'下载组标题应被简化成「下载」，实际 {titles}'


def test_legacy_directory_handlers_removed():
    """旧的处理函数也要一起删掉 —— 留着就是死代码，还会误导后来的人。"""
    _qapp()
    from pages.settings_page import SettingInterface
    for name in ('_SettingInterface__onDownloadFolderCardClicked',
                 '_SettingInterface__onMusicCacheFolderCardClicked',
                 '_SettingInterface__onMusicDownloadFolderCardClicked',
                 '_SettingInterface__onVideoDownloadRootCardClicked'):
        assert not hasattr(SettingInterface, name), f'旧的槽函数仍在：{name}'
    assert hasattr(SettingInterface, '_SettingInterface__onDownloadRootCardClicked'), \
        '缺少新的下载目录选择槽函数'


def test_gui_config_has_no_path_items():
    """qfluentwidgets 的 Config 里不该再有路径类配置项（真源只有 core.config）。"""
    from ui.widgets import common
    for name in ('musicFolders', 'downloadFolder'):
        assert not hasattr(common.Config, name), \
            f'ui.widgets.common.Config.{name} 应已删除（路径配置只保留 core.config）'
    # core.config 也不再有音乐目录配置键
    from core.config import config as CFG
    for key in ('music_cache_path', 'music_download_path'):
        assert key not in CFG.default, f'{key} 不该再是配置项'


# ═══════════════ 2. 音乐目录全部派生自下载根 ═══════════════

def test_music_dirs_follow_download_root():
    from core.config import config as CFG
    from core import paths as _paths
    from pages.music.music_player_engine import playlist_path

    assert _under(CFG.music_cache_dir, CFG.cache_dir), \
        f'音乐缓存应在 {CFG.cache_dir} 下，实际 {CFG.music_cache_dir}'
    assert _under(CFG.music_download_dir, CFG.download_root), \
        f'音乐下载应在 {CFG.download_root} 下，实际 {CFG.music_download_dir}'
    assert os.path.isdir(CFG.music_cache_dir) and os.path.isdir(CFG.music_download_dir)

    # 播放列表属于"不可再生的用户数据"，必须落在可写用户目录。
    # ⚠️ 这里只断言"落在 CFG.data 下"：脚本模式下 CFG.data 本身就是
    # ``<项目根>/scripts/data``，它**按设计**位于 program_dir()（= scripts/）之内
    # （见 AGENTS.md §4.9 的测试隔离约定），所以在此断言"不在 program_dir 下"
    # 会假失败。冻结模式下的真实保证由 smoke_storage_layout.py 的**子进程探针**
    # 覆盖（探针里会打印 music.playlist_path 并断言它落在 user_dir() 下）。
    p = playlist_path()
    assert _under(p, str(CFG.data)), f'播放列表应落在 CFG.data 下，实际 {p}'
    assert os.path.basename(p) == 'playlist.json'
    # 源码模式的真实期望：恰好等于 <项目根>/data/playlist.json（与历史行为一致，
    # 老用户已经存在的播放列表能继续被读到）
    assert _under(p, _paths.resource_root()), \
        f'源码模式下播放列表应在项目根内，实际 {p}'


def test_engine_helpers_use_derived_dirs():
    """播放引擎对外暴露的两个目录函数必须返回派生结果。"""
    from core.config import config as CFG
    from pages.music.music_player_engine import MusicPlayerEngine

    # 这两个方法不依赖实例状态，直接取未绑定函数调用，省掉 QMediaPlayer 的构造
    cache = MusicPlayerEngine.get_music_cache_dir.__wrapped__ if hasattr(
        MusicPlayerEngine.get_music_cache_dir, '__wrapped__') else None
    if cache is None:
        # 普通方法：用一个只带方法的轻量替身来调用
        class _P:
            get_music_cache_dir = MusicPlayerEngine.get_music_cache_dir
            get_music_download_dir = MusicPlayerEngine.get_music_download_dir
        p = _P()
        assert os.path.normcase(p.get_music_cache_dir()) == \
            os.path.normcase(CFG.music_cache_dir), 'get_music_cache_dir 没走派生路径'
        assert os.path.normcase(p.get_music_download_dir()) == \
            os.path.normcase(CFG.music_download_dir), 'get_music_download_dir 没走派生路径'


# ═══════════════ 3. 资源常量必须指向真实文件 ═══════════════

def test_resource_paths_exist():
    from core import resource_paths as RP

    missing = []
    checked = 0
    for name in dir(RP):
        if name.startswith('_'):
            continue
        value = getattr(RP, name)
        if not isinstance(value, str):
            continue        # PROJECT_ROOT 之类的非路径常量由下面单独校验
        if not os.path.isabs(value):
            continue
        checked += 1
        if not os.path.exists(value):
            missing.append(f'{name} -> {value}')
    assert checked > 20, f'资源常量太少（{checked} 个），解析逻辑可能坏了'
    assert not missing, (
        'resource_paths 引用了不存在的文件（界面会缺图/空白），请修正常量或补回文件：\n  '
        + '\n  '.join(missing))


def test_resource_root_points_at_project():
    from core import resource_paths as RP
    from core import paths as _paths
    assert os.path.normcase(RP.PROJECT_ROOT) == \
        os.path.normcase(str(_paths.resource_root())), \
        'resource_paths.PROJECT_ROOT 必须来自 core.paths.resource_root()'


# ═══════════════ 4. 打包进来的图片必须真的被用到 ═══════════════

_IMG_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.svg')
_TEXT_EXTS = ('.py', '.qss', '.ui', '.json', '.qrc')
#: 允许"引用了但仓库里没有"的例外（一般不该有；留个出口便于将来加动态素材）
_KEEP_FILE = '.keep_unreferenced'


def _strip_python_comments(src: str) -> str:
    """去掉 Python 注释，避免"只在注释里被提到"被误判成有用到的素材。

    这正是 resources/images/photos/header1.png 的情况：``HOME_BANNER`` 那行被
    注释掉了，但文件名还留在注释里 —— 按整段文本搜索会误以为它在被使用。
    """
    out = []
    for line in src.splitlines():
        if line.lstrip().startswith('#'):
            continue
        idx = line.find('#')
        out.append(line[:idx] if idx >= 0 else line)
    return '\n'.join(out)


def _referenced_text() -> str:
    """把全仓库（排除 .venv/build/dist/运行时数据）的文本拼起来，供关键词搜索。"""
    chunks = []
    for dirpath, dirnames, filenames in os.walk(BASE):
        dirnames[:] = [d for d in dirnames
                       if d not in ('.venv', 'build', 'dist', '__pycache__',
                                    '.git', 'data', 'logs')]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _TEXT_EXTS:
                continue
            try:
                with open(os.path.join(dirpath, fn), encoding='utf-8',
                          errors='ignore') as f:
                    src = f.read()
            except OSError:
                continue
            chunks.append(_strip_python_comments(src) if ext == '.py' else src)
    return '\n'.join(chunks)


def test_no_unreferenced_bundled_images():
    """打包进去的图片都必须被代码/样式引用，否则就是白占安装体积。

    2026-09 用这条检查清掉了 resources/images/photos/（首页轮播素材，
    常量早已注释掉）、background/bg_yangcheng.jpg、logo/user_icon1.png，
    合计约 1.9 MB。散落的"没用的图"很难靠人眼发现。
    """
    img_root = os.path.join(BASE, 'resources', 'images')
    keep = set()
    keep_path = os.path.join(img_root, _KEEP_FILE)
    if os.path.isfile(keep_path):
        with open(keep_path, encoding='utf-8') as f:
            keep = {ln.strip() for ln in f
                    if ln.strip() and not ln.startswith('#')}

    text = _referenced_text()
    unref = []
    total = 0
    for dirpath, _dirnames, filenames in os.walk(img_root):
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in _IMG_EXTS:
                continue
            total += 1
            if fn in keep:
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), BASE).replace('\\', '/')
            if fn in text or rel in text:
                continue
            unref.append(rel)

    assert total > 10, f'只扫到 {total} 张图片，资源目录结构可能变了'
    assert not unref, (
        '这些图片没有被任何代码/样式引用，属于白占安装体积；'
        '确认无用就删掉，确实需要动态加载就写进 '
        f'resources/images/{_KEEP_FILE}：\n  ' + '\n  '.join(sorted(unref)))


def test_app_icon_is_single_source():
    """应用图标必须只有一份：`logo/icon.png`。

    三个地方的图标都源自它，任何一处指到别的文件都会导致
    "资源管理器里是 A、任务栏里是 B"：
      ① exe 文件图标/快捷方式/安装器 —— 构建期 build_exe.make_icon() 由它生成 icon.ico
      ② 任务栏 / Alt+Tab / 所有窗口默认图标 —— main.py 里 app.setWindowIcon(APP_ICON)
      ③ 登录/主窗口标题栏 —— LOGIN_LOGO / MAIN_LOGO

    （logo/logo.png 与它是同一张图，被登录界面的 Qt 资源 :/images/logo.png 用着，
      因此文件保留，但应用图标常量一律指向 icon.png。）
    """
    from core import resource_paths as RP

    assert os.path.normcase(os.path.basename(RP.APP_ICON)) == 'icon.png', \
        f'APP_ICON 必须是 logo/icon.png，实际 {RP.APP_ICON}'
    assert os.path.normcase(os.path.dirname(RP.APP_ICON)) == \
        os.path.normcase(os.path.join(RP.PROJECT_ROOT, 'resources', 'images', 'logo')), \
        f'APP_ICON 必须在 resources/images/logo 下，实际 {RP.APP_ICON}'
    assert os.path.isfile(RP.APP_ICON), f'应用图标文件不存在: {RP.APP_ICON}'

    for name in ('LOGIN_LOGO', 'MAIN_LOGO', 'VIDEO_LOGO', 'VIDEO_PAGE_APP_ICON'):
        value = getattr(RP, name)
        assert os.path.normcase(value) == os.path.normcase(RP.APP_ICON), \
            f'{name} 应等于 APP_ICON（应用图标只有一份），实际 {value}'

    # exe 里也必须真的有图标 —— 构建期生成，检查产物存在即可（构建脚本自己会核验嵌入）
    from PIL import Image
    with Image.open(RP.APP_ICON) as im:
        assert im.width >= 16 and im.height >= 16, f'图标太小: {im.size}'
        if im.width < 256:
            print(f'     (提示) 图标源 {im.width}×{im.height} < 256×256，'
                  f'构建时会 LANCZOS 放大到 256，想更锐利请换更大的图')


if __name__ == '__main__':
    print('=== 设置模块 / 资源引用回归测试 ===')
    step('设置页不再有旧的目录卡片', test_no_legacy_directory_cards)
    step('旧的目录槽函数已删除', test_legacy_directory_handlers_removed)
    step('GUI 配置里没有路径项', test_gui_config_has_no_path_items)
    step('音乐目录跟随下载根目录', test_music_dirs_follow_download_root)
    step('播放引擎用派生目录', test_engine_helpers_use_derived_dirs)
    step('资源常量指向真实文件', test_resource_paths_exist)
    step('资源根取自 core.paths', test_resource_root_points_at_project)
    step('打包的图片都被引用（无死素材）', test_no_unreferenced_bundled_images)
    step('应用图标只有一份（logo/icon.png）', test_app_icon_is_single_source)

    if FAILURES:
        print('SETTINGS PATHS RESULT: FAILED ->', FAILURES)
        sys.exit(1)
    print('SETTINGS PATHS RESULT: ALL PASSED')
