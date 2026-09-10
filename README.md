# OGC - Open Generic Client

> 练手之作 🧑‍💻

一个基于 **PyQt5 + PyQt-Fluent-Widgets** 的现代化桌面客户端，集成多平台媒体下载、漫画画册、音乐播放、邮件收发、本地文件库、用户管理与权限控制等功能。

## ✨ 功能特性

### 🎵 音乐模块
- 网易云音乐**在线搜索**（歌曲、歌词）
- **歌单链接解析**（一键解析整张歌单）
- 多音质下载（含 Hi-Res / 无损 / 高品 / 标准）
- 内置播放器（底部播放栏 + 独立播放页面 + 播放引擎）
- **播放列表管理器**（TreeView 管理多个播放列表）
- 本地音乐库管理

### 🎬 视频模块（多平台）
| 平台 | 支持内容 |
|------|---------|
| 抖音 | 视频/图集下载、多清晰度选择、用户主页批量解析、二维码扫码登录获取 Cookie、**作者订阅与更新检查** |
| 哔哩哔哩 | 多 P 视频（分 P 下载、画质选择、音视频合并） |
| 推特/X | 视频/图片下载（savetwitter.net 主解析 + gallery-dl 备用解析） |
| Pixiv | 插画/动图下载（OAuth 登录、排行榜、关注流） |
| Xvideo | 视频下载（M3U8 解析） |
| YouTube(失效) | 视频多画质下载 |

**抖音模块特性（移植自 douyin_parse-master v2.0.4）：**
- 🔏 **A-Bogus / X-Bogus 双通道签名**（自动选择可用通道，需 `gmssl` 依赖）
- 🎴 **卡片式结果区**（封面预览异步加载、清晰度/图集预览）
- 🔗 **多链接并发解析**（最大并发 2，队列管理）+ 用户主页批量抓取
- 🎚️ **多清晰度下载**（1080p / 720p / 540p / 480p / 360p，自动选择最高画质）
- 🖼️ **图集下载**（含 Live 动图 / GIF，自动归类 `images/`）
- 📋 **Cookie 管理**（手动粘贴 / 二维码扫码登录，保存至 `douyin_cookie.txt`）
- 📊 **下载队列与断点状态**（完成/失败自动续下一个，进度入库 `douyin_downloads`）
- ❤️ **作者订阅页**（头像/昵称/作品数/是否有更新，支持批量检查更新）

**视频通用能力：**
- 🪟 **迷你下载窗口**：置顶小窗，多链接（回车/逗号/空格分隔）粘贴即下载，不生成卡片
- 📂 **离线/在线媒体查看器**：侧栏列出 `{下载根}/{platform}-download` 下已下载的图片/视频，支持排序、查看、播放与删除

**下载引擎特性：**
- 🚀 自适应下载模式（自动选择最优方案）
  - 多线程分块并行下载（断点续传）
  - 流式下载
  - HLS（M3U8）分片下载
- 🧠 智能文件名清洗与冲突避让
- 📊 实时下载进度显示

### 📚 画册模块（漫画/画廊）
以「画册」为父级导航，下含三个子模块，均可切换：

| 子模块 | 说明 |
|--------|------|
| 拷贝漫画 | 首页 / 发现 / 排行榜 / 个人中心 / 设置五合一，详情页支持**按章节下载**，并带**离线阅读**标签页 |
| E-Hentai | 下载画廊 / 我的收藏 / 设置三合一；完整移植 EhViewer 核心（API 引擎、解析器、下载管理器、图片缓存、阅读器、标签翻译），支持**离线阅读**与收藏同步 |
| JMComic | 搜索 / 详情 / 收藏夹 / 下载 / 账号（含自动重登）/ 订阅，内置漫画阅读器 |

- 🧭 **通用本地漫画库**：自动识别「含章节层」与「扁平」两种目录形态，生成**离线索引 JSON**（秒开），下载完成后自动失效重建
- 📖 **离线阅读器**：翻页 / 分页 / 高度自适应，支持压缩包与文件夹两种来源

### 📧 邮箱模块
- 原生 **IMAP / SMTP** 客户端，Roundcube 式三栏布局（文件夹 / 邮件列表 / 阅读窗格）
- 多账号管理，自动推断常见邮箱服务商服务器地址
- 写邮件 / 回复 / 删除 / 附件，未读数统计
- 所有网络操作在 `QThread` 后台线程执行，界面不卡顿

### 🗂️ 本地文件库（Folder Library）
- 浏览配置的下载根目录，跨平台文件检索与展示
- 目录 / 图片 / 视频 / 音频 / 压缩包 / 文本分类
- 封面异步加载、文本阅读、视频/音乐播放、图片/漫画浏览
- 目录扫描异步化，大文件夹不再卡顿；下载目录变更后自动切换

### 👥 用户系统与权限
- 注册 / 登录（头像自定义）、**记住密码**、**多账号自动登录**
- 用户资料管理（修改昵称、密码、头像）
- **模块级 + 功能级权限控制**（每个用户可单独配置可用模块与功能）
- 管理员专属**仪表盘**（用户管理、封禁、系统使用统计）

