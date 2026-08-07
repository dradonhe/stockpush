"""
Baostock 数据源 Provider

参考 docs/数据源管理/baostock/index.md
- 免费开源，登录无 token
- 覆盖：股票/基金(ETF) 历史日线、周线、月线、5/15/30/60 分钟线（无 1 分钟）
- 覆盖：股票列表（query_all_stock，不含基金）、交易日历、股票分红（query_dividend_data，基金不覆盖）
- 局限：无实时行情（盘后更新）
"""
import threading
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import baostock as bs
import pandas as pd

from stockpush.log_manager import LogManager
from .src_provider import BaseProvider
from .standard_api_adapter import StandardAPIAdapter


class BaostockProvider(BaseProvider, StandardAPIAdapter):
    NAME = 'baostock'

    # baostock adjustflag: 1=后复权, 2=前复权, 3=不复权（官方文档确认）
    _ADJUST_TO_FLAG = {'qfq': '2', 'hfq': '1', 'none': '3', '': '3'}

    # period -> baostock frequency
    _PERIOD_MAP = {'1d': 'd', '5m': '5', '15m': '15', '30m': '30', '60m': '60'}

    CAPABILITIES = {
        'stock_realtime': False,      # 盘后更新，无实时
        'stock_daily': True,
        'stock_1min': False,          # baostock 不支持 1 分钟线
        'stock_5min': True,
        'stock_15min': True,
        'stock_30min': True,
        'stock_60min': True,
        'stock_weekly': True,
        'stock_monthly': True,
        'fund_realtime': False,
        'fund_daily': True,
        'fund_1min': False,
        'fund_5min': True,
        'fund_15min': True,
        'fund_30min': True,
        'fund_60min': True,
        'stock_list': True,
        'trade_calendar': True,
    }

    # 登录/登出为全局会话，需互斥保护
    _login_lock = threading.Lock()

    def __init__(self, config: Optional[dict] = None):
        super().__init__()
        self.logger = LogManager().get_logger(self.__class__.__name__)
        self.config = config or {}

    # ========== 内部工具 ==========

    @staticmethod
    def _market_prefix(code: str) -> str:
        """6/5/9 开头 -> sh，其余 -> sz"""
        return 'sh' if code[:1] in ('6', '5', '9') else 'sz'

    @staticmethod
    def _bs_code(code: str) -> str:
        """纯数字代码 -> baostock 带市场前缀代码（sh.601336 / sz.159952）"""
        code = str(code).strip()
        if '.' in code:
            return code
        return f"{BaostockProvider._market_prefix(code)}.{code}"

    @staticmethod
    def _strip_prefix(code: str) -> str:
        """baostock 代码 -> 纯数字代码"""
        return str(code).split('.')[-1]

    def _query(self, func, *args, **kwargs) -> List[Dict[str, Any]]:
        """登录 + 查询 + 登出（互斥），返回行列表（每行 dict）"""
        with self._login_lock:
            lg = bs.login()
            if lg.error_code != '0':
                self.logger.error(f"baostock 登录失败: {lg.error_code} {lg.error_msg}")
                return []
            try:
                rs = func(*args, **kwargs)
                if rs.error_code != '0':
                    self.logger.error(f"baostock 查询失败: {rs.error_code} {rs.error_msg}")
                    return []
                fields = rs.fields
                rows = []
                while (rs.error_code == '0') and rs.next():
                    rows.append(dict(zip(fields, rs.get_row_data())))
                return rows
            except Exception as e:
                self.logger.error(f"baostock 查询异常: {e}")
                return []
            finally:
                bs.logout()

    @staticmethod
    def _parse_time(bs_time: str) -> Optional[str]:
        """baostock time 字段 'YYYYMMDDHHMMSSmmm' -> 'YYYY-MM-DD HH:MM:SS'"""
        try:
            t = str(bs_time).strip()
            return f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:{t[12:14]}"
        except Exception:
            return None

    def _to_kline_df(self, rows: list, is_minute: bool = False) -> pd.DataFrame:
        """baostock K 线行 -> 标准 DataFrame（date, open, high, low, close, volume, amount）"""
        if not rows:
            return pd.DataFrame()
        df: pd.DataFrame = pd.DataFrame(rows)
        if 'code' in df.columns:
            df['code'] = df['code'].map(self._strip_prefix)

        if is_minute:
            # 分钟线 date 仅日期，time 为完整时间戳
            df['time_str'] = df['time'].map(self._parse_time)
            df['date'] = pd.to_datetime(df['time_str'], errors='coerce')
        else:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')

        cols = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df.loc[:, cols].copy()
        for c in cols[1:]:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        # 统一 volume 单位为「手」：baostock 返回股/份（XTick 为手，1手=100股/份）
        if 'volume' in df.columns:
            df['volume'] = df['volume'] / 100.0
        df = df.loc[df['date'].notna(), :].reset_index(drop=True)
        return df

    # ========== 历史 K 线（股票 + 基金） ==========

    def _fetch_kline_bs(self, code: str, period: str, start_date: str, end_date: str,
                        adjust: str = 'qfq') -> pd.DataFrame:
        """统一 baostock K 线查询"""
        freq = self._PERIOD_MAP.get(period)
        if not freq:
            self.logger.error(f"baostock 不支持周期: {period}")
            return pd.DataFrame()
        adjust_flag = self._ADJUST_TO_FLAG.get(adjust, '2')
        start = self._date_only(start_date)
        end = self._date_only(end_date)
        # 分钟线必须请求 time 字段以获取完整时间戳；日线不需要
        fields = ('date,time,open,high,low,close,volume,amount'
                  if freq not in ('d', 'w', 'm') else
                  'date,open,high,low,close,volume,amount')
        rows = self._query(
            bs.query_history_k_data_plus,
            code=self._bs_code(code),
            fields=fields,
            start_date=start,
            end_date=end,
            frequency=freq,
            adjustflag=adjust_flag,
        )
        return self._to_kline_df(rows, is_minute=freq not in ('d', 'w', 'm'))

    def fetch_stock_daily(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        super().fetch_stock_daily(code, start_date, end_date)
        return self._fetch_kline_bs(code, '1d', start_date, end_date, adjust)

    def fetch_stock_5min(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        super().fetch_stock_5min(code, start_date, end_date)
        return self._fetch_kline_bs(code, '5m', start_date, end_date, adjust)

    def fetch_stock_15min(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        super().fetch_stock_15min(code, start_date, end_date)
        return self._fetch_kline_bs(code, '15m', start_date, end_date, adjust)

    def fetch_stock_30min(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        super().fetch_stock_30min(code, start_date, end_date)
        return self._fetch_kline_bs(code, '30m', start_date, end_date, adjust)

    def fetch_stock_60min(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        super().fetch_stock_60min(code, start_date, end_date)
        return self._fetch_kline_bs(code, '60m', start_date, end_date, adjust)

    def fetch_stock_weekly(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        super().fetch_stock_weekly(code, start_date, end_date)
        # baostock 周线 frequency='w'，字段与日线一致
        freq = 'w'
        rows = self._query(
            bs.query_history_k_data_plus,
            code=self._bs_code(code),
            fields='date,open,high,low,close,volume,amount',
            start_date=self._date_only(start_date),
            end_date=self._date_only(end_date),
            frequency=freq,
            adjustflag=self._ADJUST_TO_FLAG.get(adjust, '2'),
        )
        return self._to_kline_df(rows, is_minute=False)

    def fetch_stock_monthly(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        super().fetch_stock_monthly(code, start_date, end_date)
        rows = self._query(
            bs.query_history_k_data_plus,
            code=self._bs_code(code),
            fields='date,open,high,low,close,volume,amount',
            start_date=self._date_only(start_date),
            end_date=self._date_only(end_date),
            frequency='m',
            adjustflag=self._ADJUST_TO_FLAG.get(adjust, '2'),
        )
        return self._to_kline_df(rows, is_minute=False)

    def fetch_fund_daily(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        super().fetch_fund_daily(code, start_date, end_date)
        return self._fetch_kline_bs(code, '1d', start_date, end_date, adjust)

    def fetch_fund_5min(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        return self._fetch_kline_bs(code, '5m', start_date, end_date, adjust)

    def fetch_fund_15min(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        return self._fetch_kline_bs(code, '15m', start_date, end_date, adjust)

    def fetch_fund_30min(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        return self._fetch_kline_bs(code, '30m', start_date, end_date, adjust)

    def fetch_fund_60min(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        return self._fetch_kline_bs(code, '60m', start_date, end_date, adjust)

    # ========== 列表 / 日历 ==========

    def fetch_stock_list(self) -> pd.DataFrame:
        """股票列表（query_all_stock，不含基金/ETF；过滤指数）"""
        # 盘中查询当日可能不完整，fallback 到最近一个自然日
        day = date.today().isoformat()
        rows = self._query(bs.query_all_stock, day=day)
        if not rows:
            rows = self._query(bs.query_all_stock, day=(date.today() - timedelta(days=1)).isoformat())
        if not rows:
            return pd.DataFrame()

        df: pd.DataFrame = pd.DataFrame(rows)
        # 仅保留正常交易（tradeStatus=1）的沪深 A 股，过滤指数（6xxxxx 股票、0/3 开头深市）
        df = df.loc[df['tradeStatus'].astype(str) == '1', :]
        df = df.loc[df['code'].astype(str).str.match(r'^(sh\.(60|68|9)|sz\.(00|30|9))\d{4}$'), :]
        df['name'] = df.get('code_name', '')
        df['code'] = df['code'].astype(str).map(self._strip_prefix)
        return df.loc[:, ['code', 'name']].reset_index(drop=True)

    def fetch_trade_calendar(self, start: str, end: str) -> pd.DataFrame:
        """交易日历（query_trade_dates）"""
        rows = self._query(
            bs.query_trade_dates,
            start_date=self._date_only(start),
            end_date=self._date_only(end),
        )
        if not rows:
            return pd.DataFrame()
        df: pd.DataFrame = pd.DataFrame(rows)
        df['date'] = df['calendar_date']
        return df.loc[:, ['date', 'is_trading_day']].reset_index(drop=True)

    # ========== 分红（仅股票） ==========

    def fetch_latest_dividend_date(self, code: str, asset_type: str = 'stock', **kwargs) -> Dict:
        """
        API12: 最新分红日期（query_dividend_data，仅股票；基金返回空 dict）

        Returns:
            {code, latest_dividend_date, date_field, detail, ...} 或空 dict
        """
        if asset_type != 'stock':
            self.logger.warning(f"baostock 分红接口不覆盖 {asset_type}")
            return {}
        year = kwargs.get('year') or date.today().year
        year_type = kwargs.get('year_type', 'report')
        rows = self._query(
            bs.query_dividend_data,
            code=self._bs_code(code),
            year=str(year),
            yearType=year_type,
        )
        if not rows:
            return {}
        # 取最近一条除权除息日（dividOperateDate）
        df: pd.DataFrame = pd.DataFrame(rows)
        df['dividOperateDate'] = pd.to_datetime(df['dividOperateDate'], errors='coerce')
        df = df.loc[df['dividOperateDate'].notna(), :].sort_values(
            by='dividOperateDate', ascending=False)
        if df.empty:
            return {}
        row = df.iloc[0]
        return {
            'code': code,
            'latest_dividend_date': row['dividOperateDate'].strftime('%Y-%m-%d'),
            'date_field': 'dividOperateDate',
            'equity_record_date': (row.get('dividRegistDate') or ''),
            'divid_cash_ps': row.get('dividCashPsBeforeTax') or '',
            'detail': (row.get('dividCashStock') or row.get('dividStocksPs') or ''),
        }
