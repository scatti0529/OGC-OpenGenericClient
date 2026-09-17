# -*- coding: utf-8 -*-
"""ffmpeg「按需获取」回归测试

背景（决定了这些断言为什么存在）：ffmpeg **不随包内置** —— 全项目只有一处用它
（给本地视频抽首帧当封面），而完整构建 150~170 MB 会把安装包从 87 MB 抬到 140 MB+
（见 AGENTS.md §10）。改成"第一次真的需要时弹窗"，用户可一键下载或手动指定。

守住的东西：

1. **配置里的 ``ffmpeg_path`` 优先级最高**：用户手填/一键下载写进去的路径，
   必须盖过内置、环境变量、PATH —— 否则用户会以为"填了没用"。
2. **下载/解压/绑定链路可用**：合成一个假压缩包走一遍
   ``install_from_archive``，解压后要能从 <包>/bin/ffmpeg.exe 里认出来并绑定。
3. **找不到就优雅降级**：``find_ffmpeg()`` 返回空串，``probe_version`` 返回空串，
   **绝不抛异常**（文件库不能因为缺 ffmpeg 打不开）。
4. **弹窗语义**：默认动作是「立即下载」，点「稍后」/Esc 变成 later；
   勾了「下次不再显示」并确认后写进 ``ffmpeg_prompt_dismissed``。
5. **不再打扰**：已可用、或用户说过不再提示时，``maybe_prompt_ffmpeg`` 
   **直接返回、不弹窗**（弹了就说明这条坏了）。
6. **文件库统计**：缺 ffmpeg 时 ``BatchThumbnailWorker.videos_skipped`` 要如实计数，
   这是"要不要提示用户"的唯一依据。

全程只在临时目录里跑，并且**把下载根目录也换成临时目录** ——
否则 download_dir() 会落到真实的 ~/Downloads 里。

用法::

    .venv\\Scripts\\python.exe scripts\\smoke_ffmpeg_setup.py

退出码 0 表示全部通过。
"""
import os
import shutil
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# ⚠️ 必须在导入 Qt 之前注入插件路径（AGENTS.md §7 第 8 条）：
# 本项目路径含中文，PyQt5 5.15 会把插件目录损坏成 '?'，不注入就直接崩。
_PLUGIN_DIR = os.path.join(BASE, '.venv', 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins')
if os.path.isdir(os.path.join(_PLUGIN_DIR, 'platforms')):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', _PLUGIN_DIR)
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


TMP = tempfile.mkdtemp(prefix='ogc-ffmpeg-')


def _fake_ffmpeg(directory, name='ffmpeg.exe', content=b'MZ-FAKE-FFMPEG'):
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(content)
    return p


# ═══════════════ 1. 优先级 ═══════════════

def test_config_path_wins():
    """配置里的路径必须最优先 —— 否则用户手填了却"没生效"。"""
    from core.config import config as CFG
    from services import file_library as FL

    exe = _fake_ffmpeg(os.path.join(TMP, 'cfg'), 'ffmpeg.exe')
    old = CFG.get('ffmpeg_path', '')
    try:
        CFG['ffmpeg_path'] = str(exe)
        FL.reset_ffmpeg_cache()
        assert FL.find_ffmpeg() == str(exe), \
            f'配置的路径没有优先命中：{FL.find_ffmpeg()}'
    finally:
        CFG['ffmpeg_path'] = old
        FL.reset_ffmpeg_cache()


def test_config_path_beats_path_env():
    """机器上装着 ffmpeg（PATH 里有）时，用户显式指定的仍然要赢。"""
    from core.config import config as CFG
    from services import file_library as FL

    exe = _fake_ffmpeg(os.path.join(TMP, 'cfg2'), 'ffmpeg.exe')
    old = CFG.get('ffmpeg_path', '')
    real_which = shutil.which
    try:
        CFG['ffmpeg_path'] = str(exe)
        FL.reset_ffmpeg_cache()
        shutil.which = lambda n, *a, **k: r'C:\somewhere\else\ffmpeg.exe'
        assert FL.find_ffmpeg() == str(exe), 'PATH 里的 ffmpeg 抢走了优先级'
    finally:
        shutil.which = real_which
        CFG['ffmpeg_path'] = old
        FL.reset_ffmpeg_cache()


def test_missing_ffmpeg_is_graceful():
    """找不到时必须返回空串，**不能抛异常**（文件库不能因此打不开）。"""
    from core.config import config as CFG
    from services import ffmpeg_installer as FI
    from services import file_library as FL

    old = CFG.get('ffmpeg_path', '')
    real_which = shutil.which
    real_env = {k: os.environ.pop(k, None) for k in ('OGC_FFMPEG', 'FFMPEG')}
    try:
        CFG['ffmpeg_path'] = ''
        FL.reset_ffmpeg_cache()
        shutil.which = lambda n, *a, **k: None
        got = FL.find_ffmpeg()
        assert got == '', f'期望找不到，实际拿到 {got}'
        assert FI.probe_version('') == ''
        assert FI.probe_version(os.path.join(TMP, 'nope', 'ffmpeg.exe')) == ''
        assert FI.is_valid_exe('') is False
        assert FI.is_valid_exe(os.path.join(TMP, 'nope.exe')) is False
        # 名字不对的（哪怕存在）也不算
        wrong = _fake_ffmpeg(os.path.join(TMP, 'wrong'), 'vlc.exe')
        assert FI.is_valid_exe(wrong) is False, '非 ffmpeg 命名的文件不该被当成 ffmpeg'
    finally:
        shutil.which = real_which
        for k, v in real_env.items():
            if v is not None:
                os.environ[k] = v
        CFG['ffmpeg_path'] = old
        FL.reset_ffmpeg_cache()


# ═══════════════ 2. 下载根目录 / 解压 / 绑定 ═══════════════

def test_download_dir_is_under_download_root():
    from core.config import config as CFG
    from services import ffmpeg_installer as FI
    d = FI.download_dir()
    assert Path(CFG.download_root) in d.parents, \
        f'下载目录必须在下载根目录下：{d} vs {CFG.download_root}'
    assert d.name == FI.DOWNLOAD_DIR_NAME


def test_extract_and_bind():
    """合成一个"ffmpeg-release-essentials.zip"，走一遍解压 → 定位 → 绑定。"""
    from core.config import config as CFG
    from services import ffmpeg_installer as FI
    from services import file_library as FL

    archive = Path(TMP) / 'fake-ffmpeg.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('ffmpeg-7.1-essentials_build/bin/ffmpeg.exe', 'MZ-REAL-FFMPEG')
        z.writestr('ffmpeg-7.1-essentials_build/README.txt', 'hello')

    old = CFG.get('ffmpeg_path', '')
    try:
        exe = FI.install_from_archive(archive)
        assert os.path.isfile(exe), f'绑定到了不存在的路径: {exe}'
        assert os.path.basename(exe).lower() == 'ffmpeg.exe'
        assert 'bin' in exe, f'应该在 <包>/bin 下找到，实际 {exe}'
        assert str(CFG.get('ffmpeg_path', '')) == exe, '绑定后配置里没写上路径'
        FL.reset_ffmpeg_cache()
        assert FL.find_ffmpeg() == exe, '绑定后 find_ffmpeg() 没认出来'
    finally:
        CFG['ffmpeg_path'] = old
        FL.reset_ffmpeg_cache()


def test_find_existing_archive():
    """用户自己丢进下载目录的压缩包要能被认出来（手动兜底路径）。"""
    from services import ffmpeg_installer as FI
    d = FI.download_dir()
    p = d / 'ffmpeg-release-essentials.zip'
    with open(p, 'wb') as f:
        f.write(b'x' * (2 * 1024 * 1024))       # 要 > 1MB 才算数
    try:
        found = FI.find_existing_archive()
        assert found and Path(found).is_file(), f'没认出下载目录里的压缩包: {found}'
    finally:
        try:
            p.unlink()
        except OSError:
            pass


def test_install_from_exe_and_dir():
    """手动指定：既可以直接给 ffmpeg.exe，也可以给"装着它的目录"。"""
    from core.config import config as CFG
    from services import ffmpeg_installer as FI
    from services import file_library as FL

    d = Path(TMP) / 'manual' / 'bin'
    exe = _fake_ffmpeg(d, 'ffmpeg.exe')
    old = CFG.get('ffmpeg_path', '')
    try:
        got = FI.install_from_exe(d)          # 传目录
        assert got == str(exe), f'传目录时应自动找到 ffmpeg.exe：{got}'
        got2 = FI.install_from_exe(exe)       # 传文件
        assert got2 == str(exe)
        FL.reset_ffmpeg_cache()
        assert FL.find_ffmpeg() == str(exe)
        # 传个不是 ffmpeg 的东西要报错，而不是默默绑定
        bad = _fake_ffmpeg(Path(TMP) / 'manual2', 'notepad.exe')
        try:
            FI.install_from_exe(bad)
            raise AssertionError('指定非 ffmpeg 文件时应当报错')
        except RuntimeError:
            pass
    finally:
        CFG['ffmpeg_path'] = old
        FL.reset_ffmpeg_cache()


def test_unbind_clears():
    from core.config import config as CFG
    from services import ffmpeg_installer as FI
    from services import file_library as FL

    exe = _fake_ffmpeg(os.path.join(TMP, 'unbind'), 'ffmpeg.exe')
    old = CFG.get('ffmpeg_path', '')
    try:
        FI.bind(exe)
        assert str(CFG.get('ffmpeg_path', '')) == str(exe)
        FI.unbind()
        assert CFG.get('ffmpeg_path', 'x') == '', '清除后配置里应为空串'
        FL.reset_ffmpeg_cache()
    finally:
        CFG['ffmpeg_path'] = old
        FL.reset_ffmpeg_cache()


# ═══════════════ 3. 弹窗语义 ═══════════════

_APP = None


def _qapp():
    """建 QApplication 并**持有引用**。

    ⚠️ 不能写成裸调用：``_qapp()`` 丢弃返回值会让 QApplication 立刻被 GC 回收，
    随后任何 QWidget 都会以 ``QWidget: Must construct a QApplication before a
    QWidget`` 直接 abort（这个坑实测踩过一次）。
    """
    global _APP
    from PyQt5.QtWidgets import QApplication
    if _APP is None:
        _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def test_dialog_actions():
    """默认（点「立即下载」）→ download；点「稍后」/Esc → later；手动按钮 → manual。"""
    _qapp()
    from PyQt5.QtWidgets import QWidget
    from ui.widgets.ffmpeg_prompt import FfmpegMissingDialog

    host = QWidget()
    host.resize(1000, 700)

    d = FfmpegMissingDialog(host)
    assert d.action == 'download', '默认动作应为「立即下载」'
    assert d.yesButton.text() == '立即下载'
    assert d.cancelButton.text() == '稍后'
    assert '手动指定' in d.manualButton.text()
    d.reject()
    assert d.action == 'later', '点稍后/关闭后动作应变成 later'
    assert d.was_dismissed() is False, '没勾复选框时不该是"不再提示"'

    d2 = FfmpegMissingDialog(host)
    d2.dismissBox.setChecked(True)
    assert d2.was_dismissed() is True
    d2.deleteLater()


def test_mark_dismissed_writes_config():
    """勾了「下次不再显示」并确认 → 落配置，之后不再打扰。"""
    _qapp()
    from PyQt5.QtWidgets import QWidget
    from core.config import config as CFG
    from ui.widgets.ffmpeg_prompt import FfmpegMissingDialog

    old = CFG.get('ffmpeg_prompt_dismissed', False)
    host = QWidget()
    host.resize(1000, 700)
    try:
        CFG['ffmpeg_prompt_dismissed'] = False
        d = FfmpegMissingDialog(host)
        d.dismissBox.setChecked(True)
        d.mark_dismissed()
        assert CFG.get('ffmpeg_prompt_dismissed') is True, '勾选后没写进配置'

        # 没勾就不该写
        CFG['ffmpeg_prompt_dismissed'] = False
        d2 = FfmpegMissingDialog(host)
        d2.mark_dismissed()
        assert CFG.get('ffmpeg_prompt_dismissed') is False, '没勾却写了配置'
        d2.deleteLater()
    finally:
        CFG['ffmpeg_prompt_dismissed'] = old


def test_maybe_prompt_is_silent_when_available():
    """"已可用 / 用户说过不再提示" 两种情况都必须**不弹窗**直接返回。

    这条用"弹窗会阻塞"来判：如果实现走错分支就会卡在这里 ——
    所以用超时保护的话反而测不出来，这里靠逻辑保证（两种情况都在建对话框之前返回）。
    """
    _qapp()
    from core.config import config as CFG
    from services import file_library as FL
    from ui.widgets.ffmpeg_prompt import maybe_prompt_ffmpeg

    old_path = CFG.get('ffmpeg_path', '')
    old_dismiss = CFG.get('ffmpeg_prompt_dismissed', False)
    exe = _fake_ffmpeg(os.path.join(TMP, 'silent'), 'ffmpeg.exe')
    try:
        # ① 已可用 → 直接返回路径，不弹窗
        CFG['ffmpeg_path'] = str(exe)
        FL.reset_ffmpeg_cache()
        assert maybe_prompt_ffmpeg(None) == str(exe)

        # ② 找不到 + 用户说过不再提示 → 返回空串，不弹窗
        CFG['ffmpeg_path'] = ''
        CFG['ffmpeg_prompt_dismissed'] = True
        FL.reset_ffmpeg_cache()
        real_which = shutil.which
        real_env = {k: os.environ.pop(k, None) for k in ('OGC_FFMPEG', 'FFMPEG')}
        try:
            shutil.which = lambda n, *a, **k: None
            assert maybe_prompt_ffmpeg(None) == '', '用户说过不再提示，不该再返回路径'
        finally:
            shutil.which = real_which
            for k, v in real_env.items():
                if v is not None:
                    os.environ[k] = v
    finally:
        CFG['ffmpeg_path'] = old_path
        CFG['ffmpeg_prompt_dismissed'] = old_dismiss
        FL.reset_ffmpeg_cache()


# ═══════════════ 4. 文件库统计（决定要不要提示） ═══════════════

def test_videos_skipped_counted_without_ffmpeg():
    """缺 ffmpeg 时，批量任务要把"跳过的视频数"数出来 —— 这是提示的唯一依据。"""
    _qapp()
    from core.config import config as CFG
    from services import file_library as FL
    from pages.folder_library_page import BatchThumbnailWorker

    work = Path(TMP) / 'media'
    work.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (work / f'v{i}.mp4').write_bytes(b'\x00' * 64)
    (work / 'pic.jpg').write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 64)

    old_path = CFG.get('ffmpeg_path', '')
    real_which = shutil.which
    real_env = {k: os.environ.pop(k, None) for k in ('OGC_FFMPEG', 'FFMPEG')}
    try:
        CFG['ffmpeg_path'] = ''
        FL.reset_ffmpeg_cache()
        shutil.which = lambda n, *a, **k: None
        w = BatchThumbnailWorker(str(work), max_files=50)
        w.run()                       # 直接在测试线程里跑，避免等线程
        assert w.videos_skipped == 3, \
            f'应数出 3 个缺封面的视频，实际 {w.videos_skipped}'
    finally:
        shutil.which = real_which
        for k, v in real_env.items():
            if v is not None:
                os.environ[k] = v
        CFG['ffmpeg_path'] = old_path
        FL.reset_ffmpeg_cache()


