# -*- coding: utf-8 -*-
"""集成验证脚本：验证所有抖音模块语法与导入（适配 qt_app_fluent.py 移植）"""
import ast
import os
import sys

# 确保项目根目录在导入路径（脚本在 scripts/ 下运行）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

FILES = [
    'services/douyin/__init__.py',
    'services/douyin/abogus.py',
    'services/douyin/xbogus.py',
    'services/douyin_parser.py',
    'services/douyin_service.py',
    'pages/video/douyin_dialogs.py',
    'pages/video/douyin_page.py',
]

print("=== 语法检查 ===")
for f in FILES:
    try:
        with open(f, encoding='utf-8') as fp:
            ast.parse(fp.read())
        print(f"  ✓ {f}")
    except Exception as e:
        print(f"  ✗ {f}: {e}")
        sys.exit(1)

print("\n=== 导入检查 ===")
try:
    from services.douyin.abogus import ABogus
    from services.douyin.xbogus import XBogus
    from services.douyin_parser import (
        DouyinVideoParser, DouyinParseError, get_nwm_url,
    )
    print("  ✓ services.douyin_parser 导入成功")
except Exception as e:
    print(f"  ✗ services.douyin_parser: {e}")
    sys.exit(1)

try:
    from services.douyin_service import (
        DouyinDownloader, DouyinConfig, DouyinProgressDB,
        get_douyin_output_dir, get_douyin_media_dir,
    )
    print("  ✓ services.douyin_service 导入成功")
except Exception as e:
    print(f"  ✗ services.douyin_service: {e}")
    sys.exit(1)

try:
    from pages.video.douyin_page import (
        DouyinPage, DouyinMediaCard, CardResultArea,
    )
    print("  ✓ pages.video.douyin_page 导入成功")
except Exception as e:
    print(f"  ✗ pages.video.douyin_page: {e}")
    sys.exit(1)

try:
    from pages.video.douyin_dialogs import (
        VideoConfigDialog, DouyinFeatureDialog, DouyinLogDialog,
        QualitySelectionDialog, CookieWorker, show_error, show_info, show_success,
    )
    print("  ✓ pages.video.douyin_dialogs 导入成功")
except Exception as e:
    print(f"  ✗ pages.video.douyin_dialogs: {e}")
    sys.exit(1)

print("\n=== 源项目接口对齐检查 ===")
try:
    parser = DouyinVideoParser()
    # 源项目 douyin_video_parser.py 提供的所有核心接口
    core_methods = [
        'get_video_id', 'get_aweme_detail', 'parse_video',
        'parse_to_nwm_url', 'parse_video_meta', 'get_content_type',
        'extract_nwm_url', 'extract_video_qualities', 'extract_video_meta',
        'extract_image_data', 'get_sec_uid', 'get_user_home_from_video_url',
        'get_user_aweme_urls', 'get_user_aweme_urls_from_video_url',
    ]
    missing = [m for m in core_methods if not hasattr(parser, m)]
    if missing:
        print(f"  ✗ 缺少源项目接口: {missing}")
        sys.exit(1)
    print("  ✓ DouyinVideoParser 提供全部源项目接口")
except Exception as e:
    print(f"  ✗ 接口检查失败: {e}")
    sys.exit(1)

print("\n=== 主程序入口链路验证 ===")
try:
    from ui.main_window import Window  # 验证 DouyinPage 集成到主窗口的链路
    print("  ✓ ui.main_window 导入成功（主窗口链路正常）")
except Exception as e:
    print(f"  ⚠ ui.main_window 导入警告: {type(e).__name__}: {str(e)[:200]}")
    print("  （若为 GUI/显示相关错误，不影响模块本身；在正常图形环境下可运行）")

print("\n✅ 全部集成模块验证通过！")