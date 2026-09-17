# AGENTS.md — OGC-OpenGenericClient 项目级代理说明

> 面向在本仓库内工作的 AI 编码代理（以及新加入的人类贡献者）。
> 目标：让你**不用重新逆向**就能安全地改代码——哪些约定是硬性的、哪些坑已经踩过、改完怎么验证。
> 与 `README.md` 的分工：README 讲**功能有什么**，本文件讲**代码该怎么写**。
> ⚠️ 代码是唯一事实来源。当本文件与代码不一致时，以代码为准，并顺手更新本文件。

---

## 1. 项目是什么

一个 **Windows 优先的 PyQt5 桌面客户端**（Python 3.12 / PyQt5 5.15.11），单进程、多线程、重度网络 IO：

- **多平台媒体下载**：抖音 / 哔哩哔哩 / 推特(X) / Pixiv / Xvideo / YouTube
- **画册（漫画）**：拷贝漫画（EasyCopy）/ E-Hentai（`ehviewer/` 移植）/ JMComic
- **音乐**：网易云搜索、歌单解析、多音质下载、内置播放器
- **邮箱**：原生 IMAP/SMTP 三栏客户端
- **本地文件库 + 通用离线漫画库 + 离线索引**
- **用户系统与权限**：SQLite、模块级 + 功能级权限、管理员仪表盘、封禁

规模：约 100+ Python 模块，无类型检查、无 lint 配置、**没有 pytest**。测试以自写冒烟脚本形式存在于 `scripts/`。

技术栈：PyQt5 / PyQt-Fluent-Widgets / qframeless-window / httpx / requests / aiofiles / beautifulsoup4 / sqlite3（标准库）/ jmcomic / pixivpy3 / gmssl / pymupdf / pyzipper。

---

## 2. 环境与运行

### 必须使用的解释器

程序**只能**跑在项目自带的 `.venv/` 里：

```powershell
# 启动应用
.\.venv\Scripts\python.exe main.py

# 编译检查（改了任何文件后最小验证）
.\.venv\Scripts\python.exe -m py_compile <改动的文件...>
```

> 🚫 **绝对不要**在全局环境安装 PyQt6 / PySide6 版本的 `PyQt-Fluent-Widgets`、`qframelesswindow`。
> 它们会覆盖 PyQt5 版的 `qfluentwidgets` 包目录，导致 `installTranslator` 类型错误、`QWidget: Must construct a QApplication` 等异常。
> 新增依赖只改 `requirements.txt`（保持最小集），安装到 `.venv`。

### 无头（offscreen）运行 Qt

所有自动化验证都必须无头执行，否则会弹出真实窗口：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe scripts\smoke_test_album.py
```

### 可选环境变量（外置依赖一律「环境变量优先 + 相对路径兜底」）

| 变量 | 用途 | 兜底查找位置 |
|------|------|--------------|
| `GALLERY_DL_TWITTER_DIR` | 推特备用解析的 gallery-dl 目录 | 同级 `twitter/`、`gallery-dl/`，或项目内 `twitter/` |
| `DOUYINDL_SRC_DIR` | 抖音导入自检脚本的 `douyinDL-main/src` | 同级 `../douyinDL-main/src` |

未配置时功能优雅降级（不可用但不影响主程序）。

---

## 3. 目录地图与分层依赖规则

```
main.py              启动入口：sys.path 注入 → Qt 插件路径修复 → 日志 → crash_guard → 数据库
                      → 下载目录自检 → 玻璃效果 → QApplication → thread_guard/watchdog
                      → qfluentwidgets 补丁 → 登录窗口 → 主窗口
core/                基础设施（配置/日志/数据库/崩溃兜底/线程看门狗/资源路径）
ui/                  窗口与通用组件：login_window、main_window（导航 + 权限）、widgets/
pages/               功能页面：home / settings / about / dashboard / jmcomic / folder_library
  pages/video/       多平台视频（douyin / pixiv / 迷你窗口 / 离线查看器）
  pages/album/       画册（easycopy_* / ehentai_* / comic_offline / 各阅读器）
  pages/music/       音乐（页面 / 播放引擎 / 播放器 UI / 播放列表管理）
  pages/email/       邮箱（页面 / 账号管理 / 写信 / 后台 worker）
