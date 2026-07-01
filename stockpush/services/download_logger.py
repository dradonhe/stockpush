"""F5.1 下载请求日志记录模块

每次定时调度执行时，将每笔下载请求的详细信息记录到临时表，
用于调试和审计每时刻的API返回数据。
INSERT only，永不覆盖。
"""

import logging
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)

LOG_TABLE = "tb_download_request_log"

_CREATE_SEQ_SQL = f"CREATE SEQUENCE IF NOT EXISTS seq_{LOG_TABLE}_id START 1"

_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
    id          BIGINT PRIMARY KEY DEFAULT nextval('seq_{LOG_TABLE}_id'),
    request_time TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    period      TEXT    NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      DOUBLE PRECISION,
    amount      DOUBLE PRECISION,
    preclose    DOUBLE PRECISION,
    api_bar_time TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_INSERT_SQL = f"""INSERT INTO {LOG_TABLE}
(request_time, symbol, period, open, high, low, close, volume, amount, preclose, api_bar_time)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""


def _ensure_table(conn):
    conn.execute(_CREATE_SEQ_SQL)
    conn.execute(_CREATE_TABLE_SQL)


def log_downloads(conn, request_time: str, symbol: str, period: str,
                  df: Optional[pd.DataFrame]) -> None:
    """将 fetch_kline 返回的每根K线记录到日志表。"""
    _ensure_table(conn)

    if df is None or df.empty:
        return

    for _, row in df.iterrows():
        api_bar_time = None
        bar_dt = row.get("date") or row.get("datetime") or row.get("ts")
        if bar_dt is not None:
            try:
                api_bar_time = pd.to_datetime(bar_dt).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                api_bar_time = str(bar_dt)

        preclose = None
        for col in ("preclose", "pre_close", "昨收", "preClose"):
            if col in row and pd.notna(row[col]):
                try:
                    preclose = float(row[col])
                except (ValueError, TypeError):
                    pass
                break

        try:
            conn.execute(_INSERT_SQL, (
                request_time,
                symbol,
                period,
                float(row["open"]) if "open" in row and pd.notna(row["open"]) else None,
                float(row["high"]) if "high" in row and pd.notna(row["high"]) else None,
                float(row["low"]) if "low" in row and pd.notna(row["low"]) else None,
                float(row["close"]) if "close" in row and pd.notna(row["close"]) else None,
                float(row.get("vol") or row.get("volume")) if pd.notna(row.get("vol") or row.get("volume")) else None,
                float(row["amount"]) if "amount" in row and pd.notna(row["amount"]) else None,
                preclose,
                api_bar_time,
            ))
        except Exception as e:
            logger.warning("写入下载日志失败 [%s %s]: %s", symbol, period, e)
