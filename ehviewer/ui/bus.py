# -*- coding: utf-8 -*-
"""全局信号总线：跨页面通信（避免循环 import）"""
from PyQt5.QtCore import QObject, pyqtSignal


class Bus(QObject):
    # 收藏状态变化（gid, 是否收藏）
    favoriteChanged = pyqtSignal(int, bool)
    # 下载列表变化（触发下载页刷新）
    downloadsChanged = pyqtSignal()
    # 下载进度（gid, finished, total, 状态文案）
    downloadProgress = pyqtSignal(int, int, int, float)   # gid, finished, total, speed
    # 历史记录变化
    historyChanged = pyqtSignal()
    # 登录状态变化（是否已登录）
    loginChanged = pyqtSignal(bool)
    # 配置变化
    configChanged = pyqtSignal(str)
    # 打开画廊详情（GalleryInfo）
    openDetail = pyqtSignal(object)
    # 打开阅读器（gid, 起始页码）
    openReader = pyqtSignal(object, int)
    # 发起搜索（关键词，模式）
    doSearch = pyqtSignal(str, int)
    # 导航到页面
    navigate = pyqtSignal(str)
    # 提示信息（level: info/success/warning/error, content）
    notify = pyqtSignal(str, str)
    # 缩略图请求（key, url）—— 由列表页卡片监听，加载完成后 set_cover_pixmap
    thumbLoaded = pyqtSignal(str, object)


bus = Bus()
