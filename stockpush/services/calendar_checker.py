"""
F5.1 交易日和除权除息检查模块
"""
import pandas as pd
from datetime import date, datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
import sys

# 尝试导入主项目模块
try:
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))
except ImportError:
    pass

# SrcMgrService 和 PGConnector 在使用时动态导入


def is_trading_day(check_date: date = None) -> bool:
    """
    检查指定日期是否为交易日

    Args:
        check_date: 要检查的日期，默认为今天

    Returns:
        True=是交易日，False=不是交易日
    """
    if check_date is None:
        check_date = date.today()

    try:
        # 使用 AKShare 的 trade_cal
        import akshare as ak
        calendar = ak.tool_trade_date_hist_sina()
        trading_dates = set(pd.to_datetime(calendar['trade_date']).dt.date)
        return check_date in trading_dates
    except Exception as e:
        print(f"Warning: AKShare calendar check failed: {e}")
        # 备用方案：简单的周末判断（不精确）
        return check_date.weekday() < 5


def get_trading_dates(start_date: date, end_date: date) -> List[date]:
    """
    获取指定日期范围内的所有交易日

    Args:
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        交易日列表
    """
    try:
        import akshare as ak
        calendar = ak.tool_trade_date_hist_sina()
        df = pd.DataFrame(calendar)
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
        mask = (df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)
        return df.loc[mask, 'trade_date'].tolist()
    except Exception as e:
        print(f"Warning: Could not get trading dates: {e}")
        # 备用方案
        dates = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)
        return dates


def check_dividend_today(symbols: List[str]) -> List[Dict[str, Any]]:
    """
    检查自选股今日是否有除权除息

    Args:
        symbols: 股票代码列表

    Returns:
        有除权除息的股票列表 [{symbol, name, dividend_date, description}, ...]
    """
    today = date.today()
    dividend_stocks = []

    try:
        import akshare as ak

        # 获取所有股票的分红信息
        df = ak.stock_dividend_detail()
        if df is None or df.empty:
            return []

        # 转换日期列
        if 'equity_date' in df.columns:
            df['equity_date'] = pd.to_datetime(df['equity_date'], errors='coerce').dt.date
        elif 'dividend_date' in df.columns:
            df['dividend_date'] = pd.to_datetime(df['dividend_date'], errors='coerce').dt.date

        # 找出今天除权除息的股票
        for symbol in symbols:
            code_str = str(symbol).strip()

            # 匹配沪市或深市代码
            matches = df[
                (df['code'] == code_str) |
                (df['code'] == code_str + '.SH') |
                (df['code'] == code_str + '.SZ')
            ]

            for _, row in matches.iterrows():
                div_date = row.get('equity_date') or row.get('dividend_date')
                if div_date == today:
                    dividend_stocks.append({
                        'symbol': code_str,
                        'name': row.get('name', code_str),
                        'dividend_date': str(div_date),
                        'description': f"除权除息日"
                    })

    except Exception as e:
        print(f"Warning: Dividend check failed: {e}")

    return dividend_stocks


def get_stock_name_from_pool(symbol: str, db_path: str = None) -> Optional[str]:
    """
    从自选股池获取股票名称

    Args:
        symbol: 股票代码
        db_path: 数据库路径

    Returns:
        股票名称或 None
    """
    try:
        from stockpush.pg_connector import PGConnector
        db = PGConnector()
        result = db.execute_query(
            "SELECT name FROM tb_stock_pool WHERE symbol = ? ORDER BY updated_at DESC LIMIT 1",
            (str(symbol),)
        )
        if result and len(result) > 0:
            return result[0].get('name')
    except Exception:
        pass

    return symbol


class CalendarChecker:
    """交易日历检查器"""

    def __init__(self, db_path: str = None):
        pass

    def is_today_trading_day(self) -> bool:
        """检查今天是否是交易日"""
        return is_trading_day()

    def get_today_dividends(self, symbols: List[str] = None) -> List[Dict[str, Any]]:
        """
        获取今日有除权除息的自选股

        Args:
            symbols: 股票代码列表，如果为 None 则从数据库加载全部自选股

        Returns:
            除权除息股票列表
        """
        if symbols is None:
            symbols = self.load_watchlist()

        return check_dividend_today(symbols)

    def load_watchlist(self) -> List[str]:
        """从数据库加载自选股列表"""
        try:
            from stockpush.pg_connector import PGConnector
            db = PGConnector()
            result = db.execute_query(
                "SELECT symbol FROM tb_stock_pool WHERE type IN ('stock', 'fund')"
            )
            return [row.get('symbol') for row in result if row.get('symbol')]
        except Exception:
            return []

    def need_full_download(self, symbol: str) -> bool:
        """
        检查某只股票是否需要全量下载（除权除息日）

        Args:
            symbol: 股票代码

        Returns:
            True=需要全量下载
        """
        dividends = self.get_today_dividends([symbol])
        return len(dividends) > 0
