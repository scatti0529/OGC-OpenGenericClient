# -*- coding: utf-8 -*-
"""应用全局上下文：图片加载器 / 下载管理器 / 会话工厂（启动时注入）"""


class AppContext(object):
    def __init__(self):
        self.image_loader = None      # ImageLoader
        self.download_manager = None  # DownloadManager
        self.main_window = None       # MainWindow
        self.session_factory = None   # callable -> requests.Session

    def notify(self, level, content):
        """通过主窗口显示 InfoBar"""
        if self.main_window is not None:
            try:
                self.main_window.show_notify(level, content)
            except Exception:
                pass


ctx = AppContext()