services/            业务与网络层（下载引擎、各平台解析与下载、邮件、漫画库、订阅）
  services/douyin/   抖音签名算法（abogus / xbogus）
  services/easycopy/ 拷贝漫画服务（api / app / parser / downloader / net / models）
ehviewer/            EhViewer 核心移植
  ehviewer/*.py      引擎 / 解析 / session / db / models / downloader / image_cache / 标签翻译
  ehviewer/ui/       Qt 界面层（画廊列表 / 详情 / 阅读器 / 收藏 / 历史 / 下载 / 搜索）
resources/           config.json 默认配置、i18n、fonts、images、qss
scripts/             开发与回归脚本（smoke_* / verify_* / dbg_* / test_*）
data/                **小体积、不可再生**：索引 JSON、配置、数据库、7Z、avatars —— **不进仓库**
  data/thumb_index.json     缩略图索引        data/dir_cache/        目录扫描索引
  data/offline_index/       漫画离线索引      data/ehentai/app_db.db EhViewer 数据库
  data/7Z/  data/avatars/   解压器 / 头像     data/_migration_backup_*/  迁移备份（可删）
logs/                运行日志 ——**不进仓库**
tests/               空占位目录（只有 `__init__.py`）；真实回归都在 `scripts/`
```

> 🗂️ **缓存与数据是分开的（2026-09 重构，务必遵守）**
> `{下载根目录}/.cache/` 存**大体积可再生**缓存（`thumbs/`、`ehentai/`、`easycopy/`），
> `data/` 只存**小体积不可再生**的索引 / 配置 / 数据库。这样几百 MB 缓存不会撑大程序目录，
> 换下载盘也不丢索引。重构前 `data/` 实测 576 MB，现在约 23 MB。
> **路径一律从 `core.config` 取**（`CFG.download_root` / `CFG.cache_path(...)` /
> `CFG.offline_index_path(...)`），不要自己再拼一份 —— 详见 §4.9 与 §7 第 14、15 条。

> ⚠️ **`pages/music/` 与 `ehviewer/data/` 必须保持入库。** 它们曾被 `.gitignore` 的
> `music/`、`data/` 规则（未锚定到仓库根）吞掉、从未进入 git 历史，导致别人 clone 后
> 「主界面完全打不开」和「E-Hentai 标签翻译失效」。详见 §7 第 12、13 条与 §8。

### 依赖方向（单向，不要制造回环）

```
main.py → ui → pages → services → core
                    ↘ ehviewer/ui → ehviewer（核心）
```

- **`core/` 可以被任何层导入；它不导入 `pages/`、`services/`、`ehviewer/`。**
- **`services/` 与 `ehviewer/` 核心层默认不依赖 Qt/GUI。** 现状例外仅 3 处，属于「对外暴露 QThread 封装」的既定设计：
  `services/downloader.py`、`services/jmcomic_service.py`、`services/easycopy/app.py`；
  `ehviewer/downloader.py`、`ehviewer/image_cache.py` 亦含 Qt。
  **不要在 `services/` 里导入 `pages/` 或 `ui/`**——需要 UI 反馈就用信号回调/`progress_callback` 参数。
- `pages/` 不得被 `ehviewer/` 导入；`pages/album/ehentai_*.py` 是**桥接层**，负责把 `ehviewer/` 接到本项目 UI 体系。

---

## 4. 硬性代码约定

### 4.1 路径：禁止写死本机绝对路径

外置工具/依赖目录必须写成 **环境变量优先 + 相对路径兜底**：

```python
DIR = os.environ.get('GALLERY_DL_TWITTER_DIR', '')   # 优先
if not DIR:
    DIR = <相对项目根或同级目录推导>                  # 兜底
