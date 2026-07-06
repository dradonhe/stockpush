"""
新浪财经数据源Provider
通过直接调用新浪财经API，提供实时行情和历史数据
"""
import pandas as pd
import numpy as np
import requests
import json
from datetime import datetime
from typing import Optional

from .src_provider import BaseProvider
from .standard_api_adapter import StandardAPIAdapter


class SinaProvider(BaseProvider, StandardAPIAdapter):
    """
    新浪财经数据Provider

    【数据源说明】
    - 数据来源：新浪财经（直接HTTP API）
    - 特点：实时数据更新快、接口稳定
    - 主要功能：股票/指数实时行情、指数历史数据
    - 依赖：直接用 requests 调用新浪行情中心
    
    CAPABILITIES:
        stock_realtime: True     - 股票实时行情
        stock_daily: False       - 不提供个股日线（仅支持指数）
        fund_realtime: True      - 基金实时行情
        stock_list: True         - 股票代码列表
        trade_calendar: True     - 交易日历
        index_realtime: True     - 指数实时行情
        index_daily: True        - 指数历史日线
    """

    CAPABILITIES = {
        'stock_realtime': True,       # 股票实时行情
        'stock_daily': False,         # 不支持个股日线（仅支持指数）
        'stock_1min': False,          # 不支持分钟线
        'stock_5min': False,          # 不支持分钟线
        'stock_15min': False,         # 不支持分钟线
        'stock_30min': False,         # 不支持分钟线
        'stock_60min': False,         # 不支持分钟线
        'fund_realtime': True,        # 基金实时行情（场内ETF）
        'fund_daily': False,          # 不支持基金日线
        'stock_list': True,           # 股票代码列表
        'trade_calendar': True,       # 交易日历
        'index_realtime': True,       # 指数实时行情
        'index_daily': True,          # 指数历史日线
    }

    # 新浪行情中心API字段名 → 标准化字段名
    HQ_FIELD_MAP = {
        'symbol': 'code',
        'name': 'name',
        'trade': 'price',
        'pricechange': 'change',
        'changepercent': 'change_pct',
        'yesterday': 'pre_close',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'volume': 'volume',
        'amount': 'amount',
    }

    def __init__(self):
        """初始化新浪数据Provider"""
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.sina.com.cn/",
        })
        self.logger.info("Sina Provider 初始化成功")

    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock') -> pd.DataFrame:
        raise NotImplementedError("Sina不支持K线历史数据，仅支持实时行情和指数日线")

    def fetch_quote(self, code: str, asset_type: str = 'stock') -> pd.DataFrame:
        if asset_type == 'fund':
            return self.fetch_fund_realtime(code)
        else:
            return self.fetch_stock_realtime(code)

    def _fetch_hq_data(self, node: str = "hs_a", num: int = 5000) -> pd.DataFrame:
        """
        获取新浪行情中心节点数据

        Args:
            node: 节点名称，如 'hs_a'(A股), 'hs_index'(指数)
            num: 每页数量

        Returns:
            DataFrame: 包含实时行情数据
        """
        url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {
            "page": 1,
            "num": num,
            "sort": "symbol",
            "asc": 1,
            "node": node,
            "_s_r_a": "page",
        }
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        text = resp.text.strip()
        # API 返回的数据格式为: ({json_data})
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1]
        data = json.loads(text)
        df = pd.DataFrame(data)
        if not df.empty:
            # 重命名英文列名为标准化名称
            rename_map = {k: v for k, v in self.HQ_FIELD_MAP.items() if k in df.columns}
            if rename_map:
                df = df.rename(columns=rename_map)
        return df

    # ==================== 股票实时行情 ====================

    def fetch_stock_realtime(self, code: str = None) -> pd.DataFrame:
        """
        获取股票实时行情

        直接调用新浪行情中心API获取股票实时行情

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
        """
        super().fetch_stock_realtime(code)  # 能力检测

        try:
            self.logger.info(f"[新浪] 获取股票实时行情 {code if code else '全市场'}")

            df = self._fetch_hq_data("hs_a", 5000)

            if df is None or df.empty:
                raise ValueError("未获取到股票实时行情数据")

            # 如果指定了代码，过滤出该股票
            if code:
                df = df[df['code'] == code]
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
        """获取全市场股票实时行情"""
        return self.fetch_stock_realtime(code=None)

    # ==================== 指数数据 ====================

    def fetch_index_realtime(self) -> pd.DataFrame:
        """
        获取指数实时行情

        直接调用新浪行情中心API获取指数实时行情

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
        """
        try:
            self.logger.info("[新浪] 获取指数实时行情")

            df = self._fetch_hq_data("hs_index", 500)

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

        直接调用新浪历史K线API

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
        """
        try:
            self.logger.info(f"[新浪] 获取指数历史日线 {symbol}")

            url = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData"
            params = {
                "symbol": symbol,
                "scale": 240,  # 日线
                "datalen": 1023,
            }
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                raise ValueError(f"未获取到指数数据: {symbol}")

            df = pd.DataFrame(data)
            # 字段: day, open, high, low, close, volume (来自新浪API)
            df = df.rename(columns={
                'day': 'date',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume',
            })
            # 转换为数值类型
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            self.logger.info(f"获取成功，数据行数: {len(df)}")
            return df

        except Exception as e:
            self.logger.error(f"获取指数历史日线失败: {e}")
            raise

    # ==================== 基金实时行情 ====================

    def fetch_fund_realtime(self, code: str = None) -> pd.DataFrame:
        """
        获取场内基金(ETF/LOF)实时行情

        Args:
            code: 基金代码，如'510300'。如果为None则返回全市场数据

        Returns:
            DataFrame: 包含基金实时行情数据
        """
        try:
            self.logger.info(f"[新浪] 获取基金实时行情 {code if code else '全市场'}")

            df = self._fetch_hq_data("hs_a", 5000)

            if df is None or df.empty:
                raise ValueError("未获取到实时行情数据")

            # 过滤场内基金（代码以51/15/16/50开头）
            df = df[df['code'].str.startswith(('51', '15', '16', '50'))]

            # 如果指定了代码，进一步过滤
            if code:
                df = df[df['code'] == code]
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

        通过直接HTTP请求获取新浪交易日历数据

        Args:
            start_date: 开始日期，格式'YYYY-MM-DD'，默认不限制
            end_date: 结束日期，格式'YYYY-MM-DD'，默认不限制

        Returns:
            DataFrame: 包含交易日期列表
            - date: 交易日期
        """
        try:
            self.logger.info(f"[新浪] 获取交易日历 [{start_date} ~ {end_date}]")

            # 获取新浪交易日历数据（CSV格式）
            url = "https://finance.sina.com.cn/realstock/company/calender/calender.csv"
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()

            rows = []
            for line in lines:
                parts = line.split(",")
                if len(parts) >= 1:
                    date_str = parts[0].strip()
                    if date_str.isdigit() and len(date_str) == 8:
                        trade_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                        rows.append({"trade_date": trade_date})

            if not rows:
                raise ValueError("未获取到交易日历数据")

            df = pd.DataFrame(rows)
            df['date'] = pd.to_datetime(df['trade_date'])

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

        Returns:
            DataFrame: 包含股票代码、名称等信息
            - code: 股票代码
            - name: 股票名称
        """
        try:
            self.logger.info("[新浪] 获取股票代码列表")

            df = self._fetch_hq_data("hs_a", 5000)

            if df is None or df.empty:
                raise ValueError("未获取到股票代码列表")

            # 新浪 API 返回重复的 code 列（含前缀版 / 纯数字版）
            # df['code'] 返回 DataFrame 而非 Series，需特殊处理
            code_col = df.columns.get_loc('code')
            if isinstance(code_col, np.ndarray):
                # 重复列名：取第二列（纯数字代码）
                codes = df.iloc[:, int(code_col[1])].astype(str).str.strip()
            else:
                codes = df['code'].astype(str).str.strip()

            result = pd.DataFrame({
                'code': codes.values,
                'name': df['name'].values
            })

            # 过滤掉非股票（保留沪深北A股）
            result = result[result['code'].str.match(r'^\d{6}$')]

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

            df = self._fetch_hq_data("hs_a", 5000)

            if df is None or df.empty:
                raise ValueError("未获取到基金代码列表")

            # 提取代码和名称
            result = pd.DataFrame({
                'code': df['code'],
                'name': df['name']
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
        # 如果没有code列（说明已标准化），直接返回
        if 'code' not in df.columns:
            return df

        # 添加 date 列（实时行情使用当前时间）
        if 'date' not in df.columns:
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
