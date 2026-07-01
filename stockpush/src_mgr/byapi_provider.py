"""
Byapi数据源Provider
通过HTTP API获取实时行情数据
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import time

from .src_provider import BaseProvider
from .standard_api_adapter import StandardAPIAdapter


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
    - 不支持：1分钟历史数据（可通过实时接口采集生成临时数据）
    
    【请求频率】
    - 基础版：1分钟300次
    - 包年版：1分钟3000次
    - 白金版：1分钟6000次
    """
    
    CAPABILITIES = {
        'stock_realtime': True,       # ✅ 股票实时行情
        'stock_daily': True,          # ✅ 股票历史日线
        'stock_1min': False,          # ❌ 不支持1分钟历史数据（可用实时采集方法）
        'stock_5min': True,           # ✅ 股票5分钟线
        'stock_15min': True,          # ✅ 股票15分钟线
        'stock_30min': True,          # ✅ 股票30分钟线
        'stock_60min': True,          # ✅ 股票60分钟线
        'stock_weekly': True,         # ✅ 股票周线
        'stock_monthly': True,        # ✅ 股票月线
        'fund_realtime': True,        # ✅ 基金实时行情
        'fund_daily': True,           # ✅ 基金历史日线
        'fund_1min': False,           # ❌ 不支持1分钟历史数据
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
            
        except requests.RequestException as e:
            self.logger.error(f"HTTP请求失败: {e}")
            raise
        except Exception as e:
            self.logger.error(f"请求处理失败: {e}")
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
            df['date'] = pd.to_datetime(df['time']) if 'time' in df.columns else pd.Timestamp.now()
            
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
            df['date'] = pd.to_datetime(df['time']) if 'time' in df.columns else pd.Timestamp.now()
            
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
    
    def fetch_stock_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票历史日线数据
        
        【接口】https://api.biyingapi.com/hsstock/history/{code}.{market}/d/n/{licence}?st={start}&et={end}
        
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

            if 'date' in df.columns and not df.empty:
                col = df['date']
                if pd.api.types.is_numeric_dtype(col):
                    sample = col.dropna().iloc[0] if len(col.dropna()) > 0 else None
                    if sample is not None and abs(float(sample)) > 1e12:
                        df['date'] = pd.to_datetime(col, unit='ms')
                    elif sample is not None and abs(float(sample)) > 1e9:
                        df['date'] = pd.to_datetime(col, unit='s')
            
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

    _PERIOD_MAP_BYAPI = {
        '1d': 'd', '5m': '5', '15m': '15', '30m': '30', '60m': '60',
        '1w': 'w', '1M': 'm',
    }

    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock') -> pd.DataFrame:
        if period == '1m':
            raise NotImplementedError("Byapi不支持1分钟历史数据")
        byapi_period = self._PERIOD_MAP_BYAPI.get(period)
        if not byapi_period:
            raise ValueError(f"Byapi不支持周期: {period}")
        if period == '1d':
            return self.fetch_stock_daily(code, start, end)
        else:
            if asset_type == 'fund':
                raise NotImplementedError("Byapi基金分钟线暂未实现")
            return self._fetch_stock_period(code, start, end, byapi_period)

    def fetch_quote(self, code: str, asset_type: str = 'stock') -> pd.DataFrame:
        if asset_type == 'fund':
            return self.fetch_fund_realtime(code)
        else:
            return self.fetch_stock_realtime(code)

    def _fetch_stock_period(self, code: str, start_date: str, end_date: str, period: str) -> pd.DataFrame:
        """
        获取股票指定周期K线历史数据
        
        【支持的周期】
        - 分钟级：5、15、30、60
        - 日线及以上：d(日)、w(周)、m(月)、y(年)
        - ❌不支持1分钟
        
        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            period: 周期代码 ('5','15','30','60','d','w','m','y')
        """
        try:
            stock_code, market = self._parse_stock_code(code)
            url = f"{self.base_url_https}/hsstock/history/{stock_code}.{market}/{period}/f/{self.licence}"  # 前复权
            url += f"?st={start_date.replace('-', '')}&et={end_date.replace('-', '')}"
            
            self.logger.info(f"[Byapi] 获取股票{period}分钟线 {code} [{start_date} ~ {end_date}]")
            
            data = self._make_request(url)
            
            if not data or len(data) == 0:
                raise ValueError(f"未获取到数据: {code}")
            
            df = pd.DataFrame(data)
            
            field_map = {
                't': 'date',
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume',
                'a': 'amount',
            }
            
            df = df.rename(columns=field_map)
            df['code'] = code

            if 'date' in df.columns and not df.empty:
                col = df['date']
                if pd.api.types.is_numeric_dtype(col):
                    sample = col.dropna().iloc[0] if len(col.dropna()) > 0 else None
                    if sample is not None and abs(float(sample)) > 1e12:
                        df['date'] = pd.to_datetime(col, unit='ms')
                    elif sample is not None and abs(float(sample)) > 1e9:
                        df['date'] = pd.to_datetime(col, unit='s')
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取股票{period}分钟线失败: {e}")
            raise
