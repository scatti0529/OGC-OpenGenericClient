# OGC - Open Generic Client

> 练手之作 🧑💻

一个基于 **PyQt5 + PyQt-Fluent-Widgets** 的现代化桌面客户端，集成多平台媒体下载、音乐播放、用户管理与权限控制等功能。

## ✨ 功能特性

### 🎵 音乐模块
- 网易云音乐**在线搜索**（歌曲、歌词）
- **歌单链接解析**（一键解析整张歌单）
- 多音质下载（含 Hi-Res / 无损 / 高品 / 标准）
- 内置播放器（底部播放栏 + 播放页面）
- 本地音乐库管理

### 🎬 视频模块（多平台）
| 平台 | 支持内容 |
|------|---------|
| 抖音 | 视频/图集下载、多清晰度选择、用户主页批量解析、二维码扫码登录获取 Cookie |
| 哔哩哔哩 | 多 P 视频（分 P 下载、画质选择、音视频合并） |
| 推特/X | 视频/图片下载 |
| Pixiv | 插画/动图下载 |
| Xvideo | 视频下载（M3U8 解析） |
| YouTube | 视频多画质下载 |

**抖音模块特性（移植自 douyin_parse-master v2.0.4）：**
- 🔏 **A-Bogus / X-Bogus 双通道签名**（自动选择可用通道，需 `gmssl` 依赖）
- 🎴 **卡片式结果区**（封面预览异步加载、清晰度/图集预览）
- 🔗 **多链接并发解析**（最大并发 2，队列管理）+ 用户主页批量抓取
- 🎚️ **多清晰度下载**（1080p / 720p / 540p / 480p / 360p，自动选择最高画质）
- 🖼️ **图集下载**（含 Live 动图 / GIF，自动归类 `images/`）
- 📋 **Cookie 管理**（手动粘贴 / 二维码扫码登录，保存至 `douyin_cookie.txt`）
- 📊 **下载队列与断点状态**（完成/失败自动续下一个，进度入库 `douyin_downloads`）

**下载引擎特性：**
- 🚀 自适应下载模式（自动选择最优方案）
  - 多线程分块并行下载（断点续传）
  - 流式下载
  - HLS（M3U8）分片下载
- 🧠 智能文件名清洗与冲突避让
- 📊 实时下载进度显示

### 👥 用户系统与权限
- 注册 / 登录（头像自定义）
- 用户资料管理（修改昵称、密码、头像）
- **模块级 + 功能级权限控制**（每个用户可单独配置可用模块与功能）
- 管理员专属**仪表盘**（用户管理、封禁、系统使用统计）

### 🎨 现代化 UI
- Fluent Design 风格（微软 Fluent 设计语言）
- 全局**磨砂玻璃效果**（透明度 / 模糊度可调）
- 亮色 / 暗色主题一键切换
- 多语言支持（简体中文 / 繁体中文）
- 无边框窗口 + 导航栏自适应宽度

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
> ⚠️ **注意**：首次运行会自动创建 `data/` 目录（用户数据库、配置）。`data/` 目录包含本地敏感配置（如 Cookie），已在 `.gitignore` 中排除，请勿提交到仓库。

## 🛠️ 技术栈

| 类别 | 技术 |
|------|------|
| UI 框架 | PyQt5 / PyQt-Fluent-Widgets |
| 窗口框架 | qframeless-window（无边框 + 磨砂） |
| 网络请求 | httpx / requests / aiofiles |
| 网页解析 | beautifulsoup4 |
| 数据存储 | SQLite（内置 `sqlite3`） |
| 媒体处理 | ffmpeg（音视频合并，可选） |
| 抖音签名 | gmssl（A-Bogus / X-Bogus 生成） |

## 📂 项目结构

```
OGC-OpenGenericClient/
├── main.py                     # 启动入口（登录窗口 → 主窗口）
├── requirements.txt            # 依赖清单
├── core/                       # 核心模块
│   ├── config.py               # 配置管理
│   ├── database.py             # 用户/权限/歌单/统计（SQLite）
│   ├── logger.py               # 日志系统
│   └── resource_paths.py       # 资源路径统一管理
├── ui/                         # UI 层
│   ├── login_window.py         # 登录/注册窗口
│   ├── main_window.py          # 主窗口（导航 + 权限控制）
│   └── widgets/                # 通用组件（磨砂玻璃、主题等）
├── pages/                      # 功能页面
│   ├── home_page.py            # 首页
│   ├── music/                  # 音乐模块（搜索/歌单/播放器）
│   ├── video/                  # 视频模块（多平台，含抖音、JMComic）
│   ├── jmcomic_page.py         # 漫画下载页（JMComic）
│   ├── about_page.py           # 关于我（个人资料）
│   ├── dashboard_page.py       # 仪表盘（管理员）
│   └── settings_page.py        # 设置页
├── services/                   # 业务服务层
│   ├── download_manager.py     # 自适应下载引擎
│   ├── downloader.py           # 下载线程封装
│   ├── netease_music.py        # 网易云音乐 API
│   ├── douyin_parser.py        # 抖音解析核心（A-Bogus / X-Bogus 签名）
│   ├── douyin/                 # 抖音签名算法库（abogus / xbogus）
│   └── platform_parsers.py     # 多平台链接解析
├── resources/                  # 资源文件（图标/字体/翻译/样式）
└── scripts/                    # 开发/测试脚本
```

## 🔐 权限说明

程序内置管理员账号 **`admin`**（注册时默认创建），拥有全部权限，可访问**仪表盘**进行用户管理。普通用户在注册后默认拥有全部模块权限，管理员可在仪表盘中为每个用户单独配置：

- **模块权限**：首页 / 音乐 / 视频 / 人物 / 关于我 / 设置 / 仪表盘
- **功能权限**：音乐搜索 / 歌单解析 / 音乐下载 / 播放器、各视频平台开关、JMComic 搜索/下载/账号/订阅等

## 📝 免责声明

本项目仅用于个人学习与练习目的。请遵守各平台的服务条款及相关法律法规，**请勿将本工具用于商业用途或恶意抓取**。下载的内容请于当地法律允许范围内使用。

## ❤️ 致谢

- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) - Fluent 风格 UI 组件库
- 所有开源贡献者

---

*练手之作，如有 Bug 欢迎提 Issue 🙏*
