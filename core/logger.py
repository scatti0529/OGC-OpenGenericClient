# -*- coding: utf-8 -*-
"""
统一日志系统
============
提供操作日志与错误日志双通道输出，替代原 ilbs.common 中的 LogManager。

用法::

    from core.logger import logger

    logger.info('操作日志')
    logger.error('错误日志', exc_info=True)
    logger.warning('警告')
    logger.exception('异常')
"""
import logging
import sys
from datetime import datetime
from pathlib import Path


class MsFmtFormatter(logging.Formatter):
    """自定义格式化器，支持毫秒格式: 2026-07-13 10:51:27,099"""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created)
        return dt.strftime('%Y-%m-%d %H:%M:%S') + f',{record.msecs:03.0f}'


class LogManager:
    """统一的日志管理器（单例）"""

    _instance = None
    _operation_logger: logging.Logger = None
    _error_logger: logging.Logger = None
    _op_handler: logging.FileHandler = None
    _err_handler: logging.FileHandler = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def initialize(self, op_log_path=None, err_log_path=None):
        """初始化日志系统

        Args:
            op_log_path: 操作日志文件路径，默认主程序目录 logs/operation.log
            err_log_path: 错误日志文件路径，默认主程序目录 logs/error.log
        """
        if self._initialized:
            return

        base_dir = Path(sys.argv[0]).parent

        def _resolve(path, default):
            """相对路径基于主程序目录"""
            if path:
                p = Path(path)
                if not p.is_absolute():
                    p = base_dir / p
            else:
                p = default
            return p

        self._op_log_path = _resolve(op_log_path, base_dir / 'logs' / 'operation.log')
        self._err_log_path = _resolve(err_log_path, base_dir / 'logs' / 'error.log')

        # 确保目录存在
        self._op_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._err_log_path.parent.mkdir(parents=True, exist_ok=True)

        # ---------- 操作日志 ----------
        self._operation_logger = logging.getLogger('OGC_Operation')
        self._operation_logger.setLevel(logging.INFO)
        self._operation_logger.handlers.clear()

        self._op_handler = logging.FileHandler(str(self._op_log_path), encoding='utf-8', mode='a')
        self._op_handler.setLevel(logging.INFO)
        self._op_handler.setFormatter(MsFmtFormatter('%(asctime)s - %(levelname)s - %(message)s'))
        self._operation_logger.addHandler(self._op_handler)

        # ---------- 错误日志 ----------
        self._error_logger = logging.getLogger('OGC_Error')
        self._error_logger.setLevel(logging.ERROR)
        self._error_logger.handlers.clear()

        self._err_handler = logging.FileHandler(str(self._err_log_path), encoding='utf-8', mode='a')
        self._err_handler.setLevel(logging.ERROR)
        self._err_handler.setFormatter(MsFmtFormatter('%(asctime)s - %(levelname)s - %(message)s'))
        self._error_logger.addHandler(self._err_handler)

        self._initialized = True

        self.info(f'操作日志路径设置为: {self._op_log_path}')
        self.info(f'错误日志路径设置为: {self._err_log_path}')

    # ---------- 日志接口 ----------
    def info(self, message):
        if self._operation_logger:
            self._operation_logger.info(message)

    def error(self, message, exc_info=False):
        if self._error_logger:
            if exc_info:
                self._error_logger.error(message, exc_info=True)
            else:
                self._error_logger.error(message)

    def warning(self, message):
        """记录警告（同时记录到操作和错误日志）"""
        if self._operation_logger:
            self._operation_logger.warning(message)
        if self._error_logger:
            self._error_logger.warning(message)

    def exception(self, message):
        """记录异常（记录到错误日志，包含完整 traceback）"""
        if self._error_logger:
            self._error_logger.error(message, exc_info=True)

    # ---------- 路径管理 ----------
    def get_op_log_path(self):
        return str(self._op_log_path) if self._op_log_path else ""

    def get_err_log_path(self):
        return str(self._err_log_path) if self._err_log_path else ""

    def set_op_log_path(self, path):
        """动态设置操作日志路径"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if self._op_handler and self._operation_logger:
            self._operation_logger.removeHandler(self._op_handler)
            self._op_handler.close()

        self._op_log_path = path
        self._op_handler = logging.FileHandler(str(path), encoding='utf-8', mode='a')
        self._op_handler.setLevel(logging.INFO)
        self._op_handler.setFormatter(MsFmtFormatter(
            '%(asctime)s - %(levelname)s - %(message)s'))
        self._operation_logger.addHandler(self._op_handler)

        self.info(f'日志路径设置为: {path}')

    def set_err_log_path(self, path):
        """动态设置错误日志路径"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if self._err_handler and self._error_logger:
            self._error_logger.removeHandler(self._err_handler)
            self._err_handler.close()

        self._err_log_path = path
        self._err_handler = logging.FileHandler(str(path), encoding='utf-8', mode='a')
        self._err_handler.setLevel(logging.ERROR)
        self._err_handler.setFormatter(MsFmtFormatter(
            '%(asctime)s - %(levelname)s - %(message)s'))
        self._error_logger.addHandler(self._err_handler)

        self.info(f'错误日志路径设置为: {path}')


# 全局日志管理实例
logger = LogManager()