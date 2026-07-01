"""
通达信本地数据Provider
直接读取通达信本地数据文件（.day, .lc5, .lc1）
支持股票和场内基金（ETF/LOF）的历史数据
"""
import os
import struct
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List
import pandas as pd

from .src_provider import BaseProvider
from .standard_api_adapter import StandardAPIAdapter


class TdxLocalProvider(BaseProvider, StandardAPIAdapter):
    """
    通达信本地数据Provider
    
    【数据源说明】
    - 数据来源：通达信客户端下载的本地数据文件
    - 特点：完全离线、速度快、无调用限制
    - 主要功能：股票/场内基金历史数据（日线、5分钟、1分钟）
    
    【文件位置】
    - 日线数据：vipdoc\sh\lday\, vipdoc\sz\lday\
    - 5分钟数据：vipdoc\sh\fzline\, vipdoc\sz\fzline\
    - 1分钟数据：vipdoc\sh\minline\, vipdoc\sz\minline\
    
    【文件格式】
    - 日线：.day 文件（32字节/记录）
    - 5分钟：.lc5 文件（32字节/记录）
    - 1分钟：.lc1 文件（32字节/记录）
    
    【文件命名规则】
    - 文件名格式：{市场代码}{证券代码}.{扩展名}
    - 例如：sh601818.day（上海股票601818日线）
    - 例如：sz000001.lc5（深圳股票000001五分钟线）
    - 例如：sh510300.lc1（上海ETF510300一分钟线）
    
    【支持的数据类型】
    ✅ 股票日线/5分钟/1分钟
    ✅ 场内基金（ETF/LOF）日线/5分钟/1分钟
    ❌ 实时行情（需通达信运行）
    ❌ 开放式基金
    """
    
    CAPABILITIES = {
        'stock_realtime': False,      # ❌ 不支持实时行情
        'stock_daily': True,          # ✅ 股票日线
        'stock_1min': True,           # ✅ 股票1分钟线
        'stock_5min': True,           # ✅ 股票5分钟线
        'stock_15min': True,          # ✅ 股票15分钟线（由5分钟计算）
        'stock_30min': True,          # ✅ 股票30分钟线（由5分钟计算）
        'stock_60min': True,          # ✅ 股票60分钟线（由5分钟计算）
        'stock_weekly': True,         # ✅ 股票周线（由日线计算）
        'stock_monthly': True,        # ✅ 股票月线（由日线计算）
        'fund_realtime': False,       # ❌ 不支持实时行情
        'fund_daily': True,           # ✅ 基金日线
        'fund_1min': True,            # ✅ 基金1分钟线
        'fund_5min': True,            # ✅ 基金5分钟线
    }
    
    def __init__(self, tdx_path: str = None):
        """
        初始化通达信本地数据Provider
        
        Args:
            tdx_path: 通达信安装路径，如果不提供则自动检测
        """
        super().__init__()
        
        self.tdx_path = Path(tdx_path) if tdx_path else self._detect_tdx_path()
        self.vipdoc_path = self.tdx_path / 'vipdoc'
        
        if not self.vipdoc_path.exists():
            raise FileNotFoundError(f"通达信数据目录不存在: {self.vipdoc_path}")
        
        self.logger.info(f"通达信本地数据Provider初始化成功")
        self.logger.info(f"数据路径: {self.vipdoc_path}")
    
    def _detect_tdx_path(self) -> Path:
        """自动检测通达信安装路径"""
        common_paths = [
            r"C:\new_tdx",
            r"C:\new_hxtdx",
            r"D:\new_tdx",
            r"E:\new_tdx",
            r"D:\国金证券独立委托",
            r"C:\中信证券至胜版",
            r"C:\TDX",
            r"D:\TDX",
            r"E:\TDX",
            r"C:\zd_zsone",
            r"D:\zd_zsone",
            r"E:\zd_zsone",
        ]
        
        for path_str in common_paths:
            path = Path(path_str)
            if path.exists():
                vipdoc = path / 'vipdoc'
                if vipdoc.exists():
                    self.logger.info(f"检测到通达信安装路径: {path}")
                    return path
        
        raise FileNotFoundError(
            "未找到通达信安装目录\n"
            "请手动指定 tdx_path 参数，或将通达信安装到以下路径之一：\n"
            + "\n".join(common_paths)
        )
    
    def _get_market(self, code: str) -> str:
        """
        获取市场代码
        
        Args:
            code: 证券代码
        
        Returns:
            'sh' 或 'sz'
        """
        # 6开头：上海A股
        # 51/56开头：上海基金
        # 其他：深圳
        if code.startswith(('6', '51', '56')):
            return 'sh'
        else:
            return 'sz'
    
    def _parse_day_file(self, code: str) -> pd.DataFrame:
        """
        解析日线数据文件
        
        文件格式（32字节/记录）：
        - 日期(4字节): int, YYYYMMDD格式
        - 开盘价(4字节): float * 100
        - 最高价(4字节): float * 100
        - 最低价(4字节): float * 100
        - 收盘价(4字节): float * 100
        - 成交额(4字节): float
        - 成交量(4字节): int
        - 保留(4字节): int
        
        Args:
            code: 证券代码
        
        Returns:
            DataFrame: 包含日线数据
        """
        market = self._get_market(code)
        file_path = self.vipdoc_path / market / 'lday' / f'{market}{code}.day'
        
        if not file_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {file_path}")
        
        self.logger.debug(f"读取日线文件: {file_path}")
        
        # 读取二进制数据
        with open(file_path, 'rb') as f:
            data = f.read()
        
        # 解析数据
        records = []
        record_size = 32
        num_records = len(data) // record_size
        
        for i in range(num_records):
            offset = i * record_size
            try:
                # 解包：7个int + 1个float（32字节）
                # 日期(4) + 开(4) + 高(4) + 低(4) + 收(4) + 成交额(4) + 成交量(4) + 保留(4)
                unpacked = struct.unpack('IIIIIfII', data[offset:offset+record_size])
                
                date_int = unpacked[0]
                # 跳过无效日期
                if date_int < 19900101 or date_int > 20500101:
                    continue
                
                date = datetime.strptime(str(date_int), '%Y%m%d')
                
                records.append({
                    'date': date,
                    'open': unpacked[1] / 100.0,
                    'high': unpacked[2] / 100.0,
                    'low': unpacked[3] / 100.0,
                    'close': unpacked[4] / 100.0,
                    'amount': unpacked[5],
                    'volume': unpacked[6],
                })
            except Exception as e:
                self.logger.warning(f"解析第{i}条记录失败: {e}")
                continue
        
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records)
        df['code'] = code
        df = df.sort_values('date').reset_index(drop=True)
        
        self.logger.debug(f"成功解析 {len(df)} 条日线数据")
        return df
    
    def _parse_minute_file(self, code: str, period: str) -> pd.DataFrame:
        """
        解析分钟数据文件
        
        文件格式（32字节/记录）：
        - 日期(2字节): short, 相对1900年的天数
        - 时间(2字节): short, 分钟数（如 09:31 = 9*60+31 = 571）
        - 开盘价(4字节): float * 100
        - 最高价(4字节): float * 100
        - 最低价(4字节): float * 100
        - 收盘价(4字节): float * 100
        - 成交额(4字节): float
        - 成交量(4字节): int
        - 保留(4字节): int
        
        Args:
            code: 证券代码
            period: 周期，'1' 或 '5'
        
        Returns:
            DataFrame: 包含分钟数据
        """
        market = self._get_market(code)
        
        if period == '1':
            folder = 'minline'
            ext = '.lc1'
        elif period == '5':
            folder = 'fzline'
            ext = '.lc5'
        else:
            raise ValueError(f"不支持的周期: {period}")
        
        file_path = self.vipdoc_path / market / folder / f'{market}{code}{ext}'
        
        if not file_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {file_path}")
        
        self.logger.debug(f"读取{period}分钟文件: {file_path}")
        
        # 读取二进制数据
        with open(file_path, 'rb') as f:
            data = f.read()
        
        # 解析数据
        records = []
        record_size = 32
        num_records = len(data) // record_size
        
        base_date = datetime(1900, 1, 1)
        
        for i in range(num_records):
            offset = i * record_size
            try:
                # 解包：2个short + 4个float + 1个float + 2个int（32字节）
                # 日期offset(2) + 分钟offset(2) + 开(4) + 高(4) + 低(4) + 收(4) + 成交额(4) + 成交量(4) + 保留(4)
                # 注意：分钟数据中价格字段是float格式，直接使用不需要除以100
                unpacked = struct.unpack('HHfffffII', data[offset:offset+record_size])
                
                date_offset = unpacked[0]
                minute_offset = unpacked[1]
                
                # 计算日期和时间
                date = base_date + timedelta(days=date_offset)
                hour = minute_offset // 60
                minute = minute_offset % 60
                
                # 跳过无效时间
                if hour >= 24 or minute >= 60:
                    continue
                
                datetime_val = date.replace(hour=hour, minute=minute)
                
                # 跳过1900年以前和2050年以后的数据
                if datetime_val.year < 1990 or datetime_val.year > 2050:
                    continue
                
                records.append({
                    'datetime': datetime_val,
                    'open': unpacked[2],  # 分钟数据的价格是float，直接使用
                    'high': unpacked[3],
                    'low': unpacked[4],
                    'close': unpacked[5],
                    'amount': unpacked[6],
                    'volume': unpacked[7],
                })
            except Exception as e:
                self.logger.warning(f"解析第{i}条记录失败: {e}")
                continue
        
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records)
        df['code'] = code
        df['date'] = df['datetime']
        df = df.sort_values('datetime').reset_index(drop=True)
        
        self.logger.debug(f"成功解析 {len(df)} 条{period}分钟数据")
        return df
    
    def _filter_date_range(self, df: pd.DataFrame, start_date: str, end_date: str, 
                           date_col: str = 'date') -> pd.DataFrame:
        """
        按日期范围过滤数据
        
        Args:
            df: 数据DataFrame
            start_date: 开始日期，格式 'YYYY-MM-DD' 或 'YYYYMMDD'
            end_date: 结束日期
            date_col: 日期列名
        
        Returns:
            过滤后的DataFrame
        """
        if df.empty:
            return df
        
        # 转换日期格式
        start_date = pd.to_datetime(start_date.replace('-', ''))
        end_date = pd.to_datetime(end_date.replace('-', ''))
        
        # 确保日期列是datetime类型
        if date_col == 'date':
            df[date_col] = pd.to_datetime(df[date_col])
        elif date_col == 'datetime':
            # 只比较日期部分
            mask = (df[date_col].dt.date >= start_date.date()) & \
                   (df[date_col].dt.date <= end_date.date())
            return df[mask].copy()
        
        # 过滤
        mask = (df[date_col] >= start_date) & (df[date_col] <= end_date)
        return df[mask].copy()
    
    def fetch_stock_realtime(self, code: str) -> pd.DataFrame:
        """不支持实时行情"""
        raise NotImplementedError("通达信本地数据不支持实时行情，请使用在线数据源或启用实时监控模式")
    
    def fetch_stock_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票历史日线数据
        
        Args:
            code: 股票代码，如 '000001'
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期
        
        Returns:
            DataFrame: 包含日线数据
        """
        super().fetch_stock_daily(code, start_date, end_date)
        
        try:
            self.logger.info(f"[TdxLocal] 获取股票日线 {code} [{start_date} ~ {end_date}]")
            
            # 解析文件
            df = self._parse_day_file(code)
            
            if df.empty:
                self.logger.warning(f"未找到数据: {code}")
                return df
            
            # 过滤日期范围
            df = self._filter_date_range(df, start_date, end_date, 'date')
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
        
        except Exception as e:
            self.logger.error(f"获取股票日线失败: {e}")
            raise
    
    def fetch_stock_1min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票1分钟线数据
        
        注意：分钟数据可能存在时间段缺失（非交易时间、停牌等）
        
        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataFrame: 包含1分钟数据
        """
        try:
            self.logger.info(f"[TdxLocal] 获取股票1分钟线 {code} [{start_date} ~ {end_date}]")
            
            # 解析文件
            df = self._parse_minute_file(code, '1')
            
            if df.empty:
                self.logger.warning(f"未找到数据: {code}")
                return df
            
            # 过滤日期范围
            df = self._filter_date_range(df, start_date, end_date, 'datetime')
            
            # 检查数据连续性
            if len(df) > 0:
                time_gaps = df['datetime'].diff()
                max_gap = time_gaps.max()
                if max_gap > timedelta(minutes=10):
                    self.logger.warning(f"数据存在较大时间间隔（最大间隔: {max_gap}），可能有数据缺失")
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
        
        except Exception as e:
            self.logger.error(f"获取股票1分钟线失败: {e}")
            raise
    
    def fetch_stock_5min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票5分钟线数据
        
        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataFrame: 包含5分钟数据
        """
        try:
            self.logger.info(f"[TdxLocal] 获取股票5分钟线 {code} [{start_date} ~ {end_date}]")
            
            # 解析文件
            df = self._parse_minute_file(code, '5')
            
            if df.empty:
                self.logger.warning(f"未找到数据: {code}")
                return df
            
            # 过滤日期范围
            df = self._filter_date_range(df, start_date, end_date, 'datetime')
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
        
        except Exception as e:
            self.logger.error(f"获取股票5分钟线失败: {e}")
            raise
    
    def fetch_fund_realtime(self, code: str) -> pd.DataFrame:
        """不支持实时行情"""
        raise NotImplementedError("通达信本地数据不支持实时行情")
    
    def fetch_fund_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取场内基金（ETF/LOF）历史日线数据
        
        注意：仅支持场内基金，不支持开放式基金
        
        Args:
            code: 基金代码，如 '159001'（ETF）
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataFrame: 包含日线数据
        """
        # 场内基金与股票使用相同的文件格式
        return self.fetch_stock_daily(code, start_date, end_date)
    
    def fetch_fund_1min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取场内基金1分钟线数据"""
        return self.fetch_stock_1min(code, start_date, end_date)
    
    def fetch_fund_5min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取场内基金5分钟线数据"""
        return self.fetch_stock_5min(code, start_date, end_date)

    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock') -> pd.DataFrame:
        period_map = {
            '1d': 'daily',
            '1m': '1', '5m': '5', '15m': '5', '30m': '5', '60m': '5',
        }
        p = period_map.get(period)
        if not p:
            raise ValueError(f"TdxLocal不支持周期: {period}")
        if p == 'daily':
            return self.fetch_stock_daily(code, start, end)
        else:
            df = self._parse_minute_file(code, p)
            if df.empty:
                return df
            df = self._filter_date_range(df, start, end, 'datetime')
            if period in ('15m', '30m', '60m') and not df.empty:
                freq = period.rstrip('m') + 'min'
                df['date'] = df['datetime']
                df = df.set_index('datetime')
                ohlc_dict = {'open': 'first', 'high': 'max', 'low': 'min',
                             'close': 'last', 'volume': 'sum', 'amount': 'sum'}
                df = df.resample(freq).agg(ohlc_dict).dropna()
                df = df.reset_index()
            return df

    def fetch_quote(self, code: str, asset_type: str = 'stock') -> pd.DataFrame:
        raise NotImplementedError("TdxLocal不支持实时行情")
