"""
F5.1 数据抓取模块

从 primary 数据源获取数据并保存到数据库。
"""

import pandas as pd
from datetime import datetime, date, time, timedelta
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# 延迟导入，避免模块加载时静默吞掉 ImportError
# SrcMgrService 和 PGConnector 在使用时动态导入

# 表映射：period -> table_name
MINUTE_PERIODS = {"1m", "5m", "30m"}
PERIOD_TABLE_MAP = {
    '1m': 'tb_raw_1m',
    '5m': 'tb_raw_5m',
    '30m': 'tb_raw_30m',
    '1d': 'tb_raw_1d',
}


class DataFetcher:
    """数据抓取器

    从 primary 数据源获取数据。
    支持将数据保存到数据库，使用 INSERT ... ON CONFLICT DO UPDATE 避免覆盖历史数据。
    """

    def __init__(
        self,
        primary: str = "xtick",
        db_path: str = None
    ):
        """
        初始化数据抓取器

        Args:
            primary: 主数据源名称
            db_path: 数据库路径（可选，默认使用项目配置）
        """
        self.primary = primary
        self.db_path = db_path
        self._src_mgr: Optional[SrcMgrService] = None
        self._db = None  # PGConnector 实例（延迟初始化）
        self._current_source: str = ""

        # 延迟初始化 SrcMgrService（F5.1 本地 PostgreSQL 版）
        try:
            from stockpush.services.src_mgr import SrcMgrService
            self._src_mgr = SrcMgrService()
        except Exception as e:
            logger.warning("Failed to initialize SrcMgrService: %s", e)

    def _get_active_provider(self) -> Tuple[Optional[str], Optional[Any]]:
        """
        获取当前可用的数据源

        Returns:
            (provider_name, provider_instance) 或 (None, None)
        """
        # 先尝试主数据源
        if self.primary and self._is_provider_active(self.primary):
            instance = self._get_provider_instance(self.primary)
            if instance is not None:
                self._current_source = self.primary
                return self.primary, instance

        # 如果未激活，尝试获取实例（可能未注册但可用）
        if self.primary:
            instance = self._get_provider_instance(self.primary)
            if instance is not None:
                self._current_source = self.primary
                return self.primary, instance

        self._current_source = ""
        return None, None

    def _is_provider_active(self, provider: str) -> bool:
        """
        检查数据源是否激活

        Args:
            provider: 数据源名称

        Returns:
            bool
        """
        if self._src_mgr is None:
            return True  # 无法检查时默认视为可用

        try:
            status = self._src_mgr.get_provider_status(provider)
            if status is None:
                return True  # 未注册的数据源默认视为可用
            return bool(status.get('is_active', False))
        except Exception:
            return True  # 检查失败时默认视为可用

    def _get_provider_instance(self, provider: str):
        """
        获取数据源实例

        Args:
            provider: 数据源名称

        Returns:
            provider instance 或 None
        """
        if self._src_mgr is None:
            return None

        try:
            return self._src_mgr.get_provider_instance(provider)
        except Exception:
            return None

    _EXCHANGE_FUND_PREFIXES = ('159', '510', '511', '512', '513', '514', '515', '516', '517',
                               '518', '520', '521', '522', '523', '560', '561', '562', '563',
                               '588', '589')

    def _detect_asset_type(self, symbol: str) -> str:
        """根据代码判断资产类型，优先使用自选股池的类型定义

        Args:
            symbol: 股票/基金代码

        Returns:
            'fund' 或 'stock'
        """
        try:
            from stockpush.pg_connector import PGConnector
        except ImportError:
            return 'stock'
        try:
            if self._db is None:
                self._db = PGConnector()
            # 优先从自选股池获取用户定义的类型（最准确）
            result = self._db.execute_query(
                "SELECT type FROM tb_stock_pool WHERE symbol = ? LIMIT 1",
                (symbol,)
            )
            if result:
                pool_type = result[0].get('type', '')
                if pool_type in ('fund', 'stock'):
                    return pool_type
            # 回退：通过代码前缀判断是否交易所基金（ETF/LOF）
            if len(symbol) >= 3 and symbol[:3] in self._EXCHANGE_FUND_PREFIXES:
                return 'fund'
            # 再回退：查询 fund_codes 表
            result = self._db.execute_query(
                "SELECT COUNT(*) as cnt FROM tb_fund_codes WHERE symbol = ?",
                (symbol,)
            )
            if result and result[0].get('cnt', 0) > 0:
                return 'fund'
        except Exception:
            pass
        return 'stock'

    def fetch_kline(
        self,
        symbol: str,
        period: str = '1d',
        adjust: str = 'qfq'
    ) -> Optional[pd.DataFrame]:
        """
        获取K线数据（仅今日）

        Args:
            symbol: 股票代码
            period: 周期 ('1m', '5m', '30m', '1d')
            adjust: 复权类型 ('qfq', 'hfq', 'None')

        Returns:
            DataFrame 或 None（所有数据失败时）
        """
        today = date.today().isoformat()
        asset_type = self._detect_asset_type(symbol)
        provider_name, provider = self._get_active_provider()
        if provider is None:
            return None

        try:
            data = provider.fetch_kline(
                code=symbol,
                period=period,
                start=today,
                end=today,
                adjust=adjust,
                asset_type=asset_type
            )
            if data is not None and not data.empty:
                return data
            if data is not None and data.empty:
                logger.info("Primary provider %s returned empty data for %s %s", provider_name, symbol, period)
        except Exception as e:
            logger.warning("Primary provider %s fetch_kline failed: %s", provider_name, e)

        self._current_source = ""
        return None

    def fetch_history(
        self,
        symbol: str,
        period: str = "1d",
        start: str = None,
        end: str = None,
        adjust: str = "qfq"
    ) -> Optional[pd.DataFrame]:
        """Fetch historical kline data for a date range.

        Args:
            symbol: stock/fund code
            period: kline period ("1m", "5m", "30m", "1d")
            start: start date YYYY-MM-DD (default: 1 year ago)
            end: end date YYYY-MM-DD (default: today)
            adjust: fq type ("qfq", "hfq", "None")

        Returns:
            DataFrame with columns [ts, open, high, low, close, vol, ...] or None
        """
        if not start:
            start = (date.today() - timedelta(days=365)).isoformat()
        if not end:
            end = date.today().isoformat()
        asset_type = self._detect_asset_type(symbol)
        provider_name, provider = self._get_active_provider()
        if provider is None:
            return None

        # Minute-level data: fetch month-by-month to respect API limits
        if period in MINUTE_PERIODS:
            pages = []
            for ms, me in self._iter_month_ranges(start, end):
                data = self._fetch_range(provider, symbol, period, ms, me, adjust, asset_type)
                if data is not None and not data.empty:
                    pages.append(data)
            if pages:
                result = pd.concat(pages, ignore_index=True)
                result = result.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
                self._current_source = provider_name
                return result
            self._current_source = ""
            return None

        # 1d: fetch in one shot
        data = self._fetch_range(provider, symbol, period, start, end, adjust, asset_type)
        if data is not None and not data.empty:
            self._current_source = provider_name
            return data

        self._current_source = ""
        return None

    def _fetch_range(self, provider, symbol, period, start, end, adjust, asset_type) -> Optional[pd.DataFrame]:
        """Call provider.fetch_kline, return data or None on any exception."""
        try:
            return provider.fetch_kline(
                code=symbol, period=period,
                start=start, end=end,
                adjust=adjust, asset_type=asset_type
            )
        except Exception as e:
            logger.warning("fetch_kline failed [%s]: %s", provider.__class__.__name__, e)
            return None

    @staticmethod
    def _iter_month_ranges(start: str, end: str):
        """Yield (month_start, month_end) pairs for each month in [start, end].

        Minute-level data (1m/5m/30m) should be fetched month-by-month to respect
        API row limits. Yields tuples of (YYYY-MM-DD, YYYY-MM-DD).
        month_end is clamped to the last day of each calendar month.
        """
        from calendar import monthrange
        cur = datetime.strptime(start, "%Y-%m-%d")
        final = datetime.strptime(end, "%Y-%m-%d")
        while cur <= final:
            _, last_day = monthrange(cur.year, cur.month)
            month_end = cur.replace(day=last_day, hour=23, minute=59, second=59)
            yield (cur.strftime("%Y-%m-%d"), min(month_end, final).strftime("%Y-%m-%d"))
            month = cur.month + 1
            year = cur.year
            if month > 12:
                month = 1
                year += 1
            cur = datetime(year, month, 1)

    def _ensure_table(self, period: str) -> str:
        """Ensure the period table exists, create it if not."""
        table = PERIOD_TABLE_MAP.get(period)
        if not table:
            raise ValueError(f"Invalid period '{period}'. Must be one of: {list(PERIOD_TABLE_MAP.keys())}")
        if self._db is None:
            self._db = PGConnector()
        self._db.execute_update(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                ts TIMESTAMP NOT NULL,
                symbol VARCHAR(10) NOT NULL,
                open DECIMAL(10, 3) NOT NULL,
                high DECIMAL(10, 3) NOT NULL,
                low DECIMAL(10, 3) NOT NULL,
                close DECIMAL(10, 3) NOT NULL,
                vol BIGINT NOT NULL,
                amount DECIMAL(20, 2) NOT NULL,
                PRIMARY KEY (ts, symbol)
            )
        """)
        return table


    def save_to_db(
        self,
        data: List[Dict[str, Any]],
        period: str = '1d'
    ) -> int:
        """
        保存数据到数据库 - 支持PostgreSQL

        Args:
            data: 原始数据列表（来自数据源API）
            period: 周期 ('1m', '5m', '30m', '1d')

        Returns:
            保存的记录数
        """
        if not data:
            return 0

        try:
            from stockpush.pg_connector import PGConnector
            from stockpush.data_down.data_down import DataDownService
        except ImportError:
            return 0

        # 调用标准化处理（与F3.1保持一致）
        try:
            # 临时创建DataDownService实例用于标准化
            temp_service = DataDownService()
            normalized_data = []
            for row in data:
                # 提取symbol（从第一条记录）
                symbol = row.get('symbol', '')
                normalized = temp_service._normalize_kline_row(row, symbol, period)
                if normalized:
                    normalized_data.append(normalized)
            data = normalized_data
        except Exception as e:
            logger.warning("时间戳标准化失败，将使用原始数据: %s", e)

        table_name = self._ensure_table(period)

        try:
            if self._db is None:
                self._db = PGConnector()

            saved = 0
            columns = ["ts", "symbol", "open", "high", "low", "close", "vol", "amount"]
            placeholders = ", ".join(["%s"] * len(columns))
            columns_str = ", ".join(columns)
            sql = f"""
                INSERT INTO {table_name}
                ({columns_str})
                VALUES ({placeholders})
                ON CONFLICT (ts, symbol) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    vol = EXCLUDED.vol,
                    amount = EXCLUDED.amount
            """

            for record in data:
                try:
                    params = tuple(record.get(col) for col in columns)
                    self._db.execute_update(sql, params)
                    saved += 1
                except Exception as e:
                    logger.warning("Failed to insert record into %s: %s", table_name, e)
                    continue
            return saved

        except Exception as e:
            logger.error("save_to_db failed: %s", e)
            return 0

    def _try_seed_intraday(self, symbol: str, period: str):
        """当日线数据可用但 intraday 为空时，用今日日线 open 垫第一根 K 线。

        合成 K 线时间戳对齐 xtick 第一根真实 bar：
          5m → 09:35,  30m → 10:00
        后续 xtick 正式数据写入时自动覆写（ON CONFLICT DO UPDATE）。
        """
        if period not in ("5m", "30m"):
            return
        try:
            from stockpush.pg_connector import PGConnector
            db = PGConnector()
        except Exception:
            return

        try:
            today = date.today().isoformat()

            # 取今日日线 open
            rows = db.execute_query(
                "SELECT open FROM tb_raw_1d "
                "WHERE symbol = %s AND ts::date = %s "
                "ORDER BY ts DESC LIMIT 1",
                (symbol, today)
            )
            if not rows:
                return

            hour, minute = (9, 35) if period == "5m" else (10, 0)
            ts = datetime.combine(date.today(), time(hour, minute, 0))

            # 已有则跳过（避免重复垫入）
            table = PERIOD_TABLE_MAP.get(period, "")
            existing = db.execute_query(
                "SELECT 1 FROM %s WHERE symbol = %%s AND ts = %%s LIMIT 1" % table,
                (symbol, ts)
            )
            if existing:
                return

            columns = ["ts", "symbol", "open", "high", "low", "close", "vol", "amount"]
            placeholders = ", ".join(["%s"] * len(columns))
            columns_str = ", ".join(columns)
            sql = (
                f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders}) "
                "ON CONFLICT (ts, symbol) DO UPDATE SET "
                "open = EXCLUDED.open, high = EXCLUDED.high, "
                "low = EXCLUDED.low, close = EXCLUDED.close, "
                "vol = EXCLUDED.vol, amount = EXCLUDED.amount"
            )
            params = (ts, symbol, open_price, open_price, open_price, open_price, 0, 0)
            db.execute_update(sql, params)
            logger.info("Seeded %s %s with daily open=%.3f (ts=%s)", period, symbol, open_price, ts)
        except Exception as e:
            logger.warning("Failed to seed intraday bar for %s %s: %s", period, symbol, e)
        finally:
            db.close()

    def fetch_and_save(
        self,
        symbol: str,
        period: str = '1d',
        adjust: str = 'qfq',
        log_callback=None,
    ) -> Tuple[bool, int, str]:
        """
        获取数据并保存到数据库

        Args:
            symbol: 股票代码
            period: 周期 ('1m', '5m', '30m', '1d')
            adjust: 复权类型 ('qfq', 'hfq', 'None')
            log_callback: 可选回调, 传入原始DataFrame用于日志记录
        Returns:
            (success, saved_count, source)
        """
        df = self.fetch_kline(symbol, period, adjust)
        if df is None or df.empty:
            # ★ 5m/30m 无数据时用今日日线 open 垫合成 K 线
            self._try_seed_intraday(symbol, period)
            return False, 0, self._current_source or ""

        if callable(log_callback):
            try:
                log_callback(df)
            except Exception:
                pass

        records = self._normalize_data(df, symbol)
        if not records:
            return False, 0, self._current_source

        saved = self.save_to_db(records, period)
        return saved > 0, saved, self._current_source

    def fetch_and_save_history(
        self,
        symbol: str,
        period: str = "1d",
        start: str = None,
        end: str = None,
        adjust: str = "qfq"
    ) -> Tuple[bool, int, str]:
        """Fetch historical kline data and save to database.

        Returns:
            (success, saved_count, source)
        """
        df = self.fetch_history(symbol, period, start, end, adjust)
        if df is None or df.empty:
            return False, 0, self._current_source or ""

        records = self._normalize_data(df, symbol)
        if not records:
            return False, 0, self._current_source

        saved = self.save_to_db(records, period)
        return saved > 0, saved, self._current_source

    def _normalize_data(
        self,
        data: pd.DataFrame,
        symbol: str
    ) -> List[Dict[str, Any]]:
        """
        标准化数据格式

        Args:
            data: 原始 DataFrame
            symbol: 股票代码

        Returns:
            标准化后的字典列表
        """
        records = []

        for _, row in data.iterrows():
            ts = self._to_datetime(row.get('ts') or row.get('datetime') or row.get('date'))
            if ts is None:
                continue

            record = {
                'ts': ts,
                'symbol': symbol,
                'open': self._to_float(row.get('open')),
                'high': self._to_float(row.get('high')),
                'low': self._to_float(row.get('low')),
                'close': self._to_float(row.get('close')),
                'vol': self._to_float(row.get('vol') or row.get('volume')),
                'amount': self._to_float(row.get('amount')),
            }
            records.append(record)

        return records

    @staticmethod
    def _to_datetime(value: Any) -> Optional[datetime]:
        """转换为 datetime"""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value / 1000 if value > 1e10 else value)
            except Exception:
                return None
        try:
            return pd.to_datetime(value).to_pydatetime()
        except Exception:
            return None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """转换为 float"""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def get_current_source(self) -> str:
        """
        获取当前数据源

        Returns:
            数据源名称
        """
        return self._current_source

    def check_today_data_complete(self, symbol: str, period: str = '1d') -> bool:
        """
        检查今日数据是否完整

        Args:
            symbol: 股票代码
            period: 周期

        Returns:
            True=完整，False=不完整或无法判断
        """
        try:
            from stockpush.pg_connector import PGConnector
        except ImportError:
            return True

        if period not in PERIOD_TABLE_MAP:
            raise ValueError(f"Invalid period '{period}'. Must be one of: {list(PERIOD_TABLE_MAP.keys())}")
        table_name = PERIOD_TABLE_MAP[period]

        try:
            if self._db is None:
                self._db = PGConnector()

            table_name = PERIOD_TABLE_MAP[period]

            # 获取今日开始时间戳
            today_start = datetime.combine(date.today(), datetime.min.time())
            today_end = datetime.combine(date.today(), datetime.max.time())

            result = self._db.execute_query(
                f"""
                SELECT COUNT(*) as cnt FROM {table_name}
                WHERE symbol = ? AND ts >= ? AND ts <= ?
                """,
                (symbol, today_start, today_end)
            )

            if not result:
                return False

            count = result[0].get('cnt', 0) if isinstance(result[0], dict) else result[0][0]
            return count > 0

        except Exception as e:
            logger.warning("check_today_data_complete failed for %s %s: %s", symbol, period, e)
            return False  # 检查失败时默认视为不完整