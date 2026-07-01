"""
TdxOnline数据源Provider - 基于通达信Quant接口(TQ)
使用TPythClient.dll与通达信客户端通信
要求：通达信客户端必须运行并登录

数据源标识: TdxOnline
"""

import os
import sys
import json
import threading
import time
import pandas as pd
from typing import Optional, List, Dict, Callable
from datetime import datetime, timedelta
from pathlib import Path
from abc import ABC

# ─── DLL 搜索路径设置（必须在 import tq 之前）──────────────────────────────
# 通达信根目录（优先从环境变量/已知路径）
_TDX_ROOT = os.environ.get('TDX_PATH', r'E:\new_tdx')
_PYPLUGINS_DIR = os.path.join(_TDX_ROOT, 'PYPlugins')
_PYPLUGINS_USER = os.path.join(_TDX_ROOT, 'PYPlugins', 'user')
if os.path.isdir(_PYPLUGINS_DIR):
    os.add_dll_directory(_PYPLUGINS_DIR)       # TPythClient.dll 所在目录
if os.path.isdir(_PYPLUGINS_USER):
    os.add_dll_directory(_PYPLUGINS_USER)      # Python 3.8+ DLL 搜索路径
    os.chdir(_TDX_ROOT)                         # 工作目录切到通达信根目录

# 导入BaseProvider
try:
    from .src_provider import BaseProvider
    from .standard_api_adapter import StandardAPIAdapter
except ImportError:
    from src_provider import BaseProvider
    from standard_api_adapter import StandardAPIAdapter

# 导入TQ接口
_dll_error = ""
tq = None

for _importer in (
    lambda: __import__('stockpush.tdxonline.user.tqcenter', fromlist=['tq']).tq,
    lambda: __import__('stockpush.tqcenter', fromlist=['tq']).tq,
    lambda: __import__('tqcenter', fromlist=['tq']).tq,
):
    try:
        tq = _importer()
        break
    except (ImportError, ModuleNotFoundError):
        continue
    except (FileNotFoundError, OSError) as e:
        _dll_error = str(e)
        tq = None
        break