```

> 这条是**用户明确要求**。历史上 `services/twitter_service.py`、`scripts/test_douyin_import.py` 被改成 `E:\...` 绝对路径，`resources/config/config.json` 写死本机下载目录——都必须避免。
> 项目内资源路径**只**从 `core/resource_paths.py` 取；新增资源在那里加常量并注明使用位置。

### 4.2 配置：只用 `core.config`

```python
from core.config import config as CFG

CFG['xc']              # 读
CFG.get('key', '')     # 安全读（未知键用这个，别用 CFG['key']）
CFG['xc'] = 10         # 写 → 自动加密钥锁 + 临时文件 + os.replace 原子落盘
```

- 落盘文件：`data/config.json`（单例 `ConfigManager`）。
- **不要自己 `open(data/config.json, 'w')`**：多个线程会写它（设置页、jmcomic 账号、抖音 cookie、pixiv 选项），
  曾因并发覆盖产生半截 JSON → 下次启动回退默认值 → 用户「设置莫名其妙全丢」。
- 新增配置项：在 `ConfigManager.default` 里加默认值（老配置靠 `setdefault` 自动补全，保持向后兼容）。

### 4.3 日志：只用 `core.logger`

```python
from core.logger import logger, set_task_tag

logger.info('操作日志')                  # logs/operation.log
logger.error('错误', exc_info=True)      # logs/error.log（带 traceback）
logger.warning('警告')                   # 双写
set_task_tag('download:pixiv:12345')     # 线程本地任务标签，排查并发必用；结束置 None
```

- 日志格式含 `[线程名][任务标签]`，多线程排查优先靠**任务标签**而非线程名。
- 兜底钩子（`crash_guard`）内部**绝不允许再抛异常**，否则异常递归。

### 4.4 线程：QThread + 信号，绝不阻塞主线程

44 处 `QThread` 子类，且**全部**用 `pyqtSignal` 回传结果。新 worker 沿用同一形态：

- 命名：`*Worker` / `*Thread`（私有用 `_XxxWorker`），定义在**使用它的页面文件内**（除非被多处复用）。
- 网络/磁盘/解析一律进工作线程；主线程只做 UI。
- **失败路径也必须发信号**。历史 bug：图片加载失败不上报 → 页面永久「加载中」。
  参考 `pages/album/easycopy_reader.py`：`failed = pyqtSignal(int, int)` 注释明确写「失败也必须上报」。
- **有界并发**：不要「每条目起一个线程」。优先 `QThreadPool`/最大并发数限制（抖音解析并发上限 2；缩略图用池）。
- **不要在主线程无超时 `join()` 子线程**。用 `services.download_manager.join_threads_with_stall_detection(threads, progress_getter, stop_event)`——它按「进度是否推进」判卡死，而不是拍脑袋设固定总时长。
- 线程对象在页面 `closeEvent` 里回收；`core/thread_guard.py` 已全局拦截 `QThread.start`/`QThreadPool.start`，退出时统一 `requestInterruption + wait`（含 8 秒总预算）。

### 4.5 权限：SQLite + 导航可见性

```python
from core.database import get_user_permissions, is_admin