### 🎨 现代化 UI
- Fluent Design 风格（微软 Fluent 设计语言）
- 全局**磨砂玻璃效果**（透明度 / 模糊度可调）
- 亮色 / 暗色主题一键切换
- 多语言支持（简体中文 / 繁体中文）
- 无边框窗口 + 导航栏自适应宽度
- ⚡ **首屏加速**：首页公告/更新/关于内容延迟到窗口显示后再填充

### 🛡️ 稳定性与兼容处理
- **全局线程看门狗**（`core/thread_guard.py`）：拦截所有 `QThread.start`，退出前统一 `requestInterruption + wait`，消除 `QThread: Destroyed while thread is still running` 闪退
- **InfoBar 动画补丁**：修复 qfluentwidgets `dropAni` 缺少 start/end value 的 Qt 警告
- **动画警告过滤器**：静默动画目标已销毁等无害刷屏警告
- **中文路径兼容**：`main.py` 在导入 Qt 前自动注入 `QT_QPA_PLATFORM_PLUGIN_PATH`，解决含中文路径时 PyQt5 找不到平台插件的问题

## 📦 环境要求

- Python **3.10+**（开发环境为 3.12）
- Windows 10/11（优先支持）

## 🚀 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/scatti0529/OGC-OpenGenericClient.git
cd OGC-OpenGenericClient

