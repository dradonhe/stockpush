"""
F5.1 自选股池监听模块

监听自选股池变化，检测 tb_stock_pool 表的变更
"""

import logging
from typing import List, Dict, Optional
from pathlib import Path
import sys

logger = logging.getLogger(__name__)


class PoolWatcher:
    _DBConnector = None

    @classmethod
    def _get_connector_class(cls):
        if cls._DBConnector is None:
            project_root = Path(__file__).parent.parent.parent
            sys.path.insert(0, str(project_root))
            from stockpush.pg_connector import PGConnector
            cls._DBConnector = PGConnector
        return cls._DBConnector
    """自选股池监听器

    从 tb_stock_pool 表加载自选股列表，支持变更检测。

    Attributes:
        _last_hash: 上次加载的哈希值，用于检测变更
    """

    QUERY = "SELECT symbol, name, type FROM tb_stock_pool WHERE type IN ('stock', 'fund')"

    def __init__(self):
        """初始化自选股池监听器
        使用 PostgreSQL 作为数据源"""
        self._last_hash: Optional[int] = None

    def _get_db(self):
        """获取数据库连接"""
        DBC = self._get_connector_class()
        return DBC()

    def get_symbols(self) -> List[str]:
        """获取自选股代码列表

        Returns:
            股票代码列表，如 ['000001', '600519', ...]
        """
        watchlist = self.load_watchlist()
        return [item['symbol'] for item in watchlist]

    def load_watchlist(self) -> List[Dict]:
        """加载自选股列表

        Returns:
            自选股列表，每个元素包含 symbol, name, type
            如 [{'symbol': '000001', 'name': '平安银行', 'type': 'stock'}, ...]
        """
        db = self._get_db()
        try:
            rows = db.execute_query(self.QUERY)
            return [{'symbol': r.get('symbol'), 'name': r.get('name'), 'type': r.get('type')} for r in rows]
        finally:
            db.close()

    def _compute_hash(self) -> int:
        """计算当前自选股池的哈希值"""
        watchlist = self.load_watchlist()
        # 使用 symbol 的字符串拼接来计算哈希
        symbols_str = '|'.join(sorted(item['symbol'] for item in watchlist))
        return hash(symbols_str)

    def check_changes(self, force: bool = False) -> bool:
        """检测自选股池是否发生变化

        Args:
            force: 强制重新计算哈希

        Returns:
            True 如果自选股池发生变化，False 否则
        """
        current_hash = self._compute_hash()

        if self._last_hash is None or force:
            self._last_hash = current_hash
            return True

        if current_hash != self._last_hash:
            self._last_hash = current_hash
            return True

        return False

    def needs_reload(self) -> bool:
        """判断是否需要重新加载自选股池

        这是一个便捷方法，等同于 check_changes(force=False)

        Returns:
            True 如果自选股池发生变化或尚未加载过
        """
        return self.check_changes(force=False)