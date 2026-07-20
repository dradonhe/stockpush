"""Signal Store — 信号存档与查询

提供 tb_signal_log 表的写入/查询操作，按需要 JOIN tb_signal_functions
获取 display_name 等元信息。
"""
import logging
from datetime import date, datetime
from typing import Optional

from stockpush.pg_connector import PGConnector

logger = logging.getLogger(__name__)


class SignalStore:
    """信号存储——写入/查询 tb_signal_log"""

    def __init__(self, db: Optional[PGConnector] = None):
        self._db = db or PGConnector()

    # ── 写入 ──

    def write_signals(self, func_id: int, symbol: str, signals: list[dict]) -> list[dict]:
        """批量写入信号到 tb_signal_log，通过 ON CONFLICT 自动去重。

        所有有效信号在一条 INSERT ... ON CONFLICT DO NOTHING 中批量写入，
        由 PostgreSQL 的 (func_id, symbol, direction, signal_time) 唯一约束处理去重。
        通过 RETURNING 子句返回实际新插入的行，并映射回原始信号字典。

        Args:
            func_id: tb_signal_functions.id
            symbol: 股票代码
            signals: 信号列表，每项含 time/direction/price/open_price/indicator

        Returns:
            实际新插入的信号列表（排除重复和无效方向的），空列表表示全部已存在或无效
        """
        # 1. 预过滤：收集有效信号
        rows: list[tuple] = []  # (func_id, direction, symbol, time_str, price, open_price, indicator, sig_dict)
        for sig in signals:
            direction = sig.get('direction')
            if direction not in ('buy', 'sell'):
                logger.warning("Skipping signal with invalid direction: %s", direction)
                continue
            raw_time = sig.get('time')
            if raw_time is None:
                continue
            # Normalize pd.Timestamp / datetime → ISO string
            if hasattr(raw_time, 'strftime'):
                time_str = raw_time.strftime('%Y-%m-%d %H:%M:%S')
            else:
                time_str = str(raw_time)
            price = sig.get('price')
            open_price = sig.get('open_price')
            indicator = sig.get('indicator', '')
            rows.append((func_id, direction, symbol, time_str, price, open_price, indicator, sig))

        if not rows:
            return []

        # 2. 构建单条多行 INSERT ... ON CONFLICT DO NOTHING RETURNING
        n = len(rows)
        row_placeholder = '(?, ?, ?, ?::timestamp, ?, ?, ?)'
        placeholders = ', '.join([row_placeholder] * n)
        sql = (
            "INSERT INTO tb_signal_log "
            "(func_id, direction, symbol, signal_time, price, open_price, indicator) "
            f"VALUES {placeholders} "
            "ON CONFLICT (func_id, symbol, direction, signal_time) DO NOTHING "
            "RETURNING direction, signal_time::text AS signal_time"
        )

        # 3. 展平参数
        params = []
        for r in rows:
            params.extend(r[:7])

        # 4. 执行批量写入
        returned = self._db.execute_query(sql, tuple(params))

        # 5. 将返回行映射回原始信号字典（每个 key 只匹配第一个遇到的信号）
        inserted_keys = {(r['direction'], r['signal_time']) for r in returned}
        seen_keys: set[tuple[str, str]] = set()
        result = []
        for r in rows:
            key = (r[1], r[3])  # (direction, time_str)
            if key in inserted_keys and key not in seen_keys:
                seen_keys.add(key)
                result.append(r[7])
        return result

    # ── 查询 ──

    def get_today(self, func_name: Optional[str] = None) -> list[dict]:
        """获取当天信号，JOIN tb_signal_functions 获取 display_name。

        Args:
            func_name: 可选，按函数名称过滤

        Returns:
            信号记录列表（每行含 display_name, func_name）
        """
        today = date.today()
        sql = (
            "SELECT l.*, f.display_name, f.name AS func_name "
            "FROM tb_signal_log l "
            "JOIN tb_signal_functions f ON l.func_id = f.id "
            "WHERE l.created_at >= ?::date "
        )
        params = [today.isoformat()]
        if func_name:
            sql += "AND f.name = ? "
            params.append(func_name)
        sql += "ORDER BY l.signal_time DESC"
        return self._db.execute_query(sql, tuple(params))

    def get_history(
        self,
        symbol: str,
        func_name: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """获取历史信号。

        Args:
            symbol: 股票/合约代码
            func_name: 可选，按函数名称过滤
            limit: 最大返回条数，默认 50

        Returns:
            信号记录列表（每行含 display_name, func_name）
        """
        sql = (
            "SELECT l.*, f.display_name, f.name AS func_name "
            "FROM tb_signal_log l "
            "JOIN tb_signal_functions f ON l.func_id = f.id "
            "WHERE l.symbol = ? "
        )
        params = [symbol]
        if func_name:
            sql += "AND f.name = ? "
            params.append(func_name)
        sql += "ORDER BY l.signal_time DESC LIMIT ?"
        params.append(limit)
        return self._db.execute_query(sql, tuple(params))
