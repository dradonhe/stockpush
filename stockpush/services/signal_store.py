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
        """批量写入信号到 tb_signal_log。

        对每个信号执行 (func_id, symbol, direction, signal_time) 四元组去重：
        - 已存在的跳过（返回中排除）
        - 不存在的插入并追加到返回列表

        Args:
            func_id: tb_signal_functions.id
            symbol: 股票代码
            signals: 信号列表，每项含 time/direction/price/open_price/indicator

        Returns:
            实际新插入的信号列表（排除重复和无效方向的），空列表表示全部已存在或无效
        """
        inserted = []
        for sig in signals:
            # Check for duplicates (same func_id + symbol + direction + signal_time)
            time_val = sig.get('time')
            if hasattr(time_val, 'strftime'):
                time_str = time_val.strftime("%Y-%m-%d %H:%M:%S")
            else:
                time_str = str(time_val)
            existing = self._db.execute_query(
                "SELECT id FROM tb_signal_log WHERE func_id = ? AND symbol = ? "
                "AND direction = ? AND signal_time = ?::timestamp LIMIT 1",
                (func_id, symbol, sig.get('direction'), time_str),
            )
            if existing:
                continue
            raw_time = sig.get('time')
            if raw_time is None:
                continue

            direction = sig.get('direction')
            if direction not in ('buy', 'sell'):
                logger.warning("Skipping signal with invalid direction: %s", direction)
                continue

            # Normalize pd.Timestamp / datetime → ISO string
            if hasattr(raw_time, 'strftime'):
                time_str = raw_time.strftime('%Y-%m-%d %H:%M:%S')
            else:
                time_str = str(raw_time)

            price = sig.get('price')
            open_price = sig.get('open_price')
            indicator = sig.get('indicator', '')

            self._db.execute_update(
                "INSERT INTO tb_signal_log "
                "(func_id, direction, symbol, signal_time, price, open_price, indicator) "
                "VALUES (?, ?, ?, ?::timestamp, ?, ?, ?)",
                (func_id, direction, symbol, time_str, price, open_price, indicator),
            )
            inserted.append(sig)
        return inserted

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
