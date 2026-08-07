"""
F5.1 交易日和除权除息检查模块

使用 XTick 数据源替代 AKShare，统一数据入口。
"""
import pandas as pd
from datetime import date, datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
import logging

import requests

logger = logging.getLogger(__name__)

# 东方财富 F10 分红融资接口（股票除权除息）
_EM_F10_DIVIDEND_URL = (
    "https://emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/PageAjax"
)
_EM_F10_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; stockpush/1.0)',
    'Referer': 'https://emweb.securities.eastmoney.com/',
}
_EM_F10_TIMEOUT = 15


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


def _get_asset_type(symbol: str) -> str:
    """从自选股池获取标的资产类型，查询失败默认按股票处理。"""
    try:
        from stockpush.pg_connector import PGConnector
        db = PGConnector()
        rows = db.execute_query(
            "SELECT type FROM tb_stock_pool WHERE symbol = %s LIMIT 1",
            (symbol,)
        )
        db.close()
        if rows and rows[0].get('type') == 'fund':
            return 'fund'
    except Exception as e:
        logger.debug("_get_asset_type %s failed: %s", symbol, e)
    return 'stock'


def _stock_market_prefix(code: str) -> str:
    """根据股票代码前缀判断交易所，返回东财接口所需的市场前缀。

    SH：6（沪主板/科创板）、5（沪市ETF/LOF）、9（沪B）
    SZ：0（深主板）、3（创业板）
    """
    if code.startswith(('6', '5', '9')):
        return 'SH'
    return 'SZ'


def _check_stock_dividend_today(code: str) -> Optional[Dict[str, Any]]:
    """检查单个股票今日是否有除权除息事件（东方财富 F10 分红融资接口）。

    Returns:
        事件 dict 或 None（无事件/接口异常）
        {'symbol', 'name', 'event_type': 'dividend', 'detail', 'date'}
    """
    try:
        url = f"{_EM_F10_DIVIDEND_URL}?code={_stock_market_prefix(code)}{code}"
        resp = requests.get(url, headers=_EM_F10_HEADERS, timeout=_EM_F10_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.debug("_check_stock_dividend_today %s 请求失败: %s", code, e)
        return None

    try:
        today_str = date.today().isoformat()
        for item in payload.get('fhyx') or []:
            ex_date = str(item.get('EX_DIVIDEND_DATE') or '')[:10]
            reg_date = str(item.get('EQUITY_RECORD_DATE') or '')[:10]
            if ex_date == today_str or reg_date == today_str:
                return {
                    'symbol': code,
                    'name': item.get('SECURITY_NAME_ABBR') or code,
                    'event_type': 'dividend',
                    'detail': item.get('IMPL_PLAN_PROFILE') or '',
                    'date': ex_date or reg_date,
                }
    except Exception as e:
        logger.debug("_check_stock_dividend_today %s 解析失败: %s", code, e)
    return None


def check_dividend_today(symbols: List[str]) -> List[Dict[str, Any]]:
    """检查今日是否有除权除息或拆分事件。

    按资产类型分流：
    - 股票（stock）：东方财富 F10 分红融资接口（emweb.securities.eastmoney.com）
    - 基金（fund）：天天基金 f10 页面（fundf10.eastmoney.com）

    Args:
        symbols: 自选股代码列表

    Returns:
        事件列表
        [{'symbol': '601336', 'name': '新华保险',
          'event_type': 'dividend', 'detail': '10派20.6元', 'date': '2026-08-07'}, ...]
    """
    try:
        from stockpush.services.fund_event_checker import check_fund_events
    except ImportError:
        check_fund_events = None

    today_str = date.today().isoformat()
    results: List[Dict[str, Any]] = []

    for code in symbols:
        try:
            if _get_asset_type(code) == 'fund':
                if check_fund_events is None:
                    continue
                event = check_fund_events(code)
                if event.get('error'):
                    continue
                for ev in event.get('today_events', []):
                    if ev['type'] == 'split':
                        detail = f"{ev['split_type']} {ev['ratio']}"
                    else:
                        detail = ev.get('per_share', '')
                    results.append({
                        'symbol': code,
                        'name': event.get('name', code),
                        'event_type': ev['type'],
                        'detail': detail,
                        'date': ev.get('date') or ev.get('ex_date', today_str),
                    })
            else:
                stock_ev = _check_stock_dividend_today(code)
                if stock_ev:
                    results.append(stock_ev)
        except Exception as e:
            logger.debug("check_dividend_today %s: %s", code, e)

    return results


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
