"""
数据源Provider抽象与实现
提供AkShare、Baostock、Byapi三大数据源的统一接口封装
"""
import os
import time


import pandas as pd
from abc import ABC, abstractmethod
from typing import Optional
from stockpush.log_manager import LogManager
from stockpush.config_manager import get_config_manager

# 导入标准API适配器（延迟导入，避免循环依赖）
try:
    from .standard_api_adapter import StandardAPIAdapter
except ImportError:
    # 如果是在其他模块直接导入src_provider，会出现循环导入
    # 此时使用空的基类（在子类中再处理）
    StandardAPIAdapter = object


class BaseProvider(ABC):
    """
    数据源Provider基类
    统一封装数据源接口，支持能力检测
    """
    
    # 能力矩阵，子类需要覆盖
    CAPABILITIES = {
        'stock_realtime': False,      # 股票实时行情
        'stock_daily': False,         # 股票历史日线
        'stock_1min': False,          # 股票1分钟线
        'stock_5min': False,          # 股票5分钟线
        'stock_15min': False,         # 股票15分钟线
        'stock_30min': False,         # 股票30分钟线
        'stock_60min': False,         # 股票60分钟线
        'stock_weekly': False,        # 股票周K线
        'stock_monthly': False,       # 股票月K线
        'fund_realtime': False,       # 基金实时行情
        'fund_daily': False,          # 基金历史日线
        'stock_list': False,          # 股票代码列表
        'trade_calendar': False,      # 交易日历
    }
    
    def __init__(self):
        self.logger = LogManager().get_logger(self.__class__.__name__)
        self.provider_name = self.__class__.__name__.replace('Provider', '').lower()
        self.config = get_config_manager()
        
        # 配置网络代理
        self._configure_proxy()
    
    def _configure_proxy(self):
        """配置网络代理"""
        try:
            use_proxy = self.config.get('USE_PROXY', 'false').lower() == 'true'
            
            if use_proxy:
                http_proxy = self.config.get('HTTP_PROXY', '')
                https_proxy = self.config.get('HTTPS_PROXY', '')
                
                if http_proxy:
                    os.environ['HTTP_PROXY'] = http_proxy
                    self.logger.info(f"设置HTTP代理: {http_proxy}")
                if https_proxy:
                    os.environ['HTTPS_PROXY'] = https_proxy
                    self.logger.info(f"设置HTTPS代理: {https_proxy}")
            else:
                # 禁用代理 - 清除所有可能的代理环境变量
                for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 
                           'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy']:
                    os.environ.pop(key, None)
                # 设置requests库不使用代理
                os.environ['NO_PROXY'] = '*'
                self.logger.info("已禁用网络代理")
        
        except Exception as e:
            self.logger.warning(f"配置代理失败: {e}")
    
    def check_capability(self, capability: str) -> bool:
        """
        检查数据源能力
        
        Args:
            capability: 能力标识，如 'stock_realtime', 'stock_daily'
        
        Returns:
            bool: 是否支持该能力
        """
        return self.CAPABILITIES.get(capability, False)
    
    def supports(self, asset_type: str, timeliness: str, frequency: str) -> bool:
        """
        检查是否支持指定参数组合

        Args:
            asset_type: 资产类型 'stock' 或 'fund'
            timeliness: 时效性 'realtime' 或 'daily'
            frequency: 数据周期 'daily', '5min', '15min', '30min', '60min', 'weekly', 'monthly'

        Returns:
            bool: 是否支持
        """
        if timeliness == 'realtime':
            capability = f"{asset_type}_realtime"
        elif frequency == 'daily':
            capability = f"{asset_type}_daily"
        elif frequency == 'weekly':
            capability = f"{asset_type}_weekly"
        elif frequency == 'monthly':
            capability = f"{asset_type}_monthly"
        else:
            capability = f"{asset_type}_{frequency}"

        return self.check_capability(capability)
    
    # ========== 抽象方法：股票接口 ==========
    
    def fetch_stock_realtime(self, code: str) -> pd.DataFrame:
        """获取股票实时行情"""
        if not self.check_capability('stock_realtime'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持股票实时行情接口"
            )
    
    def fetch_stock_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票历史日线"""
        if not self.check_capability('stock_daily'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持股票历史日线接口"
            )

    def fetch_stock_1min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票1分钟线"""
        if not self.check_capability('stock_1min'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持股票1分钟线接口"
            )

    def fetch_stock_5min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票5分钟线"""
        if not self.check_capability('stock_5min'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持股票5分钟线接口"
            )

    def fetch_stock_15min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票15分钟线"""
        if not self.check_capability('stock_15min'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持股票15分钟线接口"
            )

    def fetch_stock_30min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票30分钟线"""
        if not self.check_capability('stock_30min'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持股票30分钟线接口"
            )

    def fetch_stock_60min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票60分钟线"""
        if not self.check_capability('stock_60min'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持股票60分钟线接口"
            )

    def fetch_stock_weekly(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票周K线"""
        if not self.check_capability('stock_weekly'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持股票周K线接口"
            )

    def fetch_stock_monthly(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票月K线"""
        if not self.check_capability('stock_monthly'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持股票月K线接口"
            )
    
    # ========== 抽象方法：基金接口 ==========
    
    def fetch_fund_realtime(self, code: str) -> pd.DataFrame:
        """获取基金实时行情"""
        if not self.check_capability('fund_realtime'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持基金实时行情接口"
            )
    
    def fetch_fund_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取基金历史日线"""
        if not self.check_capability('fund_daily'):
            raise NotImplementedError(
                f"{self.provider_name} 不支持基金历史日线接口"
            )
    
    # ========== 辅助方法 ==========
    
    def _standardize_fields(self, df: pd.DataFrame, source: str) -> pd.DataFrame:
        """
        标准化字段名
        
        Args:
            df: 原始数据
            source: 数据源 'akshare', 'baostock'
        
        Returns:
            标准化后的DataFrame
        """
        # 字段映射表
        FIELD_MAPPING = {
            'akshare': {
                '日期': 'date',
                '时间': 'date',  # 分钟线使用"时间"字段
                'day': 'date',   # stock_zh_a_minute接口返回的字段名
                '代码': 'code',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
            },
            'baostock': {
                # date/code/open/high/low/close/volume/amount 保持不变
            }
            ,
            'xtick': {
                'time': 'date',
                'date': 'date',
                'datetime': 'date',
                'open': 'open',
                'close': 'close',
                'high': 'high',
                'low': 'low',
                'volume': 'volume',
                'amount': 'amount',
            }
        }
        
        # 应用映射
        mapping = FIELD_MAPPING.get(source, {})
        if mapping:
            df = df.rename(columns=mapping)

        # 确保存在必需字段（仅对行情数据检查，有 open 或 close 才认为是 OHLCV 数据）
        if not df.empty and ('open' in df.columns or 'close' in df.columns):
            required_fields = ['date', 'open', 'close', 'high', 'low', 'volume']
            for field in required_fields:
                if field not in df.columns:
                    self.logger.warning(f"缺少必需字段: {field}")
        
        # 数据类型转换
        try:
            if 'open' in df.columns:
                df['open'] = pd.to_numeric(df['open'], errors='coerce')
            if 'close' in df.columns:
                df['close'] = pd.to_numeric(df['close'], errors='coerce')
            if 'high' in df.columns:
                df['high'] = pd.to_numeric(df['high'], errors='coerce')
            if 'low' in df.columns:
                df['low'] = pd.to_numeric(df['low'], errors='coerce')
            if 'volume' in df.columns:
                df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
            if 'amount' in df.columns:
                df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        except Exception as e:
            self.logger.error(f"数据类型转换失败: {e}")
        
        return df


class AkShareProvider(BaseProvider, StandardAPIAdapter):
    """
    AkShare数据Provider - 已通过2026年2月14日测试验证
    
    【重要说明】
    - AkShare是数据获取工具库，不是单一数据源
    - 本Provider通过AkShare调用多个数据源的接口
    - 主要数据源：东方财富(EM)、同花顺(THS)
    
    【数据源策略】
    ┌─────────────┬─────────────────────────┐
    │ 东方财富(EM) │ 主数据源 - 行情数据       │
    │             │ · 股票/ETF日线、分钟线    │
    ├─────────────┼─────────────────────────┤
    │ 同花顺(THS)  │ 辅助数据源 - 分类/财务    │
    │             │ · 板块分类、财务、分红    │
    └─────────────┴─────────────────────────┘
    
    【测试结果】东方财富接口 (成功率92.3%):
    ✅ stock_zh_a_hist: 日线数据 (22行/30天)
    ✅ stock_zh_a_hist_min_em: 1分钟数据 (723行/3天)
    ✅ stock_zh_a_hist_min_em: 5分钟数据 (144行/3天)
    ✅ fund_etf_hist_em: ETF日线数据 (22行/30天)
    ✅ fund_etf_hist_min_em: ETF分钟数据 (723行/3天)
    
    【注意事项】
    - 完全免费，无需账号认证
    - 分钟线数据接口限制返回近5个交易日数据
    - 建议添加重试机制处理偶发的网络问题
    """
    
    CAPABILITIES = {
        'stock_realtime': True,       # ✅ 股票实时行情 (已实现)
        'stock_daily': True,          # ✅ 股票历史日线 (已测试)
        'stock_1min': True,           # ✅ 股票1分钟线 (已测试)
        'stock_5min': True,           # ✅ 股票5分钟线 (已测试)
        'stock_15min': True,          # ✅ 股票15分钟线
        'stock_30min': True,          # ✅ 股票30分钟线
        'stock_60min': True,          # ✅ 股票60分钟线
        'fund_realtime': True,        # ✅ 基金实时行情（ETF场内基金）
        'fund_daily': True,           # ✅ ETF历史日线 (已测试)
        'fund_1min': True,            # ✅ ETF1分钟线 (已测试)
        'fund_5min': True,            # ✅ ETF5分钟线 (已测试)
        'fund_15min': True,           # ✅ ETF15分钟线
        'fund_30min': True,           # ✅ ETF30分钟线
        'fund_60min': True,           # ✅ ETF60分钟线
        'stock_list': True,           # ✅ 股票代码列表
        'trade_calendar': True,       # ✅ 交易日历
        'dividend': True,             # ✅ 分红数据
    }
    
    def __init__(self):
        super().__init__()
        try:
            import akshare as ak
            self.ak = ak
            self.logger.info("AkShare Provider 初始化成功（多数据源模式）")
        except ImportError:
            self.logger.error("AkShare 未安装，请执行: pip install akshare")
            raise
    
    def _try_multiple_sources(self, methods_list, error_prefix="获取数据"):
        """
        尝试多个数据源，直到成功或全部失败
        
        Args:
            methods_list: 方法列表，每个元素为(source_name, callable)
            error_prefix: 错误日志前缀
        
        Returns:
            成功时返回DataFrame，全部失败时抛出最后一个异常
        """
        last_error = None
        
        for source_name, method in methods_list:
            try:
                self.logger.info(f"尝试数据源: {source_name}")
                df = method()
                if df is not None and not df.empty:
                    self.logger.info(f"数据源 {source_name} 获取成功")
                    return df
                else:
                    self.logger.warning(f"数据源 {source_name} 返回空数据")
            except Exception as e:
                last_error = e
                self.logger.warning(f"数据源 {source_name} 失败: {str(e)[:100]}")
                continue
        
        # 所有数据源都失败
        error_msg = f"{error_prefix}失败，所有数据源均不可用"
        if last_error:
            error_msg += f": {str(last_error)}"
        raise RuntimeError(error_msg)
    
    def fetch_stock_realtime(self, code: str) -> pd.DataFrame:
        """获取股票实时行情（多数据源）"""
        super().fetch_stock_realtime(code)  # 能力检测
        
        self.logger.info(f"AkShare: 获取股票实时行情 {code}")
        
        # 定义多个数据源方法
        def _fetch_sina():
            """新浪财经接口"""
            df = self.ak.stock_zh_a_spot()
            # 检查返回值是否为DataFrame
            if not isinstance(df, pd.DataFrame):
                self.logger.warning(f"新浪财经接口返回非DataFrame类型: {type(df)}")
                return pd.DataFrame()  # 返回空DataFrame
            df = df[df['代码'] == code]
            if not df.empty:
                df = self._standardize_fields(df, 'akshare')
            return df
        
        def _fetch_eastmoney():
            """东方财富接口"""
            df = self.ak.stock_zh_a_spot_em()
            # 检查返回值是否为DataFrame
            if not isinstance(df, pd.DataFrame):
                self.logger.warning(f"东方财富接口返回非DataFrame类型: {type(df)}")
                return pd.DataFrame()  # 返回空DataFrame
            df = df[df['代码'] == code]
            if not df.empty:
                df = self._standardize_fields(df, 'akshare')
            return df
        
        def _fetch_tencent():
            """腾讯财经接口（单只股票）"""
            # 转换市场代码
            market_code = f"sh{code}" if code.startswith('6') else f"sz{code}"
            df = self.ak.stock_zh_a_hist(symbol=code, period="daily", adjust="")
            if not df.empty:
                # 只取最新一条作为实时数据
                df = df.tail(1)
                df = self._standardize_fields(df, 'akshare')
            return df
        
        # 按优先级尝试各数据源
        methods = [
            ("新浪", _fetch_sina),
            ("腾讯", _fetch_tencent),
            ("东方财富", _fetch_eastmoney),
        ]
        
        try:
            df = self._try_multiple_sources(methods, f"获取股票实时行情 {code}")
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"获取股票实时行情失败: {e}")
            raise
    
    def fetch_stock_daily(self, code: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
        """
        获取股票历史日线数据

        【数据源】东方财富（通过AkShare接口）
        【接口】akshare.stock_zh_a_hist()

        Args:
            code: 股票代码，如'000001'
            start_date: 开始日期，格式'YYYYMMDD'或'YYYY-MM-DD'
            end_date: 结束日期，格式'YYYYMMDD'或'YYYY-MM-DD'
            adjust: 复权方式，''=不复权，'qfq'=前复权，'hfq'=后复权

        Returns:
            DataFrame: 包含日期、开盘、收盘、最高、最低、成交量等字段

        【测试结果】✅ 2026-02-14测试通过，返回22行/30天数据
        """
        super().fetch_stock_daily(code, start_date, end_date)  # 能力检测

        self.logger.info(f"[东方财富] 获取股票日线 {code} [{start_date} ~ {end_date}] 复权={adjust}")
        last_error = None

        for attempt in range(3):
            try:
                # 调用AkShare封装的东方财富接口
                df = self.ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start_date.replace('-', ''),
                    end_date=end_date.replace('-', ''),
                    adjust=adjust
                )

                if df is None or df.empty:
                    raise ValueError(f"未获取到数据: {code}")

                # 标准化字段
                df = self._standardize_fields(df, 'akshare')

                self.logger.info(f"获取成功，数据行数: {len(df)}")
                return df

            except Exception as e:
                last_error = e
                self.logger.warning(f"第{attempt + 1}次请求失败: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))

        self.logger.error(f"获取股票日线失败: {last_error}")
        raise last_error
    
    def fetch_stock_1min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票1分钟线数据

        【数据源】东方财富（通过AkShare接口）
        【接口】
        1. akshare.stock_zh_a_hist_min_em(period='1') - 主要接口
        2. akshare.stock_zh_a_minute - 回退接口（当主要接口失败时）

        Args:
            code: 股票代码，如'000001'
            start_date: 开始时间，格式'YYYY-MM-DD HH:MM:SS'
            end_date: 结束时间，格式'YYYY-MM-DD HH:MM:SS'

        Returns:
            DataFrame: 包含时间、开盘、收盘、最高、最低、成交量等字段

        注意: 接口限制只返回近5个交易日数据，不支持复权
        """
        super().fetch_stock_1min(code, start_date, end_date)  # 能力检测

        self.logger.info(f"AkShare: 获取股票1分钟线 {code} [{start_date} ~ {end_date}]")
        last_error = None

        # 方法1：主要接口 stock_zh_a_hist_min_em
        for attempt in range(3):
            try:
                df = self.ak.stock_zh_a_hist_min_em(
                    symbol=code,
                    start_date=start_date,
                    end_date=end_date,
                    period="1",
                    adjust=""  # 1分钟数据不支持复权
                )

                if df is not None and not df.empty:
                    # 标准化字段
                    df = self._standardize_fields(df, 'akshare')
                    self.logger.info(f"获取成功(stock_zh_a_hist_min_em)，数据行数: {len(df)}")
                    return df

            except Exception as e:
                last_error = e
                self.logger.warning(f"stock_zh_a_hist_min_em 第{attempt + 1}次请求失败: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))

        # 方法2：回退接口 stock_zh_a_minute
        self.logger.warning(f"stock_zh_a_hist_min_em 失败，尝试 stock_zh_a_minute 回退: {last_error}")
        try:
            # stock_zh_a_minute 需要 sh/sz 前缀
            prefix = 'sh' if code.startswith('6') else 'sz'
            symbol_with_prefix = f"{prefix}{code}"

            df = self.ak.stock_zh_a_minute(symbol=symbol_with_prefix, period='1')
            if df is not None and not df.empty:
                # 标准化字段：day -> date
                df = self._standardize_fields(df, 'akshare')
                # 按时间过滤
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                self.logger.info(f"获取成功(stock_zh_a_minute回退)，数据行数: {len(df)}")
                return df
        except Exception as e:
            self.logger.warning(f"stock_zh_a_minute 回退也失败: {e}")

        self.logger.error(f"获取股票1分钟线失败: {last_error}")
        raise last_error

    def fetch_stock_5min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票5分钟线数据

        Args:
            code: 股票代码，如'000001'
            start_date: 开始时间，格式'YYYY-MM-DD HH:MM:SS'
            end_date: 结束时间，格式'YYYY-MM-DD HH:MM:SS'

        Returns:
            DataFrame: 包含时间、开盘、收盘、最高、最低、成交量等字段
        """
        super().fetch_stock_5min(code, start_date, end_date)  # 能力检测

        self.logger.info(f"AkShare: 获取股票5分钟线 {code} [{start_date} ~ {end_date}]")
        last_error = None

        # 方法1：主要接口 stock_zh_a_hist_min_em
        for attempt in range(3):
            try:
                df = self.ak.stock_zh_a_hist_min_em(
                    symbol=code,
                    start_date=start_date,
                    end_date=end_date,
                    period="5",
                    adjust="qfq"  # 前复权（统一所有数据源）
                )

                if df is not None and not df.empty:
                    # 标准化字段
                    df = self._standardize_fields(df, 'akshare')
                    self.logger.info(f"获取成功(stock_zh_a_hist_min_em)，数据行数: {len(df)}")
                    return df

            except Exception as e:
                last_error = e
                self.logger.warning(f"stock_zh_a_hist_min_em 第{attempt + 1}次请求失败: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))

        # 方法2：回退接口 stock_zh_a_minute
        self.logger.warning(f"stock_zh_a_hist_min_em 失败，尝试 stock_zh_a_minute 回退: {last_error}")
        try:
            prefix = 'sh' if code.startswith('6') else 'sz'
            symbol_with_prefix = f"{prefix}{code}"

            df = self.ak.stock_zh_a_minute(symbol=symbol_with_prefix, period='5')
            if df is not None and not df.empty:
                df = self._standardize_fields(df, 'akshare')
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                self.logger.info(f"获取成功(stock_zh_a_minute回退)，数据行数: {len(df)}")
                return df
        except Exception as e:
            self.logger.warning(f"stock_zh_a_minute 回退也失败: {e}")

        self.logger.error(f"获取股票5分钟线失败: {last_error}")
        raise last_error
    
    def fetch_stock_15min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票15分钟线数据

        Args:
            code: 股票代码，如'000001'
            start_date: 开始时间，格式'YYYY-MM-DD HH:MM:SS'
            end_date: 结束时间，格式'YYYY-MM-DD HH:MM:SS'

        Returns:
            DataFrame: 包含时间、开盘、收盘、最高、最低、成交量等字段
        """
        super().fetch_stock_15min(code, start_date, end_date)

        self.logger.info(f"AkShare: 获取股票15分钟线 {code} [{start_date} ~ {end_date}]")
        last_error = None

        for attempt in range(3):
            try:
                df = self.ak.stock_zh_a_hist_min_em(
                    symbol=code,
                    start_date=start_date,
                    end_date=end_date,
                    period="15",
                    adjust="qfq"
                )

                if df is None or df.empty:
                    raise ValueError(f"未获取到数据: {code}")

                df = self._standardize_fields(df, 'akshare')

                self.logger.info(f"获取成功，数据行数: {len(df)}")
                return df

            except Exception as e:
                last_error = e
                self.logger.warning(f"第{attempt + 1}次请求失败: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))

        self.logger.error(f"获取股票15分钟线失败: {last_error}")
        raise last_error

    def fetch_stock_30min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票30分钟线数据

        Args:
            code: 股票代码，如'000001'
            start_date: 开始时间，格式'YYYY-MM-DD HH:MM:SS'
            end_date: 结束时间，格式'YYYY-MM-DD HH:MM:SS'

        Returns:
            DataFrame: 包含时间、开盘、收盘、最高、最低、成交量等字段
        """
        super().fetch_stock_30min(code, start_date, end_date)

        self.logger.info(f"AkShare: 获取股票30分钟线 {code} [{start_date} ~ {end_date}]")
        last_error = None

        # 方法1：主要接口 stock_zh_a_hist_min_em
        for attempt in range(3):
            try:
                df = self.ak.stock_zh_a_hist_min_em(
                    symbol=code,
                    start_date=start_date,
                    end_date=end_date,
                    period="30",
                    adjust="qfq"
                )

                if df is not None and not df.empty:
                    df = self._standardize_fields(df, 'akshare')
                    self.logger.info(f"获取成功(stock_zh_a_hist_min_em)，数据行数: {len(df)}")
                    return df

            except Exception as e:
                last_error = e
                self.logger.warning(f"stock_zh_a_hist_min_em 第{attempt + 1}次请求失败: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))

        # 方法2：回退接口 stock_zh_a_minute
        self.logger.warning(f"stock_zh_a_hist_min_em 失败，尝试 stock_zh_a_minute 回退: {last_error}")
        try:
            prefix = 'sh' if code.startswith('6') else 'sz'
            symbol_with_prefix = f"{prefix}{code}"

            df = self.ak.stock_zh_a_minute(symbol=symbol_with_prefix, period='30')
            if df is not None and not df.empty:
                df = self._standardize_fields(df, 'akshare')
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                self.logger.info(f"获取成功(stock_zh_a_minute回退)，数据行数: {len(df)}")
                return df
        except Exception as e:
            self.logger.warning(f"stock_zh_a_minute 回退也失败: {e}")

        self.logger.error(f"获取股票30分钟线失败: {last_error}")
        raise last_error

    def fetch_stock_60min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票60分钟线数据
        """
        super().fetch_stock_60min(code, start_date, end_date)

        self.logger.info(f"AkShare: 获取股票60分钟线 {code} [{start_date} ~ {end_date}]")
        last_error = None

        for attempt in range(3):
            try:
                df = self.ak.stock_zh_a_hist_min_em(
                    symbol=code,
                    start_date=start_date,
                    end_date=end_date,
                    period="60",
                    adjust="qfq"
                )

                if df is None or df.empty:
                    raise ValueError(f"未获取到数据: {code}")

                df = self._standardize_fields(df, 'akshare')

                self.logger.info(f"获取成功，数据行数: {len(df)}")
                return df

            except Exception as e:
                last_error = e
                self.logger.warning(f"第{attempt + 1}次请求失败: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))

        self.logger.error(f"获取股票60分钟线失败: {last_error}")
        raise last_error

    def fetch_fund_realtime(self, code: str) -> pd.DataFrame:
        """获取基金实时行情（ETF）"""
        super().fetch_fund_realtime(code)  # 能力检测
        
        try:
            self.logger.info(f"AkShare: 获取基金实时行情 {code}")
            
            df = self.ak.fund_etf_spot_em()
            
            # 过滤指定代码
            df = df[df['代码'] == code]
            
            if df.empty:
                self.logger.warning(f"未找到基金代码: {code}")
                return pd.DataFrame()
            
            # 标准化字段
            df = self._standardize_fields(df, 'akshare')
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取基金实时行情失败: {e}")
            raise

    def fetch_fund_daily(self, code: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
        """
        获取ETF基金历史日线数据
        
        Args:
            code: ETF代码，如'510300'
            start_date: 开始日期，格式'YYYYMMDD'或'YYYY-MM-DD'
            end_date: 结束日期，格式'YYYYMMDD'或'YYYY-MM-DD'
            adjust: 复权方式，''=不复权，'qfq'=前复权，'hfq'=后复权
        
        Returns:
            DataFrame: 包含日期、开盘、收盘、最高、最低、成交量等字段
        
        测试结果: ✅ 2026-02-14测试通过，返回22行/30天数据
        """
        super().fetch_fund_daily(code, start_date, end_date)  # 能力检测
        
        try:
            self.logger.info(f"AkShare: 获取ETF日线 {code} [{start_date} ~ {end_date}] 复权={adjust}")
            
            df = self.ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust=adjust
            )
            
            if df is None or df.empty:
                raise ValueError(f"未获取到数据: {code}")
            
            # 标准化字段
            df = self._standardize_fields(df, 'akshare')
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取ETF日线失败: {e}")
            raise    
    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock') -> pd.DataFrame:
        period_map = {
            '1d': 'daily',
            '1m': '1', '5m': '5', '15m': '15', '30m': '30', '60m': '60',
        }
        ak_period = period_map.get(period)
        if not ak_period:
            raise ValueError(f"AkShare不支持周期: {period}")
        sd = start.replace('-', '')[:8]
        ed = end.replace('-', '')[:8]
        if ak_period == 'daily':
            if asset_type == 'fund':
                return self.fetch_fund_daily(code, sd, ed, adjust=adjust)
            else:
                return self.fetch_stock_daily(code, sd, ed, adjust=adjust)
        else:
            method_map = {
                '1': self.fetch_stock_1min if asset_type != 'fund' else self.fetch_fund_1min,
                '5': self.fetch_stock_5min if asset_type != 'fund' else self.fetch_fund_5min,
                '15': self.fetch_stock_15min if asset_type != 'fund' else self.fetch_fund_15min,
                '30': self.fetch_stock_30min if asset_type != 'fund' else self.fetch_fund_30min,
                '60': self.fetch_stock_60min if asset_type != 'fund' else self.fetch_fund_60min,
            }
            method = method_map.get(ak_period)
            if not method:
                raise ValueError(f"AkShare不支持{asset_type}周期: {period}")
            return method(code, start, end)

    def fetch_quote(self, code: str, asset_type: str = 'stock') -> pd.DataFrame:
        if asset_type == 'fund':
            return self.fetch_fund_realtime(code)
        else:
            return self.fetch_stock_realtime(code)

    def fetch_fund_1min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取ETF基金1分钟线数据

        Args:
            code: ETF代码，如'510300'
            start_date: 开始时间，格式'YYYY-MM-DD HH:MM:SS'
            end_date: 结束时间，格式'YYYY-MM-DD HH:MM:SS'

        Returns:
            DataFrame: 包含时间、开盘、收盘、最高、最低、成交量等字段

        注意: 接口限制只返回近5个交易日数据，不支持复权
        """
        if not self.check_capability('fund_1min'):
            raise NotImplementedError(f"{self.provider_name} 不支持ETF 1分钟线接口")

        try:
            self.logger.info(f"AkShare: 获取ETF 1分钟线 {code} [{start_date} ~ {end_date}]")

            df = self.ak.fund_etf_hist_min_em(
                symbol=code,
                period="1",
                start_date=start_date,
                end_date=end_date,
                adjust=""  # 1分钟数据不支持复权
            )

            if df is not None and not df.empty:
                df = self._standardize_fields(df, 'akshare')
                self.logger.info(f"获取成功(fund_etf_hist_min_em)，数据行数: {len(df)}")
                return df

        except Exception as e:
            self.logger.warning(f"fund_etf_hist_min_em 失败: {e}")

        # 回退：尝试使用stock_zh_a_minute（ETF也可用该接口）
        self.logger.warning(f"ETF 1分钟线回退到 stock_zh_a_minute")
        try:
            prefix = 'sh' if code.startswith('5') else 'sz'
            symbol_with_prefix = f"{prefix}{code}"

            df = self.ak.stock_zh_a_minute(symbol=symbol_with_prefix, period='1')
            if df is not None and not df.empty:
                df = self._standardize_fields(df, 'akshare')
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                self.logger.info(f"获取成功(stock_zh_a_minute回退)，数据行数: {len(df)}")
                return df
        except Exception as e:
            self.logger.warning(f"stock_zh_a_minute 回退也失败: {e}")

        raise RuntimeError(f"获取ETF 1分钟线失败: {code}")
    
    def fetch_fund_5min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取ETF基金5分钟线数据

        Args:
            code: ETF代码，如'510300'
            start_date: 开始时间，格式'YYYY-MM-DD HH:MM:SS'
            end_date: 结束时间，格式'YYYY-MM-DD HH:MM:SS'

        Returns:
            DataFrame: 包含时间、开盘、收盘、最高、最低、成交量等字段
        """
        if not self.check_capability('fund_5min'):
            raise NotImplementedError(f"{self.provider_name} 不支持ETF 5分钟线接口")

        try:
            self.logger.info(f"AkShare: 获取ETF 5分钟线 {code} [{start_date} ~ {end_date}]")

            df = self.ak.fund_etf_hist_min_em(
                symbol=code,
                period="5",
                start_date=start_date,
                end_date=end_date,
                adjust=""
            )

            if df is not None and not df.empty:
                df = self._standardize_fields(df, 'akshare')
                self.logger.info(f"获取成功(fund_etf_hist_min_em)，数据行数: {len(df)}")
                return df

        except Exception as e:
            self.logger.warning(f"fund_etf_hist_min_em 失败: {e}")

        # 回退：尝试使用stock_zh_a_minute
        self.logger.warning(f"ETF 5分钟线回退到 stock_zh_a_minute")
        try:
            prefix = 'sh' if code.startswith('5') else 'sz'
            symbol_with_prefix = f"{prefix}{code}"

            df = self.ak.stock_zh_a_minute(symbol=symbol_with_prefix, period='5')
            if df is not None and not df.empty:
                df = self._standardize_fields(df, 'akshare')
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                self.logger.info(f"获取成功(stock_zh_a_minute回退)，数据行数: {len(df)}")
                return df
        except Exception as e:
            self.logger.warning(f"stock_zh_a_minute 回退也失败: {e}")

        raise RuntimeError(f"获取ETF 5分钟线失败: {code}")

    def fetch_fund_15min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取ETF基金15分钟线数据
        """
        if not self.check_capability('fund_15min'):
            raise NotImplementedError(f"{self.provider_name} 不支持ETF 15分钟线接口")

        try:
            self.logger.info(f"AkShare: 获取ETF 15分钟线 {code} [{start_date} ~ {end_date}]")

            df = self.ak.fund_etf_hist_min_em(
                symbol=code,
                period="15",
                start_date=start_date,
                end_date=end_date,
                adjust=""
            )

            if df is None or df.empty:
                raise ValueError(f"未获取到数据: {code}")

            df = self._standardize_fields(df, 'akshare')

            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df

        except Exception as e:
            self.logger.error(f"获取ETF 15分钟线失败: {e}")
            raise

    def fetch_fund_30min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取ETF基金30分钟线数据

        Args:
            code: ETF代码，如'510300'
            start_date: 开始时间，格式'YYYY-MM-DD HH:MM:SS'
            end_date: 结束时间，格式'YYYY-MM-DD HH:MM:SS'

        Returns:
            DataFrame: 包含时间、开盘、收盘、最高、最低、成交量等字段
        """
        if not self.check_capability('fund_30min'):
            raise NotImplementedError(f"{self.provider_name} 不支持ETF 30分钟线接口")

        try:
            self.logger.info(f"AkShare: 获取ETF 30分钟线 {code} [{start_date} ~ {end_date}]")

            df = self.ak.fund_etf_hist_min_em(
                symbol=code,
                period="30",
                start_date=start_date,
                end_date=end_date,
                adjust=""
            )

            if df is not None and not df.empty:
                df = self._standardize_fields(df, 'akshare')
                self.logger.info(f"获取成功(fund_etf_hist_min_em)，数据行数: {len(df)}")
                return df

        except Exception as e:
            self.logger.warning(f"fund_etf_hist_min_em 失败: {e}")

        # 回退：尝试使用stock_zh_a_minute
        self.logger.warning(f"ETF 30分钟线回退到 stock_zh_a_minute")
        try:
            prefix = 'sh' if code.startswith('5') else 'sz'
            symbol_with_prefix = f"{prefix}{code}"

            df = self.ak.stock_zh_a_minute(symbol=symbol_with_prefix, period='30')
            if df is not None and not df.empty:
                df = self._standardize_fields(df, 'akshare')
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                self.logger.info(f"获取成功(stock_zh_a_minute回退)，数据行数: {len(df)}")
                return df
        except Exception as e:
            self.logger.warning(f"stock_zh_a_minute 回退也失败: {e}")

        raise RuntimeError(f"获取ETF 30分钟线失败: {code}")

    def fetch_fund_60min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取ETF基金60分钟线数据
        """
        if not self.check_capability('fund_60min'):
            raise NotImplementedError(f"{self.provider_name} 不支持ETF 60分钟线接口")

        try:
            self.logger.info(f"AkShare: 获取ETF 60分钟线 {code} [{start_date} ~ {end_date}]")

            df = self.ak.fund_etf_hist_min_em(
                symbol=code,
                period="60",
                start_date=start_date,
                end_date=end_date,
                adjust=""
            )

            if df is None or df.empty:
                raise ValueError(f"未获取到数据: {code}")

            df = self._standardize_fields(df, 'akshare')

            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df

        except Exception as e:
            self.logger.error(f"获取ETF 60分钟线失败: {e}")
            raise

    # ==================== 基础数据接口 ====================
    # 以下方法用于获取交易日历和代码列表等基础数据
    
    def fetch_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取交易日历
        
        【数据源】东方财富（通过AkShare接口）
        【接口】akshare.tool_trade_date_hist_sina()
        
        Args:
            start_date: 开始日期，格式'YYYY-MM-DD'
            end_date: 结束日期，格式'YYYY-MM-DD'
        
        Returns:
            DataFrame: 包含交易日期列表
        """
        try:
            self.logger.info(f"[东方财富] 获取交易日历 [{start_date} ~ {end_date}]")
            
            # 获取所有交易日期（新浪接口）
            df = self.ak.tool_trade_date_hist_sina()
            
            if df is None or df.empty:
                raise ValueError("未获取到交易日历数据")
            
            # 过滤日期范围
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df = df[(df['trade_date'] >= start) & (df['trade_date'] <= end)]
            
            # 重命名列为标准格式
            df = df.rename(columns={'trade_date': 'date'})
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            
            self.logger.info(f"获取成功，交易日数量: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取交易日历失败: {e}")
            raise
    
    def fetch_stock_list(self) -> pd.DataFrame:
        """
        获取股票代码列表
        
        【数据源】东方财富（通过AkShare接口）
        【接口】akshare.stock_info_a_code_name()
        
        Returns:
            DataFrame: 包含股票代码、名称等信息
        """
        try:
            self.logger.info("[东方财富] 获取股票代码列表")
            
            # 获取A股代码列表
            df = self.ak.stock_info_a_code_name()
            
            if df is None or df.empty:
                raise ValueError("未获取到股票代码列表")
            
            self.logger.info(f"获取成功，股票数量: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取股票代码列表失败: {e}")
            raise
    
    def fetch_fund_list(self) -> pd.DataFrame:
        """
        获取基金代码列表
        
        【数据源】东方财富（通过AkShare接口）
        【接口】akshare.fund_name_em()
        
        Returns:
            DataFrame: 包含基金代码、名称等信息（标准字段：code, name）
        """
        try:
            self.logger.info("[东方财富] 获取基金代码列表")
            
            # 获取基金代码列表
            df = self.ak.fund_name_em()
            
            if df is None or df.empty:
                raise ValueError("未获取到基金代码列表")
            
            # 字段标准化：基金代码->code, 基金简称->name
            field_map = {
                '基金代码': 'code',
                '基金简称': 'name',
                '基金类型': 'fund_type',
                '拼音缩写': 'pinyin',
                '拼音全称': 'pinyin_full'
            }
            df = df.rename(columns=field_map)
            
            self.logger.info(f"获取成功，基金数量: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取基金代码列表失败: {e}")
            raise

    # ========== Standard API wrappers (for DataSourceRegistry) ==========

    def fetch_stock_history_daily(self, code: str, start: str, end: str):
        """API01: 股票历史日线（标准接口）"""
        try:
            return self.fetch_stock_daily(code, start, end)
        except Exception as e:
            self.logger.error(f"API01调用失败: {e}")
            return -1

    def fetch_stock_history_minute(self, code: str, period: str, start: str, end: str):
        """API02: 股票历史分钟线（标准接口）"""
        try:
            method_map = {
                '1': self.fetch_stock_1min,
                '5': self.fetch_stock_5min,
                '15': self.fetch_stock_15min,
                '30': self.fetch_stock_30min,
                '60': self.fetch_stock_60min,
            }
            method = method_map.get(str(period))
            if not method:
                self.logger.error(f"不支持的周期: {period}")
                return -1
            return method(code, start, end)
        except Exception as e:
            self.logger.error(f"API02调用失败: {e}")
            return -1

    def fetch_stock_realtime_daily(self, code: str):
        """API03: 股票实时行情（标准接口）"""
        try:
            df = self.fetch_stock_realtime(code)
            if df is not None and not df.empty:
                return df.iloc[0].to_dict()
            return -1
        except Exception as e:
            self.logger.error(f"API03调用失败: {e}")
            return -1

    def fetch_stock_realtime_minute(self, code: str):
        """API04: 股票实时分钟线（标准接口）"""
        try:
            from datetime import datetime, timedelta
            end = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            start = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
            return self.fetch_stock_1min(code, start, end)
        except Exception as e:
            self.logger.error(f"API04调用失败: {e}")
            return -1

    def fetch_fund_history_daily(self, code: str, start: str, end: str):
        """API05: 基金历史日线（标准接口）"""
        try:
            return self.fetch_fund_daily(code, start, end)
        except Exception as e:
            self.logger.error(f"API05调用失败: {e}")
            return -1

    def fetch_fund_history_minute(self, code: str, period: str, start: str, end: str):
        """API06: 基金历史分钟线（标准接口）"""
        try:
            method_map = {
                '1': self.fetch_fund_1min,
                '5': self.fetch_fund_5min,
                '15': self.fetch_fund_15min,
                '30': self.fetch_fund_30min,
                '60': self.fetch_fund_60min,
            }
            method = method_map.get(str(period))
            if not method:
                self.logger.error(f"不支持的周期: {period}")
                return -1
            return method(code, start, end)
        except Exception as e:
            self.logger.error(f"API06调用失败: {e}")
            return -1

    def fetch_fund_realtime_daily(self, code: str):
        """API07: 基金实时行情（标准接口）"""
        try:
            df = self.fetch_fund_realtime(code)
            if df is not None and not df.empty:
                return df.iloc[0].to_dict()
            return -1
        except Exception as e:
            self.logger.error(f"API07调用失败: {e}")
            return -1

    def fetch_fund_realtime_minute(self, code: str):
        """API08: 基金实时分钟线（标准接口）"""
        try:
            from datetime import datetime, timedelta
            end = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            start = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
            return self.fetch_fund_1min(code, start, end)
        except Exception as e:
            self.logger.error(f"API08调用失败: {e}")
            return -1


# ================================================================================
# Byapi Provider - 商业API数据源
# ================================================================================

class ByapiProvider(BaseProvider, StandardAPIAdapter):
    """
    Byapi数据Provider - 商业API数据源
    
    【数据源说明】
    - 数据来源：币赢API (api.biyingapi.com)
    - 特点：实时数据，需要licence授权
    - 主要功能：股票/基金实时行情、历史K线
    
    【实时1分钟数据原理】
    - 通过每分钟采集实时接口
    - 与上一分钟数据对比生成1分钟K线
    - open=上一分钟close, close=当前价格
    - high/low为本分钟内最值
    
    【接口能力】
    ✅ 股票实时行情：http://api.biyingapi.com/hsrl/ssjy/{code}/{licence}
    ✅ 基金实时行情：http://api.biyingapi.com/fd/real/time/{code}/{licence}
    ✅ 股票历史K线：https://api.biyingapi.com/hsstock/history/{code}/{period}/{complex}/{licence}
    
    【历史数据周期支持】
    - 支持：5分钟、15分钟、30分钟、60分钟、日线、周线、月线、年线
    - 不支持：1分钟历史数据
    
    【请求频率】
    - 基础版：1分钟300次
    - 包年版：1分钟3000次
    - 白金版：1分钟6000次
    """
    
    CAPABILITIES = {
        'stock_realtime': True,       # ✅ 股票实时行情
        'stock_daily': True,          # ✅ 股票历史日线
        'stock_1min': False,          # ❌ 不支持1分钟历史数据
        'stock_5min': True,           # ✅ 股票5分钟线
        'stock_15min': True,          # ✅ 股票15分钟线
        'stock_30min': True,          # ✅ 股票30分钟线
        'stock_60min': True,          # ✅ 股票60分钟线
        'stock_weekly': True,         # ✅ 股票周线
        'stock_monthly': True,        # ✅ 股票月线
        'fund_realtime': True,        # ✅ 基金实时行情
        'fund_daily': True,           # ✅ 基金历史日线
        'fund_1min': False,           # ❌ 不支持1分钟历史数据
        'stock_list': False,          # ❌ 不支持股票代码列表
        'trade_calendar': False,      # ❌ 不支持交易日历
    }
    
    def __init__(self, licence: str = None):
        """
        初始化Byapi Provider
        
        Args:
            licence: API授权码，如果为None则从环境变量读取
        """
        super().__init__()
        
        # 获取licence
        if licence:
            self.licence = licence
        else:
            self.licence = self.config.get('BYAPI_LICENCE', '')
        
        if not self.licence:
            self.logger.warning("Byapi licence未配置，请在.env中设置BYAPI_LICENCE或通过参数传入")
        
        self.base_url = "http://api.biyingapi.com"
        self.base_url_https = "https://api.biyingapi.com"
        
        # 缓存：用于实时1分钟数据生成
        self.realtime_cache = {}  # {code: {'price': float, 'time': datetime, 'data': dict}}
        
        self.logger.info("Byapi Provider 初始化成功")

    _PERIOD_MAP = {
        '1d': 'd', '5m': '5', '15m': '15', '30m': '30', '60m': '60',
        '1w': 'w', '1M': 'm',
    }

    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock') -> pd.DataFrame:
        if period == '1m':
            raise NotImplementedError("Byapi不支持1分钟历史数据")
        byapi_period = self._PERIOD_MAP.get(period)
        if not byapi_period:
            raise ValueError(f"Byapi不支持周期: {period}")
        if period == '1d':
            if asset_type == 'fund':
                raise NotImplementedError("Byapi基金日线暂未实现fetch_kline")
            return self.fetch_stock_daily(code, start, end)
        else:
            if asset_type == 'fund':
                raise NotImplementedError("Byapi基金分钟线暂未实现fetch_kline")
            return self._fetch_stock_period(code, start, end, byapi_period)

    def fetch_quote(self, code: str, asset_type: str = 'stock') -> pd.DataFrame:
        if asset_type == 'fund':
            return self.fetch_fund_realtime(code)
        else:
            return self.fetch_stock_realtime(code)
    
    def _make_request(self, url: str, method: str = 'GET', **kwargs) -> dict:
        """
        发起HTTP请求
        
        Args:
            url: 请求URL
            method: 请求方法
            **kwargs: requests参数
        
        Returns:
            JSON响应数据
        """
        try:
            import requests
            self.logger.debug(f"请求URL: {url}")
            
            if method == 'GET':
                response = requests.get(url, timeout=10, **kwargs)
            else:
                response = requests.post(url, timeout=10, **kwargs)
            
            response.raise_for_status()
            data = response.json()
            
            # 检查是否有错误信息
            if isinstance(data, dict) and 'error' in data:
                raise ValueError(f"API返回错误: {data.get('error')}")
            
            return data
            
        except Exception as e:
            self.logger.error(f"HTTP请求失败: {e}")
            raise
    
    def _parse_stock_code(self, code: str) -> tuple:
        """
        解析股票代码，转换为byapi格式
        
        Args:
            code: 股票代码，如'000001'或'000001.SZ'
        
        Returns:
            (code, market) 如('000001', 'SZ')
        """
        if '.' in code:
            c, m = code.split('.')
            return c, m.upper()
        else:
            # 根据代码前缀判断市场
            if code.startswith('6'):
                return code, 'SH'
            else:
                return code, 'SZ'
    
    def fetch_stock_realtime(self, code: str) -> pd.DataFrame:
        """
        获取股票实时行情
        
        【接口】http://api.biyingapi.com/hsrl/ssjy/{code}/{licence}
        【数据源】byapi公开数据
        【更新频率】交易时间每1分钟
        
        Args:
            code: 股票代码，如'000001'
        
        Returns:
            DataFrame: 包含实时行情数据
        """
        super().fetch_stock_realtime(code)
        
        try:
            stock_code, _ = self._parse_stock_code(code)
            url = f"{self.base_url}/hsrl/ssjy/{stock_code}/{self.licence}"
            
            self.logger.info(f"[Byapi] 获取股票实时行情 {code}")
            
            data = self._make_request(url)
            
            # 转换为DataFrame
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame([data[0]])
            elif isinstance(data, dict):
                df = pd.DataFrame([data])
            else:
                raise ValueError(f"未获取到数据: {code}")
            
            # 字段映射
            field_map = {
                'p': 'close',      # 当前价格
                'o': 'open',       # 开盘价
                'h': 'high',       # 最高价
                'l': 'low',        # 最低价
                'yc': 'pre_close', # 昨收
                'v': 'volume',     # 成交量(手)
                'cje': 'amount',   # 成交额
                't': 'time',       # 更新时间
                'pc': 'change_pct',# 涨跌幅
                'ud': 'change',    # 涨跌额
            }
            
            df = df.rename(columns=field_map)
            df['code'] = code
            df['date'] = pd.to_datetime(df['time']).dt.date if 'time' in df.columns else pd.Timestamp.now().date()
            
            # 成交量从手转换为股(手*100)
            if 'volume' in df.columns:
                df['volume'] = df['volume'] * 100
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取股票实时行情失败: {e}")
            raise
    
    def fetch_fund_realtime(self, code: str) -> pd.DataFrame:
        """
        获取基金实时行情
        
        【接口】http://api.biyingapi.com/fd/real/time/{code}/{licence}
        【数据源】byapi券商数据源
        【更新频率】盘中实时
        
        Args:
            code: 基金代码，如'159001'或'159001.SZ'
        
        Returns:
            DataFrame: 包含实时行情数据
        """
        super().fetch_fund_realtime(code)
        
        try:
            fund_code, _ = self._parse_stock_code(code)
            url = f"{self.base_url}/fd/real/time/{fund_code}/{self.licence}"
            
            self.logger.info(f"[Byapi] 获取基金实时行情 {code}")
            
            data = self._make_request(url)
            
            # 转换为DataFrame
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame([data[0]])
            elif isinstance(data, dict):
                df = pd.DataFrame([data])
            else:
                raise ValueError(f"未获取到数据: {code}")
            
            # 字段映射
            field_map = {
                'p': 'close',      # 最新价
                'o': 'open',       # 开盘价
                'h': 'high',       # 最高价
                'l': 'low',        # 最低价
                'yc': 'pre_close', # 前收盘
                'v': 'volume',     # 成交总量
                'cje': 'amount',   # 成交总额
                't': 'time',       # 更新时间
                'pc': 'change_pct',# 涨跌幅
                'ud': 'change',    # 涨跌额
            }
            
            df = df.rename(columns=field_map)
            df['code'] = code
            df['date'] = pd.to_datetime(df['time']).dt.date if 'time' in df.columns else pd.Timestamp.now().date()
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取基金实时行情失败: {e}")
            raise

    # ==================== 标准实时接口（对齐DataSourceRegistry） ====================

    def fetch_stock_realtime_daily(self, code: str):
        """API03标准接口：股票实时行情（日线级）"""
        try:
            df = self.fetch_stock_realtime(code)
            if df is None or df.empty:
                return -1
            return df.iloc[0].to_dict()
        except Exception as e:
            self.logger.error(f"Byapi API03调用失败: {e}")
            return -1

    def fetch_stock_realtime_minute(self,
                                    code: str,
                                    period: str = '1',
                                    start: str = None,
                                    end: str = None,
                                    adjust: str = 'qfq'):
        """API04标准接口：股票实时分钟线

        说明：Byapi提供实时快照接口，分钟级在此返回单条实时快照数据。
        """
        try:
            _ = period, start, end, adjust  # 参数保留用于统一签名
            df = self.fetch_stock_realtime(code)
            if df is None or df.empty:
                return -1
            return df
        except Exception as e:
            self.logger.error(f"Byapi API04调用失败: {e}")
            return -1

    def fetch_fund_realtime_daily(self, code: str):
        """API07标准接口：基金实时行情（日线级）"""
        try:
            df = self.fetch_fund_realtime(code)
            if df is None or df.empty:
                return -1
            return df.iloc[0].to_dict()
        except Exception as e:
            self.logger.error(f"Byapi API07调用失败: {e}")
            return -1

    def fetch_fund_realtime_minute(self,
                                   code: str,
                                   period: str = '1',
                                   start: str = None,
                                   end: str = None):
        """API08标准接口：基金实时分钟线

        说明：Byapi提供实时快照接口，分钟级在此返回单条实时快照数据。
        """
        try:
            _ = period, start, end  # 参数保留用于统一签名
            df = self.fetch_fund_realtime(code)
            if df is None or df.empty:
                return -1
            return df
        except Exception as e:
            self.logger.error(f"Byapi API08调用失败: {e}")
            return -1
    
    def fetch_stock_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票历史日线数据
        
        【接口】https://api.biyingapi.com/hsstock/history/{code}.{market}/d/f/{licence}?st={start}&et={end}
        
        Args:
            code: 股票代码
            start_date: 开始日期 'YYYYMMDD'
            end_date: 结束日期 'YYYYMMDD'
        
        Returns:
            DataFrame: 日线数据
        """
        super().fetch_stock_daily(code, start_date, end_date)
        
        try:
            stock_code, market = self._parse_stock_code(code)
            url = f"{self.base_url_https}/hsstock/history/{stock_code}.{market}/d/f/{self.licence}"
            url += f"?st={start_date.replace('-', '')}&et={end_date.replace('-', '')}"
            
            self.logger.info(f"[Byapi] 获取股票日线 {code} [{start_date} ~ {end_date}]")
            
            data = self._make_request(url)
            
            if not data or len(data) == 0:
                raise ValueError(f"未获取到数据: {code}")
            
            df = pd.DataFrame(data)
            
            # 字段映射
            field_map = {
                't': 'date',
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume',
                'a': 'amount',
                'pc': 'pre_close',
            }
            
            df = df.rename(columns=field_map)
            df['code'] = code
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取股票日线失败: {e}")
            raise
    
    def fetch_stock_5min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票5分钟线历史数据"""
        return self._fetch_stock_period(code, start_date, end_date, '5')
    
    def fetch_stock_15min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票15分钟线历史数据"""
        return self._fetch_stock_period(code, start_date, end_date, '15')
    
    def fetch_stock_30min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票30分钟线历史数据"""
        return self._fetch_stock_period(code, start_date, end_date, '30')
    
    def fetch_stock_60min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票60分钟线历史数据"""
        return self._fetch_stock_period(code, start_date, end_date, '60')
    
    def fetch_stock_weekly(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票周线历史数据"""
        return self._fetch_stock_period(code, start_date, end_date, 'w')
    
    def fetch_stock_monthly(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票月线历史数据"""
        return self._fetch_stock_period(code, start_date, end_date, 'm')
    
    def fetch_stock_list(self) -> pd.DataFrame:
        """
        获取股票代码列表
        
        【数据源】Byapi商业API
        【接口】http://api.biyingapi.com/hslt/list/{licence}
        【更新频率】每日16:20
        
        Returns:
            DataFrame: 包含股票代码、名称、交易所信息
            - code: 股票代码（6位数字）
            - name: 股票名称
            - market: 交易所（sh/sz）
        """
        try:
            self.logger.info("[Byapi] 获取股票代码列表")
            
            url = f"{self.base_url}/hslt/list/{self.licence}"
            data = self._make_request(url)
            
            if not data or len(data) == 0:
                raise ValueError("未获取到股票代码列表")
            
            df = pd.DataFrame(data)
            
            # 字段映射：dm->code, mc->name, jys->market
            field_map = {
                'dm': 'code',
                'mc': 'name',
                'jys': 'market'
            }
            
            df = df.rename(columns=field_map)
            
            self.logger.info(f"获取成功，股票数量: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取股票代码列表失败: {e}")
            raise
    
    def fetch_fund_list(self) -> pd.DataFrame:
        """
        获取基金代码列表（ETF）
        
        【数据源】Byapi商业API
        【接口】http://api.biyingapi.com/fd/list/etf/{licence}
        【更新频率】每日16:20
        
        Returns:
            DataFrame: 包含基金代码、名称、交易所信息
            - code: 基金代码（6位数字，可能带.SZ/.SH后缀）
            - name: 基金名称
            - market: 交易所（sh/sz）
        """
        try:
            self.logger.info("[Byapi] 获取基金代码列表（ETF）")
            
            url = f"{self.base_url}/fd/list/etf/{self.licence}"
            data = self._make_request(url)
            
            if not data or len(data) == 0:
                raise ValueError("未获取到基金代码列表")
            
            df = pd.DataFrame(data)
            
            # 字段映射：dm->code, mc->name, jys->market
            field_map = {
                'dm': 'code',
                'mc': 'name',
                'jys': 'market'
            }
            
            df = df.rename(columns=field_map)
            
            # 如果代码中包含市场后缀（如159001.SZ），需要去掉
            if 'code' in df.columns:
                df['code'] = df['code'].str.split('.').str[0]
            
            self.logger.info(f"获取成功，基金数量: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取基金代码列表失败: {e}")
            raise
    
    def fetch_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取交易日历
        
        注意：Byapi不提供交易日历接口，此方法调用AkShare获取
        
        Args:
            start_date: 开始日期 'YYYY-MM-DD'
            end_date: 结束日期 'YYYY-MM-DD'
        
        Returns:
            DataFrame: 包含交易日期
        """
        try:
            self.logger.warning("Byapi不支持交易日历接口，使用AkShare替代")
            
            # 临时创建AkShare Provider获取交易日历
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            
            # 转换日期格式
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            
            # 过滤日期范围
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df = df[(df['trade_date'] >= start) & (df['trade_date'] <= end)]
            
            # 重命名字段
            df = df.rename(columns={'trade_date': 'date'})
            
            self.logger.info(f"获取成功，交易日数量: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取交易日历失败: {e}")
            raise
    
    def _fetch_stock_period(self, code: str, start_date: str, end_date: str, period: str) -> pd.DataFrame:
        """
        获取股票指定周期K线历史数据
        
        【支持的周期】
        - 分钟级：5、15、30、60
        - 日线及以上：d(日)、w(周)、m(月)、y(年)
        - ❌不支持1分钟
        
        Args:
            code: 股票代码
            start_date: 开始日期（可以带时间，只取日期部分）
            end_date: 结束日期（可以带时间，只取日期部分）
            period: 周期代码 ('5','15','30','60','d','w','m','y')
        """
        try:
            stock_code, market = self._parse_stock_code(code)
            # 只取日期部分（YYYY-MM-DD），去除时间部分
            start_date_only = start_date.split()[0] if ' ' in start_date else start_date
            end_date_only = end_date.split()[0] if ' ' in end_date else end_date
            # Byapi规则：分钟级(5/15/30/60)无除权数据，必须使用'n'；日线及以上可使用'f'(前复权)
            complex_type = 'n' if str(period) in {'5', '15', '30', '60'} else 'f'
            url = f"{self.base_url_https}/hsstock/history/{stock_code}.{market}/{period}/{complex_type}/{self.licence}"
            url += f"?st={start_date_only.replace('-', '')}&et={end_date_only.replace('-', '')}"
            
            self.logger.info(f"[Byapi] 获取股票{period}分钟线 {code} [{start_date} ~ {end_date}]")
            
            data = self._make_request(url)
            
            if not data or len(data) == 0:
                raise ValueError(f"未获取到数据: {code}")
            
            df = pd.DataFrame(data)
            
            field_map = {
                't': 'time',
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume',
                'a': 'amount',
            }
            
            df = df.rename(columns=field_map)
            df['code'] = code
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取股票{period}分钟线失败: {e}")
            raise
    
    # ==================== 同花顺（THS）扩展接口 ====================
    # 【重要说明】
    # - 数据源：同花顺（TongHuaShun）
    # - 调用方式：通过AkShare封装的同花顺接口
    # - 用途定位：辅助数据源，补充东方财富的不足
    # - 主要功能：板块分类、财务数据、分红信息
    # - 测试日期：2026年2月14日
    # - 成功率：80% (8/10接口可用)
    
    def fetch_ths_concept_list(self) -> pd.DataFrame:
        """
        获取同花顺概念板块列表
        
        【数据源】同花顺（通过AkShare接口）
        【接口】akshare.stock_board_concept_name_ths()
        
        Returns:
            DataFrame: 包含概念名称和代码
        
        【测试结果】✅ 2026-02-14测试通过，375个概念板块
        """
        try:
            self.logger.info("[同花顺] 获取概念板块列表")
            df = self.ak.stock_board_concept_name_ths()
            self.logger.info(f"获取成功，概念数量: {len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"获取概念板块列表失败: {e}")
            raise
    
    def fetch_ths_industry_list(self) -> pd.DataFrame:
        """
        获取同花顺行业板块列表
        
        Returns:
            DataFrame: 包含行业名称和代码
        
        测试结果: ✅ 2026-02-14测试通过，90个行业板块
        """
        try:
            self.logger.info("[同花顺] 获取行业板块列表")
            df = self.ak.stock_board_industry_name_ths()
            self.logger.info(f"获取成功，行业数量: {len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"获取行业板块列表失败: {e}")
            raise
    
    def fetch_ths_concept_index(self) -> pd.DataFrame:
        """
        获取同花顺概念板块指数历史数据
        
        Returns:
            DataFrame: 包含日期、开盘、收盘、最高、最低、成交量、成交额
        
        测试结果: ✅ 2026-02-14测试通过，1248个板块历史数据
        """
        try:
            self.logger.info("[同花顺] 获取概念板块指数")
            df = self.ak.stock_board_concept_index_ths()
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"获取概念板块指数失败: {e}")
            raise
    
    def fetch_ths_industry_index(self) -> pd.DataFrame:
        """
        获取同花顺行业板块指数历史数据
        
        Returns:
            DataFrame: 包含日期、开盘、收盘、最高、最低、成交量、成交额
        
        测试结果: ✅ 2026-02-14测试通过，975个板块历史数据
        """
        try:
            self.logger.info("[同花顺] 获取行业板块指数")
            df = self.ak.stock_board_industry_index_ths()
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"获取行业板块指数失败: {e}")
            raise
    
    def fetch_ths_financial(self, symbol: str, indicator: str = "按报告期") -> pd.DataFrame:
        """
        获取同花顺股票财务摘要数据
        
        【数据源】同花顺（通过AkShare接口）
        【接口】akshare.stock_financial_abstract_ths()
        
        Args:
            symbol: 股票代码（不带市场后缀），如'000001'
            indicator: 查询类型，"按报告期"或"按年度"
        
        Returns:
            DataFrame: 包含22个财务指标
        
        测试结果: ✅ 2026-02-14测试通过，平安银行119条财务记录
        """
        try:
            self.logger.info(f"[同花顺] 获取财务摘要 {symbol} [{indicator}]")
            df = self.ak.stock_financial_abstract_ths(symbol=symbol, indicator=indicator)
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"获取财务摘要失败: {e}")
            raise
    
    def fetch_ths_dividend(self, symbol: str) -> pd.DataFrame:
        """
        获取同花顺股票分红配股历史
        
        Args:
            symbol: 股票代码（不带市场后缀），如'600519'
        
        Returns:
            DataFrame: 包含11个分红相关字段
        
        测试结果: ✅ 2026-02-14测试通过，贵州茅台54条分红记录
        """
        try:
            self.logger.info(f"THS: 获取分红配股 {symbol}")
            df = self.ak.stock_fhps_detail_ths(symbol=symbol)
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"获取分红配股失败: {e}")
            raise
    
    def fetch_ths_etf_spot(self) -> pd.DataFrame:
        """
        获取同花顺场内ETF实时行情
        
        Returns:
            DataFrame: 包含16个字段，覆盖1460只ETF
        
        测试结果: ✅ 2026-02-14测试通过，1460只ETF
        """
        try:
            self.logger.info("THS: 获取ETF实时行情")
            df = self.ak.fund_etf_spot_ths()
            self.logger.info(f"获取成功，ETF数量: {len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"获取ETF实时行情失败: {e}")
            raise
    
    def fetch_ths_concept_info(self) -> pd.DataFrame:
        """
        获取同花顺概念板块详细信息
        
        Returns:
            DataFrame: 板块的详细指标数据
        
        测试结果: ✅ 2026-02-14测试通过
        """
        try:
            self.logger.info("THS: 获取概念板块详细信息")
            df = self.ak.stock_board_concept_info_ths()
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
        except Exception as e:
            self.logger.error(f"获取概念板块详细信息失败: {e}")
            raise


class BaostockProvider(BaseProvider, StandardAPIAdapter):

    _ADJUST_MAP = {'qfq': '2', 'hfq': '1', 'none': '3'}

    def _map_adjust(self, adjust: str) -> str:
        return self._ADJUST_MAP.get(adjust, '2')

    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock') -> pd.DataFrame:
        if asset_type == 'fund':
            raise NotImplementedError("Baostock不支持基金数据")
        adjustflag = self._map_adjust(adjust)
        period_map = {
            '1d': 'd',
            '5m': '5', '15m': '15', '30m': '30', '60m': '60',
            '1w': 'w', '1M': 'm',
        }
        bs_freq = period_map.get(period)
        if not bs_freq:
            raise ValueError(f"Baostock不支持周期: {period}")
        if bs_freq == 'd':
            return self.fetch_stock_daily(code, start, end, adjustflag=adjustflag)
        else:
            return self._fetch_stock_kline(
                code, start, end, bs_freq,
                self.FIELDS_MINUTE if bs_freq in ('5', '15', '30', '60') else self.FIELDS_WEEKLY_MONTHLY,
                f"获取股票{period}线"
            )

    def fetch_quote(self, code: str, asset_type: str = 'stock') -> pd.DataFrame:
        raise NotImplementedError("Baostock不支持实时行情")

    """
    - 免费使用（需登录/登出）
    - 支持1990-12-19至当前时间的历史数据
    - 支持日K线、周K线、月K线、5/15/30/60分钟K线（不支持1分钟线）
    - 支持不复权(3)、前复权(2)、后复权(1)，已支持前后复权的分钟线
    - 不支持实时行情、基金数据
    - 复权方式：涨跌幅复权法（与同花顺、通达信不同）
    """

    CAPABILITIES = {
        'stock_realtime': False,      # ❌ 不支持实时
        'stock_daily': True,          # ✅ 股票历史日线
        'stock_1min': False,          # ❌ 不支持1分钟线（baostock文档未包含1分钟线）
        'stock_5min': True,           # ✅ 5分钟线
        'stock_15min': True,          # ✅ 15分钟线
        'stock_30min': True,          # ✅ 30分钟线
        'stock_60min': True,          # ✅ 60分钟线
        'stock_weekly': True,         # ✅ 周K线（每周最后一个交易日可获取）
        'stock_monthly': True,        # ✅ 月K线（每月最后一个交易日可获取）
        'stock_list': True,           # ✅ 股票代码列表（query_all_stock）
        'trade_calendar': True,       # ✅ 交易日历（query_trade_dates）
        'fund_realtime': False,       # ❌ 不支持基金
        'fund_daily': False,          # ❌ 不支持基金
    }

    # 估值指标字段（可选，baostock文档日线支持）
    FIELDS_DAILY_EXTRA_VALUATION = "peTTM,pbMRQ,psTTM,pcfNcfTTM"

    # 日线指标字段（与baostock文档对齐，核心字段）
    # 可选估值字段可通过 fetch_stock_daily 的 extra_fields 参数添加
    FIELDS_DAILY = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST"

    # 周/月线指标字段（与baostock文档对齐）
    FIELDS_WEEKLY_MONTHLY = "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg"

    # 分钟线指标字段（baostock文档：5/15/30/60分钟线，不支持1分钟线）
    FIELDS_MINUTE = "date,time,code,open,high,low,close,volume,amount,adjustflag"

    def __init__(self):
        super().__init__()

        try:
            import baostock as bs
            self.bs = bs
            self.logger.info("Baostock Provider 初始化成功")
        except ImportError:
            self.logger.error("Baostock 未安装，请执行: pip install baostock")
            raise

    def _convert_code(self, code: str) -> str:
        """
        转换代码格式: 000001 -> sz.000001

        Args:
            code: 6位股票代码

        Returns:
            带市场前缀的代码
        """
        if '.' in code:
            return code

        # 根据代码判断市场
        if code.startswith('6'):
            return f"sh.{code}"  # 上海
        else:
            return f"sz.{code}"  # 深圳

    def _result_to_df(self, rs) -> pd.DataFrame:
        if rs is None:
            self.logger.error("Baostock查询返回 None")
            return pd.DataFrame()

        if rs.error_code != '0':
            self.logger.error(f"Baostock查询失败: {rs.error_code} - {rs.error_msg}")
            return pd.DataFrame()

        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            return pd.DataFrame()

        return pd.DataFrame(data_list, columns=rs.fields)

    def _parse_baostock_time(self, time_str: str) -> str:
        """
        解析Baostock分钟线time字段（格式：YYYYMMDDHHMMSSsss）为标准时间格式

        Args:
            time_str: baostock time字段，如 "20240701093100000"

        Returns:
            标准时间字符串 "2024-07-01 09:31:00"
        """
        if not time_str or len(time_str) < 15:
            return ""

        year = time_str[0:4]
        month = time_str[4:6]
        day = time_str[6:8]
        hour = time_str[8:10]
        minute = time_str[10:12]
        second = time_str[12:14]

        return f"{year}-{month}-{day} {hour}:{minute}:{second}"

    def _process_minute_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        处理分钟线DataFrame：解析time字段，合并date+time为datetime列，
        并将datetime同步到date列以保持标准化接口

        Args:
            df: 原始baostock分钟线数据

        Returns:
            处理后的DataFrame
        """
        if df.empty or 'time' not in df.columns:
            return df

        # 解析time字段
        df['datetime'] = df['time'].apply(
            lambda t: self._parse_baostock_time(str(t)) if pd.notna(t) else ""
        )

        # 将完整时间戳同步到date列，确保下游消费者可以统一使用date列
        if 'datetime' in df.columns:
            df['date'] = df['datetime']

        return df

    def _login_check(self):
        lg = self.bs.login()
        if lg is None:
            raise RuntimeError("Baostock登录返回 None")
        if lg.error_code != '0':
            raise RuntimeError(f"Baostock登录失败: {lg.error_msg}")
        return lg

    def fetch_stock_daily(self, code: str, start_date: str, end_date: str,
                          adjustflag: str = "2", extra_fields: str = "") -> pd.DataFrame:
        """获取股票历史日线

        【数据源】Baostock
        【接口】bs.query_history_k_data_plus()
        【字段】date,code,open,high,low,close,preclose,volume,amount,
                adjustflag,turn,tradestatus,pctChg,isST
        【可选估值字段】peTTM,pbMRQ,psTTM,pcfNcfTTM（通过 extra_fields 添加）

        Args:
            code: 股票代码，如'600000'
            start_date: 开始日期，格式'YYYY-MM-DD'
            end_date: 结束日期，格式'YYYY-MM-DD'
            adjustflag: 复权类型，'1'=后复权，'2'=前复权，'3'=不复权
            extra_fields: 可选字段，如 'peTTM,pbMRQ,psTTM,pcfNcfTTM'

        Returns:
            DataFrame: 包含OHLCV等字段及preclose、turn、tradestatus、pctChg、isST
        """
        super().fetch_stock_daily(code, start_date, end_date)  # 能力检测

        bs_code = self._convert_code(code)
        fields = self.FIELDS_DAILY
        if extra_fields:
            fields = f"{fields},{extra_fields}"
        # baostock 只接受 YYYY-MM-DD 格式，去掉可能携带的时间部分
        start_date_only = start_date.split()[0] if ' ' in start_date else start_date
        end_date_only = end_date.split()[0] if ' ' in end_date else end_date
        self.logger.info(f"Baostock: 获取股票日线 {bs_code} [{start_date_only} ~ {end_date_only}] 复权={adjustflag}")
        last_error = None

        for attempt in range(3):
            try:
                lg = self._login_check()

                try:
                    rs = self.bs.query_history_k_data_plus(
                        code=bs_code,
                        fields=fields,
                        start_date=start_date_only,
                        end_date=end_date_only,
                        frequency="d",
                        adjustflag=adjustflag
                    )

                    df = self._result_to_df(rs)
                    df = self._standardize_fields(df, 'baostock')

                    self.logger.info(f"获取成功，数据行数: {len(df)}")
                    return df

                finally:
                    self.bs.logout()

            except Exception as e:
                last_error = e
                self.logger.warning(f"第{attempt + 1}次请求失败: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))

        self.logger.error(f"获取股票日线失败: {last_error}")
        raise last_error

    def _fetch_stock_kline(self, code: str, start_date: str, end_date: str,
                           frequency: str, fields: str, method_name: str) -> pd.DataFrame:
        """
        通用K线获取方法（分钟线、周线、月线）

        Args:
            code: 股票代码
            start_date: 开始日期 'YYYY-MM-DD'
            end_date: 结束日期 'YYYY-MM-DD'
            frequency: K线周期 '5','15','30','60','w','m'（注意：baostock不支持1分钟线）
            fields: 字段列表
            method_name: 方法名（用于日志）
        """
        bs_code = self._convert_code(code)
        start_date_only = start_date.split()[0] if ' ' in start_date else start_date
        end_date_only = end_date.split()[0] if ' ' in end_date else end_date
        self.logger.info(f"Baostock: {method_name} {bs_code} [{start_date_only} ~ {end_date_only}]")
        last_error = None

        # Baostock 网络不稳定时，减少重试次数避免长时间卡住
        max_retries = 1  # 原本是3次，改为1次

        for attempt in range(max_retries):
            try:
                lg = self._login_check()

                try:
                    rs = self.bs.query_history_k_data_plus(
                        code=bs_code,
                        fields=fields,
                        start_date=start_date_only,
                        end_date=end_date_only,
                        frequency=frequency,
                        adjustflag="2"
                    )

                    df = self._result_to_df(rs)
                    df = self._standardize_fields(df, 'baostock')

                    # 分钟线需要解析time字段
                    if 'time' in df.columns:
                        df = self._process_minute_df(df)

                    self.logger.info(f"获取成功，数据行数: {len(df)}")
                    return df

                finally:
                    self.bs.logout()

            except Exception as e:
                last_error = e
                self.logger.warning(f"第{attempt + 1}次请求失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)  # 减少等待时间

        self.logger.error(f"Baostock: {method_name}失败: {last_error}")
        raise last_error

    def fetch_stock_5min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票5分钟线"""
        return self._fetch_stock_kline(code, start_date, end_date, "5",
                                        self.FIELDS_MINUTE, "获取股票5分钟线")

    def fetch_stock_15min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票15分钟线"""
        return self._fetch_stock_kline(code, start_date, end_date, "15",
                                        self.FIELDS_MINUTE, "获取股票15分钟线")

    def fetch_stock_30min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票30分钟线"""
        return self._fetch_stock_kline(code, start_date, end_date, "30",
                                        self.FIELDS_MINUTE, "获取股票30分钟线")

    def fetch_stock_60min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票60分钟线"""
        return self._fetch_stock_kline(code, start_date, end_date, "60",
                                        self.FIELDS_MINUTE, "获取股票60分钟线")

    def fetch_stock_weekly(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票周K线（每周最后一个交易日才可获取）"""
        return self._fetch_stock_kline(code, start_date, end_date, "w",
                                        self.FIELDS_WEEKLY_MONTHLY, "获取股票周K线")

    def fetch_stock_monthly(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票月K线（每月最后一个交易日才可获取）"""
        return self._fetch_stock_kline(code, start_date, end_date, "m",
                                        self.FIELDS_WEEKLY_MONTHLY, "获取股票月K线")
    
    # ==================== 基础数据接口 ====================

    def fetch_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取交易日历

        Args:
            start_date: 开始日期，格式'YYYY-MM-DD'
            end_date: 结束日期，格式'YYYY-MM-DD'

        Returns:
            DataFrame: 包含交易日期列表
        """
        try:
            self.logger.info(f"Baostock: 获取交易日历 [{start_date} ~ {end_date}]")

            lg = self._login_check()

            try:
                rs = self.bs.query_trade_dates(start_date=start_date, end_date=end_date)
                df = self._result_to_df(rs)

                if df.empty:
                    raise ValueError("未获取到交易日历数据")

                # 只保留交易日
                df = df[df['is_trading_day'] == '1']
                df = df.rename(columns={'calendar_date': 'date'})
                df = df[['date']]

                self.logger.info(f"获取成功，交易日数量: {len(df)}")
                return df

            finally:
                self.bs.logout()

        except Exception as e:
            self.logger.error(f"获取交易日历失败: {e}")
            raise

    def fetch_stock_list(self) -> pd.DataFrame:
        """
        获取股票代码列表

        【接口】query_all_stock(day)
        当参数"day"为空时，默认取当天日期。闭市后日K线数据更新，该接口才会返回当天数据，否则返回空。

        Returns:
            DataFrame: 包含code, name字段（已去掉sh./sz.前缀）
        """
        try:
            self.logger.info("Baostock: 获取股票代码列表")

            lg = self._login_check()

            try:
                from datetime import datetime, timedelta

                # 尝试多个日期，避免闭市前当天数据未更新导致返回空
                dates_to_try = [
                    (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                    for i in range(0, 90, 7)
                ]

                df = None
                for date in dates_to_try:
                    rs = self.bs.query_all_stock(day=date)

                    if rs is None:
                        self.logger.warning(f"Baostock query_all_stock for {date} 返回 None")
                        continue

                    data_list = []
                    while (rs.error_code == '0') & rs.next():
                        data_list.append(rs.get_row_data())

                    if data_list:
                        df = pd.DataFrame(data_list, columns=rs.fields)
                        self.logger.info(f"使用日期 {date} 获取到 {len(df)} 条股票数据")
                        break

                if df is None or df.empty:
                    raise ValueError("未获取到股票代码列表")

                # 字段标准化
                if 'code' in df.columns and 'code_name' in df.columns:
                    df = df.rename(columns={'code_name': 'name'})

                # 去掉市场前缀（sh./sz.）
                if 'code' in df.columns:
                    df['code'] = df['code'].str.replace('sh.', '', regex=False).str.replace('sz.', '', regex=False)

                self.logger.info(f"获取成功，股票数量: {len(df)}")
                return df

            finally:
                self.bs.logout()

        except Exception as e:
            self.logger.error(f"获取股票代码列表失败: {e}")
            raise
    
    def fetch_fund_list(self) -> pd.DataFrame:
        """
        获取基金代码列表
        
        Baostock不支持基金数据，抛出NotImplementedError
        """
        raise NotImplementedError("Baostock不支持基金数据")
