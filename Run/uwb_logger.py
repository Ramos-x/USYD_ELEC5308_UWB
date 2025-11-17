"""
UWB系统日志模块
提供统一的日志配置和管理功能
"""

import logging
import logging.handlers
import os
import sys
from typing import Optional
from datetime import datetime


class UWBLogger:
    """UWB系统日志管理器"""

    # 日志级别映射
    LEVEL_MAP = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }

    def __init__(
        self,
        name: str = 'uwb_system',
        log_file: Optional[str] = None,
        level: str = 'INFO',
        console_output: bool = True,
        file_output: bool = True,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5
    ):
        """
        初始化日志管理器

        Args:
            name: 日志记录器名称
            log_file: 日志文件路径，默认为logs/uwb_YYYYMMDD.log
            level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
            console_output: 是否输出到控制台
            file_output: 是否输出到文件
            max_bytes: 单个日志文件最大字节数
            backup_count: 保留的备份日志文件数量
        """
        self.name = name
        self.level = self.LEVEL_MAP.get(level.upper(), logging.INFO)
        self.console_output = console_output
        self.file_output = file_output

        # 设置日志文件路径
        if log_file is None and file_output:
            log_dir = 'logs'
            os.makedirs(log_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d')
            log_file = os.path.join(log_dir, f'uwb_{timestamp}.log')

        self.log_file = log_file
        self.max_bytes = max_bytes
        self.backup_count = backup_count

        # 创建日志记录器
        self.logger = logging.getLogger(name)
        self.logger.setLevel(self.level)
        self.logger.handlers.clear()  # 清除已有处理器

        # 设置日志格式
        self._setup_handlers()

    def _setup_handlers(self):
        """设置日志处理器"""
        # 详细格式（用于文件）
        detailed_formatter = logging.Formatter(
            '[%(asctime)s] [%(name)s] [%(levelname)s] '
            '[%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 简洁格式（用于控制台）
        console_formatter = logging.Formatter(
            '[%(levelname)s] %(message)s'
        )

        # 控制台处理器
        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self.level)
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)

        # 文件处理器（使用RotatingFileHandler自动轮转）
        if self.file_output and self.log_file:
            try:
                file_handler = logging.handlers.RotatingFileHandler(
                    self.log_file,
                    maxBytes=self.max_bytes,
                    backupCount=self.backup_count,
                    encoding='utf-8'
                )
                file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
                file_handler.setFormatter(detailed_formatter)
                self.logger.addHandler(file_handler)
            except Exception as e:
                print(f"警告: 无法创建日志文件 {self.log_file}: {e}")

    def get_logger(self) -> logging.Logger:
        """
        获取日志记录器实例

        Returns:
            logging.Logger实例
        """
        return self.logger

    def set_level(self, level: str):
        """
        设置日志级别

        Args:
            level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        """
        new_level = self.LEVEL_MAP.get(level.upper(), logging.INFO)
        self.logger.setLevel(new_level)
        self.level = new_level


# 全局日志管理器
_global_logger = None


def setup_logging(
    name: str = 'uwb_system',
    log_file: Optional[str] = None,
    level: str = 'INFO',
    console_output: bool = True,
    file_output: bool = True
) -> logging.Logger:
    """
    设置全局日志系统

    Args:
        name: 日志记录器名称
        log_file: 日志文件路径
        level: 日志级别
        console_output: 是否输出到控制台
        file_output: 是否输出到文件

    Returns:
        logging.Logger实例
    """
    global _global_logger
    _global_logger = UWBLogger(
        name=name,
        log_file=log_file,
        level=level,
        console_output=console_output,
        file_output=file_output
    )
    return _global_logger.get_logger()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取日志记录器

    Args:
        name: 日志记录器名称，如果为None则使用全局日志记录器

    Returns:
        logging.Logger实例
    """
    global _global_logger

    if name is None:
        # 返回全局日志记录器
        if _global_logger is None:
            _global_logger = UWBLogger()
        return _global_logger.get_logger()
    else:
        # 返回指定名称的日志记录器
        return logging.getLogger(name)


# 便捷函数
def debug(msg: str, *args, **kwargs):
    """记录DEBUG级别日志"""
    get_logger().debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs):
    """记录INFO级别日志"""
    get_logger().info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    """记录WARNING级别日志"""
    get_logger().warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    """记录ERROR级别日志"""
    get_logger().error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs):
    """记录CRITICAL级别日志"""
    get_logger().critical(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs):
    """记录异常信息（包含堆栈跟踪）"""
    get_logger().exception(msg, *args, **kwargs)
