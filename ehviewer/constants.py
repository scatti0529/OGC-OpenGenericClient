# -*- coding: utf-8 -*-
"""
全局常量与中文文案映射
对应 Android 版 EhConfig / EhUtils / ListUrlBuilder 中的常量
"""
import sys

APP_NAME = "EhViewer PC"
APP_VERSION = "1.0.0"
APP_ORG = "EhViewer"

# ---------- 站点 ----------
SITE_E = 0   # 表站 e-hentai.org
SITE_EX = 1  # 里站 exhentai.org
SITE_NAMES = {SITE_E: "表站 (e-hentai.org)", SITE_EX: "里站 (exhentai.org)"}

# ---------- 分类（位掩码，与 EhConfig 一致） ----------
CAT_MISC = 0x1
CAT_DOUJINSHI = 0x2
CAT_MANGA = 0x4
CAT_ARTIST_CG = 0x8
CAT_GAME_CG = 0x10
CAT_IMAGE_SET = 0x20
CAT_COSPLAY = 0x40
CAT_ASIAN_PORN = 0x80
CAT_NON_H = 0x100
CAT_WESTERN = 0x200
ALL_CATEGORY = 0x3FF
UNKNOWN_CATEGORY = 0x400
NONE = -1

CATEGORY_VALUES = [CAT_MISC, CAT_DOUJINSHI, CAT_MANGA, CAT_ARTIST_CG, CAT_GAME_CG,
                   CAT_IMAGE_SET, CAT_COSPLAY, CAT_ASIAN_PORN, CAT_NON_H, CAT_WESTERN]

CATEGORY_NAMES = {
    CAT_MISC: "其他", CAT_DOUJINSHI: "同人志", CAT_MANGA: "漫画", CAT_ARTIST_CG: "画师CG",
    CAT_GAME_CG: "游戏CG", CAT_IMAGE_SET: "图集", CAT_COSPLAY: "Cosplay",
    CAT_ASIAN_PORN: "亚洲色情", CAT_NON_H: "非H", CAT_WESTERN: "欧美",
}
CATEGORY_COLORS = {
    CAT_MISC: "#F06292", CAT_DOUJINSHI: "#F44336", CAT_MANGA: "#FF9800",
    CAT_ARTIST_CG: "#FFBC2D", CAT_GAME_CG: "#4CAF50", CAT_IMAGE_SET: "#3F51B5",
    CAT_COSPLAY: "#9C27B0", CAT_ASIAN_PORN: "#9575CD", CAT_NON_H: "#2196F3",
    CAT_WESTERN: "#8BC34A",
}

def get_category_name(cat):
    return CATEGORY_NAMES.get(cat, "未知")

def get_category_color(cat):
    return CATEGORY_COLORS.get(cat, "#000000")

# ---------- 列表模式（ListUrlBuilder） ----------
MODE_NORMAL = 0x0
MODE_UPLOADER = 0x1
MODE_TAG = 0x2
MODE_WHATS_HOT = 0x3
MODE_IMAGE_SEARCH = 0x4
MODE_SUBSCRIPTION = 0x5
MODE_FILTER = 0x6
MODE_TOP_LIST = 0x7

# ---------- 高级搜索掩码（AdvanceSearchTable） ----------
SNAME = 0x1
STAGS = 0x2
SDESC = 0x4
STORR = 0x8
STO = 0x10
SDT1 = 0x20
SDT2 = 0x40
SH = 0x80
SFL = 0x100
SFU = 0x200
SFT = 0x400
DEFAULT_ADVANCE = SNAME | STAGS

# ---------- 下载状态（DownloadInfo） ----------
STATE_INVALID = -1
STATE_NONE = 0
STATE_WAIT = 1
STATE_DOWNLOAD = 2
STATE_FINISH = 3
STATE_FAILED = 4
STATE_UPDATE = 5

STATE_NAMES = {
    STATE_NONE: "无状态", STATE_WAIT: "等待中", STATE_DOWNLOAD: "下载中",
    STATE_FINISH: "已完成", STATE_FAILED: "下载失败", STATE_UPDATE: "待更新",
}