perms = get_user_permissions(username)
perms['modules'].get('video', True)      # 模块级
perms['features'].get('video_douyin', True)  # 功能级
```

- 权限键的真实定义在 `core/database.py`：`ALL_MODULES` / `ALL_FEATURES`。**新增权限项必须同时加进这两个列表**，否则仪表盘里勾不到、`get_default_permissions()` 也不会补键。
- 现有关键字：模块 `home / music / video / people / about_me / settings / dashboard`；功能 `music_*`、`video_*`、`jmcomic_*`。
- 未知键在导航层按 `True` 兜底（`perms.get(...).get(key, True)`），所以 `main_window.py` 里的 `'email'` 等键不会崩，但也不受控——**要真正可控就得进 ALL_MODULES**。
- 导航控制：树形**子项禁用必须用 `removeInterface(sub, isDelete=False)`**，不能 `setVisible(False)`（会破坏布局导致重叠）。见 `ui/main_window.py::setCurrentUser` / `_apply_feature_permissions`。
- `admin` 恒定可见仪表盘。

### 4.6 数据库

- 文件 `data/ogc_users.db`，启用 **WAL + synchronous=NORMAL**（多线程并发读写的必要前提）。
- 一律走 `core/database.py` 的函数；页面层**不要**自己 `sqlite3.connect` 写业务表。
- 每次操作 `get_db_connection()` → `try/finally: conn.close()`；行是 dict 风格（`row['username']`）。
- 建表/建索引必须幂等（`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`），并容忍「表/列尚不存在」的失败。
- **内置管理员账号**：`init_db()` 末尾会调用 `ensure_admin_account()`，首次建库时写入 `admin` / `11111111`（`role='管理员'`、全量权限）。该方法**幂等且绝不覆盖已有密码**——只在账号不存在时插入，已存在则仅补齐空的 role/permissions。⚠️ 改动此处务必保住「不重置密码」这条语义，否则每次启动都会把用户改过的密码打回默认值。

### 4.7 下载：只用统一引擎

```python
from services.download_manager import download_media, get_platform_dir, get_download_root
success, message, path = download_media(url, filename, platform, file_type='video',
                                        progress_callback=cb, referer=referer, is_hls=False)
```

- 目录结构：`{video_download_root}/{platform}-download/{images|videos|audios|sourcefiles}`。
  平台目录名映射见 `PLATFORM_FOLDERS`（如 `douyin-download`、`easycopy-download`）。
- 根目录取 `CFG.download_root`：**配置了就以配置为准并自动建目录**；只有真的建不出来（盘符不存在/无权限）才回退 `data/`。
  旧实现是「配置路径不存在 → 静默回退 data/」，结果用户指定的下载盘只要还没建目录就失效，几百 MB 全落回项目内。启动时 `ensure_download_dirs()` 自检。
- 文件名必须过 `sanitize_filename()`；写盘前用 `get_unique_path()` 避免覆盖。
- 下载模式自适应（`auto` → 并发分块 / 流式 / HLS），不要绕过它自己写 `requests.get(..., stream=True)` 存盘。

### 4.8 代码风格

- 文件头 `# -*- coding: utf-8 -*-`，模块 docstring 用中文说明「为什么」而非「做了什么」。
- 注释/文档字符串**用中文**；分段用 `# ═══ 标题 ═══` 或 `# ── 标题 ──`。
- **注释要写清踩过的坑与理由**（本仓库的注释密度是有意为之，别「顺手精简」）。
- 大段修复处常带「原实现…现改为…」的因果说明——保留它们。
- 导入沿用现有分组：标准库 → 第三方 → PyQt5/qfluentwidgets → `core` → `ui/pages/services`。
- 不引入新的 linter/formatter 配置；保持与周围代码一致即可。

### 4.9 存储路径：一切从 `core.config` 取，别自己拼

```python
from core.config import config as CFG

CFG.download_root                     # 下载根目录（权威解析 + 自动创建）
CFG.cache_path('ehentai', 'cache')    # {下载根}/.cache/...  大体积可再生的缓存
CFG.offline_index_path('easycopy')    # data/offline_index/... 索引（小体积不可再生）
CFG.set_root(项目根)                   # 仅维护脚本需要（见下）
```

判断新文件该放哪，只问一句：**丢了能不能重新生成？**

| 能重新生成（缓存/缩略图/预览/阅读临时图） | 不能（索引/配置/数据库/进度/头像） |
|---|---|
| `CFG.cache_path(...)` → `{下载根}/.cache/` | `data/` 内（`CFG.data` / `CFG.offline_index_path`） |

