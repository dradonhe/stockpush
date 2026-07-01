"""
数据源管理模块
提供数据源Provider抽象、能力检测、状态管理、双源共识校验、数据映射
"""

from .src_provider import BaseProvider, AkShareProvider, BaostockProvider, ByapiProvider
from .tdx_local_provider import TdxLocalProvider
from .src_mgr import SrcMgrService
from .src_validator import ConsensusValidator
from .data_mapper import DataMapper

__all__ = [
    'BaseProvider',
    'AkShareProvider', 
    'BaostockProvider',
    'ByapiProvider',
    'TdxLocalProvider',
    'SrcMgrService',
    'ConsensusValidator',
    'DataMapper',
]