# ---------- 图片分辨率（EhConfig） ----------
IMAGE_SIZE_AUTO = "a"
IMAGE_SIZE_780 = "780"
IMAGE_SIZE_980 = "980"
IMAGE_SIZE_1280 = "1280"
IMAGE_SIZE_1600 = "1600"
IMAGE_SIZE_2400 = "2400"
IMAGE_SIZE_NAMES = {
    IMAGE_SIZE_AUTO: "自动", IMAGE_SIZE_780: "780x", IMAGE_SIZE_980: "980x",
    IMAGE_SIZE_1280: "1280x", IMAGE_SIZE_1600: "1600x", IMAGE_SIZE_2400: "2400x",
}

# ---------- 下载类型（archiver） ----------
ARCHIVER_DOWNLOAD_ORIGINAL = "0"   # 原图
ARCHIVER_DOWNLOAD_RESIZED = "1"    # 压缩图

# ---------- 收藏 ----------
FAVORITE_CAT_COUNT = 10
FAVORITE_CAT_NAMES = ["收藏夹 0", "收藏夹 1", "收藏夹 2", "收藏夹 3", "收藏夹 4",
                      "收藏夹 5", "收藏夹 6", "收藏夹 7", "收藏夹 8", "收藏夹 9"]
DEFAULT_FAVORITE_CAT = 0

# ---------- 时间 / 文本 ----------
def format_size(num_bytes):
    """将字节数格式化为人类可读字符串"""
    try:
        num = float(num_bytes)
    except (TypeError, ValueError):
        return "未知"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return "%.1f %s" % (num, unit) if unit != "B" else "%d B" % int(num)
        num /= 1024.0
    return ""

def format_speed(bytes_per_sec):
    return format_size(bytes_per_sec) + "/秒"

def format_count(n):
    return "未知" if n is None else str(n)

# 语言标签（GalleryInfo）
LANG_TAGS = ["language:english", "language:chinese", "language:spanish", "language:korean",
             "language:russian", "language:french", "language:portuguese", "language:thai",
             "language:german", "language:italian", "language:vietnamese", "language:polish",
             "language:hungarian", "language:dutch"]
LANG_NAMES = ["英语", "中文", "西班牙语", "韩语", "俄语", "法语", "葡萄牙语", "泰语",
              "德语", "意大利语", "越南语", "波兰语", "匈牙利语", "荷兰语"]
LANG_TITLE_PATTERNS = [
    (r"[([]eng(?:lish)?[)\]]|英訳", "英语"),
    (r"[(\uFF08\[]ch(?:inese)?[)\uFF09\]]|[汉漢]化|中[国國][语語]|中文|中国翻訳", "中文"),
    (r"[([]spanish[)\]]|[([]Español[)\]]|スペイン翻訳", "西班牙语"),
    (r"[([]korean?[)\]]|韓国翻訳", "韩语"),
    (r"[([]rus(?:sian)?[)\]]|ロシア翻訳", "俄语"),
    (r"[([]fr(?:ench)?[)\]]|フランス翻訳", "法语"),
    (r"[([]portuguese|ポルトガル翻訳", "葡萄牙语"),
    (r"[([]thai(?: ภาษาไทย)?[)\]]|แปลไทย|タイ翻訳", "泰语"),
    (r"[([]german[)\]]|ドイツ翻訳", "德语"),
    (r"[([]italiano?[)\]]|イタリア翻訳", "意大利语"),
    (r"[([]vietnamese(?: Tiếng Việt)?[)\]]|ベトナム翻訳", "越南语"),
    (r"[([]polish[)\]]|ポーランド翻訳", "波兰语"),
    (r"[([]hun(?:garian)?[)\]]|ハンガリー翻訳", "匈牙利语"),
    (r"[([]dutch[)\]]|オランダ翻訳", "荷兰语"),
]

def ensure_unicode(s):
    if isinstance(s, bytes):
        return s.decode("utf-8", "replace")
    return s
