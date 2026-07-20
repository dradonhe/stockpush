"""
数据源Provider抽象与实现
提供Byapi/XTick数据源的统一接口封装
"""
import os
import time
from datetime import datetime


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
        """
        FIELD_MAPPING = {
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

    def fetch_stock_1min_realtime(self, code: str, duration_minutes: int = 5) -> pd.DataFrame:
        """
        通过实时接口生成1分钟K线数据
        
        ⚠️ 注意：byapi不提供1分钟历史数据接口，此方法用于实时采集生成临时数据
        
        【算法原理】
        1. 每分钟采集一次实时接口
        2. 与上一分钟数据对比生成K线
        3. open = 上一分钟的close
        4. close = 当前价格
        5. high/low = 本分钟内最高/最低价
        
        【使用场景】
        - 仅用于盘中实时监控和短期分析
        - 不适合回测和历史数据分析
        - 需要连续运行duration_minutes分钟才能生成完整数据
        
        Args:
            code: 股票代码
            duration_minutes: 采集时长(分钟)，默认5分钟
        
        Returns:
            DataFrame: 1分钟K线数据（临时生成，非历史数据）
        """
        self.logger.info(f"[Byapi] 开始实时采集{code}的1分钟数据，时长{duration_minutes}分钟")
        
        result_data = []
        prev_data = None
        
        for i in range(duration_minutes):
            try:
                # 获取实时数据
                df = self.fetch_stock_realtime(code)
                current_data = df.iloc[0].to_dict()
                current_time = datetime.now()
                current_price = current_data.get('close', 0)
                
                if prev_data is not None:
                    # 生成1分钟K线
                    kline = {
                        'time': current_time.strftime('%Y-%m-%d %H:%M:00'),
                        'open': prev_data.get('close', current_price),
                        'close': current_price,
                        'high': max(prev_data.get('close', current_price), current_price),
                        'low': min(prev_data.get('close', current_price), current_price),
                        'volume': current_data.get('volume', 0) - prev_data.get('volume', 0),
                        'amount': current_data.get('amount', 0) - prev_data.get('amount', 0),
                    }
                    result_data.append(kline)
                    self.logger.info(f"第{i+1}分钟: O={kline['open']:.2f}, C={kline['close']:.2f}, V={kline['volume']}")
                
                prev_data = current_data
                
                # 等待1分钟(最后一次不等待)
                if i < duration_minutes - 1:
                    time.sleep(60)
                    
            except Exception as e:
                self.logger.error(f"第{i+1}分钟采集失败: {e}")
                continue
        
        if not result_data:
            raise ValueError("未采集到任何数据")
        
        df = pd.DataFrame(result_data)
        self.logger.info(f"实时采集完成，共生成{len(df)}条1分钟K线")
        return df


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
        
        注意：Byapi不提供交易日历接口，此方法不可用
        
        Args:
            start_date: 开始日期 'YYYY-MM-DD'
            end_date: 结束日期 'YYYY-MM-DD'
        
        Returns:
            DataFrame: 包含交易日期
        """
        raise NotImplementedError("Byapi不支持交易日历接口")
    
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