class RealtimeSubscriptionManager:
    """
    TQ订阅管理器 - 管理实时行情订阅和分钟级K线数据缓存

    工作流程（正确模式）：
    1. 调用 subscribe() 订阅股票实时行情 (tq.subscribe_hq)
    2. TQ在行情更新时触发回调（通知不包含K线数据）
    3. 回调中用 tq.get_market_data(period='1m'/'5m'/'30m') 拉取K线
    4. 将K线数据缓存起来
    5. 调用 get_cached_minute_data() 获取缓存的分钟级数据

    限制：
    - 最多订阅100只股票
    - get_market_data 支持 1m/5m/15m/30m/60m/1d 等周期
    """

    # 支持的分钟周期映射（标准period -> TQ period）
    TQ_PERIOD_MAP = {
        '1': '1m',
        '5': '5m',
        '15': '1m',   # TQ没有15m，用1m然后自己对齐
        '30': '5m',   # TQ没有30m，用5m然后自己对齐
        '60': '1h',
    }

    def __init__(self, tq_module):
        self.tq = tq_module
        self._lock = threading.RLock()

        # 订阅状态: set of stock_code (如 '000001.SZ')
        self._subscribed: set = set()

        # 分钟K线缓存: { stock_code: { period: [ {date, open, high, low, close, volume, amount}, ... ] } }
        self._minute_cache: Dict[str, Dict[str, List[dict]]] = {}

        # 每只股票在TQ周期下的最后一条K线时间（用于去重拉取）
        # { stock_code: { tq_period: last_kline_time } }
        self._last_fetch: Dict[str, Dict[str, datetime]] = {}

        # 回调注册: { stock_code: callback_fn }
        self._callbacks: Dict[str, Callable] = {}

        # 最大缓存条数（防止内存无限增长）
        self._max_cache_size = 300

    def subscribe(self, stock_list: List[str], period: str = '1') -> bool:
        """
        订阅股票实时行情并缓存分钟级数据

        :param stock_list: 股票代码列表，如['000001.SZ', '600519.SH']
        :param period: 分钟周期，'1', '5', '15', '30', '60'
        :return: 是否成功
        """
        if not stock_list:
            return False

        tq_period = self.TQ_PERIOD_MAP.get(period, '1m')

        try:
            # 为每只股票创建独立的回调闭包
            def make_callback(c, tp):
                def on_hq_update(data_str: str):
                    try:
                        payload = json.loads(data_str)
                        if payload.get('ErrorId') == '0':
                            # 回调只收到通知，真正数据要拉取
                            self._fetch_and_cache(c, tp, period)
                            # 触发用户回调
                            cb = self._callbacks.get(c)
                            if cb:
                                cb(payload)
                    except Exception as e:
                        print(f"[RealtimeSub] 回调处理异常: {e}")
                return on_hq_update

            callbacks_to_register = {}
            for code in stock_list:
                cb = make_callback(code, tq_period)
                callbacks_to_register[code] = cb
                self._callbacks[code] = None

            # 注册到TQ的回调字典（run_id级别）
            run_id = self.tq._get_run_id()
            if run_id not in self.tq.data_callback_func:
                self.tq.data_callback_func[run_id] = {}
            for code in stock_list:
                self.tq.data_callback_func[run_id][code] = callbacks_to_register[code]

            self.tq.subscribe_hq(stock_list, callbacks_to_register[stock_list[0]])

            with self._lock:
                for code in stock_list:
                    self._subscribed.add(code)
                    if code not in self._minute_cache:
                        self._minute_cache[code] = {}
                    if code not in self._last_fetch:
                        self._last_fetch[code] = {}

            # 订阅成功后立即拉取一次数据
            for code in stock_list:
                self._fetch_and_cache(code, tq_period, period)

            print(f"[RealtimeSub] 订阅成功: {stock_list}, 周期: {period}(TQ:{tq_period})")
            return True

        except Exception as e:
            print(f"[RealtimeSub] 订阅失败: {e}")
            return False

    def _fetch_and_cache(self, stock_code: str, tq_period: str, std_period: str):
        """
        拉取指定股票的分钟K线并缓存

        :param stock_code: 股票代码，带后缀
        :param tq_period: TQ周期字符串，'1m'/'5m'/'1h'等
        :param std_period: 标准周期字符串，'1'/'5'/'15'/'30'/'60'
        """
        try:
            result = self.tq.get_market_data(
                stock_list=[stock_code],
                period=tq_period,
                start_time='',
                end_time='',
                count=10,  # 每次拉最近10根
                dividend_type='none',
                fill_data=True
            )

            if not result or stock_code not in result:
                return

            # get_market_data 返回格式: {field: DataFrame(索引=时间, 列=股票代码)}
            # 例如 result['Close'] 是 DataFrame，索引是 DatetimeIndex，列是 stock_code
            field_map = {
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume',
                'amount': 'Amount',
            }

            df = pd.DataFrame(index=pd.DatetimeIndex([]))
            for out_col, in_field in field_map.items():
                field_df = result.get(in_field)
                if isinstance(field_df, pd.DataFrame) and stock_code in field_df.columns:
                    df[out_col] = field_df[stock_code]

            if df.empty:
                return

            df = df.dropna(how='all')
            if df.empty:
                return

            with self._lock:
                if stock_code not in self._minute_cache:
                    self._minute_cache[stock_code] = {}
                if std_period not in self._minute_cache[stock_code]:
                    self._minute_cache[stock_code][std_period] = []

                existing_dates = {r['date'] for r in self._minute_cache[stock_code][std_period]}

                for ts, row in df.iterrows():
                    # 标准周期分钟对齐
                    dt_aligned = self._align_to_period(ts.to_pydatetime(), std_period)
                    date_str = dt_aligned.strftime('%Y-%m-%d %H:%M:%S')
                    if date_str in existing_dates:
                        continue

                    self._minute_cache[stock_code][std_period].append({
                        'date': date_str,
                        'open': float(row.get('open', 0)) if not pd.isna(row.get('open')) else 0,
                        'high': float(row.get('high', 0)) if not pd.isna(row.get('high')) else 0,
                        'low': float(row.get('low', 0)) if not pd.isna(row.get('low')) else 0,
                        'close': float(row.get('close', 0)) if not pd.isna(row.get('close')) else 0,
                        'volume': float(row.get('volume', 0)) if not pd.isna(row.get('volume')) else 0,
                        'amount': float(row.get('amount', 0)) if not pd.isna(row.get('amount')) else 0,
                    })
                    existing_dates.add(date_str)

                # 限制缓存大小
                cache = self._minute_cache[stock_code][std_period]
                if len(cache) > self._max_cache_size:
                    self._minute_cache[stock_code][std_period] = cache[-self._max_cache_size:]

                # 记录最后拉取时间
                if stock_code not in self._last_fetch:
                    self._last_fetch[stock_code] = {}
                self._last_fetch[stock_code][tq_period] = datetime.now()

        except Exception as e:
            print(f"[RealtimeSub] 拉取K线异常 {stock_code}: {e}")

    def _align_to_period(self, dt: datetime, std_period: str) -> datetime:
        """将datetime对齐到标准分钟周期"""
        p = int(std_period) if std_period.isdigit() else 1
        minute = (dt.minute // p) * p
        return dt.replace(second=0, microsecond=0).replace(minute=minute)

    def unsubscribe(self, stock_list: List[str]):
        """取消订阅"""
        try:
            self.tq.unsubscribe_hq(stock_list)
        except Exception as e:
            print(f"[RealtimeSub] 取消订阅异常: {e}")

        with self._lock:
            for code in stock_list:
                self._subscribed.discard(code)
                self._callbacks.pop(code, None)

    def add_cache_row(self, stock_code: str, period: str, row: dict):
        """手动添加一行到缓存（用于外部数据注入）"""
        with self._lock:
            if stock_code not in self._minute_cache:
                self._minute_cache[stock_code] = {}
            if period not in self._minute_cache[stock_code]:
                self._minute_cache[stock_code][period] = []

            cache = self._minute_cache[stock_code][period]
            cache.append(row)

            if len(cache) > self._max_cache_size:
                self._minute_cache[stock_code][period] = cache[-self._max_cache_size:]

    def get_cached_minute_data(self, stock_code: str, period: str = '1') -> List[dict]:
        """获取缓存的分钟级数据"""
        with self._lock:
            return list(self._minute_cache.get(stock_code, {}).get(period, []))

    def get_cached_minute_df(self, stock_code: str, period: str = '1') -> pd.DataFrame:
        """获取缓存的分钟级数据（DataFrame格式）"""
        rows = self.get_cached_minute_data(stock_code, period)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        return df

    def flush_cache(self, stock_code: str = None):
        """刷新缓存（当前实现已实时，无需额外固化）"""
        pass


# ==================== 导入TQ接口 ====================


class TdxOnlineProvider(BaseProvider, StandardAPIAdapter):
    """
    TdxOnline数据源Provider
    基于通达信Quant接口(TQ)实现11个标准API
    
    特点：
    - 需要通达信客户端运行并登录
    - 通过TPythClient.dll与客户端通信
    - 支持实时行情和历史数据
    - 股票代码格式：6位数.市场后缀(如000001.SZ, 600519.SH)
    """
    
    # 能力矩阵 - 覆盖BaseProvider的默认值
    CAPABILITIES = {
        'stock_realtime': True,      # 股票实时行情
        'stock_daily': True,         # 股票历史日线
        'stock_1min': True,          # 股票1分钟线
        'stock_5min': True,          # 股票5分钟线
        'stock_15min': True,         # 股票15分钟线
        'stock_30min': True,         # 股票30分钟线
        'stock_60min': True,         # 股票60分钟线
        'fund_realtime': True,       # 基金实时行情
        'fund_daily': True,          # 基金历史日线
        'fund_1min': True,           # 基金1分钟线
        'fund_5min': True,           # 基金5分钟线
        'fund_15min': True,          # 基金15分钟线
        'fund_30min': True,          # 基金30分钟线
        'fund_60min': True,          # 基金60分钟线
        'subscription_realtime': True,  # 订阅模式实时数据
    }
    
    def __init__(self,
                 tdx_path: Optional[str] = None,
                 connection_path: Optional[str] = None,
                 dll_path: Optional[str] = None):
        """初始化TQ连接"""
        super().__init__()
        self.source_name = "TdxOnline"
        self._initialized = False
        self.tdx_path = self._resolve_tdx_path(tdx_path)
        self.connection_path = self._resolve_connection_path(connection_path)
        self.dll_path = self._resolve_dll_path(dll_path)
        self._sub_manager = None  # RealtimeSubscriptionManager，惰性初始化
        self._initialize_tq()

    def _resolve_tdx_path(self, tdx_path: Optional[str]) -> str:
        """解析通达信根目录，优先级：入参 > 环境变量TDX_PATH"""
        candidates = [tdx_path, os.environ.get('TDX_PATH')]
        for path in candidates:
            if path and os.path.exists(path):
                return str(Path(path).resolve())
        return ""

    def _resolve_connection_path(self, connection_path: Optional[str]) -> str:
        """解析TQ初始化连接路径，使用PYPlugins/user目录"""
        if connection_path:
            return str(Path(connection_path).resolve())

        if self.tdx_path:
            # TQ初始化需要连接路径，使用目录路径（与test_market_data.py行为一致）
            # 当脚本在PYPlugins/user目录运行时，__file__就是该目录下的某个脚本
            plugin_user_dir = Path(self.tdx_path) / 'PYPlugins' / 'user'
            return str(plugin_user_dir)

        return ""

    def _resolve_dll_path(self, dll_path: Optional[str]) -> str:
        """解析TPythClient.dll路径，优先级：入参 > TDX_PATH目录 > 默认空(交给tqcenter默认)"""
        if dll_path and os.path.exists(dll_path):
            return str(Path(dll_path).resolve())

        if self.tdx_path:
            for candidate in (
                Path(self.tdx_path) / 'PYPlugins' / 'TPythClient.dll',
                Path(self.tdx_path) / 'TPythClient.dll',
            ):
                if candidate.exists():
                    return str(candidate.resolve())

        return ""
    
    def _initialize_tq(self):
        """初始化TQ连接"""
        # 检查tq模块是否成功加载
        if tq is None:
            if not hasattr(self, '_tq_dll_error_printed'):
                print(f"[{self.source_name}] [ERROR] TPythClient.dll文件缺失")
                if _dll_error:
                    print(f"[{self.source_name}] DLL加载错误: {_dll_error}")
                print("\n【解决方案】")
                print("方案1（推荐）：使用其他数据源")
                print("  - akshare: 免费，无需配置")
                print("  - baostock: 免费，仅需登录")
                print("  - byapi: 商业API，稳定可靠")
                print("\n方案2：获取TPythClient.dll")
                print("  1. 从通达信官方获取TQCenter开发包")
                print("  2. 将TPythClient.dll复制到项目目录: services/")
                print("     完整路径: E:\\Pydata\\stock\\services\\TPythClient.dll")
                print("  3. 确保通达信客户端已启动并登录")
                self._tq_dll_error_printed = True
            self._initialized = False
            return
        
        try:
            if self.tdx_path:
                setattr(tq, 'tdx_path', self.tdx_path)

            # 设置run_mode=0（客户端模式），避免使用默认的-1导致连接失败
            tq.run_mode = 0

            # 调用TQ初始化（优先显式传入dll_path，避免隐式硬编码路径）
            if self.dll_path:
                tq.initialize(self.connection_path, self.dll_path)
            else:
                tq.initialize(self.connection_path)

            self._initialized = True
            print(f"[{self.source_name}] TQ接口初始化成功")
            print(f"[{self.source_name}] 连接路径: {self.connection_path}")
            if self.tdx_path:
                print(f"[{self.source_name}] 通达信目录: {self.tdx_path}")
        except Exception as e:
            self._initialized = False
            # 只在首次初始化失败时打印警告，重试时不重复打印
            if not hasattr(self, '_tq_init_failed_printed'):
                print(f"[{self.source_name}] TQ接口初始化失败: {e}")
                print("\n提示：请确保通达信客户端已启动并登录")
                self._tq_init_failed_printed = True
    
    def test_connection(self) -> bool:
        """
        测试连接是否可用
        通过获取股票列表来验证
        """
        try:
            if not self._initialized:
                self._initialize_tq()
            
            # 尝试获取少量股票列表
            result = tq.get_stock_list('5')  # 获取所有A股
            
            if result and len(result) > 0:
                print(f"[{self.source_name}] 连接测试成功，获取到 {len(result)} 只股票")
                return True
            else:
                print(f"[{self.source_name}] 连接测试失败，未获取到数据")
                return False
        except Exception as e:
            print(f"[{self.source_name}] 连接测试异常: {e}")
            return False

    # ==================== 订阅模式实时分钟数据 ====================

    def _ensure_sub_manager(self):
        """惰性初始化订阅管理器"""
        if self._sub_manager is None:
            self._check_initialized()
            self._sub_manager = RealtimeSubscriptionManager(tq)
        return self._sub_manager

    def subscribe_realtime_minute(self,
                                  codes: List[str],
                                  period: str = '1',
                                  callback: Callable = None) -> bool:
        """
        订阅股票/基金实时行情，按分钟周期缓存K线数据

        通过TQ的 subscribe_hq 订阅实时行情更新，每次回调时获取快照数据，
        将快照数据按分钟对齐，构建K线行并缓存。

        :param codes: 6位股票代码列表，如 ['000001', '600519']
        :param period: 分钟周期 '1'/'5'/'15'/'30'/'60'
        :param callback: 可选回调函数，接收快照JSON数据
        :return: 是否订阅成功
        """
        self._check_initialized()
        manager = self._ensure_sub_manager()

        # 转换为带后缀格式
        stock_list = [self._add_market_suffix(c) for c in codes]

        # 注入回调
        if callback:
            for code in stock_list:
                manager._callbacks[code] = callback

        ok = manager.subscribe(stock_list, period)
        if ok:
            print(f"[{self.source_name}] 订阅实时分钟数据成功: {codes}, 周期={period}分钟")

            # 触发TQ刷新缓存以加速首次数据获取
            try:
                tq_period_map = {'1': '1m', '5': '5m', '15': '1m', '30': '5m', '60': '1h'}
                effective_period = tq_period_map.get(period, '1m')
                if effective_period in ('1m', '5m'):
                    tq.refresh_kline(stock_list, effective_period)
            except Exception as e:
                print(f"[{self.source_name}] 刷新K线缓存提示: {e}")

        return ok

    def unsubscribe_realtime_minute(self, codes: List[str]):
        """
        取消订阅实时行情

        :param codes: 6位股票代码列表
        """
        if self._sub_manager is None:
            return
        stock_list = [self._add_market_suffix(c) for c in codes]
        self._sub_manager.unsubscribe(stock_list)
        print(f"[{self.source_name}] 取消订阅: {codes}")

    def get_subscribed_minute_data(self,
                                   code: str,
                                   period: str = '1') -> pd.DataFrame:
        """
        获取订阅缓存的分钟级数据

        :param code: 6位股票代码
        :param period: 分钟周期 '1'/'5'/'15'/'30'/'60'
        :return: DataFrame，列[date, open, high, low, close, volume, amount]
        """
        if self._sub_manager is None:
            return pd.DataFrame()

        stock_code = self._add_market_suffix(code)
        df = self._sub_manager.get_cached_minute_df(stock_code, period)

        if not df.empty:
            # 清理内部字段
            for col in ('_minute',):
                if col in df.columns:
                    df = df.drop(columns=[col])
        return df

    def flush_minute_cache(self, code: str = None):
        """
        刷新分钟缓存 - 将当前正在构建的K线固化

        :param code: 6位股票代码，None则刷新所有
        """
        if self._sub_manager is None:
            return
        if code:
            stock_code = self._add_market_suffix(code)
            self._sub_manager.flush_cache(stock_code)
        else:
            self._sub_manager.flush_cache()

    def refresh_kline_cache(self, codes: List[str], period: str = '1m'):
        """
        主动刷新TQ的K线缓存

        注意：refresh_kline仅支持'1m', '5m', '1d'三种周期

        :param codes: 6位股票代码列表
        :param period: TQ周期，'1m'/'5m'/'1d'
        """
        self._check_initialized()
        stock_list = [self._add_market_suffix(c) for c in codes]
        try:
            tq.refresh_kline(stock_list, period)
            print(f"[{self.source_name}] 刷新K线缓存: {stock_list}, 周期={period}")
        except Exception as e:
            print(f"[{self.source_name}] 刷新K线缓存失败: {e}")

    def get_subscription_status(self) -> dict:
        """
        获取当前订阅状态

        :return: {'subscribed': [...], 'cache_sizes': {...}}
        """
        if self._sub_manager is None:
            return {'subscribed': [], 'cache_sizes': {}}
        with self._sub_manager._lock:
            return {
                'subscribed': list(self._sub_manager._subscribed),
                'cache_sizes': {
                    code: {p: len(rows) for p, rows in cache.items()}
                    for code, cache in self._sub_manager._minute_cache.items()
                },
            }

    # ==================== 辅助方法 ====================
    
    def _add_market_suffix(self, code: str) -> str:
        """
        为股票/基金代码添加市场后缀
        :param code: 6位代码，如'000001'(股票) 或 '588200'(基金)
        :return: 带后缀的代码，如'000001.SZ' 或 '588200.SH'
        """
        if '.' in code:
            # 已经有后缀，直接返回
            return code
        
        # 根据代码首位判断市场
        if code.startswith('6'):
            # 沪市主板（股票）或沪市基金
            return f"{code}.SH"
        elif code.startswith('5'):
            # 上海基金代码（580000-589999）
            return f"{code}.SH"
        elif code.startswith('688'):
            # 科创板
            return f"{code}.SH"
        elif code.startswith('000') or code.startswith('001'):
            # 深市主板
            return f"{code}.SZ"
        elif code.startswith('2'):
            # 深市基金代码（200000-299999）
            return f"{code}.SZ"
        elif code.startswith('002'):
            # 中小板（已合并到主板）
            return f"{code}.SZ"
        elif code.startswith('300'):
            # 创业板
            return f"{code}.SZ"
        elif code.startswith('8') or code.startswith('4'):
            # 北交所
            return f"{code}.BJ"
        else:
            # 默认深市
            return f"{code}.SZ"
    
    def _remove_market_suffix(self, code: str) -> str:
        """
        移除市场后缀，返回6位代码
        :param code: 带后缀的代码，如'000001.SZ'
        :return: 6位代码，如'000001'
        """
        if '.' in code:
            return code.split('.')[0]
        return code
    
    def _convert_period_to_tq(self, period: str, freq: str) -> str:
        """
        将标准周期转换为TQ周期格式
        :param period: 标准周期，如'1min', '5min', 'day'
        :param freq: 频率类型，'minute'或'daily'
        :return: TQ周期，如'1m', '5m', '1d'
        """
        if freq == 'daily':
            return '1d'
        elif freq == 'minute':
            # 分钟周期映射
            period_map = {
                '1': '1m',
                '5': '5m',
                '15': '15m',
                '30': '30m',
                '60': '1h',
            }
            # 提取数字
            num = ''.join(filter(str.isdigit, period))
            return period_map.get(num, '1m')
        else:
            return '1d'

    def _normalize_tq_datetime(self, dt_text: str) -> str:
        """将时间字符串规范化为TQ可接受格式（YYYYMMDD 或 YYYYMMDDHHMMSS）"""
        if not dt_text:
            return ''

        text = str(dt_text).strip()
        if text.isdigit() and len(text) in (8, 14):
            return text

        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.strftime('%Y%m%d%H%M%S' if fmt == '%Y-%m-%d %H:%M:%S' else '%Y%m%d')
            except ValueError:
                continue

        # 兜底：移除非数字字符后尝试
        digits = ''.join(ch for ch in text if ch.isdigit())
        if len(digits) in (8, 14):
            return digits

        raise ValueError("时间格式不正确，应为 YYYYMMDD、YYYYMMDDHHMMSS、YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS")

    def _parse_tq_datetime(self, dt_text: str, is_end: bool = False) -> datetime:
        """将 TQ 时间字符串解析为 datetime；8 位日期会补齐到日初/日末。"""
        text = self._normalize_tq_datetime(dt_text)
        if len(text) == 14:
            return datetime.strptime(text, '%Y%m%d%H%M%S')
        if len(text) == 8:
            base = datetime.strptime(text, '%Y%m%d')
            if is_end:
                return base.replace(hour=23, minute=59, second=59)
            return base
        raise ValueError(f"不支持的时间格式: {dt_text}")

    def _fetch_hist_minute_paged(self,
                                 code_with_suffix: str,
                                 start_datetime: str,
                                 end_datetime: str,
                                 tq_period: str,
                                 dividend_type: str,
                                 api_name: str) -> pd.DataFrame:
        """按天切片拉取分钟线并聚合，避免单次查询被 300 条上限截断。"""
        start_dt = self._parse_tq_datetime(start_datetime, is_end=False)
        end_dt = self._parse_tq_datetime(end_datetime, is_end=True)

        if end_dt < start_dt:
            return pd.DataFrame()

        pages: List[pd.DataFrame] = []

        current_day = start_dt.date()
        end_day = end_dt.date()
        while current_day <= end_day:
            day_start = datetime.combine(current_day, datetime.min.time())
            day_end = datetime.combine(current_day, datetime.max.time()).replace(microsecond=0)

            if day_start < start_dt:
                day_start = start_dt
            if day_end > end_dt:
                day_end = end_dt

            result = tq.get_market_data(
                stock_list=[code_with_suffix],
                period=tq_period,
                start_time=day_start.strftime('%Y%m%d%H%M%S'),
                end_time=day_end.strftime('%Y%m%d%H%M%S'),
                count=300,
                dividend_type=dividend_type,
                fill_data=False
            )

            df = self._convert_tq_data_to_dataframe(result, code_with_suffix)
            if not df.empty:
                df = df.sort_values('date')
                df = df[(df['date'] >= day_start) & (df['date'] <= day_end)]
                if not df.empty:
                    pages.append(df)

            current_day += timedelta(days=1)

        if not pages:
            print(f"[{self.source_name}] {api_name} 未获取到数据")
            return pd.DataFrame()

        merged = pd.concat(pages, ignore_index=True)
        merged = merged.drop_duplicates(subset=['date'], keep='first')
        merged = merged.sort_values('date').reset_index(drop=True)
        return merged
    
    def _convert_tq_data_to_dataframe(self, tq_data: Dict, stock_code: str) -> pd.DataFrame:
        """
        将TQ返回的K线数据转换为标准DataFrame
        :param tq_data: TQ的get_market_data返回的Dict
        :param stock_code: 股票代码
        :return: 标准DataFrame格式
        """
        if not tq_data or not isinstance(tq_data, dict):
            return pd.DataFrame()

        # 结构1：按股票分组（兼容旧版）
        if stock_code in tq_data and isinstance(tq_data.get(stock_code), dict):
            data = tq_data[stock_code]
            df = pd.DataFrame({
                'date': data.get('Date', []),
                'open': data.get('Open', []),
                'high': data.get('High', []),
                'low': data.get('Low', []),
                'close': data.get('Close', []),
                'volume': data.get('Volume', []),
                'amount': data.get('Amount', []),
            })
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
            return df

        # 结构2：按字段分组（当前TQ常见结构）
        # tq_data = {'Open': DataFrame(index=date, columns=[code]), ...}
        field_map = {
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume',
            'amount': 'Amount',
        }

        def _pick_series(field_name: str) -> Optional[pd.Series]:
            field_df = tq_data.get(field_name)
            if not isinstance(field_df, pd.DataFrame) or field_df.empty:
                return None

            if stock_code in field_df.columns:
                return field_df[stock_code]

            # 兜底：仅1列时取首列
            if len(field_df.columns) == 1:
                return field_df.iloc[:, 0]

            return None

        ref_series = _pick_series('Close')
        if ref_series is None:
            ref_series = _pick_series('Open')
        if ref_series is None:
            return pd.DataFrame()

        df = pd.DataFrame(index=ref_series.index)
        for out_col, in_field in field_map.items():
            series = _pick_series(in_field)
            if series is not None:
                df[out_col] = series

        if df.empty:
            return pd.DataFrame()

        df = df.reset_index().rename(columns={'index': 'date'})
        df['date'] = pd.to_datetime(df['date'])
        return df
    
    def _convert_snapshot_to_dataframe(self, snapshot: Dict) -> pd.DataFrame:
        """
        将TQ的实时快照数据转换为标准DataFrame
        :param snapshot: TQ的get_market_snapshot返回的Dict
        :return: 标准DataFrame格式（单行）
        """
        if not snapshot or snapshot.get('ErrorId') != '0':
            return pd.DataFrame()

        # 尝试从快照中解析时间，兼容多种字段名；若解析失败则使用当前时间
        time_candidates = ['Time', 'time', 'TimeStr', 'NowTime', 'Datetime', 'DateTime', 'Date', 'date']
        time_val = None
        for k in time_candidates:
            if k in snapshot and snapshot.get(k) is not None:
                time_val = snapshot.get(k)
                break

        source_time = None
        if time_val is None:
            source_time = datetime.now()
        else:
            try:
                if isinstance(time_val, (int, float)):
                    # 识别为秒或毫秒时间戳
                    if time_val > 1e12:
                        # 毫秒
                        source_time = datetime.fromtimestamp(int(time_val) / 1000)
                    else:
                        source_time = datetime.fromtimestamp(int(time_val))
                else:
                    # 常见字符串格式
                    try:
                        source_time = datetime.strptime(str(time_val), '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        try:
                            source_time = datetime.strptime(str(time_val), '%Y-%m-%d')
                        except Exception:
                            # 兜底：不解析为datetime，保留原始字符串
                            source_time = str(time_val)
            except Exception:
                source_time = datetime.now()

        # 从快照中提取OHLCV数据
        # JSON字段: Open, Max, Min, Now, Volume, Amount
        row = {
            'date': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            'time': [source_time],
            'open': [snapshot.get('Open', 0)],
            'high': [snapshot.get('Max', 0)],  # 最高价是Max字段
            'low': [snapshot.get('Min', 0)],   # 最低价是Min字段
            'close': [snapshot.get('Now', 0)],  # 最新价是Now字段
            'volume': [snapshot.get('Volume', 0)],
            'amount': [snapshot.get('Amount', 0)],
        }

        return pd.DataFrame(row)
    
    # ==================== API 01-04: 股票数据接口 ====================
    
    def api01_stock_hist_daily(self, code: str, start_date: str, end_date: str, 
                                adjust: str = 'qfq') -> pd.DataFrame:
        """
        API01 - 获取股票历史日线数据
        
        :param code: 股票代码，6位数字，如'000001'
        :param start_date: 开始日期，格式'YYYYMMDD'
        :param end_date: 结束日期，格式'YYYYMMDD'
        :param adjust: 复权类型，'qfq'-前复权, 'hfq'-后复权, 'none'-不复权
        :return: DataFrame，列[date, open, high, low, close, volume, amount]
        """
        try:
            # 添加市场后缀
            stock_code_with_suffix = self._add_market_suffix(code)
            
            # 调整类型映射
            dividend_type_map = {
                'qfq': 'front',
                'hfq': 'back',
                'none': 'none'
            }
            dividend_type = dividend_type_map.get(adjust, 'none')
            
            # 调用TQ接口获取K线数据
            result = tq.get_market_data(
                stock_list=[stock_code_with_suffix],
                period='1d',
                start_time=start_date,
                end_time=end_date,
                count=-1,
                dividend_type=dividend_type,
                fill_data=False
            )
            
            # 转换为DataFrame
            df = self._convert_tq_data_to_dataframe(result, stock_code_with_suffix)
            
            if df.empty:
                print(f"[{self.source_name}] API01 未获取到数据: {code}")
                return pd.DataFrame()
            
            return df
            
        except Exception as e:
            print(f"[{self.source_name}] API01 获取失败: {e}")
            return pd.DataFrame()
    
    def api02_stock_hist_minute(self, code: str, start_datetime: str, 
                                 end_datetime: str, period: str = '1',
                                 adjust: str = 'qfq') -> pd.DataFrame:
        """
        API02 - 获取股票历史分钟线数据
        
        :param code: 股票代码，6位数字
        :param start_datetime: 开始时间，格式'YYYYMMDD' 或 'YYYYMMDD HH:MM:SS'
        :param end_datetime: 结束时间，格式'YYYYMMDD' 或 'YYYYMMDD HH:MM:SS'
        :param period: 分钟周期，'1', '5', '15', '30', '60'
        :param adjust: 复权类型
        :return: DataFrame
        """
        try:
            # 添加市场后缀
            stock_code_with_suffix = self._add_market_suffix(code)

            # 规范化时间格式（兼容 YYYY-MM-DD HH:MM:SS / YYYY-MM-DD / YYYYMMDDHHMMSS / YYYYMMDD）
            start_datetime = self._normalize_tq_datetime(start_datetime)
            end_datetime = self._normalize_tq_datetime(end_datetime)
            
            # 转换周期格式
            tq_period = self._convert_period_to_tq(period, 'minute')
            
            # 复权类型映射
            dividend_type_map = {
                'qfq': 'front',
                'hfq': 'back',
                'none': 'none'
            }
            dividend_type = dividend_type_map.get(adjust, 'none')
            
            # 分页回溯拉取，避免单次 count=300 截断整月数据
            df = self._fetch_hist_minute_paged(
                code_with_suffix=stock_code_with_suffix,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                tq_period=tq_period,
                dividend_type=dividend_type,
                api_name='API02'
            )
            
            if df.empty:
                print(f"[{self.source_name}] API02 未获取到数据: {code}")
                return pd.DataFrame()
            
            return df
            
        except Exception as e:
            print(f"[{self.source_name}] API02 获取失败: {e}")
            return pd.DataFrame()
    
    def api03_stock_rt_daily(self, code: str) -> pd.DataFrame:
        """
        API03 - 获取股票实时日线数据
        
        通过实时快照数据构建当日OHLCV
        注意：TQ的实时快照可能不包含完整的OHLCV，这里做简化处理
        
        :param code: 股票代码，6位数字
        :return: DataFrame，单行数据
        """
        try:
            # 添加市场后缀
            stock_code_with_suffix = self._add_market_suffix(code)
            
            # 调用TQ接口获取实时快照
            snapshot = tq.get_market_snapshot(stock_code_with_suffix)
            
            # 转换为DataFrame
            df = self._convert_snapshot_to_dataframe(snapshot)
            
            if df.empty:
                print(f"[{self.source_name}] API03 未获取到数据: {code}")
                return pd.DataFrame()
            
            return df
            
        except Exception as e:
            print(f"[{self.source_name}] API03 获取失败: {e}")
            return pd.DataFrame()
    
    def api04_stock_rt_minute(self,
                              code: str,
                              period: str = '1',
                              start_datetime: Optional[str] = None,
                              end_datetime: Optional[str] = None,
                              adjust: str = 'qfq') -> pd.DataFrame:
        """
        API04 - 获取股票实时分钟线数据

        数据获取优先级：
        1. 订阅缓存（如果已订阅该股票的实时行情）
        2. get_market_data历史分钟线
        3. 实时快照兜底

        默认返回最近1小时分钟线；可通过period/start_datetime/end_datetime指定窗口

        :param code: 股票代码，6位数字
        :param period: 分钟周期，'1', '5', '15', '30', '60'
        :param start_datetime: 开始时间，支持YYYYMMDDHHMMSS / YYYY-MM-DD HH:MM:SS
        :param end_datetime: 结束时间，支持YYYYMMDDHHMMSS / YYYY-MM-DD HH:MM:SS
        :param adjust: 复权类型，'qfq'/'hfq'/'none'
        :return: DataFrame
        """
        try:
            # 优先检查订阅缓存
            if self._sub_manager is not None:
                sub_df = self.get_subscribed_minute_data(code, period)
                if not sub_df.empty:
                    return sub_df

            if end_datetime is None:
                end_dt = datetime.now()
                end_datetime = end_dt.strftime('%Y%m%d%H%M%S')
            else:
                end_datetime = self._normalize_tq_datetime(end_datetime)

            if start_datetime is None:
                start_dt = datetime.strptime(end_datetime, '%Y%m%d%H%M%S') - timedelta(hours=1)
                start_datetime = start_dt.strftime('%Y%m%d%H%M%S')
            else:
                start_datetime = self._normalize_tq_datetime(start_datetime)

            df = self.api02_stock_hist_minute(
                code=code,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                period=period,
                adjust=adjust
            )

            # 兜底：若分钟线为空，尝试实时快照并使用通用生成器生成1分钟K线
            if df.empty:
                stock_code_with_suffix = self._add_market_suffix(code)
                snapshot = tq.get_market_snapshot(stock_code_with_suffix)
                # 将快照转换为DataFrame（包含time字段）
                snap_df = self._convert_snapshot_to_dataframe(snapshot)
                if not snap_df.empty:
                    # 转换为records并选择第一条快照
                    record = snap_df.to_dict('records')[0]
                    # 构造通用snapshot字典，field名与build_realtime_kline_row期望的映射一致
                    std_snapshot = {
                        'time': record.get('time', record.get('date')),
                        'open': record.get('open'),
                        'high': record.get('high'),
                        'low': record.get('low'),
                        'close': record.get('close'),
                        'volume': record.get('volume'),
                        'amount': record.get('amount'),
                    }
                    # 获取上一分钟行数据
                    from stockpush.rt_test.rt_test import build_realtime_kline_row
                    prev = None
                    try:
                        prev = self._get_prev_row('tdxonline', 'stock', code, floor_to_minute(datetime.now()))
                    except Exception:
                        prev = None
                    try:
                        row = build_realtime_kline_row(symbol=code, asset_type='stock', snapshot=std_snapshot, prev_row=prev, provider_name='tdxonline')
                        if row is None:
                            print(f"[{self.source_name}] API04 快照无变化，未生成新的K线: {code}")
                            return pd.DataFrame()
                        # 将row转换为DataFrame单行返回，列名与API一致
                        df = pd.DataFrame([{
                            'date': row['ts'],
                            'open': row['open'],
                            'high': row['high'],
                            'low': row['low'],
                            'close': row['close'],
                            'volume': row['vol'] if row['vol'] is not None else None,
                            'amount': row['amount'] if row['amount'] is not None else None,
                        }])
                    except Exception as e:
                        print(f"[{self.source_name}] 使用快照生成1分钟K线失败: {e}")
                        return pd.DataFrame()
            
            if df.empty:
                print(f"[{self.source_name}] API04 未获取到数据: {code}")
                return pd.DataFrame()
            
            return df
            
        except Exception as e:
            print(f"[{self.source_name}] API04 获取失败: {e}")
            return pd.DataFrame()
    
    # ==================== API 05-08: 基金数据接口 ====================
    
    def api05_fund_hist_daily(self, code: str, start_date: str,
                              end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        """
        API05 - 获取基金历史日线数据
        
        TQ接口中基金和股票使用相同的获取方法，只是代码不同
        基金代码通常以 '5' 或 '16' 开头
        
        :param code: 基金代码，6位数字
        :param start_date: 开始日期
        :param end_date: 结束日期
        :param adjust: 复权类型，'qfq'-前复权, 'hfq'-后复权, 'none'-不复权
        :return: DataFrame
        """
        try:
            # 添加市场后缀
            fund_code_with_suffix = self._add_market_suffix(code)

            # 复权类型映射
            dividend_type_map = {
                'qfq': 'front',
                'hfq': 'back',
                'none': 'none'
            }
            dividend_type = dividend_type_map.get(adjust, 'front')
            
            # 调用TQ接口
            result = tq.get_market_data(
                stock_list=[fund_code_with_suffix],
                period='1d',
                start_time=start_date,
                end_time=end_date,
                count=-1,
                dividend_type=dividend_type,
                fill_data=False
            )
            
            # 转换为DataFrame
            df = self._convert_tq_data_to_dataframe(result, fund_code_with_suffix)
            
            if df.empty:
                print(f"[{self.source_name}] API05 未获取到数据: {code}")
                return pd.DataFrame()
            
            return df
            
        except Exception as e:
            print(f"[{self.source_name}] API05 获取失败: {e}")
            return pd.DataFrame()
    
    def api06_fund_hist_minute(self, code: str, start_datetime: str,
                               end_datetime: str, period: str = '1',
                               adjust: str = 'qfq') -> pd.DataFrame:
        """
        API06 - 获取基金历史分钟线数据
        
        :param code: 基金代码
        :param start_datetime: 开始时间
        :param end_datetime: 结束时间
        :param period: 分钟周期
        :param adjust: 复权类型，'qfq'-前复权, 'hfq'-后复权, 'none'-不复权
        :return: DataFrame
        """
        try:
            # 添加市场后缀
            fund_code_with_suffix = self._add_market_suffix(code)

            # 规范化时间格式（兼容 YYYY-MM-DD HH:MM:SS / YYYY-MM-DD / YYYYMMDDHHMMSS / YYYYMMDD）
            start_datetime = self._normalize_tq_datetime(start_datetime)
            end_datetime = self._normalize_tq_datetime(end_datetime)
            
            # 转换周期格式
            tq_period = self._convert_period_to_tq(period, 'minute')

            # 复权类型映射
            dividend_type_map = {
                'qfq': 'front',
                'hfq': 'back',
                'none': 'none'
            }
            dividend_type = dividend_type_map.get(adjust, 'front')
            
            # 分页回溯拉取，避免单次 count=300 截断整月数据
            df = self._fetch_hist_minute_paged(
                code_with_suffix=fund_code_with_suffix,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                tq_period=tq_period,
                dividend_type=dividend_type,
                api_name='API06'
            )
            
            if df.empty:
                print(f"[{self.source_name}] API06 未获取到数据: {code}")
                return pd.DataFrame()
            
            return df
            
        except Exception as e:
            print(f"[{self.source_name}] API06 获取失败: {e}")
            return pd.DataFrame()
    
    def api07_fund_rt_daily(self, code: str) -> pd.DataFrame:
        """
        API07 - 获取基金实时日线数据
        
        :param code: 基金代码
        :return: DataFrame
        """
        try:
            # 添加市场后缀
            fund_code_with_suffix = self._add_market_suffix(code)
            
            # 调用TQ接口获取实时快照
            snapshot = tq.get_market_snapshot(fund_code_with_suffix)
            
            # 转换为DataFrame
            df = self._convert_snapshot_to_dataframe(snapshot)
            
            if df.empty:
                print(f"[{self.source_name}] API07 未获取到数据: {code}")
                return pd.DataFrame()
            
            return df
            
        except Exception as e:
            print(f"[{self.source_name}] API07 获取失败: {e}")
            return pd.DataFrame()
    
    def api08_fund_rt_minute(self,
                             code: str,
                             period: str = '1',
                             start_datetime: Optional[str] = None,
                             end_datetime: Optional[str] = None,
                             adjust: str = 'qfq') -> pd.DataFrame:
        """
        API08 - 获取基金实时分钟线数据

        数据获取优先级：
        1. 订阅缓存（如果已订阅该基金的实时行情）
        2. get_market_data历史分钟线
        3. 实时快照兜底

        :param code: 基金代码
        :param period: 分钟周期，'1', '5', '15', '30', '60'
        :param start_datetime: 开始时间，支持YYYYMMDDHHMMSS / YYYY-MM-DD HH:MM:SS
        :param end_datetime: 结束时间，支持YYYYMMDDHHMMSS / YYYY-MM-DD HH:MM:SS
        :param adjust: 复权类型，'qfq'/'hfq'/'none'
        :return: DataFrame
        """
        try:
            # 优先检查订阅缓存
            if self._sub_manager is not None:
                sub_df = self.get_subscribed_minute_data(code, period)
                if not sub_df.empty:
                    return sub_df

            if end_datetime is None:
                end_dt = datetime.now()
                end_datetime = end_dt.strftime('%Y%m%d%H%M%S')
            else:
                end_datetime = self._normalize_tq_datetime(end_datetime)

            if start_datetime is None:
                start_dt = datetime.strptime(end_datetime, '%Y%m%d%H%M%S') - timedelta(hours=1)
                start_datetime = start_dt.strftime('%Y%m%d%H%M%S')
            else:
                start_datetime = self._normalize_tq_datetime(start_datetime)

            df = self.api06_fund_hist_minute(
                code=code,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                period=period,
                adjust=adjust
            )

            # 兜底：若分钟线为空，尝试实时快照
            if df.empty:
                fund_code_with_suffix = self._add_market_suffix(code)
                snapshot = tq.get_market_snapshot(fund_code_with_suffix)
                df = self._convert_snapshot_to_dataframe(snapshot)
            
            if df.empty:
                print(f"[{self.source_name}] API08 未获取到数据: {code}")
                return pd.DataFrame()
            
            return df
            
        except Exception as e:
            print(f"[{self.source_name}] API08 获取失败: {e}")
            return pd.DataFrame()
    
    # ==================== API 09-10: 代码列表接口 ====================
    
    def api09_code_list_stock(self) -> List[str]:
        """
        API09 - 获取股票代码列表
        
        :return: 股票代码列表，不含市场后缀，如['000001', '600519', ...]
        """
        try:
            # market='5' 表示所有A股
            result = tq.get_stock_list('5')
            
            if not result:
                print(f"[{self.source_name}] API09 未获取到股票列表")
                return []
            
            # 移除市场后缀，只返回6位代码
            code_list = [self._remove_market_suffix(code) for code in result]
            
            return code_list
            
        except Exception as e:
            print(f"[{self.source_name}] API09 获取失败: {e}")
            return []
    
    def api10_code_list_fund(self) -> List[str]:
        """
        API10 - 获取基金代码列表
        
        从TQ的股票列表中筛选基金
        market参数:
        - '31': ETF基金
        - '34': 所有可交易基金
        
        :return: 基金代码列表
        """
        try:
            # market='34' 表示所有可交易基金
            result = tq.get_stock_list('34')
            
            if not result:
                print(f"[{self.source_name}] API10 未获取到基金列表")
                return []
            
            # 移除市场后缀
            code_list = [self._remove_market_suffix(code) for code in result]
            
            return code_list
            
        except Exception as e:
            print(f"[{self.source_name}] API10 获取失败: {e}")
            return []
    
    # ==================== API 11: 交易日历接口 ====================
    
    def api11_trade_calendar(self, start_date: str, end_date: str) -> List[str]:
        """
        API11 - 获取交易日历
        
        :param start_date: 开始日期，格式'YYYYMMDD'
        :param end_date: 结束日期，格式'YYYYMMDD'
        :return: 交易日列表，格式['YYYY-MM-DD', ...]
        """
        try:
            # market='SH' 表示上海市场
            # TQ要求在客户端下载上证指数(999999)的盘后数据
            result = tq.get_trading_dates(
                market='SH',
                start_time=start_date,
                end_time=end_date,
                count=-1
            )
            
            if not result:
                print(f"[{self.source_name}] API11 未获取到交易日历")
                return []
            
            # TQ返回的日期格式可能是 'YYYY-MM-DD' 或 'YYYYMMDD'
            # 统一转换为 'YYYY-MM-DD'
            formatted_dates = []
            for date_str in result:
                if '-' in date_str:
                    formatted_dates.append(date_str)
                else:
                    # YYYYMMDD -> YYYY-MM-DD
                    formatted_dates.append(f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}")
            
            return formatted_dates
            
        except Exception as e:
            print(f"[{self.source_name}] API11 获取失败: {e}")
            return []
    
    # ==================== 辅助方法 ====================
    
    def get_capabilities(self) -> Dict[str, bool]:
        """
        获取数据源能力清单
        
        :return: 能力字典
        """
        return {
            'api01_stock_hist_daily': True,
            'api02_stock_hist_minute': True,
            'api03_stock_rt_daily': True,
            'api04_stock_rt_minute': True,
            'api05_fund_hist_daily': True,
            'api06_fund_hist_minute': True,
            'api07_fund_rt_daily': True,
            'api08_fund_rt_minute': True,
            'api09_code_list_stock': True,
            'api10_code_list_fund': True,
            'api11_trade_calendar': True,
            'subscription_realtime': True,
            'stock_15min': True,
            'stock_30min': True,
            'stock_60min': True,
            'fund_15min': True,
            'fund_30min': True,
            'fund_60min': True,
        }
    
    # ==================== 简化调用方法（兼容SourceComparatorService） ====================
    
    def _check_initialized(self):
        """
        检查TQ是否已初始化，未初始化则尝试重新初始化一次
        
        支持场景：
        - 如果首次初始化时通达信客户端未启动，后续可以在客户端启动后重试
        - 支持热重启通达信客户端后的自动重连
        """
        if not self._initialized:
            # 尝试重新初始化一次（可能通达信客户端现在已启动）
            self._initialize_tq()
            
            # 如果重新初始化仍然失败，才抛出异常
            if not self._initialized:
                raise RuntimeError(
                    "TdxOnline数据源不可用: TQ接口未初始化。"
                    "请确保通达信客户端已启动并登录，或使用其他数据源(akshare/baostock/byapi)"
                )

    def release_connection(self):
        """显式释放 TQ 连接，避免进程残留占用。"""
        try:
            if tq is not None:
                tq.close()
        except Exception:
            pass
        finally:
            self._initialized = False
    
    def fetch_stock_5min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票5分钟线数据（简化调用）
        
        :param code: 股票代码，6位数字，如'000001'
        :param start_date: 开始时间，格式'YYYY-MM-DD'或'YYYY-MM-DD HH:MM:SS'
        :param end_date: 结束时间，格式'YYYY-MM-DD'或'YYYY-MM-DD HH:MM:SS'
        :return: DataFrame，列[date, open, high, low, close, volume, amount]
        """
        self._check_initialized()
        # 调用api02_stock_hist_minute，周期为5分钟，使用前复权
        return self.api02_stock_hist_minute(code, start_date, end_date, period='5', adjust='qfq')
    
    def fetch_stock_1min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票1分钟线数据"""
        self._check_initialized()
        return self.api02_stock_hist_minute(code, start_date, end_date, period='1', adjust='qfq')
    
    def fetch_stock_15min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票15分钟线数据"""
        self._check_initialized()
        return self.api02_stock_hist_minute(code, start_date, end_date, period='15', adjust='qfq')
    
    def fetch_stock_30min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票30分钟线数据"""
        self._check_initialized()
        return self.api02_stock_hist_minute(code, start_date, end_date, period='30', adjust='qfq')
    
    def fetch_stock_60min(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票60分钟线数据"""
        self._check_initialized()
        return self.api02_stock_hist_minute(code, start_date, end_date, period='60', adjust='qfq')
    
    def fetch_stock_daily(self, code: str, start_date: str, end_date: str, adjust: str = 'qfq') -> pd.DataFrame:
        """
        获取股票日线数据（简化调用）
        
        :param code: 股票代码
        :param start_date: 开始日期，格式'YYYY-MM-DD'或'YYYYMMDD'
        :param end_date: 结束日期
        :param adjust: 复权类型，'qfq'-前复权, 'hfq'-后复权, 'none'-不复权（默认前复权）
        :return: DataFrame
        """
        self._check_initialized()
        # 转换日期格式为YYYYMMDD
        start_date_fmt = start_date.replace('-', '').replace(' ', '').split()[0] if ' ' in start_date else start_date.replace('-', '')
        end_date_fmt = end_date.replace('-', '').replace(' ', '').split()[0] if ' ' in end_date else end_date.replace('-', '')
        # 调用api01
        return self.api01_stock_hist_daily(code, start_date_fmt, end_date_fmt, adjust=adjust)
    
    def fetch_fund_5min(self, code: str, start_date: str, end_date: str,
                        adjust: str = 'qfq') -> pd.DataFrame:
        """获取基金5分钟线数据"""
        self._check_initialized()
        return self.api06_fund_hist_minute(code, start_date, end_date, period='5', adjust=adjust)
    
    def fetch_fund_1min(self, code: str, start_date: str, end_date: str,
                        adjust: str = 'qfq') -> pd.DataFrame:
        """获取基金1分钟线数据"""
        self._check_initialized()
        return self.api06_fund_hist_minute(code, start_date, end_date, period='1', adjust=adjust)

    def fetch_fund_15min(self, code: str, start_date: str, end_date: str,
                         adjust: str = 'qfq') -> pd.DataFrame:
        """获取基金15分钟线数据"""
        self._check_initialized()
        return self.api06_fund_hist_minute(code, start_date, end_date, period='15', adjust=adjust)

    def fetch_fund_30min(self, code: str, start_date: str, end_date: str,
                         adjust: str = 'qfq') -> pd.DataFrame:
        """获取基金30分钟线数据"""
        self._check_initialized()
        return self.api06_fund_hist_minute(code, start_date, end_date, period='30', adjust=adjust)

    def fetch_fund_60min(self, code: str, start_date: str, end_date: str,
                         adjust: str = 'qfq') -> pd.DataFrame:
        """获取基金60分钟线数据"""
        self._check_initialized()
        return self.api06_fund_hist_minute(code, start_date, end_date, period='60', adjust=adjust)
    
    def fetch_fund_daily(self, code: str, start_date: str, end_date: str,
                         adjust: str = 'qfq') -> pd.DataFrame:
        """获取基金日线数据"""
        self._check_initialized()
        # 转换日期格式
        start_date_fmt = start_date.replace('-', '').replace(' ', '').split()[0] if ' ' in start_date else start_date.replace('-', '')
        end_date_fmt = end_date.replace('-', '').replace(' ', '').split()[0] if ' ' in end_date else end_date.replace('-', '')
        return self.api05_fund_hist_daily(code, start_date_fmt, end_date_fmt, adjust=adjust)
    
    def fetch_stock_list(self):
        """API09标准接口：股票代码列表"""
        try:
            self._check_initialized()
            stocks = self.api09_code_list_stock()
            return stocks if stocks else -1
        except Exception:
            return -1

    # ==================== F2.1 标准接口（DataSourceRegistry） ====================

    def fetch_stock_history_daily(self, code: str, start: str, end: str, adjust: str = 'qfq'):
        """API01标准接口：股票历史日线"""
        try:
            df = self.fetch_stock_daily(code, start, end, adjust=adjust)
            return df if not df.empty else -1
        except RuntimeError as e:
            # TQ 初始化失败，记录详细错误
            self.logger.error(f"API01 失败 (TQ 未初始化): {e}")
            return -1
        except Exception as e:
            # 其他错误
            self.logger.error(f"API01 失败: {e}")
            return -1

    def fetch_stock_history_minute(self, code: str, period: str, start: str, end: str, adjust: str = 'qfq'):
        """API02标准接口：股票历史分钟线"""
        try:
            period_map = {
                '1': self.fetch_stock_1min,
                '5': self.fetch_stock_5min,
                '15': self.fetch_stock_15min,
                '30': self.fetch_stock_30min,
                '60': self.fetch_stock_60min,
            }
            method = period_map.get(str(period))
            if method is None:
                return -1
            # 注意：分钟线数据不应用复权参数（adjust参数接收但不使用）
            df = method(code, start, end)
            return df if not df.empty else -1
        except RuntimeError as e:
            # TQ 初始化失败
            self.logger.error(f"API02 失败 (TQ 未初始化): {e}")
            return -1
        except Exception as e:
            # 其他错误
            self.logger.error(f"API02 失败: {e}")
            return -1

    def fetch_stock_realtime(self, code: str) -> pd.DataFrame:
        """获取股票实时行情 - BaseProvider要求的方法"""
        try:
            # 使用api03_stock_rt_daily获取实时日线数据
            df = self.api03_stock_rt_daily(code)
            if df.empty:
                return pd.DataFrame()
            return df
        except Exception as e:
            self.logger.error(f"获取股票实时行情失败: {code}, 错误: {e}")
            return pd.DataFrame()
    
    def fetch_stock_realtime_daily(self, code: str):
        """API03标准接口：股票实时行情（日线级）"""
        try:
            df = self.api03_stock_rt_daily(code)
            if df.empty:
                return -1
            return df.iloc[0].to_dict()
        except Exception:
            return -1

    def fetch_stock_realtime_minute(self,
                                    code: str,
                                    period: str = '1',
                                    start: Optional[str] = None,
                                    end: Optional[str] = None,
                                    adjust: str = 'qfq'):
        """API04标准接口：股票实时分钟线"""
        try:
            df = self.api04_stock_rt_minute(
                code=code,
                period=period,
                start_datetime=start,
                end_datetime=end,
                adjust=adjust
            )
            return df if not df.empty else -1
        except Exception:
            return -1

    def fetch_fund_history_daily(self, code: str, start: str, end: str, adjust: str = 'qfq'):
        """API05标准接口：基金历史日线"""
        try:
            df = self.fetch_fund_daily(code, start, end, adjust=adjust)
            return df if not df.empty else -1
        except RuntimeError as e:
            # TQ 初始化失败
            self.logger.error(f"API05 失败 (TQ 未初始化): {e}")
            return -1
        except Exception as e:
            # 其他错误
            self.logger.error(f"API05 失败: {e}")
            return -1

    def fetch_fund_history_minute(self, code: str, period: str, start: str, end: str, adjust: str = 'qfq'):
        """API06标准接口：基金历史分钟线"""
        try:
            period_map = {
                '1': self.fetch_fund_1min,
                '5': self.fetch_fund_5min,
                '15': self.fetch_fund_15min,
                '30': self.fetch_fund_30min,
                '60': self.fetch_fund_60min,
            }
            method = period_map.get(str(period))
            if method is None:
                return -1
            # 注意：分钟线数据不应用复权参数（adjust参数接收但不使用）
            df = method(code, start, end)
            return df if not df.empty else -1
        except RuntimeError as e:
            # TQ 初始化失败
            self.logger.error(f"API06 失败 (TQ 未初始化): {e}")
            return -1
        except Exception as e:
            # 其他错误
            self.logger.error(f"API06 失败: {e}")
            return -1

    def fetch_fund_realtime(self, code: str) -> pd.DataFrame:
        """获取基金实时行情 - BaseProvider要求的方法"""
        try:
            # 使用api07_fund_rt_daily获取实时日线数据
            df = self.api07_fund_rt_daily(code)
            if df.empty:
                return pd.DataFrame()
            return df
        except Exception as e:
            self.logger.error(f"获取基金实时行情失败: {code}, 错误: {e}")
            return pd.DataFrame()
    
    def fetch_fund_realtime_daily(self, code: str):
        """API07标准接口：基金实时行情（日线级）"""
        try:
            df = self.api07_fund_rt_daily(code)
            if df.empty:
                return -1
            return df.iloc[0].to_dict()
        except Exception:
            return -1

    def fetch_fund_realtime_minute(self,
                                   code: str,
                                   period: str = '1',
                                   start: Optional[str] = None,
                                   end: Optional[str] = None,
                                   adjust: str = 'qfq'):
        """API08标准接口：基金实时分钟线"""
        try:
            df = self.api08_fund_rt_minute(
                code=code,
                period=period,
                start_datetime=start,
                end_datetime=end,
                adjust=adjust
            )
            return df if not df.empty else -1
        except Exception:
            return -1

    def fetch_fund_list(self):
        """API10标准接口：基金代码列表"""
        try:
            self._check_initialized()
            funds = self.api10_code_list_fund()
            return funds if funds else -1
        except Exception:
            return -1

    def fetch_trade_calendar(self, start: str, end: str):
        """API11标准接口：交易日历"""
        try:
            self._check_initialized()

            start_norm = self._normalize_tq_datetime(start)
            end_norm = self._normalize_tq_datetime(end)
            start_date = start_norm[:8]
            end_date = end_norm[:8]

            dates = self.api11_trade_calendar(start_date, end_date)
            return dates if dates else -1
        except Exception:
            return -1
    
    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock') -> pd.DataFrame:
        _ADJUST_MAP = {'qfq': 'front', 'hfq': 'back', 'none': 'none'}
        dividend_type = _ADJUST_MAP.get(adjust, 'front')
        code_with_suffix = self._add_market_suffix(code)
        if period == '1d':
            start_fmt = self._normalize_tq_datetime(start)
            end_fmt = self._normalize_tq_datetime(end)
            if asset_type == 'fund':
                result = tq.get_market_data(
                    stock_list=[code_with_suffix], period='1d',
                    start_time=start_fmt[:8], end_time=end_fmt[:8],
                    count=-1, dividend_type=dividend_type, fill_data=False
                )
            else:
                result = tq.get_market_data(
                    stock_list=[code_with_suffix], period='1d',
                    start_time=start_fmt[:8], end_time=end_fmt[:8],
                    count=-1, dividend_type=dividend_type, fill_data=False
                )
            return self._convert_tq_data_to_dataframe(result, code_with_suffix)
        else:
            period_map = {'1m': '1', '5m': '5', '15m': '15', '30m': '30', '60m': '60'}
            p = period_map.get(period)
            if not p:
                raise ValueError(f"TdxOnline不支持周期: {period}")
            return self.api02_stock_hist_minute(
                code=code, start_datetime=start, end_datetime=end,
                period=p, adjust=adjust
            )

    def fetch_quote(self, code: str, asset_type: str = 'stock') -> pd.DataFrame:
        code_with_suffix = self._add_market_suffix(code)
        snapshot = tq.get_market_snapshot(code_with_suffix)
        return self._convert_snapshot_to_dataframe(snapshot)

    def __del__(self):
        """析构时关闭TQ连接"""
        try:
            self.release_connection()
        except Exception:
            pass


# ==================== 模块测试代码 ====================

def _test_provider():
    """测试TdxOnlineProvider的基本功能"""
    print("=" * 60)
    print("TdxOnlineProvider 测试")
    print("=" * 60)
    
    # 创建provider实例
    provider = TdxOnlineProvider()
    
    # 测试连接
    print("\n1. 测试连接...")
    if not provider.test_connection():
        print("警告：连接失败，请确保通达信客户端已启动并登录")
        return
    
    # 测试API01 - 股票历史日线
    print("\n2. 测试API01 - 股票历史日线（600519 茅台）...")
    df = provider.api01_stock_hist_daily('600519', '20240101', '20240110')
    print(f"获取数据行数: {len(df)}")
    if not df.empty:
        print(df.head())
    
    # 测试API09 - 股票代码列表
    print("\n3. 测试API09 - 股票代码列表...")
    stock_list = provider.api09_code_list_stock()
    print(f"股票总数: {len(stock_list)}")
    print(f"前10只股票: {stock_list[:10]}")
    
    # 测试API11 - 交易日历
    print("\n4. 测试API11 - 交易日历...")
    trade_dates = provider.api11_trade_calendar('20240101', '20240131')
    print(f"交易日数量: {len(trade_dates)}")
    print(f"交易日列表: {trade_dates}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == '__main__':
    _test_provider()
