"""
标准API适配器
为所有Provider添加统一的标准API接口，适配到现有方法

创建日期: 2026-02-15
更新日期: 2026-05-02
目的: 使所有Provider符合DataSourceRegistry的11个标准API接口

【复权说明】
- 所有历史日线/分钟线数据默认使用"前复权"(qfq)
- 复权参数: adjust='qfq' (前复权) / 'hfq' (后复权) / '' (不复权)
- 注意: 分钟线数据通常不支持复权
"""
from typing import Union
import pandas as pd
from stockpush.log_manager import LogManager


class StandardAPIAdapter:
    """
    标准API适配器Mixin类
    为Provider添加标准API方法，内部调用现有的fetch_xxx方法

    【设计原则】
    1. 所有历史行情数据默认使用前复权(qfq)
    2. Provider若不支持某复权方式，调用时会忽略或报错
    3. 实时数据不需要复权参数
    4. 日期参数统一截断为 YYYY-MM-DD 格式（部分Provider不支持带时间戳）
    """

    DEFAULT_ADJUST = 'qfq'

    @staticmethod
    def _date_only(dt_str: str) -> str:
        """截断日期时间为纯日期 YYYY-MM-DD（部分Provider不支持时间戳）"""
        return dt_str[:10] if dt_str else dt_str

    def __init__(self):
        if not hasattr(self, 'logger'):
            self.logger = LogManager().get_logger(self.__class__.__name__)

    # ========== API01: 股票历史日线 ==========
    def fetch_stock_history_daily(self, code: str, start: str, end: str,
                                   adjust: str = 'qfq') -> Union[pd.DataFrame, int]:
        try:
            if hasattr(self, 'fetch_stock_daily'):
                sd, ed = self._date_only(start), self._date_only(end)
                try:
                    return self.fetch_stock_daily(code, sd, ed, adjust=adjust)
                except TypeError:
                    return self.fetch_stock_daily(code, sd, ed)
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_stock_daily")
                return -1
        except Exception as e:
            self.logger.error(f"API01调用失败: {e}")
            return -1

    # ========== API02: 股票历史分钟线 ==========
    def fetch_stock_history_minute(self, code: str, period: str, start: str, end: str,
                                    adjust: str = 'qfq') -> Union[pd.DataFrame, int]:
        try:
            method_map = {
                '1': 'fetch_stock_1min',
                '5': 'fetch_stock_5min',
                '15': 'fetch_stock_15min',
                '30': 'fetch_stock_30min',
                '60': 'fetch_stock_60min',
            }

            method_name = method_map.get(period)
            if not method_name:
                self.logger.error(f"不支持的周期: {period}")
                return -1

            if hasattr(self, method_name):
                method = getattr(self, method_name)
                try:
                    return method(code, start, end, adjust=adjust)
                except TypeError:
                    return method(code, start, end)
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 {method_name}")
                return -1
        except Exception as e:
            self.logger.error(f"API02调用失败: {e}")
            return -1
    
    # ========== API03: 股票实时行情（日线级别） ==========
    def fetch_stock_realtime_daily(self, code: str) -> Union[dict, int]:
        """
        API03: 获取股票实时行情（日线级别）
        
        Args:
            code: 股票代码
        
        Returns:
            成功: dict，包含 {code, name, price, change, volume, open, high, low, ...}
            失败: -1
        """
        try:
            if hasattr(self, 'fetch_stock_realtime'):
                df = self.fetch_stock_realtime(code)
                if df is not None and not df.empty:
                    # 转换DataFrame为dict
                    return df.iloc[0].to_dict()
                return -1
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_stock_realtime")
                return -1
        except Exception as e:
            self.logger.error(f"API03调用失败: {e}")
            return -1

    # ========== API04: 股票实时分钟线 ==========
    def fetch_stock_realtime_minute(self, code: str) -> Union[pd.DataFrame, int]:
        """
        API04: 获取股票实时分钟线数据

        Args:
            code: 股票代码

        Returns:
            成功: DataFrame（最近若干分钟的数据）
            失败: -1
        """
        try:
            # 通常实时分钟线就是获取最近的1分钟数据
            if hasattr(self, 'fetch_stock_1min'):
                from datetime import datetime, timedelta
                end = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                start = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
                return self.fetch_stock_1min(code, start, end)
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_stock_1min")
                return -1
        except Exception as e:
            self.logger.error(f"API04调用失败: {e}")
            return -1

    # ========== API05: 基金历史日线 ==========
    def fetch_fund_history_daily(self, code: str, start: str, end: str,
                                  adjust: str = 'qfq') -> Union[pd.DataFrame, int]:
        try:
            if hasattr(self, 'fetch_fund_daily'):
                sd, ed = self._date_only(start), self._date_only(end)
                try:
                    return self.fetch_fund_daily(code, sd, ed, adjust=adjust)
                except TypeError:
                    return self.fetch_fund_daily(code, sd, ed)
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_fund_daily")
                return -1
        except Exception as e:
            self.logger.error(f"API05调用失败: {e}")
            return -1

    # ========== API06: 基金历史分钟线 ==========
    def fetch_fund_history_minute(self, code: str, period: str, start: str, end: str,
                                  adjust: str = 'qfq') -> Union[pd.DataFrame, int]:
        try:
            method_map = {
                '1': 'fetch_fund_1min',
                '5': 'fetch_fund_5min',
                '15': 'fetch_fund_15min',
                '30': 'fetch_fund_30min',
                '60': 'fetch_fund_60min',
            }

            method_name = method_map.get(period)
            if not method_name:
                self.logger.error(f"不支持的周期: {period}")
                return -1
            
            if hasattr(self, method_name):
                method = getattr(self, method_name)
                try:
                    return method(code, start, end, adjust=adjust)
                except TypeError:
                    return method(code, start, end)
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 {method_name}")
                return -1
        except Exception as e:
            self.logger.error(f"API06调用失败: {e}")
            return -1
    
    # ========== API07: 基金实时行情（日线级别） ==========
    def fetch_fund_realtime_daily(self, code: str) -> Union[dict, int]:
        """
        API07: 获取基金实时行情（日线级别）
        
        Args:
            code: 基金代码
        
        Returns:
            成功: dict
            失败: -1
        """
        try:
            if hasattr(self, 'fetch_fund_realtime'):
                df = self.fetch_fund_realtime(code)
                if df is not None and not df.empty:
                    return df.iloc[0].to_dict()
                return -1
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_fund_realtime")
                return -1
        except Exception as e:
            self.logger.error(f"API07调用失败: {e}")
            return -1
    
    # ========== API08: 基金实时分钟线 ==========
    def fetch_fund_realtime_minute(self, code: str) -> Union[pd.DataFrame, int]:
        """
        API08: 获取基金实时分钟线数据
        
        Args:
            code: 基金代码
        
        Returns:
            成功: DataFrame
            失败: -1
        """
        try:
            if hasattr(self, 'fetch_fund_1min'):
                from datetime import datetime, timedelta
                end = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                start = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
                return self.fetch_fund_1min(code, start, end)
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_fund_1min")
                return -1
        except Exception as e:
            self.logger.error(f"API08调用失败: {e}")
            return -1

    # ========== API09: 股票代码列表 ==========
    def fetch_stock_list(self) -> Union[pd.DataFrame, int]:
        """
        API09: 获取股票代码列表

        Returns:
            成功: DataFrame，字段包含 [code, name]
            失败: -1
        """
        try:
            _p = getattr(self, 'provider', None)
            if _p is not None and hasattr(_p, 'fetch_stock_list'):
                return _p.fetch_stock_list()
            elif hasattr(self, '_fetch_stock_list'):
                return self._fetch_stock_list()
            elif hasattr(self, 'get_stock_list'):
                return self.get_stock_list()
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_stock_list")
                return -1
        except Exception as e:
            self.logger.error(f"API09调用失败: {e}")
            return -1

    # ========== API10: 基金代码列表 ==========
    def fetch_fund_list(self) -> Union[pd.DataFrame, int]:
        """
        API10: 获取基金代码列表

        Returns:
            成功: DataFrame，字段包含 [code, name]
            失败: -1
        """
        try:
            _p = getattr(self, 'provider', None)
            if _p is not None and hasattr(_p, 'fetch_fund_list'):
                return _p.fetch_fund_list()
            elif hasattr(self, '_fetch_fund_list'):
                return self._fetch_fund_list()
            elif hasattr(self, 'get_fund_list'):
                return self.get_fund_list()
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_fund_list")
                return -1
        except Exception as e:
            self.logger.error(f"API10调用失败: {e}")
            return -1

    # ========== API11: 交易日历 ==========
    def fetch_trade_calendar(self, start: str, end: str) -> Union[pd.DataFrame, int]:
        """
        API11: 获取交易日历

        Args:
            start: 开始日期 YYYY-MM-DD
            end: 结束日期 YYYY-MM-DD

        Returns:
            成功: DataFrame，字段包含 [date]
            失败: -1
        """
        try:
            _p = getattr(self, 'provider', None)
            if _p is not None and hasattr(_p, 'fetch_trade_calendar'):
                return _p.fetch_trade_calendar(start, end)
            elif hasattr(self, '_fetch_trade_calendar'):
                return self._fetch_trade_calendar(start, end)
            elif hasattr(self, 'get_trade_calendar'):
                return self.get_trade_calendar(start, end)
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_trade_calendar")
                return -1
        except Exception as e:
            self.logger.error(f"API11调用失败: {e}")
            return -1

    # ========== API12: 最新分红日期 ==========
    def fetch_latest_dividend_date(self, code: str, asset_type: str = 'stock', **kwargs) -> Union[dict, int]:
        """
        API12: 获取指定证券的最新分红日期

        Args:
            code: 证券代码
            asset_type: 资产类型 'stock' 或 'fund'
            **kwargs: 可选参数 (year, year_type, date_field_priority)

        Returns:
            成功: dict，包含 {code, latest_dividend_date, date_field, ...}
            失败: -1
        """
        try:
            _p = getattr(self, 'provider', None)
            if _p is not None and hasattr(_p, 'fetch_latest_dividend_date'):
                return _p.fetch_latest_dividend_date(code, asset_type, **kwargs)
            elif hasattr(self, '_fetch_latest_dividend_date'):
                return self._fetch_latest_dividend_date(code, asset_type, **kwargs)
            elif hasattr(self, 'get_dividend'):
                return self.get_dividend(code, asset_type)
            else:
                self.logger.warning(f"{self.__class__.__name__} 未实现 fetch_latest_dividend_date")
                return -1
        except Exception as e:
            self.logger.error(f"API12调用失败: {e}")
            return -1
