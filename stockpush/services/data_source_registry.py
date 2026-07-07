"""
F5.1 数据源注册表（PostgreSQL 版）

PostgreSQL 中 tb_datasource_registry 表已存在，用幂等方式确保种子数据。
"""
import logging
from typing import Dict, Optional

from stockpush.pg_connector import PGConnector

logger = logging.getLogger(__name__)

# ── Provider class map ─────────────────────────────────────────

_PROVIDER_CLASSES: Dict[str, str] = {
    'byapi':      'stockpush.src_mgr.src_provider.ByapiProvider',
    'xtick':      'stockpush.src_mgr.xtick_provider.XTickProvider',
}


class DataSourceRegistry:
    """
    F5.1 数据源注册表（PostgreSQL 版）

    从 PostgreSQL 的 tb_datasource_registry 表加载数据源配置，
    初始化时幂等地确保种子数据存在（不覆盖已有配置）。
    """

    def __init__(self):
        self.db = PGConnector()
        self.logger = logger
        self.providers: dict = {}
        self.registry: list = []
        self._load_registry()

    # ── 加载 ──────────────────────────────────────────────────

    def _load_registry(self):
        """加载数据源注册表（幂等播种，不覆盖已存在的记录）"""
        try:
            self._seed_registry(self.db)
            rows = self.db.execute_query(
                "SELECT * FROM tb_datasource_registry ORDER BY priority"
            )
            self.registry = rows
            logger.info("F5.1 数据源注册表加载成功：%d 个数据源", len(self.registry))
        except Exception as e:
            logger.error("F5.1 加载数据源注册表失败: %s", e)
            self.registry = []

    def _seed_registry(self, conn):
        """幂等创建 tb_datasource_registry 表并插入种子数据（不覆盖已有记录）"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tb_datasource_registry (
                id INTEGER PRIMARY KEY,
                provider_name VARCHAR(50) NOT NULL UNIQUE,
                display_name VARCHAR(100) NOT NULL,
                provider_class VARCHAR(200) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                priority INTEGER NOT NULL DEFAULT 50,
                config_json VARCHAR,
                timeout INTEGER NOT NULL DEFAULT 30,
                retry INTEGER NOT NULL DEFAULT 3,
                capability_api01 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api02 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api03 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api04 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api05 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api06 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api07 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api08 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api09 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api10 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api11 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api12 BOOLEAN NOT NULL DEFAULT FALSE,
                last_test_time TIMESTAMP, test_result VARCHAR(20),
                test_details VARCHAR, error_msg VARCHAR,
                call_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                avg_response_time REAL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        providers = [
            ('byapi', '币赢API', 'stockpush.src_mgr.src_provider.ByapiProvider', True, 15,
             '{"licence":"","timeout":10,"retry":2}', 10, 2,
             True,True,True,False, True,True,True,False, True,True,True,False),
            ('xtick', 'XTick', 'stockpush.src_mgr.xtick_provider.XTickProvider', True, 12,
             '{"timeout":15}', 15, 2,
             True,True,True,True, True,True,True,True, True,True,True,False),
        ]
        for i, p in enumerate(providers, 1):
            conn.execute("""
                INSERT INTO tb_datasource_registry
                (id, provider_name, display_name, provider_class,
                 enabled, priority, config_json, timeout, retry,
                 capability_api01, capability_api02, capability_api03, capability_api04,
                 capability_api05, capability_api06, capability_api07, capability_api08,
                 capability_api09, capability_api10, capability_api11, capability_api12,
                 last_test_time, test_result, test_details, error_msg,
                 call_count, success_count, fail_count, avg_response_time,
                 created_at, updated_at)
                VALUES (?,?,?,?,?,?,
                        ?,?,?,
                        ?,?,?,?, ?,?,?,?,
                        ?,?,?,?,
                        NULL,NULL,NULL,NULL,
                        0,0,0,NULL,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (provider_name) DO NOTHING
            """, (i,) + p)
        logger.info("F5.1 数据源注册表初始化完成：%d 个数据源", len(providers))

    # ── Provider 管理 ─────────────────────────────────────────

    def list_providers(self) -> list:
        """列出可用数据源（供 console 菜单使用）"""
        try:
            rows = self.db.execute_query(
                "SELECT * FROM tb_datasource_registry ORDER BY priority"
            )
            return rows
        except Exception as e:
            logger.error("list_providers failed: %s", e)
            return []

    def _get_provider(self, provider_name: str):
        """获取 Provider 实例（延迟加载 + 缓存）"""
        provider_name = provider_name.lower()
        if provider_name in self.providers:
            return self.providers[provider_name]

        cls_path = _PROVIDER_CLASSES.get(provider_name)
        if not cls_path:
            logger.warning("Unknown provider: %s", provider_name)
            return None

        try:
            import importlib
            mod_path, _, cls_name = cls_path.rpartition('.')
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            instance = cls()
            self.providers[provider_name] = instance
            return instance
        except Exception as e:
            logger.warning("Failed to load provider %s: %s", provider_name, e)
            return None


# ── 全局单例 ─────────────────────────────────────────────────

_registry_instance: Optional[DataSourceRegistry] = None


def get_registry() -> DataSourceRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = DataSourceRegistry()
    return _registry_instance