# 2. 创建并激活虚拟环境（推荐）
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动程序
# Windows（使用项目虚拟环境）:
.venv\Scripts\python.exe main.py
# 或激活虚拟环境后:
python main.py
```

> ⚠️ **注意**：程序运行于独立虚拟环境 `.venv/`，请勿在全局环境安装 PyQt6 / PySide6 系列的 Fluent Widgets、qframelesswindow 等包，否则会与 PyQt5 版本混用导致 `qfluentwidgets` 包目录被覆盖，引发 `installTranslator` 类型错误 / `QWidget: Must construct a QApplication` 等异常。
>
> ⚠️ **注意**：项目路径含中文时 PyQt5 无法自动定位平台插件，`main.py` 已在导入 Qt 前自动注入 `QT_QPA_PLATFORM_PLUGIN_PATH` 环境变量解决此问题。
>
> ⚠️ **注意**：首次运行会自动创建 `data/` 目录（用户数据库、配置）。`data/` 目录包含本地敏感配置（Cookie、账号、自动登录信息），已在 `.gitignore` 中排除，请勿提交到仓库。

### 🔧 可选环境变量

部分功能依赖**外置项目 / 外置工具**，通过环境变量指定位置；未配置时程序会自动尝试相对路径，找不到则优雅降级（功能不可用但不影响主程序）：

| 环境变量 | 用途 | 默认查找位置 |
|----------|------|--------------|
| `GALLERY_DL_TWITTER_DIR` | 推特备用解析所用的 gallery-dl 目录 | 本项目同级 `twitter/`、`gallery-dl/`，或本项目内 `twitter/` |
| `DOUYINDL_SRC_DIR` | 抖音导入自检脚本所用的 `douyinDL-main/src` | 本项目同级 `../douyinDL-main/src` |

## 🛠️ 技术栈

| 类别 | 技术 |
|------|------|
| UI 框架 | PyQt5 / PyQt-Fluent-Widgets |
| 窗口框架 | qframeless-window（无边框 + 磨砂） |
| 网络请求 | httpx / requests / aiofiles |
| 网页解析 | beautifulsoup4 |
| 数据存储 | SQLite（内置 `sqlite3`） |
| 邮件协议 | imaplib / smtplib / email（标准库） |
| 媒体处理 | ffmpeg（音视频合并，可选） |
| 漫画下载 | jmcomic / pymupdf / pyzipper |
| 抖音签名 | gmssl（A-Bogus / X-Bogus 生成） |
| Pixiv | pixivpy3 |
| 抖音爬虫内核 | f2 |

## 📂 项目结构

```
OGC-OpenGenericClient/
├── main.py                     # 启动入口（登录窗口 → 主窗口）
├── requirements.txt            # 依赖清单
├── core/                       # 核心模块
│   ├── config.py               # 配置管理
│   ├── database.py             # 用户/权限/歌单/统计（SQLite）
│   ├── auto_login.py           # 多账号自动登录（data/config.json）
│   ├── thread_guard.py         # 全局线程看门狗（退出安全回收）
│   ├── logger.py               # 日志系统
│   └── resource_paths.py       # 资源路径统一管理
├── ui/                         # UI 层
│   ├── login_window.py         # 登录/注册窗口（含记住密码）
│   ├── main_window.py          # 主窗口（导航 + 权限控制）
│   └── widgets/                # 通用组件（磨砂玻璃、主题等）
├── pages/                      # 功能页面
│   ├── home_page.py            # 首页（延迟填充，首屏加速）
│   ├── music/                  # 音乐（搜索/歌单/播放器/播放列表管理）
│   ├── video/                  # 视频多平台（抖音/订阅/哔哩哔哩/推特/Pixiv/Xvideo/YouTube）
│   │   ├── video_multiplatform_page.py
│   │   ├── douyin_page.py      # 抖音
│   │   ├── douyin_subscription_page.py
│   │   ├── pixiv_page.py / pixiv_page_ui.py / pixiv_dialogs.py
│   │   ├── video_mini_window.py    # 迷你下载窗口（复用）
│   │   └── media_offline.py        # 离线/在线媒体查看器（复用）
│   ├── album/                  # 画册（拷贝漫画 / E-Hentai / JMComic）
│   │   ├── album_interface.py
│   │   ├── easycopy_*          # 拷贝漫画（页面/详情/离线/阅读器/标签页/组件）
│   │   ├── ehentai_*           # E-Hentai（桥接/嵌入/收藏/设置/同步/阅读器/封面/预览）
│   │   ├── jmcomic_reader.py
│   │   └── comic_offline.py    # 通用离线漫画阅读
│   ├── email/                  # 邮箱（账号管理/写邮件/主页面/后台工作线程）
│   ├── folder_library_page.py  # 本地文件库
│   ├── jmcomic_page.py         # JMComic 主页面
│   ├── about_page.py           # 关于我（个人资料）
│   ├── dashboard_page.py       # 仪表盘（管理员）
│   └── settings_page.py        # 设置页
├── services/                   # 业务服务层
│   ├── download_manager.py     # 自适应下载引擎
│   ├── downloader.py           # 下载线程封装
│   ├── netease_music.py        # 网易云音乐 API
│   ├── douyin_parser.py        # 抖音解析核心（A-Bogus / X-Bogus 签名）
│   ├── douyin_service.py       # 抖音解析/下载服务
│   ├── douyin_subscription.py  # 抖音作者订阅
│   ├── douyin/                 # 抖音签名算法库（abogus / xbogus）
│   ├── easycopy/               # 拷贝漫画服务（api/app/config/downloader/parser/…）
│   ├── ehentai_downloader.py   # E-Hentai 画廊下载核心
│   ├── comic_library.py        # 通用本地漫画库扫描 + 离线索引
│   ├── file_library.py         # 下载文件库扫描
│   ├── email_service.py        # IMAP/SMTP 邮件服务
│   ├── jmcomic_service.py      # JMComic 服务
│   ├── pixiv_service.py        # Pixiv 服务
│   ├── twitter_service.py      # 推特解析（savetwitter + gallery-dl 备用）
│   ├── xvideo_service.py / bilibili_service.py / youtube_service.py
│   └── platform_parsers.py     # 多平台链接解析
├── ehviewer/                   # EhViewer 核心移植（无 GUI 依赖层 + Qt 界面层）
│   ├── engine.py / parsers.py / session.py / db.py / models.py
│   ├── downloader.py / image_cache.py / config.py / urls.py
│   ├── tag_translation.py + data/tag_translations.json.gz
│   └── ui/                     # 画廊列表/详情/阅读器/收藏/历史/下载/搜索等
├── resources/                  # 资源文件（图标/字体/翻译/样式）
│   ├── config/config.json      # 应用默认配置（路径/主题/下载）
│   ├── i18n/ fonts/ images/ qss/
└── scripts/                    # 开发/测试脚本（smoke_* / verify_*）
```

## 🔐 权限说明

程序内置管理员账号 **`admin`**（注册时默认创建），拥有全部权限，可访问**仪表盘**进行用户管理。普通用户在注册后默认拥有全部模块权限，管理员可在仪表盘中为每个用户单独配置：

- **模块权限**：首页 / 音乐 / 视频 / 画册 / 邮箱 / 本地文件 / 关于我 / 设置 / 仪表盘
- **功能权限**：音乐搜索 / 歌单解析 / 音乐下载 / 播放器、各视频平台开关、JMComic / 拷贝漫画 / E-Hentai 的搜索、下载、账号、订阅等

## 🔒 隐私与安全说明

本仓库**不包含**任何个人凭据与运行期数据，以下内容均在 `.gitignore` 中排除：

- `data/`（用户数据库 `*.db`、`data/config.json` 中的邮箱账号、自动登录信息）
- Cookie 类文件（`douyin_cookie.txt`、`*cookies*.json` 等）
- 日志（`logs/`、`*.log`）
- 下载内容与媒体文件（`music/`、`*.mp4`、`*.mp3` …）

请勿将上述文件提交到公开仓库。若不慎提交，请立即在各平台**吊销 / 重新登录**对应账号并清理 Git 历史。

## 📝 免责声明

本项目仅用于个人学习与练习目的。请遵守各平台的服务条款及相关法律法规，**请勿将本工具用于商业用途或恶意抓取**。下载的内容请于当地法律允许范围内使用。

## ❤️ 致谢

- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) - Fluent 风格 UI 组件库
- [EhViewer](https://github.com/seven332/EhViewer) - E-Hentai 客户端，本项目 `ehviewer/` 的移植来源
- [JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python) - JMComic 下载内核
- [douyin_parse](https://github.com/ihmily/douyin_parse) 系列 - 抖音解析架构参考
- 所有开源贡献者

---

*练手之作，如有 Bug 欢迎提 Issue 🙏*
