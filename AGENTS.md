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
  services/ffmpeg_installer.py  ffmpeg 按需下载/解压/绑定（**不含 Qt**，见 §10）
ui/widgets/ffmpeg_prompt.py     缺 ffmpeg 的弹窗 + 下载工作线程（**含 Qt**，见 §10）
ehviewer/            EhViewer 核心移植
  ehviewer/*.py      引擎 / 解析 / session / db / models / downloader / image_cache / 标签翻译
  ehviewer/ui/       Qt 界面层（画廊列表 / 详情 / 阅读器 / 收藏 / 历史 / 下载 / 搜索）
resources/           config.json 默认配置、i18n、fonts、images、qss
scripts/             开发与回归脚本（smoke_* / verify_* / dbg_* / test_*）
data/                **小体积、不可再生**：索引 JSON、配置、数据库、7Z、avatars —— **不进仓库**
  data/ogc_users.db         **唯一的数据库**（账号+权限+音乐+JM+抖音+E-Hentai 收藏/下载/历史）
  data/thumb_index.json     缩略图索引        data/dir_cache/        目录扫描索引
  data/offline_index/       漫画离线索引      data/7Z/  data/avatars/  解压器 / 头像
  data/*.merged-<时间戳>     旧数据库留档（合并后改名，确认无误可删）
  data/_migration_backup_*/  迁移备份（可删）
logs/                运行日志 ——**不进仓库**
tests/               空占位目录（只有 `__init__.py`）；真实回归都在 `scripts/`

本机另有一个**构建工作区**（与源码目录平级，不属于本仓库，见 §10）：
  ../OGC-OpenGenericClient-exe/    packaging/（spec、iss、构建脚本）· build/ · dist/
```

> 📦 **打包相关的一切都以 §10 为准**（冻结、安装器、卸载、工作区标记）。

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

> 🎯 **全程序只有一个 SQLite 文件**：`data/ogc_users.db`（冻结时 `%APPDATA%\OGC-OpenGenericClient\ogc_users.db`）。
> 历史上 E-Hentai 用的是**另一个**文件 `data/ehentai/app_db.db`，于是账号库与收藏/下载记录分家 ——
> 卸载向导只备份得到一个、换机只带走一个就会丢另一半。2026-09 已合并（用户明确要求）。

- **表结构只有一个真源**：`core/database.py::EHENTAI_DDL`（E-Hentai 的 10 张表：
  `DOWNLOADS` / `DOWNLOAD_LABELS` / `DOWNLOAD_DIRNAME` / `HISTORY` / `LOCAL_FAVORITES` /
  `QUICK_SEARCH` / `FILTER` / `Gallery_Tags` / `Black_List` / `BOOKMARKS`）。
  `ehviewer/db.py` 从这里 `import`，**不要再抄一份 DDL**。
- **首次启动就建全结构**：`init_db()` 依次建账号表 + `init_jmcomic_tables()` +
  `init_usage_table()` + `init_ehentai_tables()` + `init_pixiv_tokens_table()` +
  `init_music_tables()`，最后用 `missing_tables()` 自检并告警。
  ⚠️ 音乐 / Pixiv 的表以前只在首次用到该功能时才懒创建，会出现"全新安装 → 打开音乐页 →
  no such table"。新增模块的表**必须**挂进 `init_db()`，并把表名加进 `ALL_TABLES`，
  否则 `scripts/smoke_unified_db.py` 会失败（这是它的用途）。
- 取数据库路径：应用代码用 `core.database.get_db_path()`；E-Hentai 侧用
  `ehviewer.db.get_db_path()`（默认同一个文件，测试可临时指向副本）。
  **不要**再引入 `KEY_DB_PATH` 之类的"第二个库"设置项。
- **旧库合并**：`core/db_unify.py` 在启动时（`init_db()` 之后）把 `ehentai/app_db.db`、
  `<程序目录>/app_db.db`、`<程序目录>/ehviewer/app_db.db` 里的数据搬进统一库，
  然后把旧文件改名成 `*.merged-<时间戳>` **留档不删除**（改名本身就是幂等标记）。
  合并是通用的：旧库里有什么表就建什么表、列取交集，所以未知的新表也不会丢。
  主键冲突时 `INSERT OR IGNORE` —— **保留统一库里已有的行**，不会用旧数据覆盖用户当前数据。
- 文件 `data/ogc_users.db`，启用 **WAL + synchronous=NORMAL**（多线程并发读写的必要前提）。
- 一律走 `core/database.py` 的函数；页面层**不要**自己 `sqlite3.connect` 写业务表。
- 每次操作 `get_db_connection()` → `try/finally: conn.close()`；行是 dict 风格（`row['username']`）。
- 建表/建索引必须幂等（`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`），并容忍「表/列尚不存在」的失败。
- **内置管理员账号**：`init_db()` 末尾会调用 `ensure_admin_account()`，首次建库时写入 `admin` / `11111111`（`role='管理员'`、全量权限）。该方法**幂等且绝不覆盖已有密码**——只在账号不存在时插入，已存在则仅补齐空的 role/permissions。⚠️ 改动此处务必保住「不重置密码」这条语义，否则每次启动都会把用户改过的密码打回默认值。
- **冒烟脚本要隔离数据库**：E-Hentai 的脚本会写下载记录/收藏，
  用 `scripts/_eh_db_testkit.py::use_temp_db()` 拷一份统一库到临时目录再跑
  （它内部用 `ehdb.set_db_path()` 指过去；`ehentai_sync.db_path()` / 收藏页的
  `db_path()` 都走 `ehdb.get_db_path()`，所以会一起跟过去）。
  ⚠️ **应用代码不要调 `set_db_path()`** —— 那会让界面与下载记录读写不同的库。

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
CFG.music_download_dir                # {下载根}/music-download（派生，不是配置项）
CFG.music_cache_dir                   # {下载根}/.cache/music（派生，不是配置项）
CFG.set_root(项目根)                   # 仅维护脚本需要（见下）
```