- **禁止再写第二份「配置 → 回退」实现**：历史上 `download_manager` 与 `file_library` 各有一份且细节不同，
  同一次运行两处算出不同根目录，缓存被写到两个地方。
- 缓存目录一律放在下载根的 `.cache/` 下（点号前缀），文件库扫描会跳过隐藏项，不会把缓存当用户内容列出来。
- **维护脚本必须显式 `CFG.set_root(<项目根>)`**：默认 root 取自 `sys.argv[0]`，`python scripts/xxx.py`
  会解析成 `scripts/`，于是 `data/` 变成 `scripts/data`（这是为了让冒烟测试与真实数据隔离，别改）。
  需要动真实 `data/` 的脚本（如 `scripts/migrate_storage.py`）不调用它就会改错地方。

---

## 5. 运行时可靠性三件套（改代码前必须理解）

| 模块 | 解决什么 | 对你的约束 |
|------|----------|-----------|
| `core/crash_guard.py` | 槽函数异常默认触发 PyQt5 `qFatal()→abort()` 静默闪退；线程异常静默死亡；C 层硬崩溃 | 启动早期安装，`sys.excepthook` / `threading.excepthook` / `faulthandler` → `logs/crash.log`。**钩子内不能抛异常** |
| `core/thread_guard.py` | `QThread: Destroyed while thread is still running` 闪退 | 已拦 `QThread.start`/`QThreadPool.start`；登记表会回收。**别自己 patch 回来，也别删线程的强引用** |
| `core/watchdog.py` | 「界面卡死但没崩」无法取证 | 主线程心跳 >8s 未刷新 → 转储**全部线程栈**到 `logs/crash.log`；存活线程 ≥96 告警。**只取证不自动重启**（GUI 主线程无法安全强杀） |

排障入口：卡死/闪退**先看 `logs/crash.log`，再看 `logs/error.log`**，配合任务标签定位到具体下载/解析任务。

---

## 6. 验证：怎么测

**没有 pytest。回归测试在 `scripts/`**，命名 `smoke_*.py`（回归/护栏）、`verify_*.py`（集成接线自检）、`test_*.py`（早期单点）、`dbg_*.py`（手工取证）。

约定：打印 `[PASS]/[FAIL]` 或 `RESULT: ALL PASSED`，**失败 `sys.exit(1)`**，成功退出码 0。所以你只需看退出码。

```powershell
# 单个脚本
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe scripts\smoke_test_album.py

# 改了并发/线程/看门狗相关代码，跑这三套
.\.venv\Scripts\python.exe scripts\smoke_concurrency_fixes.py
.\.venv\Scripts\python.exe scripts\smoke_concurrency_guard.py
.\.venv\Scripts\python.exe scripts\smoke_watchdog_observability.py
```

常用脚本索引：

| 脚本 | 覆盖 |
|------|------|
| `smoke_fresh_install.py` | **全新安装**：随包模块/资源是否齐全、core 未反向依赖 ui、首建库自带管理员且不覆盖密码 |
| `smoke_storage_layout.py` | **存储布局**：缓存只在 `{下载根}/.cache`、索引只在 `data/`、缓存不出现在文件库列表、迁移幂等与去重/冲突规则 |
| `smoke_test_album.py` | 画册：编译 + 导入 + 无头构建页面 |
| `smoke_test_ehentai_fix.py` / `smoke_eh_*.py` | E-Hentai：新结构、分页、同步、下载队列、写库、对账 |
| `smoke_test_easycopy.py` / `smoke_test_readers.py` | 拷贝漫画 / 各阅读器 |
| `smoke_test_media_offline.py` / `smoke_test_offline_index.py` | 离线查看器 / 漫画离线索引 |
| `smoke_test_email.py` / `smoke_test_dashboard.py` / `smoke_test_window.py` | 邮箱 / 仪表盘 / 窗口 |
| `smoke_startup_lifecycle.py` | 启动→退出生命周期（区别于 `smoke_test_window.py` 的硬 `sys.exit(0)`） |
| `smoke_reader_stuck_fix.py` / `smoke_detail_tag_flow.py` | 阅读器卡死修复 / 详情标签流 |
| `verify_*_integration.py` | 抖音/拷贝/JMComic/离线索引接线是否生效 |

