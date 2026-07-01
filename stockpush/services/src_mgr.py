"""
F5.1 数据源管理服务（PostgreSQL 版）

与共享层 services.src_mgr.src_mgr 接口兼容，但后端使用 PGConnector。
tb_src_status 表仅在 DuckDB 中存在 —— PG 版 get_provider_status 默认返回 None（视为可用）。
"""
import logging
from typing import Dict, Optional, Any

from .data_source_registry import get_registry

logger = logging.getLogger(__name__)


class SrcMgrService:
    """F5.1 数据源管理服务（PostgreSQL 版）"""

    def __init__(self):
        self._providers: Dict[str, Any] = {}

        # DataSourceRegistry 单例（F5.1 本地版）
        self.registry = get_registry()

        # 从注册表加载 Provider 实例
        self._init_providers()
        logger.info("F5.1 SrcMgrService 初始化完成")

    def _init_providers(self):
        """从 DataSourceRegistry 动态加载 Provider 实例"""
        try:
            for item in self.registry.registry:
                pname = item['provider_name']
                try:
                    self._providers[pname] = self.registry._get_provider(pname)
                except Exception as e:
                    logger.warning("Provider %s 加载失败: %s", pname, e)
        except Exception as e:
            logger.warning("从注册表加载 Provider 失败: %s", e)

    def get_provider_status(self, provider: str) -> Optional[dict]:
        """获取数据源状态
        PG 中无 tb_src_status 表，统一返回 None（调用方视为可用）。
        """
        return None

    def get_provider_instance(self, provider: str) -> Optional[Any]:
        """获取 Provider 实例"""
        return self._providers.get(provider.lower())

    def list_providers(self) -> list:
        """列出所有注册数据源"""
        return self.registry.list_providers()