> 🎯 **设置里只有「一个下载目录」是用户可见的目录选项**（用户明确要求）。
> 历史上这里分散着五项 —— 本地音乐库 / 下载目录 / 音乐缓存目录 / 音乐下载目录 /
> 视频下载根目录 —— 用户得同时维护好几个路径，还常常出现"音乐下到 A 盘、缓存在 C 盘"。
> 现在**音乐不再有目录配置**：`music_cache_path` / `music_download_path` 两个键已删除，
> 一律由 `download_root` 派生（见上面两个属性）。
> 老配置里残留的这两个键**不再被读取**，其内容由
> `core/storage_migration.py::_migrate_music_dirs` 一次性搬进新位置。
> 回归测试：`scripts/smoke_settings_paths.py`。
> ⚠️ 别再加回"某个模块自己的目录设置" —— 那正是这次要收敛掉的东西。

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

### 4.10 冻结（exe）模式：写数据的路径规则

打包后 `python main.py` 那套假设全部不成立，三条硬规则：

1. **可写数据一律走 `core/paths.user_dir()`**（冻结时 = `%APPDATA%\OGC-OpenGenericClient`），
   **绝不能**落在安装目录 —— 用户可能装到 Program Files / `%LOCALAPPDATA%\Programs`，那里通常只读。
   实测过一次反面案例：`data/` 按 exe 同级解析，结果程序把库和缓存写进了安装目录。
2. **只读资源一律走 `core/paths.resource_root()`**（冻结时 = `sys._MEIPASS`，即 onedir 的
   `_internal/`）。**不能**用 exe 所在目录 —— PyInstaller 6.x 把随包数据放在 `_internal/` 下。
