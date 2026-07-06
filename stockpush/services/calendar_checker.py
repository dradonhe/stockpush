"""
F5.1 交易日和除权除息检查模块

使用 XTick 数据源替代 AKShare，统一数据入口。
"""
import pandas as pd
from datetime import date, datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
import sys
import logging

logger = logging.getLogger(__name__)


def _get_xtick_provider():
    """延迟加载 XTickProvider"""
    from stockpush.src_mgr.xtick_provider import XTickProvider
    return XTickProvider()


def is_trading_day(check_date: date = None) -> bool:
    """检查指定日期是否为 A 股交易日。

    通过 XTick /doc/calendar 接口判断。
    接口不可用时降级为简单的周末判断（周一至周五视为交易日）。

    Args:
        check_date: 待检查日期，默认今天

    Returns:
        True=交易日，False=非交易日
    """
    if check_date is None:
        check_date = date.today()

    try:
        provider = _get_xtick_provider()
        start_str = check_date.isoformat()
        end_str = check_date.isoformat()
        df = provider.fetch_trade_calendar(start_str, end_str)
        if df.empty:
            raise ValueError("XTick calendar returned empty")

        # 尝试多种可能的日期列名
        date_col = None
        for col in ('date', 'trade_date', 'calendar_date', 'day'):
            if col in df.columns:
                date_col = col
                break

        if date_col is None:
            raise ValueError(f"No date column found in calendar data: {df.columns.tolist()}")

        # 转换日期列
        cal_dates = pd.to_datetime(df[date_col]).dt.date
        return check_date in cal_dates.values

    except Exception as e:
        logger.warning(f"XTick calendar check failed, fallback to weekend check: {e}")
        return check_date.weekday() < 5


def get_trading_dates(start_date: date, end_date: date) -> List[date]:
    """获取指定日期范围内的所有交易日。

    Args:
        start_date: 起始日期
        end_date: 截止日期

    Returns:
        交易日列表（date 对象）
    """
    try:
        provider = _get_xtick_provider()
        df = provider.fetch_trade_calendar(
            start_date.isoformat(),
            end_date.isoformat(),
        )
        if df.empty:
            raise ValueError("XTick calendar returned empty")

        # 尝试多种可能的日期列名
        date_col = None
        for col in ('date', 'trade_date', 'calendar_date', 'day'):
            if col in df.columns:
                date_col = col
                break

        if date_col is None:
            raise ValueError(f"No date column found: {df.columns.tolist()}")

        dates = pd.to_datetime(df[date_col]).dt.date.tolist()
        return [d for d in dates if start_date <= d <= end_date]

    except Exception as e:
        logger.warning(f"XTick trading dates fetch failed, fallback to weekday filter: {e}")
        # 降级：周一到周五视为交易日
        dates = []
        d = start_date
        while d <= end_date:
            if d.weekday() < 5:
                dates.append(d)
            d += timedelta(days=1)
        return dates


def check_dividend_today(symbols: List[str]) -> List[Dict[str, Any]]:
    """检查今日是否有除权除息。

    通过 XTick /doc/calendar 接口获取今日分红数据。
    如果 XTick 不支持分红查询，返回空列表并记录警告。

    Args:
        symbols: 自选股代码列表

    Returns:
        除权除息股票信息列表
        [{'symbol': '000001', 'name': '平安银行', 'dividend': '10派2.0', 'ex_date': '2026-07-01'}, ...]
    """
    today_str = date.today().isoformat()

    try:
        provider = _get_xtick_provider()
        # 尝试获取分红数据 — 如果 XTick 支持
        df = provider.fetch_trade_calendar(today_str, today_str)
        if df.empty:
            return []

        # 检查返回的数据中是否有分红相关字段
        dividend_cols = [c for c in df.columns if 'dividend' in c.lower() or 'bonu' in c.lower() or 'ex' in c.lower()]
        if not dividend_cols:
            logger.info("XTick calendar does not provide dividend data, skipping dividend check.")
            return []

        # 提取与自选股相关的分红数据
        results = []
        for _, row in df.iterrows():
            code = row.get('code') or row.get('symbol') or ''
            if code in symbols or code.lstrip('0') in symbols:
                results.append({
                    'symbol': code,
                    'name': row.get('name', ''),
                    'dividend': str(row.get(dividend_cols[0], '')),
                    'ex_date': today_str,
                })

        return results

    except Exception as e:
        logger.warning(f"XTick dividend check failed: {e}")
        return []


def get_stock_name_from_pool(symbol: str, db_path: str = None) -> Optional[str]:
    """从自选股池获取股票名称。

    Args:
        symbol: 股票代码
        db_path: 数据库路径（未使用，保留参数兼容）

    Returns:
        股票名称，未找到返回 symbol 本身
    """
    try:
        from stockpush.pg_connector import PGConnector
        db = PGConnector()
        rows = db.execute_query(
            "SELECT name FROM tb_stock_pool WHERE symbol = %s",
            (symbol,)
        )
        db.close()
        if rows:
            return rows[0]['name']
    except Exception as e:
        logger.warning(f"get_stock_name_from_pool failed for {symbol}: {e}")
    return symbol


class CalendarChecker:
    """交易日历检查器

    使用 XTick 数据源判断交易日和除权除息。
    """

    def __init__(self, xtick_provider=None):
        self._provider = xtick_provider

    def _get_provider(self):
        if self._provider is None:
            self._provider = _get_xtick_provider()
        return self._provider

    def is_today_trading_day(self) -> bool:
        """检查今天是否为交易日。"""
        return is_trading_day()

    def is_trading_day(self, check_date: date = None) -> bool:
        """检查指定日期是否为交易日。"""
        return is_trading_day(check_date)

    def load_watchlist(self) -> List[str]:
        """从自选股池加载股票列表。

        Returns:
            股票代码列表
        """
        try:
            from stockpush.pg_connector import PGConnector
            db = PGConnector()
            rows = db.execute_query(
                "SELECT symbol FROM tb_stock_pool WHERE type IN ('stock', 'fund')"
            )
            db.close()
            return [row['symbol'] for row in rows]
        except Exception as e:
            logger.error(f"Failed to load watchlist: {e}")
            return []

    def get_today_dividends(self, symbols: List[str] = None) -> List[Dict[str, Any]]:
        """返回今日除权除息的股票列表。

        Args:
            symbols: 待检查的股票列表，None 时从自选股池加载

        Returns:
            除权除息信息列表
        """
        if symbols is None:
            symbols = self.load_watchlist()
        if not symbols:
            return []
        return check_dividend_today(symbols)

    def has_dividends_today(self, symbols: List[str] = None) -> bool:
        """检查今日是否有除权除息。"""
        dividends = self.get_today_dividends(symbols)
        return len(dividends) > 0