**最小验证流程（任何改动）**：
1. `python -m py_compile` 所有改动文件；
2. 跑与改动模块对应的 `scripts/smoke_*.py`（无头）；
3. 涉及 UI 装配的改动，跑 `smoke_test_album.py` 或 `smoke_test_window.py` 确认能无头构建；
4. 涉及启动链路的改动，跑 `smoke_startup_lifecycle.py`。

> ⚠️ 验证陷阱：`PyQt5` 的 `exec_` 是**存在**的（`exec` 才是 PyQt6 写法）。用静态文本搜「`exec_` 已废弃」会得到假阳性，别顺手改成 `exec` 而不是实际运行程序。

---

## 7. 已经踩过的坑（不要重犯）

1. **槽函数异常 → `qFatal` 闪退且无日志**：任何 Qt 槽内代码都要能容忍异常；`crash_guard` 已兜底，但别依赖它掩盖逻辑错误。
2. **`config.json` 并发写坏** → 只用 `CFG[...] = v`（原子写）。
3. **主线程阻塞**（等锁 / 等 IO / `join` 子线程 / 跑长任务）→ 界面卡死，靠看门狗转储。长任务必须进工作线程。
4. **`join()` 无超时** → 下载永远停在 99%。用 `join_threads_with_stall_detection`。
5. **无界并发线程** → 内存持续增长 + `QThread` 泄漏。图形/缩略图走线程池。
6. **失败路径不发信号** → 永久「加载中」。每个 worker 都要有失败信号。
7. **树形导航子项 `setVisible(False)`** → 布局重叠。用 `removeInterface`。
8. **中文/非 ASCII 项目路径** → PyQt5 找不到平台插件。`main.py` 与各 smoke 脚本都在**导入 Qt 之前**注入 `QT_QPA_PLATFORM_PLUGIN_PATH`（指向 `.venv\Lib\site-packages\PyQt5\Qt5\plugins`）；新写独立脚本必须照抄这段。
9. **PyQt6/PySide6 版 qfluentwidgets 混装** → 见 §2 警告。
10. **`data/`、Cookie、日志被提交** → 见 §8。`jm_cookies.json`、`remembered_login.json`、`ogc_users.db` 都在 `data/` 内，属敏感数据。
11. **qfluentwidgets 上游瑕疵**：`InfoBarManager.add` 的 `dropAni` 缺 start/end value、动画目标销毁刷屏——已在 `main.py` 用运行时补丁 + Qt 消息过滤器处理。**升级 qfluentwidgets 后要回归这两处补丁**。
12. **`.gitignore` 目录规则未锚定 → 源码/资源从未入库**（本项目最严重的一次事故）：
    写成 `data/`、`music/` 会匹配**任意深度**的同名目录，于是 `ehviewer/data/tag_translations.json.gz`
    与整个 `pages/music/` 从未进入 git 历史。别人 clone 后一登录就 `ModuleNotFoundError: No module named 'pages.music'`，
    **主界面完全打不开**（除登录页外全不可用）。规则一律写成 `/dirname/`，并跑 `scripts/smoke_fresh_install.py` 验证。
13. **相对路径当配置默认值 → 在 CWD 下建目录**：`ui/widgets/common.py` 的 `downloadFolder` 原默认值是 `"app/download"`，
    qfluentwidgets 的 `FolderValidator.correct()` 会 `Path(value).mkdir()`，于是**每次 import 都在当前工作目录重新长出 `app/download/`**
    （位置还随 cwd 漂移）。删除目录无用，必须把默认值改成基于 `__file__` 的绝对路径。
    推而广之：任何带 `FolderValidator` 的配置项默认值都要用绝对路径。
