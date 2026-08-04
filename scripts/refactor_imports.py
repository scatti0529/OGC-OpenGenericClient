# -*- coding: utf-8 -*-
"""
批量重构脚本：更新新架构中所有文件的 import 引用和资源路径
"""
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent

# 需要处理的目录（新架构）
TARGET_DIRS = ['core', 'ui', 'pages', 'services', 'main.py']

# ═══════════════════════════════════════
#  import 映射表
# ═══════════════════════════════════════
IMPORT_MAP = [
    # 旧引用 → 新引用
    ('from app.config import', 'from core.config import'),
    ('from app.logger import', 'from core.logger import'),
    ('from app.glass_effect import', 'from ui.widgets.glass_effect import'),
    ('from app.ui_utils import', 'from ui.widgets.ui_utils import'),
    ('from app.download_manager import', 'from services.download_manager import'),
    ('from app.downloader import', 'from services.downloader import'),
    ('from app.platform_parsers import', 'from services.platform_parsers import'),
    ('from app.services.netease_music import', 'from services.netease_music import'),
    ('from app.services import', 'from services import'),
    # sqlit → core.database
    ('from sqlit import', 'from core.database import'),
    ('import sqlit', 'from core import database'),
    # ilbs 页面引用
    ('from ilbs.settings import', 'from pages.settings_page import'),
    ('from ilbs.about_me import', 'from pages.about_page import'),
    ('from ilbs.home import', 'from pages.home_page import'),
    ('from ilbs.people_info import', 'from pages.people_page import'),
    ('from ilbs.video_multiplatform_page import', 'from pages.video.video_multiplatform_page import'),
    ('from ilbs.music_page import', 'from pages.music.music_page import'),
    ('from ilbs.dashboard import', 'from pages.dashboard_page import'),
    ('from ilbs.common import', 'from ui.widgets.common import'),
    ('from ilbs.gallery_interface import', 'from pages.gallery_interface import'),
    ('from ilbs.gallery_interface_2 import', 'from pages.gallery_interface_2 import'),
    ('from ilbs.music_player_engine import', 'from pages.music.music_player_engine import'),
    ('from ilbs.music_player_ui import', 'from pages.music.music_player_ui import'),
    ('from ilbs.music_playlist_manager_page import', 'from pages.music.music_playlist_manager_page import'),
    ('from ilbs.video_page import', 'from pages.video.video_page import'),
    # OGClogin / OGChome
    ('from OGClogin import', 'from ui.login_window import'),
    ('from OGChome import', 'from ui.main_window import'),
    ('from Ui_LoginWindow import', 'from ui.login_ui import'),
]

# ═══════════════════════════════════════
#  资源路径映射表
# ═══════════════════════════════════════
RESOURCE_MAP = [
    # res/ → resources/images/
    ('"res/background/', '"resources/images/background/'),
    ("'res/background/", "'resources/images/background/"),
    ('"res/logo/', '"resources/images/logo/'),
    ("'res/logo/", "'resources/images/logo/"),
    ('"res/photos/', '"resources/images/photos/'),
    ("'res/photos/", "'resources/images/photos/"),
    ('"res/font/', '"resources/fonts/'),
    ("'res/font/", "'resources/fonts/"),
    ('"res/ui/', '"resources/images/ui/'),
    ("'res/ui/", "'resources/images/ui/"),
    # 特殊：完整路径替换
    ('"res/setting_res/qss', '"resources/qss'),
    ("'res/setting_res/qss", "'resources/qss"),
    ('"res/setting_res/i18n', '"resources/i18n'),
    ("'res/setting_res/i18n", "'resources/i18n"),
    # 其他 res 引用（非以上子目录）
    ('"res/', '"resources/images/'),
    ("'res/", "'resources/images/"),
]


def process_file(filepath: Path):
    """处理单个文件"""
    if filepath.name.startswith('refactor_'):
        return False
    try:
        content = filepath.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        # 尝试 gbk 编码
        try:
            content = filepath.read_text(encoding='gbk')
        except Exception:
            return False

    original = content
    changes = []

    # 处理 import 映射
    for old, new in IMPORT_MAP:
        if old in content:
            # 只替换行首的 import 语句
            pattern = r'^' + re.escape(old) + r'(?=\s|$)'
            content_new = re.sub(pattern, new, content, flags=re.MULTILINE)
            # 错误日志中的引用也处理
            if 'from app.config import' in content or 'from app.logger import' in content:
                content = content_new
            else:
                content = content_new
            if content != original:
                changes.append(f'{old} -> {new}')

    # 处理资源路径
    for old, new in RESOURCE_MAP:
        if old in content:
            content = content.replace(old, new)
            changes.append(f'路径: {old} -> {new}')

    # 处理 common.py 中特殊路径
    if filepath.name == 'common.py':
        # config 路径更新
        content = content.replace(
            "os.path.join(base_dir, 'config', 'config.json')",
            "os.path.join(os.path.dirname(os.path.dirname(base_dir)), 'resources', 'config', 'config.json')"
        )
        # qss 路径更新
        content = content.replace(
            "os.path.join(base_dir, '..', 'res', 'setting_res', 'qss')",
            "os.path.join(os.path.dirname(os.path.dirname(base_dir)), 'resources', 'qss')"
        )

    if content != original:
        filepath.write_text(content, encoding='utf-8')
        return True, changes
    return False, []


def main():
    changed_files = []
    for d in TARGET_DIRS:
        p = ROOT / d
        if p.is_file():
            ok, changes = process_file(p)
            if ok:
                changed_files.append((str(p), changes))
        elif p.is_dir():
            for f in sorted(p.rglob('*.py')):
                ok, changes = process_file(f)
                if ok:
                    changed_files.append((str(f), changes))

    print(f"共更新 {len(changed_files)} 个文件:")
    for path, changes in changed_files:
        print(f"\n📄 {path}")
        for c in changes:
            print(f"   {c}")

    # 创建 resources/config 目录并复制配置
    config_src = ROOT / 'ilbs' / 'config' / 'config.json'
    config_dst_dir = ROOT / 'resources' / 'config'
    config_dst = config_dst_dir / 'config.json'
    if config_src.exists():
        config_dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_src, config_dst)
        print(f"\n📋 配置复制: {config_src} -> {config_dst}")
    else:
        print(f"\n⚠️ 配置源不存在: {config_src}")


if __name__ == '__main__':
    main()