def test_config_defaults_exist():
    """两个新配置键必须存在（老配置靠 setdefault 补全）。"""
    from core.config import config as CFG
    d = CFG.default
    assert 'ffmpeg_path' in d, '缺少默认键 ffmpeg_path'
    assert 'ffmpeg_prompt_dismissed' in d, '缺少默认键 ffmpeg_prompt_dismissed'
    assert d['ffmpeg_path'] == ''
    assert d['ffmpeg_prompt_dismissed'] is False
    # ffmpeg **不该**被内置：内置目录存在就说明打包策略被改了
    from core import paths as _p
    assert d['ffmpeg_path'] == '', 'ffmpeg 不应内置（见 AGENTS.md §10）'
    assert not os.path.isfile(os.path.join(str(_p.resource_root()), 'ffmpeg', 'ffmpeg.exe')), \
        '资源根下出现了内置 ffmpeg.exe —— 与"按需下载"策略冲突'


if __name__ == '__main__':
    print('=== ffmpeg 按需获取回归测试 ===')
    from core.config import config as CFG

    # 关键：把下载根目录指到临时目录，否则 download_dir() 会写进用户的 ~/Downloads
    _saved_root = CFG.get('video_download_root', None)
    _saved_path = CFG.get('ffmpeg_path', '')
    _saved_dismiss = CFG.get('ffmpeg_prompt_dismissed', False)
    CFG['video_download_root'] = str(Path(TMP) / 'download-root')
    try:
        step('配置的 ffmpeg_path 优先级最高', test_config_path_wins)
        step('配置路径压过 PATH 里的 ffmpeg', test_config_path_beats_path_env)
        step('找不到时优雅降级（不抛异常）', test_missing_ffmpeg_is_graceful)
        step('下载目录位于下载根目录下', test_download_dir_is_under_download_root)
        step('解压 → 定位 → 绑定 全链路', test_extract_and_bind)
        step('认出手动放进下载目录的压缩包', test_find_existing_archive)
        step('手动指定 ffmpeg.exe / 目录', test_install_from_exe_and_dir)
        step('清除绑定', test_unbind_clears)
        step('弹窗动作语义（下载/稍后/手动）', test_dialog_actions)
        step('「下次不再显示」落配置', test_mark_dismissed_writes_config)
        step('已可用/不再提示时不弹窗', test_maybe_prompt_is_silent_when_available)
        step('缺 ffmpeg 时统计跳过的视频数', test_videos_skipped_counted_without_ffmpeg)
        step('配置默认键与"不内置"策略', test_config_defaults_exist)
    finally:
        if _saved_root is not None:
            CFG['video_download_root'] = _saved_root
        CFG['ffmpeg_path'] = _saved_path
        CFG['ffmpeg_prompt_dismissed'] = _saved_dismiss
        shutil.rmtree(TMP, ignore_errors=True)

    if FAILURES:
        print('FFMPEG SETUP RESULT: FAILED ->', FAILURES)
        sys.exit(1)
    print('FFMPEG SETUP RESULT: ALL PASSED')