3. **下载根目录默认值不能是 data/**：下载内容 + `.cache` 缓存动辄几百 MB 到数 GB。
   默认取 `~\Downloads\OGC-OpenGenericClient`（见 `_default_download_root()`）。
   同一条理由：`%APPDATA%` 放得下几 MB 的索引与账号库，放不下缓存。

> 判断某个新文件该放哪，只问一句：**它是不是随程序分发、且永不修改？**
> 是 → `resource_root()`；否 → `user_dir()`；体积大且可再生 → `CFG.cache_path(...)`。

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
| `smoke_storage_layout.py` | **存储布局**：缓存只在 `{下载根}/.cache`、索引只在 `data/`、缓存不出现在文件库列表、迁移幂等与去重/冲突规则、**冻结模式可写数据不落安装目录**、**子进程探针校验"可写路径常量"来自 `user_dir()`** |
| `smoke_workspace.py` | **工作区标记**：可移植副本与标记生成、**凭据绝不落进下载目录**、全新安装自动还原、已有数据时不擅自动手、拒绝更高 schema、换盘改写索引路径 |
| `smoke_ffmpeg_setup.py` | **ffmpeg 按需获取**：`ffmpeg_path` 优先级最高、解压→定位→绑定全链路、找不到时优雅降级、弹窗动作与「下次不再显示」、**已可用/不再提示时不弹窗**、缺 ffmpeg 时文件库如实统计跳过的视频数 |
| `smoke_settings_paths.py` | **设置只留一个下载目录**：旧的 5 张目录卡片与槽函数确实已删、GUI 配置里没有路径项、**音乐缓存/下载都派生自下载根**、播放列表落在可写用户目录、**资源常量指向的文件真实存在**、**打包的图片都被引用（无死素材）** |
| `smoke_unified_db.py` | **统一数据库**：首次 `init_db()` 就建全 `ALL_TABLES`、`ehviewer.db` 与账号库是同一个文件且写入真的落进去、**旧 app_db.db 能连未知表一起合并**、重复合并幂等、主键冲突保留统一库现有数据、旧库改名留档 |
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

> ⚠️ **两个冒烟脚本的退出码不可信，要看打印内容**：
> `scripts/smoke_test_album.py` 会无头构建真实页面，跑完全部检查后仍以
> `QThread: Destroyed while thread is still running` **进程级 abort**
> （退出码 `-1073740791`），连 `SMOKE TEST RESULT: ALL PASSED` 都来不及打印。
> 已在 `git worktree` 的 **HEAD 基线上复现同样行为**（试过 `os._exit`、`gc.disable()`、
> 留住页面强引用，均无效 —— 是 Qt 自身析构时序），所以**判断它通过与否要看
> 有没有 `[FAIL]` 与 `ERROR`，不要看退出码**。要看退出码就用
> `smoke_test_readers.py` / `smoke_test_offline_index.py` / `smoke_startup_lifecycle.py`
> 这些正常返回 0 的脚本。
> `scripts/smoke_test_window.py` 已修好（结尾改成 `os._exit` 跳过 Qt 收尾，退出码 0）。

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

### 打包（冻结成 exe / 做安装器）时必踩的坑

16. **PyInstaller + 非 ASCII 路径 → Qt 插件目录被损坏成 `?`**，构建直接失败：
    `Qt plugin directory 'E:/????/PY??/????/.../PyQt5/Qt5/plugins' does not exist!`。
    这正是本项目 `main.py` 一直在运行时绕过的问题，但**构建期绕不过去**。
    解法：给源码目录建 ASCII 目录联接，**并且必须用该联接下的解释器重跑构建** ——
    PyQt5 装在源码的 `.venv` 里，只把项目路径换成 ASCII 是不够的。见 §10。
17. **`Qt5Charts.dll` 名字带 s**：Python 模块叫 `PyQt5.QtChart`，但 Qt 库文件是
    `Qt5Charts.dll`。按 `Qt5Chart.dll` 去校验产物会得到假阴性，白折腾一轮。
18. **Inno Pascal 的 `{ }` 注释不能嵌套**：注释以 `{` 开始、**遇到第一个 `}` 就结束**。
    在注释里写 `{下载根}` 这类示例会让注释提前闭合，而且报错位置指向**下一行**，极具误导性。
    实测连续踩了两次（第二次还是在"说明这条规则"的那行注释里踩的）。
19. **自动恢复必须早于 `init_db()`**：`init_db()` 会先把 `ogc_users.db` 建出来，
    「全新安装」判定立刻变假，恢复逻辑**永远不会触发**。main.py 的正确顺序是：
    日志 → 单实例 → **工作区恢复** → crash_guard → **init_db** → 存储迁移 → 工作区同步。
20. **静默卸载必须短路**：`unins000.exe /SILENT` 时 `[Code]` 里的 `MsgBox` 会卡住无人值守流程。
    用 `if UninstallSilent then Exit;` 直接返回，只删程序本体、不询问不删数据。
21. **改了源码要重建再验证**：踩过一次 —— 改完 `user_dir()` 没重建就跑端到端，
    验证到的是**旧构建**的行为（数据落点不对），白排查一轮。顺序永远是：
    改源码 → 重建 exe → 重编安装器 → 再验证。
22. **模块级路径常量不能用 `__file__` 推导**（冻结模式的隐形杀手）：
    `core/database.py` 的 `DB_PATH`/`AVATAR_DIR`、`ehviewer/db.py` 的 `DB_PATH`、
    `ehviewer/ui/reader_window.py` 的 `PROGRESS_PATH` 都曾这么写。冻结后 `__file__`
    指向 `_internal/`，于是账号库、头像、阅读进度全写进**安装目录** —— 装在
    Program Files 就是"启动即失败"，装在用户可写目录则**侥幸能跑**，实测残留过
    `_internal\data\ogc_users.db`。现在一律从 `CFG.data` 取（保持模块级变量名，
    因为 `smoke_fresh_install.py` / `smoke_concurrency_guard.py` 会 monkeypatch `db.DB_PATH`）。
    ⚠️ 这类常量在 **import 那一刻**就定死：在同一个进程里改 `sys.frozen` 再断言
    **测不出来**（假阴性）。`smoke_storage_layout.py` 因此用**子进程探针**
    （先伪造 `sys.frozen` 再 import），并已用变异测试确认它真能抓住旧写法。
23. **冻结后 pywin32 由 PyInstaller 的 `pyimod04_pywin32` 兜底**：`qframelesswindow`
    会 `import win32api`，而 `pywintypes.py` 在 `sys.frozen` 下改成"从 `sys.path` 找
    `pywintypesNNN.dll`"。PyInstaller 在引导期把 `_internal/pywin32_system32` 塞进
    `sys.path`、`os.add_dll_directory()` 与 `PATH`，所以产物必须含
    `_internal/pywin32_system32/*.dll` + `_internal/win32/*.pyd`（已确认齐全）。
    **不要**去"修" `pywintypes.py` 的冻结分支。自己写冻结探针时要手动补这一步，
    否则会得到"假导入失败"，掩盖真实结论。
24. **护栏测试必须做变异验证**：写完"应该能抓住某个 bug"的测试，就把代码临时改回旧写法
    确认它**真的失败**，再改回来。上面第 22 条的子进程探针第一次写出来时，
    断言是"不能落在安装目录下"—— 而子进程里 `__file__` 仍是真实源码路径，
    旧写法算出来的是真实项目根，**照样通过**。断言改成"必须落在 `user_dir()` 下"才抓得住。
25. **写 Qt 冒烟测试时：`QApplication` 必须留引用**。写成裸调用
    `_qapp()` 丢弃返回值 → QApplication 立刻被 GC 回收 → 之后任何 QWidget 都以
    `QWidget: Must construct a QApplication before a QWidget` **直接 abort**（不是抛异常，
    是进程级 abort，退出码 `-1073740791`）。正确写法见
    `scripts/smoke_ffmpeg_setup.py::_qapp`：模块级 `_APP` 全局持有。
26. **`MaskDialogBase` 的 parent 不能是 None**：`qfluentwidgets` 的
    `MaskDialogBase.__init__` 会做 `parent.width()` / `parent.height()`，
    传 `None` 直接 `AttributeError`。弹窗入口要先解析出真实父控件
    （页面 → 其所在窗口 → `QApplication.activeWindow()`），解析不到就**放弃弹窗并记日志**，
    绝不能让"提示用户"这件事本身把页面搞崩（参考
    `ui/widgets/ffmpeg_prompt.py::_need_dialog_parent`）。
27. **`sys.argv[0]` 推路径的"运行时"代码同样会写进安装目录**（第 22 条的姊妹坑，
    但更隐蔽 —— 第 22 条是 import 期定死的常量，这条是**调用期**算出来的）：
    `pages/music/music_player_engine.py::_get_playlist_path` 原实现是
    ``Path(sys.argv[0]).parent / 'data'``，注释还写着"使用主程序目录，而不是 CFG
    （可能有误）"。源码模式下它恰好等于项目根的 `data/`，所以**多年都没暴露**；
    冻结后 `sys.argv[0]` 是 exe，路径变成 ``<安装目录>\data\playlist.json`` ——
    装在 Program Files 时普通用户无写权限，保存播放列表**静默失败**。
    现已改为模块级 `playlist_path()`（走 `CFG.data`），并且
    `smoke_storage_layout.py` 的**冻结子进程探针**会断言它落在 `user_dir()` 下。
    同类风险点排查口诀：**任何 `sys.argv[0]` / `sys.executable` / `__file__`
    参与拼出来的可写路径，都要问一句"冻结后这指向哪"。**
28. **Pillow 的 ICO 写入器不会把图放大**：`img.save(x, format='ICO',
    sizes=[…, (256,256)])` 在源图小于 256×256 时**静默跳过** 256 那一帧，
    `.ico` 最大只剩 128×128 —— 不报错、不警告。表现是"图标明明换了，但资源管理器
    用大图标视图看是糊的"。修法：先把源图 `resize((256,256), Image.LANCZOS)`
    再交给 ICO 写入器（见 `build_exe.py::make_icon()`，它会打印实际写出的尺寸列表）。
    另一条相关：**只给窗口 `setWindowIcon` 不够**，要在 `main.py` 里
    `app.setWindowIcon(...)`，否则没有显式设图标的对话框/EhViewer 子窗口在任务栏里
    是白板图标。
29. **改图不改 `resource_rc.py` → 界面里还是旧图；而 `pyrcc5` 在非 ASCII 路径下
    「静默成功」**：`resources/resource_rc.py` 是编译产物（8 MB），登录页的
    `:/images/logo.png` 走的是它，不是文件系统里的 PNG —— 换图标必须重跑
    `pyrcc5 resources/resource.qrc -o resources/resource_rc.py`。
    更坑的是：直接在 `E:\项目程序\...` 下调 `pyrcc5` 会**返回码 1 且什么都不写、不报错**，
    看起来像"跑了但没变化"；必须经 §7 第 16 条的 ASCII 目录联接
    （`C:\ogc-src-*\.venv\Scripts\pyrcc5.exe`）才有输出。
    还有一条连带陷阱：`resource.qrc` 早先**已经过期**（3 个 `<file>` 全指向已移动/已删除的文件），
    此时"重新生成"会把 `:/images/...` 的资源名一起改掉，导致一堆界面找不到图。
    正确做法是给每条 `<file>` 加 **`alias`** 锁住资源名，例如
    `<file alias="images/logo.png">images/logo/logo.png</file>`。
    误提交了非 ASCII 路径下生成的空/半截 `resource_rc.py`，表现是登录页图标空白。

---

## 8. 提交与安全纪律

- **永远不要提交**：`data/`（数据库、`config.json`、cookie、自动登录信息）、`logs/`、`douyin_cookie.txt`、`*cookies*.json`、媒体文件（`music/`、`*.mp4`…）、`scripts/data/`、`*.zip`、`SKILL.md`。以上均已在 `.gitignore` 中；新增敏感路径要同步补进去。
- **`.gitignore` 的目录型规则一律写成 `/dirname/`（锚定仓库根）**。不加锚点会匹配任意深度的同名目录：`data/` 曾吞掉 `ehviewer/data/`，`music/` 曾吞掉 `pages/music/`，两者都从未入库。新增/修改规则后**必须**用 `git check-ignore -v <关键文件>` 验证，并跑一次 `scripts/smoke_fresh_install.py`。
- 本仓库工作树中可能残留本机产物（如 `douyin_cookie.txt`、`video.zip`、`scripts/data/`）。推送前**确认暂存范围**里没有这些，以及没有被改成 `E:\...` 绝对路径的源码。
- 远端：`https://github.com/scatti0529/OGC-OpenGenericClient.git`（以 `git remote -v` 为准）。
  GitHub 默认分支为 `main`，本地长期开发在 `master`——推送前确认目标分支，别推错。
- **本机推送要过系统代理**（`127.0.0.1:7888`，已写进该仓库局部配置 `http.proxy`）：
  直连 GitHub 会 `Recv failure: Connection was reset`。
  ⚠️ **推送的报错不可尽信**：经常出现
  `! [remote rejected] (cannot lock ref 'refs/heads/X': is at <新commit> but expected <旧commit>)`，
  但**这次推送其实已经生效**了 —— 报错里的 "is at" 就是本次要推的新提交，
  属于 CAS 校验假失败。**判断真实结果一律用
  `git ls-remote origin refs/heads/main refs/heads/master`**；
  若某个分支确实落后，重推一次即可（分支之间不会互相连带更新）。
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

---

## 10. 打包与分发（exe / 安装器 / 卸载）

### 目录：源码与产物严格分开

```
..\OGC-OpenGenericClient\        源码，**不含任何构建产物**
..\OGC-OpenGenericClient-exe\    构建工作区（不在版本控制内，见其 README-build.md）
    packaging\                   OGC.spec · installer.iss · build_exe.py · 说明文本
    build\  dist\                PyInstaller 中间产物 / 产物 + 安装器
```

`packaging/` 放在仓库外是用户的明确要求（避免产物与源码混淆）。
代价是 **clone 出来的仓库不含构建配置** —— 若要恢复可复现构建，把 `packaging/`
（几十 KB，无产物）挪回仓库即可。

### 构建

```powershell
# exe（onedir）
<源码>\.venv\Scripts\python.exe ..\OGC-OpenGenericClient-exe\packaging\build_exe.py
# 安装器
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" ..\OGC-OpenGenericClient-exe\packaging\installer.iss
```

工具链：PyInstaller 6.22.3（装在源码 `.venv`）、Inno Setup 6.7.3 +
`Languages\ChineseSimplified.isl`（含非 ASCII 的 .iss 必须存成 **UTF-8 with BOM**）。

### 产物体积与瘦身（`OGC.spec` 的 `_prune`）

| 阶段 | `dist/OGC` | 安装包 | 安装后 |
|---|---|---|---|
| 瘦身前 | 220.7 MB | 85.0 MB | 225.0 MB / 428 文件 |
| 瘦身后 | **212.3 MB** / 323 文件 | **82.9 MB** | **216.6 MB / 326 文件** |

（瘦身后这组数已含 512×512 高清图标与随之变大的 `resource_rc.py`；
换图标会让 `dist/` 与安装包各浮动约 1 MB，属正常。）

`_prune` 只剔**确定用不到**的：Qt 自带翻译（93 个 `*_qm`，只留 `*_zh_CN.qm`，4.9 MB ——
`FluentTranslator` 读的是 Qt 资源 `:/qfluentwidgets/i18n/*`，全项目没有代码加载 Qt 的翻译）、
`resources/**/__pycache__`（1.8 MB）、`qwebgl.dll`（0.46 MB）、未引用素材（1.9 MB）。
构建日志会打印省下多少，`build_exe.py::verify()` 会核对结果（翻译剩几个、有没有死重量、
被引用的素材在不在）。

> ⚠️ **刻意没动的三大块**：`opengl32sw.dll`（20 MB，Qt 软件 OpenGL 兜底 ——
> **远程桌面 / 虚拟机 / 无显卡驱动的机器靠它才能启动**）、ANGLE（约 7 MB，Qt5 在 Windows 的
> 默认 GL 后端）、`Qt5Qml.dll`+`Qt5Quick.dll`（约 8 MB）。合计约 35 MB，但删错的表现是
> "在别人的机器上启动失败"，本机验证不出来 —— 要删必须换台机器实测。

### 图标：唯一源 `resources/images/logo/icon.png`

三个地方的图标必须来自**同一张图**，否则会出现"资源管理器里是 A、任务栏里是 B"：

| 表面 | 来源 | 生效时机 |
|---|---|---|
| exe 文件图标 / 快捷方式 / 安装器 / 卸载器 | 构建期 `build_exe.make_icon()` 由 `icon.png` 生成多尺寸 `icon.ico` → `OGC.spec` 的 `icon=` → 内嵌进 `OGC.exe`；`installer.iss` 的 `SetupIconFile` 用同一个 ico | **必须重新打包** |
| 任务栏 / Alt+Tab / 所有窗口的默认图标 | `main.py` 里 `app.setWindowIcon(QIcon(APP_ICON))` | 重启程序 |
| 登录窗口 / 主窗口标题栏 | `resource_paths.LOGIN_LOGO` / `MAIN_LOGO`（= `APP_ICON`） | 重启程序 |

- 唯一常量是 `core.resource_paths.APP_ICON`。换图标就替换那一个 PNG 文件。
- ⚠️ **换了图片只重启程序是不够的**：exe 文件图标是构建期嵌进去的，不重新打包就还是旧图，
  而任务栏图标已经变成新图 —— 两边不一致，看起来像"没换成功"。
- ⚠️ **Pillow 的 ICO 写入器不会把图放大**：源图小于 256×256 时，即使请求了 256×256 也会被
  静默跳过，`.ico` 最大只有 128×128，Windows 在"大图标/超大图标"视图下只能自己拉伸 → 糊。
  `make_icon()` 因此先 LANCZOS 放大到 256 再生成全部尺寸，并在源图过小时打印提示。
  本项目源图**已是 512×512**（`icon.png` 即 512 高清图），
  构建日志会打印实际写出的尺寸列表，正常应为
  `[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]`。
- `logo/logo.png` 与 `icon.png` 是**同一张图**（字节相同、均为 512×512），保留 `logo.png` 只因为
  登录界面的 Qt 资源用的是 `:/images/logo.png`（见 `resources/resource.qrc`）。
  应用图标一律以 `APP_ICON` 为准，别再往 `logo.png` 上引。
- 校验：`build_exe.py::verify()` 会用 `ExtractIconExW(exe, -1, ...)` 数 exe 里的图标组，
  为 0 就报错（PyInstaller 遇到坏图标会静默忽略，不查就发现不了）。
- ⚠️ **改动 `icon.png` / `logo.png` 后必须重生成 Qt 资源**：登录界面的图标走的是
  `:/images/logo.png` 这条 **Qt 资源**，而不是文件系统路径，所以只换 PNG 文件不够 ——
  还得 `pyrcc5 resources/resource.qrc -o resources/resource_rc.py`，否则界面里仍是旧图
  （文件图标已新、登录页还旧，看起来像"只换了一半"）。
  ⚠️ **`pyrcc5` 在非 ASCII 路径下会静默失败**（返回码 1、不写文件、不报错），
  必须经 §7 第 16 条的 ASCII 目录联接调用：`C:\ogc-src-*\.venv\Scripts\pyrcc5.exe`。
  另外 `resource.qrc` 里的 `<file>` 必须用 **`alias`** 保持资源名不变
  （如 `<file alias="images/logo.png">images/logo/logo.png</file>`）——
  它以前是过期内容，直接"重新生成"会把 `:/images/...` 路径改掉，导致一堆界面找不到图。
  回归测试：`scripts/smoke_settings_paths.py`（校验资源常量指向的文件真实存在、
  打包图片无死素材）。

### 安装 / 卸载行为

| 项 | 行为 |
|---|---|
| 安装范围 | 仅当前用户，默认 `%LOCALAPPDATA%\Programs\OGC-OpenGenericClient`，**不弹 UAC** |
| 用户数据 | `%APPDATA%\OGC-OpenGenericClient`（由 `core/paths.user_dir()` 管理） |
| 下载内容 | 用户自选下载根目录，**安装/卸载都不主动碰** |
| 卸载 | 只删程序本体；依次询问「备份用户数据到下载根？」→「清理 `.cache`？」→「清空 `%APPDATA%` 数据？」 |
| 静默卸载 | `/SILENT` 或 `/VERYSILENT` 时 `UninstallSilent` 短路，**只删程序本体**，不询问不删数据 |
| 删除安全 | 目标不得是磁盘根目录，且必须含工作区标记（`.ogc-workspace.json`/`.ogc-portable`/`.cache`） |

程序内入口：**设置 → 维护**（工作区状态 / 打开用户数据目录 / 卸载按钮）。
「卸载」按钮**交互式**启动卸载器（不静默），让用户看到卸载器自己的询问；非安装副本时按钮隐藏。

### 端到端验证（改了路径 / 安装器 / 工作区后必跑）

两个脚本都在构建工作区里（`..\OGC-OpenGenericClient-exe\packaging\`，见其 `README-build.md`）：

| 脚本 | 覆盖 |
|---|---|
| `e2e_install.py` | 静默安装 → offscreen 启动 → 校验 `%APPDATA%` 落点与「安装目录零可写数据」→ 静默卸载只删程序本体 |
| `e2e_restore.py` | 装/跑 → 卸载 → **删掉 `%APPDATA%` 模拟全新重装** → 重装同一目录 → 断言索引被逐字节恢复、可移植配置键并回 |

两者都用 Python 传参（本机 pwsh 会把命令行里的中文路径字面量弄坏）。
实测结论：安装 **216.6 MB / 326 文件**（瘦身后）；`%APPDATA%` 落点正确；安装目录内无可写数据；
静默卸载只删程序本体；**重装同一目录后索引与配置自动恢复 ALL PASSED**。

### 工作区标记（`core/workspace.py`）

```
{下载根}/.ogc-workspace.json      版本、时间、条目清单（重装时据此认出旧工作区）
{下载根}/.ogc-portable/           运行期自动维护：索引 + **脱敏**配置，绝不含凭据
{下载根}/.ogc-portable/userdata/  仅卸载时用户选择才写入：含账号库，重装可完整恢复
```

两层设计的安全边界：**程序自己默默干的不含凭据；含账号库的那份必须用户点头**。

### 尚未验证 / 已知风险（接手时优先处理）

- **代码签名**：未签名，用户双击会看到「Windows 已保护你的电脑」。
  无法用技术绕过（自签名证书无效）；要么买证书，要么在发布说明里教用户点「仍要运行」。
- **杀软误报**：PyInstaller 产物常见误报；已刻意不用 UPX 以降低概率，但未实测各杀软。
- **真实交互式卸载未走通**：卸载时的 `MsgBox` 需要人工点击，自动化只验证了
  **静默卸载**路径（程序删除 + 数据保留）。带备份的交互式流程需要手动点一遍。
- **非 ASCII 安装路径未验证**：安装器默认目录是 ASCII，但用户可自选中文路径。
  冻结后的 Qt 是否仍受该问题影响**未实测** —— 源码模式确认受影响（见 §7 第 8、16 条）。
- **Playwright（抖音扫码登录）未打包**：它需要额外下载 Chromium（~150MB），
  冻结后必然不可用，界面上会提示缺少 playwright。
- **ffmpeg 不随包内置，改为「第一次真的需要时弹窗下载」**（用户明确要求）。
  全项目只有一处用它：给本地视频抽第一帧当封面缩略图。完整构建实测 166 MB
  （`avcodec-62.dll` 一个就 97.8 MB），内置会把安装包从 87 MB 抬到 140 MB+，
  而收益只有一个缩略图。现在的链路：
  `pages/folder_library_page.py::BatchThumbnailWorker.videos_skipped` 计数 →
  `_maybe_prompt_ffmpeg()` → `ui/widgets/ffmpeg_prompt.py::maybe_prompt_ffmpeg()`
  → 弹窗（**立即下载 / 手动指定 / 稍后** + 「我已知晓，下次不再显示」）
  → `services/ffmpeg_installer.py` 下载到 `{下载根}/ffmpeg-download/`、自动解压、
  绑定进配置 `ffmpeg_path`、打开所在文件夹。
  `services/file_library.py::find_ffmpeg()` 的查找顺序是
  **配置 `ffmpeg_path` → 内置资源 → `OGC_FFMPEG`/`FFMPEG` → 相对路径 → PATH**。
  设置页入口在「工具依赖」组。回归测试：`scripts/smoke_ffmpeg_setup.py`。
  ⚠️ 下载**刻意不做"证书校验失败就忽略"的降级** —— 那是要拿去执行的二进制，
  不能给中间人开门；TLS 失败就如实报错，让用户走手动指定那条路。
- **ffmpeg 一键下载未在本机实测走通**：本机 PATH 里已经有 ffmpeg，`find_ffmpeg()`
  会直接命中，因此弹窗与下载分支不会被触发；自动化只覆盖到"不弹窗"和"解压/绑定"
  这些可离线验证的部分。真实下载（约 40 MB）需要在一台没有 ffmpeg 的机器上点一遍。
- **升级安装未实测**：`UsePreviousAppDir=yes` 应能覆盖安装并保留 `%APPDATA%` 数据，但没跑过。
- **多用户**：数据在 `%APPDATA%`，每个 Windows 用户各有一套账号库（这是预期行为）。
