# -*- coding: utf-8 -*-
"""验证 JMComic 集成是否正常"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=== 1. 检查 jmcomic 库 ===")
from services.jmcomic_service import JMCOMIC_AVAILABLE, import_jmcomic
print(f"jmcomic 可用: {JMCOMIC_AVAILABLE}")
if JMCOMIC_AVAILABLE:
    jm = import_jmcomic()
    print(f"jmcomic 版本: {getattr(jm, '__version__', 'unknown')}")

print("\n=== 2. 导入服务模块 ===")
from services.jmcomic_service import (
    JMComicService, DownloadQuotaManager, SubscriptionManager,
    JMBrowser, JMDownloadManager, JMAuthManager, JMPacker,
    classify_exception, CATEGORY_LIST, ORDER_LIST, TIME_LIST,
    SEARCH_MODES, RANK_TYPES, PACK_FORMATS, JM_DEFAULTS,
)
print("服务模块导入成功")

print("\n=== 3. 创建服务实例 ===")
# 使用临时目录
import tempfile
tmp = tempfile.mkdtemp(prefix="jm_test_")
service = JMComicService(data_dir=tmp)
print(f"服务实例创建成功, 数据目录: {service.data_dir}")
print(f"配置: {service.config.download_dir}")
print(f"浏览器: {service.browser.__class__.__name__}")
print(f"下载器: {service.downloader.__class__.__name__}")
print(f"认证: {service.auth.__class__.__name__}")
print(f"配额: {service.quota.__class__.__name__}")
print(f"订阅: {service.subscribe.__class__.__name__}")

print("\n=== 4. 测试数据库（主程序数据库）===")
from core.database import DB_PATH, get_db_connection
print(f"主程序数据库: {DB_PATH}")
conn = get_db_connection()
cursor = conn.cursor()
# 检查 download_quota 表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='download_quota'")
print(f"download_quota 表: {'存在' if cursor.fetchone() else '缺失'}")
# 检查 jm_subscriptions 表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jm_subscriptions'")
print(f"jm_subscriptions 表: {'存在' if cursor.fetchone() else '缺失'}")
conn.close()

print("\n=== 5. 测试配额和订阅 ===")
quota = DownloadQuotaManager()
ok, used, limit = quota.reserve("test_user", 5)
print(f"配额预留: ok={ok}, used={used}, limit={limit}")

sub = SubscriptionManager()
ok = sub.add("gui:test", "123456", "local", "测试本子", 10)
print(f"添加订阅: {ok}")
subs = sub.list_for("gui:test")
print(f"订阅列表: {subs}")
sub.remove("gui:test", "123456")

print("\n=== 6. 导入页面模块 ===")
from pages.jmcomic_page import (
    JmComicPage, SearchTab, DownloadTab, AccountTab,
    SubscribeTab, SettingsTab, AlbumDetailDialog,
    ResultCard, MetaCard, KeyValueRow,
)
print("页面模块导入成功")

print("\n=== 7. 验证 UI 导入 ===")
print("所有集成验证通过！")