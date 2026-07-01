"""
新浪财经数据源Provider
通过AkShare调用新浪财经接口，提供实时行情和历史数据
"""
import pandas as pd
from datetime import datetime
from typing import Optional

from .src_provider import BaseProvider
from .standard_api_adapter import StandardAPIAdapter


class SinaProvider(BaseProvider, StandardAPIAdapter):
    """
    新浪财经数据Provider

    【数据源说明】
    - 数据来源：新浪财经（通过AkShare接口）
    - 特点：实时数据更新快、接口稳定
    - 主要功能：股票/指数实时行情、指数历史数据

    【接口能力】
    ✅ 股票实时行情：ak.stock_zh_a_spot() - 全市场实时行情
    ✅ 指数实时行情：ak.stock_zh_index_spot_sina() - 指数实时数据
    ✅ 指数历史日线：ak.stock_zh_index_daily(symbol) - 指数历史数据
    ✅ 交易日历：ak.tool_trade_date_hist_sina() - 交易日列表
    ❌ 分钟线数据：不支持

    【与东方财富接口对比】
    ┌──────────────┬────────────────────┬────────────────────┐
    │     特性     │      新浪(Sina)    │    东方财富(EM)    │
    ├──────────────┼────────────────────┼────────────────────┤
    │ 实时行情速度 │        更快        │        稍慢        │
    │ 分钟线数据   │        ❌          │        ✅          │
    │ 复权支持     │        ❌          │        ✅          │
    │ 日线历史     │   仅指数(部分)     │   全部股票/ETF     │
    │ 代码列表     │        ✅          │        ✅          │
    │ 交易日历     │        ✅          │        ✅          │
    └──────────────┴────────────────────┴────────────────────┘

    【使用场景】
    - 实时行情监控（首选）
    - 指数数据查询
    - 交易日历获取
    """

    CAPABILITIES = {
        'stock_realtime': True,       # ✅ 股票实时行情
        'stock_daily': False,         # ❌ 不支持个股日线（仅支持指数）
        'stock_1min': False,          # ❌ 不支持分钟线
        'stock_5min': False,          # ❌ 不支持分钟线
        'stock_15min': False,         # ❌ 不支持分钟线
        'stock_30min': False,         # ❌ 不支持分钟线
        'stock_60min': False,         # ❌ 不支持分钟线
        'fund_realtime': True,        # ✅ 基金实时行情（场内ETF）
        'fund_daily': False,          # ❌ 不支持基金日线
        'stock_list': True,           # ✅ 股票代码列表
        'trade_calendar': True,       # ✅ 交易日历
        'index_realtime': True,       # ✅ 指数实时行情
        'index_daily': True,          # ✅ 指数历史日线
    }
    
    def __init__(self):
        """初始化新浪数据Provider"""
        super().__init__()
        
        try:
            import akshare as ak
            self.ak = ak
            self.logger.info("Sina Provider 初始化成功")
        except ImportError:
            self.logger.error("AkShare 未安装，请执行: pip install akshare")
            raise

    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock') -> pd.DataFrame:
        raise NotImplementedError("Sina不支持K线历史数据，仅支持实时行情和指数日线")

    def fetch_quote(self, code: str, asset_type: str = 'stock') -> pd.DataFrame:
        if asset_type == 'fund':
            return self.fetch_fund_realtime(code)
        else:
            return self.fetch_stock_realtime(code)

    # ==================== 股票实时行情 ====================
    
    def fetch_stock_realtime(self, code: str = None) -> pd.DataFrame:
        """
        获取股票实时行情
        
        【接口】akshare.stock_zh_a_spot()
        【数据源】新浪财经
        【更新频率】交易时间实时更新
        
        Args:
            code: 股票代码，如'000001'。如果为None则返回全市场数据
        
        Returns:
            DataFrame: 包含实时行情数据
            - 代码: 股票代码
            - 名称: 股票名称
            - 最新价: 当前价格
            - 涨跌额: 价格变动
            - 涨跌幅: 涨跌百分比
            - 昨收: 昨日收盘价
            - 今开: 今日开盘价
            - 最高: 今日最高价
            - 最低: 今日最低价
            - 成交量: 成交量(手)
            - 成交额: 成交金额(元)
        
        示例:
            >>> provider = SinaProvider()
            >>> df = provider.fetch_stock_realtime("000001")
            >>> print(df)
        """
        super().fetch_stock_realtime(code)  # 能力检测
        
        try:
            self.logger.info(f"[新浪] 获取股票实时行情 {code if code else '全市场'}")
            
            # 获取全市场实时行情
            df = self.ak.stock_zh_a_spot()
            
            if df is None or df.empty:
                raise ValueError("未获取到股票实时行情数据")
            
            # 如果指定了代码，过滤出该股票
            if code:
                df = df[df['代码'] == code]
                if df.empty:
                    raise ValueError(f"未找到股票代码: {code}")
            
            # 标准化字段名
            df = self._standardize_realtime_fields(df)
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取股票实时行情失败: {e}")
            raise
    
    def fetch_stock_realtime_all(self) -> pd.DataFrame:
        """
        获取全市场股票实时行情
        
        Returns:
            DataFrame: 全市场实时行情数据
        """
        return self.fetch_stock_realtime(code=None)
    
    # ==================== 指数数据 ====================
    
    def fetch_index_realtime(self) -> pd.DataFrame:
        """
        获取指数实时行情
        
        【接口】akshare.stock_zh_index_spot_sina()
        【数据源】新浪财经
        
        Returns:
            DataFrame: 包含指数实时数据
            - 代码: 指数代码
            - 名称: 指数名称
            - 最新价: 当前点位
            - 涨跌额: 点位变动
            - 涨跌幅: 涨跌百分比
            - 昨收: 昨日收盘
            - 今开: 今日开盘
            - 最高: 今日最高
            - 最低: 今日最低
            - 成交量: 成交量(手)
            - 成交额: 成交金额(元)
        
        示例:
            >>> provider = SinaProvider()
            >>> df = provider.fetch_index_realtime()
            >>> print(df[df['名称'].str.contains('上证')])
        """
        try:
            self.logger.info("[新浪] 获取指数实时行情")
            
            df = self.ak.stock_zh_index_spot_sina()
            
            if df is None or df.empty:
                raise ValueError("未获取到指数实时行情数据")
            
            # 标准化字段名
            df = self._standardize_realtime_fields(df)
            
            self.logger.info(f"获取成功，指数数量: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取指数实时行情失败: {e}")
            raise
    
    def fetch_index_daily(self, symbol: str) -> pd.DataFrame:
        """
        获取指数历史日线数据
        
        【接口】akshare.stock_zh_index_daily(symbol)
        【数据源】新浪财经
        
        Args:
            symbol: 指数代码，格式如 'sh000001' 或 'sz399001'
                    - sh: 上海证券交易所
                    - sz: 深圳证券交易所
        
        Returns:
            DataFrame: 包含指数历史日线数据
            - date: 日期
            - open: 开盘点位
            - close: 收盘点位
            - high: 最高点位
            - low: 最低点位
            - volume: 成交量
        
        示例:
            >>> provider = SinaProvider()
            >>> df = provider.fetch_index_daily("sh000001")  # 上证指数
            >>> print(df.tail())
        """
        try:
            self.logger.info(f"[新浪] 获取指数历史日线 {symbol}")
            
            df = self.ak.stock_zh_index_daily(symbol=symbol)
            
            if df is None or df.empty:
                raise ValueError(f"未获取到指数数据: {symbol}")
            
            # 标准化字段（新浪指数接口字段已经是标准格式）
            # 字段: date, open, close, high, low, volume
            df = self._standardize_fields(df, 'akshare')
            
            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取指数历史日线失败: {e}")
            raise
    
    # ==================== 基金实时行情 ====================
    
    def fetch_fund_realtime(self, code: str = None) -> pd.DataFrame:
        """
        获取场内基金(ETF/LOF)实时行情
        
        注意：新浪接口的股票实时行情也包含场内基金
        
        Args:
            code: 基金代码，如'510300'。如果为None则返回全市场数据
        
        Returns:
            DataFrame: 包含基金实时行情数据
        """
        try:
            self.logger.info(f"[新浪] 获取基金实时行情 {code if code else '全市场'}")
            
            # 获取全市场实时行情（包含ETF）
            df = self.ak.stock_zh_a_spot()
            
            if df is None or df.empty:
                raise ValueError("未获取到实时行情数据")
            
            # 过滤场内基金（代码以5开头）
            df = df[df['代码'].str.startswith(('51', '15', '16', '50'))]
            
            # 如果指定了代码，进一步过滤
            if code:
                df = df[df['代码'] == code]
                if df.empty:
                    raise ValueError(f"未找到基金代码: {code}")
            
            # 标准化字段名
            df = self._standardize_realtime_fields(df)
            
            self.logger.info(f"获取成功，基金数量: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取基金实时行情失败: {e}")
            raise
    
    # ==================== 基础数据接口 ====================
    
    def fetch_trade_calendar(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        获取交易日历
        
        【接口】akshare.tool_trade_date_hist_sina()
        【数据源】新浪财经
        
        Args:
            start_date: 开始日期，格式'YYYY-MM-DD'，默认不限制
            end_date: 结束日期，格式'YYYY-MM-DD'，默认不限制
        
        Returns:
            DataFrame: 包含交易日期列表
            - date: 交易日期
        
        示例:
            >>> provider = SinaProvider()
            >>> df = provider.fetch_trade_calendar("2024-01-01", "2024-03-01")
            >>> print(df.head())
        """
        try:
            self.logger.info(f"[新浪] 获取交易日历 [{start_date} ~ {end_date}]")
            
            # 获取所有交易日期
            df = self.ak.tool_trade_date_hist_sina()
            
            if df is None or df.empty:
                raise ValueError("未获取到交易日历数据")
            
            # 重命名列
            df = df.rename(columns={'trade_date': 'date'})
            
            # 转换日期格式
            df['date'] = pd.to_datetime(df['date'])
            
            # 过滤日期范围
            if start_date:
                start = pd.to_datetime(start_date)
                df = df[df['date'] >= start]
            
            if end_date:
                end = pd.to_datetime(end_date)
                df = df[df['date'] <= end]
            
            # 格式化日期
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            
            self.logger.info(f"获取成功，交易日数量: {len(df)}")
            return df
            
        except Exception as e:
            self.logger.error(f"获取交易日历失败: {e}")
            raise
    
    def fetch_stock_list(self) -> pd.DataFrame:
        """
        获取股票代码列表
        
        注意：新浪实时行情接口可以获取全市场代码
        
        Returns:
            DataFrame: 包含股票代码、名称等信息
            - code: 股票代码
            - name: 股票名称
        """
        try:
            self.logger.info("[新浪] 获取股票代码列表")
            
            # 通过实时行情接口获取代码列表
            df = self.ak.stock_zh_a_spot()
            
            if df is None or df.empty:
                raise ValueError("未获取到股票代码列表")
            
            # 提取代码和名称
            result = pd.DataFrame({
                'code': df['代码'],
                'name': df['名称']
            })
            
            # 过滤掉非股票（如指数、基金等）
            # 股票代码: 6开头(上海)、00/30开头(深圳)
            result = result[result['code'].str.match(r'^[036]\d{5}$')]
            
            self.logger.info(f"获取成功，股票数量: {len(result)}")
            return result
            
        except Exception as e:
            self.logger.error(f"获取股票代码列表失败: {e}")
            raise
    
    def fetch_fund_list(self) -> pd.DataFrame:
        """
        获取场内基金(ETF/LOF)代码列表
        
        Returns:
            DataFrame: 包含基金代码、名称等信息
            - code: 基金代码
            - name: 基金名称
        """
        try:
            self.logger.info("[新浪] 获取场内基金代码列表")
            
            # 通过实时行情接口获取代码列表
            df = self.ak.stock_zh_a_spot()
            
            if df is None or df.empty:
                raise ValueError("未获取到基金代码列表")
            
            # 提取代码和名称
            result = pd.DataFrame({
                'code': df['代码'],
                'name': df['名称']
            })
            
            # 过滤场内基金（代码以51/15/16/50开头）
            result = result[result['code'].str.startswith(('51', '15', '16', '50'))]
            
            self.logger.info(f"获取成功，基金数量: {len(result)}")
            return result
            
        except Exception as e:
            self.logger.error(f"获取基金代码列表失败: {e}")
            raise
    
    # ==================== 辅助方法 ====================
    
    def _standardize_realtime_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        标准化实时行情字段名
        
        Args:
            df: 原始数据
        
        Returns:
            标准化后的DataFrame
        """
        field_map = {
            '代码': 'code',
            '名称': 'name',
            '最新价': 'price',
            '涨跌额': 'change',
            '涨跌幅': 'change_pct',
            '昨收': 'pre_close',
            '今开': 'open',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
        }
        
        df = df.rename(columns=field_map)
        
        # 添加 date 列（实时行情没有时间戳字段，使用当前时间）
        df['date'] = pd.Timestamp.now()
        
        # 成交量从手转换为股（手 * 100）
        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce') * 100
        
        # 转换数值类型
        numeric_fields = ['price', 'change', 'change_pct', 'pre_close', 'open', 'high', 'low', 'amount']
        for field in numeric_fields:
            if field in df.columns:
                df[field] = pd.to_numeric(df[field], errors='coerce')
        
        return df
    
    def get_capability_matrix(self) -> dict:
        """
        获取数据源能力矩阵
        
        Returns:
            能力字典
        """
        return self.CAPABILITIES.copy()


# ==================== 测试代码 ====================

if __name__ == "__main__":
    """测试新浪数据源接口"""
    
    print("=" * 60)
    print("新浪财经数据源接口测试")
    print("=" * 60)
    
    provider = SinaProvider()
    
    # 1. 测试股票实时行情
    print("\n1. 测试股票实时行情...")
    try:
        df = provider.fetch_stock_realtime("000001")
        print(f"   ✅ 获取成功，数据行数: {len(df)}")
        print(df.head())
    except Exception as e:
        print(f"   ❌ 获取失败: {e}")
    
    # 2. 测试指数实时行情
    print("\n2. 测试指数实时行情...")
    try:
        df = provider.fetch_index_realtime()
        print(f"   ✅ 获取成功，指数数量: {len(df)}")
        print(df.head())
    except Exception as e:
        print(f"   ❌ 获取失败: {e}")
    
    # 3. 测试指数历史日线
    print("\n3. 测试指数历史日线...")
    try:
        df = provider.fetch_index_daily("sh000001")
        print(f"   ✅ 获取成功，数据行数: {len(df)}")
        print(df.tail())
    except Exception as e:
        print(f"   ❌ 获取失败: {e}")
    
    # 4. 测试交易日历
    print("\n4. 测试交易日历...")
    try:
        df = provider.fetch_trade_calendar("2024-01-01", "2024-03-01")
        print(f"   ✅ 获取成功，交易日数量: {len(df)}")
        print(df.head())
    except Exception as e:
        print(f"   ❌ 获取失败: {e}")
    
    # 5. 测试股票代码列表
    print("\n5. 测试股票代码列表...")
    try:
        df = provider.fetch_stock_list()
        print(f"   ✅ 获取成功，股票数量: {len(df)}")
        print(df.head())
    except Exception as e:
        print(f"   ❌ 获取失败: {e}")
    
    # 6. 测试基金代码列表
    print("\n6. 测试基金代码列表...")
    try:
        df = provider.fetch_fund_list()
        print(f"   ✅ 获取成功，基金数量: {len(df)}")
        print(df.head())
    except Exception as e:
        print(f"   ❌ 获取失败: {e}")
    
    # 7. 显示能力矩阵
    print("\n7. 数据源能力矩阵:")
    caps = provider.get_capability_matrix()
    for cap, status in caps.items():
        symbol = "✅" if status else "❌"
        print(f"   {symbol} {cap}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)