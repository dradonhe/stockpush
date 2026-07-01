"""
日志管理器模块
负责全局日志管理和记录
"""
import logging
import sys
from pathlib import Path
from typing import Optional


class LogManager:
    """日志管理器
    
    提供全局日志配置和获取功能
    """
    
    _initialized = False
    _logger: Optional[logging.Logger] = None
    
    @classmethod
    def setup(cls, log_level: str = "INFO", log_file: Optional[str] = None) -> None:
        """设置日志配置
        
        Args:
            log_level: 日志级别
            log_file: 日志文件路径（可选）
        """
        if cls._initialized:
            return
        
        # 创建根日志记录器
        logger = logging.getLogger("zenith_quant")
        logger.setLevel(getattr(logging, log_level.upper()))
        
        # 清除已有的处理器
        logger.handlers.clear()
        
        # 创建格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 添加控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # 添加文件处理器（如果指定）
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(getattr(logging, log_level.upper()))
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        cls._logger = logger
        cls._initialized = True
    
    @classmethod
    def get_logger(cls, name: Optional[str] = None) -> logging.Logger:
        """获取日志记录器
        
        Args:
            name: 日志记录器名称（可选）
        
        Returns:
            logging.Logger: 日志记录器
        """
        if not cls._initialized:
            cls.setup()
        
        if name:
            return logging.getLogger(f"zenith_quant.{name}")
        return cls._logger or logging.getLogger("zenith_quant")
