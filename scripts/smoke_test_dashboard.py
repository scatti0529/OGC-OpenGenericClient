# -*- coding: utf-8 -*-
"""仪表盘优化冒烟测试：
1. 改动文件编译
2. get_system_stats / get_module_file_counts / get_usage_stats 正确性
3. record_usage 写入并统计（含日期筛选的总下载量）
4. DashboardInterface 无头构建（含模块文件卡片区）
"""
import os
import sys
import traceback

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


def test_compile():
    import py_compile
    files = [
        'core/database.py',
        'services/download_manager.py',
        'services/ehentai_downloader.py',
        'services/easycopy/downloader.py',
        'pages/video/video_multiplatform_page.py',
        'pages/video/video_mini_window.py',
        'pages/video/douyin_page.py',
        'pages/video/pixiv_page.py',
        'pages/dashboard_page.py',
    ]
    for f in files:
        py_compile.compile(os.path.join(BASE, f), doraise=True)
    print('  compiled:', len(files), 'files')


def test_stats():
    from core.database import get_system_stats, get_module_file_counts, get_usage_stats
    mf = get_module_file_counts()
    assert 'total' in mf, 'module_files 缺少 total'
    for k in ('douyin', 'bilibili', 'twitter', 'pixiv', 'xvideo', 'youtube',
              'jmcomic', 'easycopy', 'ehentai', 'music'):
        assert k in mf, f'module_files 缺少 {k}'
    assert mf['total'] == sum(v for k, v in mf.items() if k != 'total'), 'total 不一致'
    print('  module file counts:', mf)

    stats = get_system_stats()
    assert 'module_files' in stats and 'total_download_files' in stats
    assert stats['video_file_count'] == sum(
        stats['module_files'].get(k, 0)
        for k in ('douyin', 'bilibili', 'twitter', 'pixiv', 'xvideo', 'youtube')
    ), 'video_file_count 与 module_files 不一致'
    assert 'user_count' in stats and 'banned_count' in stats
    print('  stats keys:', sorted(k for k in stats.keys() if k != 'usage'))

    usage = get_usage_stats()
    assert 'downloads' in usage and 'total' in usage['downloads']
    assert 'ehentai' in usage and 'easycopy' in usage
    # 带日期筛选不报错（修复 AND WHERE 拼接 bug）
    usage2 = get_usage_stats('2000-01-01', '2999-12-31')
    assert 'downloads' in usage2 and 'total' in usage2['downloads']
    print('  usage stats ok; downloads total =', usage['downloads']['total'])


def test_record_usage():
    from core.database import record_usage, get_usage_stats, get_db_connection
    import uuid
    tag = 'dash_test_' + uuid.uuid4().hex[:8]
    record_usage('ehentai', 'download', tag)
    record_usage('easycopy', 'download', tag)
    record_usage('video', 'parse', tag)
    usage = get_usage_stats()
    assert usage.get('ehentai', {}).get('download', 0) >= 1, 'ehentai 下载未记录'
    assert usage.get('easycopy', {}).get('download', 0) >= 1, 'easycopy 下载未记录'
    assert usage.get('video', {}).get('parse', 0) >= 1, 'video parse 未记录'
    assert usage['downloads']['total'] >= 2, '总下载量统计错误'
    # 仅清理本次测试写入的行（按唯一 detail 删除，不影响真实数据）
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM usage_stats WHERE detail=?", (tag,))
    conn.commit()
    conn.close()
    print('  record_usage + 统计 OK')


def test_dashboard_gui():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    site_packages = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from pages.dashboard_page import DashboardInterface
    d = DashboardInterface()
    d.resize(1080, 780)
    d.show()
    app.processEvents()
    assert len(d._module_file_cards) == 10, '模块文件卡片数量应为 10'
    assert d.moduleTotalLabel is not None
    print('  dashboard built; module cards =', len(d._module_file_cards),
          '; total label =', d.moduleTotalLabel.text())
    # 手动刷新（触发 stats + 图表 + 用户列表）
    d.refresh()
    app.processEvents()
    print('  dashboard refresh OK')


if __name__ == '__main__':
    step('compile', test_compile)
    step('stats', test_stats)
    step('record_usage', test_record_usage)
    step('dashboard_gui', test_dashboard_gui)

    if FAILURES:
        print('RESULT: FAILED ->', FAILURES)
        sys.exit(1)
    print('RESULT: ALL PASSED')
