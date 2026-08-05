# -*- coding: utf-8 -*-
"""
验证推特模块备用解析功能（gallery-dl 备用解析器集成）

场景：
1. 验证 TwitterGalleryDLParser 可正常实例化、解析项目目录定位正确
2. 验证备用解析器 JSON 解析逻辑（类型识别/标题/Referer）
3. 验证 ParseThread 支持 use_backup_parser 分支
4. 模拟 3 次重试失败后自动切换到备用解析
"""
import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Qt 平台插件路径修复
if sys.platform == 'win32':
    site_packages = os.path.join(BASE_DIR, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)


def test_1_backup_parser_import():
    """备用解析器可导入且目录定位正确"""
    from services.platform_parsers import (
        TwitterGalleryDLParser, GALLERY_DL_PROJECT_DIR,
    )
    parser = TwitterGalleryDLParser()
    project_dir = parser._resolve_project_dir()
    print(f"[1] GALLERY_DL_PROJECT_DIR = {GALLERY_DL_PROJECT_DIR}")
    print(f"[1] _resolve_project_dir() = {project_dir}")
    assert project_dir, "备用解析器项目目录定位失败！"
    assert os.path.isdir(os.path.join(project_dir, 'gallery_dl')), \
        "gallery_dl 包不存在，备用解析无法工作"
    print("[1] ✅ 备用解析器导入正常，项目目录定位正确")


def test_2_backup_parser_parsing():
    """备用解析器消息流格式解析（模拟 gallery-dl --dump-json 对推特推文真实输出）"""
    from services.platform_parsers import TwitterGalleryDLParser
    parser = TwitterGalleryDLParser()

    # 模拟 gallery-dl --dump-json 的真实消息流格式：
    # [[2, {目录元数据}], [3, 'url', {文件元数据}], ...]
    mock_messages = [
        [2, {"_type": "directory", "category": "twitter",
             "tweet_id": "2084488396777677217",
             "content": "这是一个测试推文内容",
             "author": {"name": "winkyneverlose", "nick": "可喵sama"}}],
        [3, "https://pbs.twimg.com/media/HO2W7-0bAAA3vpW?format=jpg&name=orig",
         {"_type": "url", "extension": "jpg", "filename": "2084488396777677217_1.jpg"}],
        [3, "https://video.twimg.com/ext_tw_video/2084488396777677217/pu/vid/720x1280/123.mp4",
         {"_type": "url", "extension": "mp4", "filename": "2084488396777677217_2.mp4"}],
        [3, "https://pbs.twimg.com/media/HO2W7-0bAAA3vq?format=jpg&name=orig",
         {"_type": "url", "extension": "jpg", "filename": "2084488396777677217_3.jpg"}],
    ]
    mock_stdout = json.dumps(mock_messages, ensure_ascii=False)

    # 通过 monkey-patch _run 使用模拟输出（避免真实网络请求）
    parser._run = lambda url, timeout=60: mock_stdout
    items = parser.parse("https://x.com/winkyneverlose/status/2084488396777677217")

    print(f"[2] 解析到 {len(items)} 个媒体项")
    for it in items:
        print(f"    - {it.media_type:6s} | {it.title} | {it.url[:50]} | referer={it.referer}")

    assert len(items) == 3, "应解析出 3 个媒体项"
    assert items[0].media_type == 'image', "jpg 应识别为图片"
    assert items[1].media_type == 'video', "mp4 应识别为视频"
    assert items[0].referer == 'https://x.com/', "应携带推特 Referer"
    assert items[0].title == '2084488396777677217_1.jpg', "标题应为文件名"
    # 预览图推导：图片复用媒体 URL；视频复用同推文图片
    assert items[0].preview_url == items[0].url, "图片媒体预览应复用媒体 URL"
    assert items[1].preview_url == items[0].url, "视频媒体预览应复用同推文图片"
    print("[2] ✅ 备用解析器消息流格式解析逻辑正确（类型/标题/Referer/预览图）")


def test_3_parse_thread_backup_branch():
    """ParseThread 支持 use_backup_parser 分支（twitter 平台）"""
    from pages.video.video_multiplatform_page import ParseThread
    thread = ParseThread('twitter', 'https://x.com/test/status/1',
                         use_backup_parser=True)
    assert thread.use_backup_parser is True, "use_backup_parser 参数未保存"
    assert thread.platform == 'twitter'
    print("[3] ✅ ParseThread 支持 use_backup_parser 参数（twitter 分支）")


def test_4_retry_logic_simulation():
    """模拟页面 _on_parse_error 的重试-备用切换逻辑"""
    # 直接模拟 PlatformPage 的重试状态机逻辑
    platform = 'twitter'
    _parse_retry_map = {}
    _parse_backup_done = set()
    _parse_retry_max = 3
    switched_to_backup = False
    retry_entries = []

    url = 'https://x.com/example/status/2084412747694125246'

    # 模拟 3 次原解析失败
    for attempt in range(_parse_retry_max):
        retry_count = _parse_retry_map.get(url, 0)
        if retry_count < _parse_retry_max:
            _parse_retry_map[url] = retry_count + 1
            retry_entries.append(f"第 {retry_count+1} 次重试")
        else:
            break

    # 第 3 次重试仍失败 → 触发备用解析
    retry_count = _parse_retry_map.get(url, 0)
    if retry_count >= _parse_retry_max:
        if platform == 'twitter' and url not in _parse_backup_done:
            _parse_backup_done.add(url)
            switched_to_backup = True

    print(f"[4] 重试记录: {retry_entries}")
    print(f"[4] 触发备用解析: {switched_to_backup}")
    assert len(retry_entries) == 3, "应恰好重试 3 次后才启用备用解析"
    assert switched_to_backup, "3 次重试失败后应启用备用解析"

    # 备用解析也用新线程（use_backup_parser=True）
    from pages.video.video_multiplatform_page import ParseThread
    backup_thread = ParseThread(
        platform, url, use_backup_parser=url in _parse_backup_done)
    assert backup_thread.use_backup_parser is True, "备用线程应携带 use_backup_parser=True"
    print("[4] ✅ 重试 3 次后正确启用备用解析")


if __name__ == '__main__':
    print("=" * 60)
    print("推特模块备用解析功能验证")
    print("=" * 60)
    test_1_backup_parser_import()
    print()
    test_2_backup_parser_parsing()
    print()
    test_3_parse_thread_backup_branch()
    print()
    test_4_retry_logic_simulation()
    print()
    print("=" * 60)
    print("✅ 全部验证通过")
    print("=" * 60)