14. **缓存混进 data/ → 程序目录被几百 MB 撑大**：重构前 `data/ehentai/cache`(433MB)、`data/thumb_cache`(53MB)、
    `data/easycopy/images`(49MB) 全在程序目录内，而另一份现行缩略图缓存 `.thumbs`(191MB) 又在下载根目录 ——
    同类缓存散落两地。现已统一：缓存 → `{下载根}/.cache/`，索引 → `data/`（`data/` 从 576MB 降到 23MB）。
    **新增大体积产物一律走 `CFG.cache_path(...)`**，别再往 data/ 里塞。
15. **切页即重载 → 每次切回来都要重新等**：`easycopy_page._refresh_current_tab` 在**每次标签切换**都 `load()`；
    `ehentai_reader` / `jmcomic_reader._on_pivot_changed` **每次切到离线标签都重扫本地目录**。
    现改为「**首次进入才加载**」（`_loaded_tabs` / `_offline_loaded` 守卫），刷新按钮与删除信号走 `force=True`。
    写"显示本地文件"的新页面时照此办理：**扫描结果要留驻，不要在 show / 切页里无条件重扫**。

---

## 8. 提交与安全纪律

- **永远不要提交**：`data/`（数据库、`config.json`、cookie、自动登录信息）、`logs/`、`douyin_cookie.txt`、`*cookies*.json`、媒体文件（`music/`、`*.mp4`…）、`scripts/data/`、`*.zip`、`SKILL.md`。以上均已在 `.gitignore` 中；新增敏感路径要同步补进去。
- **`.gitignore` 的目录型规则一律写成 `/dirname/`（锚定仓库根）**。不加锚点会匹配任意深度的同名目录：`data/` 曾吞掉 `ehviewer/data/`，`music/` 曾吞掉 `pages/music/`，两者都从未入库。新增/修改规则后**必须**用 `git check-ignore -v <关键文件>` 验证，并跑一次 `scripts/smoke_fresh_install.py`。
- 本仓库工作树中可能残留本机产物（如 `douyin_cookie.txt`、`video.zip`、`scripts/data/`）。推送前**确认暂存范围**里没有这些，以及没有被改成 `E:\...` 绝对路径的源码。
- 远端：`https://github.com/scatti0529/OGC-OpenGenericClient.git`（以 `git remote -v` 为准）。
  GitHub 默认分支为 `main`，本地长期开发在 `master`——推送前确认目标分支，别推错。
- 本机 git 可能因目录属主为 Administrators 而报 `dubious ownership`，需
  `git config --global --add safe.directory <仓库路径>` 才能执行 git 命令。
- 安全审查类改动后，凭据只存本机、不进归档、不进远端。

---

## 9. 改动自检清单

- [ ] 改动文件全部 `py_compile` 通过
- [ ] 没写死本机绝对路径；外置目录走「环境变量 + 相对兜底」
- [ ] 没新增 `pages/ ← services/core` 反向依赖；`services/` 未导入 GUI 层
- [ ] 新资源路径来自 `core/resource_paths.py`
- [ ] 配置读写走 `CFG`，未直接写 `data/config.json`
- [ ] 工作线程有成功**与失败**信号，且不在主线程阻塞等待
- [ ] 新权限项已加入 `ALL_MODULES` / `ALL_FEATURES`（若有）
- [ ] 新下载走 `download_manager`，未自建目录与命名规则
- [ ] 关键路径有中文日志，长任务设置了 `set_task_tag`
- [ ] 对应的 `scripts/smoke_*.py` 已跑且退出码为 0（无头）
- [ ] 新的大体积产物走 `CFG.cache_path(...)`（不塞进 `data/`）；索引走 `CFG.data` / `CFG.offline_index_path(...)`
- [ ] 显示本地文件的页面不在切页时重扫（首次加载 + 显式刷新，见 §7 第 15 条）
- [ ] 暂存区无 `data/`、cookie、日志、媒体文件与本机绝对路径
