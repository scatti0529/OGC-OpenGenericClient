# -*- coding: utf-8 -*-
"""测试 douyinDL-main 核心功能模块是否可以正常导入"""
import sys
import os

# 添加 douyinDL-main/src 到 sys.path（通过环境变量 DOUYINDL_SRC_DIR 指定，
# 或放到与本项目同级的 douyinDL-main/src 目录下）
SRC_DIR = os.environ.get(
    'DOUYINDL_SRC_DIR',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 '..', 'douyinDL-main', 'src'))
sys.path.insert(0, SRC_DIR)

try:
    # 应用 msToken 补丁
    from f2.apps.douyin.utils import TokenManager as _F2TokenManager

    _original_gen_real_msToken = _F2TokenManager.gen_real_msToken.__func__

    def _safe_gen_real_msToken(cls):
        try:
            return _original_gen_real_msToken(cls)
        except Exception:
            return _F2TokenManager.gen_false_msToken()

    _F2TokenManager.gen_real_msToken = classmethod(_safe_gen_real_msToken)

    from f2.apps.douyin.crawler import DouyinCrawler
    from f2.apps.douyin.model import UserMix, PostDetail
    from f2.apps.douyin.filter import UserMixFilter, PostDetailFilter
    from f2.apps.douyin.utils import TokenManager
    print("f2 imports OK")

    import yaml
    print("yaml OK")

    import httpx
    print("httpx OK, version:", httpx.__version__)

    print("ALL IMPORTS OK")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()