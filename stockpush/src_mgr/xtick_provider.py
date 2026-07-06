"""
XTick 数据源 Provider

参考 docs/数据源管理/xtick/xtick_api.md
提供最小可用的历史/实时/逐笔/竞价 调用封装，返回标准化的 DataFrame
"""
import os
import time
import json
import threading
from pathlib import Path
from typing import Optional, List, Callable

import requests
import pandas as pd

from stockpush.log_manager import LogManager
from stockpush.config_manager import get_config_manager
from .src_provider import BaseProvider
from .standard_api_adapter import StandardAPIAdapter


class XTickProvider(BaseProvider, StandardAPIAdapter):
    NAME = 'xtick'

    _ADJUST_TO_FQ = {'qfq': 'front', 'hfq': 'back', 'none': 'none', '': 'none',
                      'front': 'front', 'back': 'back', 'front_ratio': 'front_ratio', 'back_ratio': 'back_ratio'}

    _PERIOD_MAP = {
        '1d': '1d', '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '60m': '1h',
    }
    _ASSET_TYPE_MAP = {'stock': 1, 'fund': 20}

    def _map_adjust(self, adjust: str) -> str:
        return self._ADJUST_TO_FQ.get(adjust, 'none')

    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock') -> pd.DataFrame:
        """统一K线接口"""
        period_val = self._PERIOD_MAP.get(period)
        if not period_val:
            raise ValueError(f"XTick不支持周期: {period}")
        type_val = self._ASSET_TYPE_MAP.get(asset_type, 1)
        fq_val = self._map_adjust(adjust)
        start_date = self._date_only(start) if period != '1d' else start
        end_date = self._date_only(end) if period != '1d' else end
        params = {
            'type': type_val, 'code': code, 'period': period_val,
            'fq': fq_val, 'startDate': start_date, 'endDate': end_date,
        }
        data = self._request('/doc/market', params=params)
        return self._to_df(data)

    def fetch_quote(self, code: str, asset_type: str = 'stock') -> pd.DataFrame:
        """统一实时行情接口"""
        type_val = self._ASSET_TYPE_MAP.get(asset_type, 1)
        params = {'type': type_val, 'code': code, 'period': 'tick'}
        data = self._request('/doc/tick/time', params=params)
        return self._to_df(data)

    CAPABILITIES = {
        'stock_realtime': True,
        'stock_daily': True,
        'stock_1min': True,
        'stock_5min': True,
        'stock_15min': True,
        'stock_30min': True,
        'stock_60min': True,
        'stock_weekly': True,
        'stock_monthly': True,
        'fund_realtime': True,
        'fund_daily': True,
        'fund_1min': True,
        'fund_5min': True,
        'fund_15min': True,
        'fund_30min': True,
        'fund_60min': True,
        'stock_list': True,
        'trade_calendar': True,
    }

    def __init__(self, config: Optional[dict] = None):
        super().__init__()
        self.logger = LogManager().get_logger(self.__class__.__name__)
        self.config = config or get_config_manager()

        self.base_url = self.config.get('XTICK_BASE_URL', 'http://api.xtick.top')
        # token 优先使用环境变量
        self.token = os.getenv('XTICK_TOKEN') or self.config.get('XTICK_TOKEN') or self._load_token_file()

        self.session = requests.Session()

        self.logger.info(f"XTickProvider 初始化，base_url={self.base_url}")

    def _load_token_file(self) -> Optional[str]:
        # 默认 token 文件位于项目 docs 目录
        try:
            project_root = Path(__file__).resolve().parents[2]
            default = project_root / 'docs' / '数据源管理' / 'xtick' / 'token.md'
            path = Path(self.config.get('XTICK_TOKEN_FILE', default))
            if path.exists():
                return path.read_text(encoding='utf-8').strip()
        except Exception:
            pass
        return None

    def _request(self, path: str, params: Optional[dict] = None, timeout: int = 15):
        url = self.base_url.rstrip('/') + path
        params = params.copy() if params else {}
        if self.token:
            params['token'] = self.token

        import time as _time
        last_error = None
        for attempt in range(4):
            try:
                resp = self.session.get(url, params=params, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_error = e
                if attempt < 2:
                    self.logger.warning(f"XTick 请求失败 第{attempt+1}次: {e}")
                    _time.sleep(2 * (attempt + 1))
                else:
                    self.logger.warning(f"XTick 请求失败 第{attempt+1}次(已重试3次): {e}")
        raise last_error

    @staticmethod
    def _date_only(dt_str: str) -> str:
        """将 'YYYY-MM-DD HH:MM:SS' 或 'YYYY-MM-DD' 统一截取为 'YYYY-MM-DD'。"""
        return str(dt_str)[:10]

    def _to_df(self, data) -> pd.DataFrame:
        if data is None:
            return pd.DataFrame()
        try:
            if isinstance(data, list):
                if not data:
                    return pd.DataFrame()
                # /doc/codes 返回 ["1-000001", ...] 字符串列表，需要解析
                if isinstance(data[0], str) and '-' in data[0]:
                    rows = []
                    for item in data:
                        parts = item.split('-', 1)
                        rows.append({'type': int(parts[0]), 'code': parts[1]})
                    df = pd.DataFrame(rows)
                else:
                    df = pd.DataFrame(data)
            elif isinstance(data, dict):
                # 检测 XTick 错误响应：{"code": -1, "message": "...", "data": null}
                if 'code' in data and data.get('code') != 0 and 'message' in data:
                    self.logger.warning(f"XTick API 错误: {data.get('message', '')}")
                    return pd.DataFrame()
                # data 字段为 list 时直接提取（标准成功响应 {"code":0,"data":[...]}）
                for key in ('data', 'records', 'items'):
                    if key in data and isinstance(data[key], list):
                        df = pd.DataFrame(data[key])
                        break
                else:
                    # tick/time 等返回 {key: {...}} 结构，如 {"1_000001": {...}}
                    data_keys = list(data.keys())
                    if data_keys and isinstance(data[data_keys[0]], dict):
                        records = []
                        for k, v in data.items():
                            record = dict(v)
                            # 保留复合key作为标识，如 "1_000001" -> type_code
                            record['type_code'] = k
                            records.append(record)
                        df = pd.DataFrame(records)
                    else:
                        df = pd.DataFrame([data])
            else:
                df = pd.DataFrame(data)

            if df.empty:
                return df

            # 标准化字段名
            df = self._standardize_fields(df, 'xtick')

            # XTick 返回毫秒 Unix 时间戳（如 1779154200000），需转换为 datetime
            # XTick 时间戳为 CST（UTC+8），pd.to_datetime(unit='ms') 按 UTC 解析，
            # 因此需要 +8 小时修正为北京时间
            if 'date' in df.columns and not df.empty:
                col = df['date']
                if pd.api.types.is_numeric_dtype(col):
                    sample = col.dropna().iloc[0] if len(col.dropna()) > 0 else None
                    if sample is not None and abs(float(sample)) > 1e12:
                        df['date'] = pd.to_datetime(col, unit='ms') + pd.Timedelta(hours=8)

            return df
        except Exception as e:
            self.logger.warning(f"XTick 数据转换为DataFrame失败: {e}")
            return pd.DataFrame()

    # ========== 历史/实时/逐笔 ==========
    def fetch_stock_daily(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        super().fetch_stock_daily(code, start_date, end_date)
        params = {
            'type': 1,
            'code': code,
            'period': '1d',
            'fq': self._map_adjust(adjust),
            'startDate': start_date,
            'endDate': end_date,
        }
        data = self._request('/doc/market', params=params)
        return self._to_df(data)

    def fetch_stock_1min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        super().fetch_stock_1min(code, start_date, end_date)
        params = {
            'type': 1,
            'code': code,
            'period': '1m',
            'fq': self._map_adjust(adjust),
            'startDate': self._date_only(start_date),
            'endDate': self._date_only(end_date),
        }
        data = self._request('/doc/market', params=params)
        return self._to_df(data)

    def fetch_stock_5min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        super().fetch_stock_5min(code, start_date, end_date)
        params = {
            'type': 1,
            'code': code,
            'period': '5m',
            'fq': self._map_adjust(adjust),
            'startDate': self._date_only(start_date),
            'endDate': self._date_only(end_date),
        }
        data = self._request('/doc/market', params=params)
        return self._to_df(data)

    def fetch_stock_15min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        super().fetch_stock_15min(code, start_date, end_date)
        params = {
            'type': 1,
            'code': code,
            'period': '15m',
            'fq': self._map_adjust(adjust),
            'startDate': self._date_only(start_date),
            'endDate': self._date_only(end_date),
        }
        data = self._request('/doc/market', params=params)
        return self._to_df(data)

    def fetch_stock_30min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        super().fetch_stock_30min(code, start_date, end_date)
        params = {
            'type': 1,
            'code': code,
            'period': '30m',
            'fq': self._map_adjust(adjust),
            'startDate': self._date_only(start_date),
            'endDate': self._date_only(end_date),
        }
        data = self._request('/doc/market', params=params)
        return self._to_df(data)

    def fetch_stock_60min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        super().fetch_stock_60min(code, start_date, end_date)
        params = {
            'type': 1,
            'code': code,
            'period': '1h',
            'fq': self._map_adjust(adjust),
            'startDate': self._date_only(start_date),
            'endDate': self._date_only(end_date),
        }
        data = self._request('/doc/market', params=params)
        return self._to_df(data)

    def fetch_stock_realtime(self, code: str) -> pd.DataFrame:
        super().fetch_stock_realtime(code)
        # 使用 tick/time 快照接口获取最近逐笔或快照数据
        params = {'type': 1, 'code': code, 'period': 'tick'}
        data = self._request('/doc/tick/time', params=params)
        return self._to_df(data)

    def fetch_tick_history(self, code: str, trade_date: str) -> pd.DataFrame:
        params = {'type': 1, 'code': code, 'tradeDate': trade_date}
        data = self._request('/doc/tick/history', params=params)
        return self._to_df(data)

    def fetch_auction(self, code: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        # /doc/bid/history: code=all 时 startDate/endDate 必须为同一天（获取全市场单日竞价）
        params = {'type': 1, 'code': code}
        if start_date:
            params['startDate'] = start_date
        if end_date:
            params['endDate'] = end_date
        data = self._request('/doc/bid/history', params=params)
        # 返回可能是 dict（错误）或 list（正常）
        if isinstance(data, dict) and data.get('data') is not None:
            d = data['data']
            if isinstance(d, list):
                return pd.DataFrame(d)
            elif isinstance(d, dict):
                return pd.DataFrame([d])
            return pd.DataFrame()
        if isinstance(data, list):
            return pd.DataFrame(data)
        return pd.DataFrame()

    def fetch_stock_list(self) -> pd.DataFrame:
        # /doc/codes 返回 "type-code" 格式，如 "1-000001"
        try:
            data = self._request('/doc/codes', params={})
            return self._to_df(data)
        except Exception:
            self.logger.warning('XTick /doc/codes 调用失败')
            return pd.DataFrame()


    def fetch_trade_calendar(self, start: str, end: str) -> pd.DataFrame:
        """获取交易日历。

        调用 XTick /doc/calendar 接口，返回指定日期范围内所有交易日。
        code=all 时获取全市场统一日历（含节假日标记）。

        Args:
            start: 开始日期 YYYY-MM-DD
            end: 结束日期 YYYY-MM-DD

        Returns:
            DataFrame，字段包含 [date, is_trading_day, ...]（取决于 API 返回）
            失败返回空 DataFrame
        """
        try:
            # 以沪深 A 股指数的交易日作为全市场日历
            params = {
                'type': 1,
                'code': '000001',
                'startDate': start,
                'endDate': end,
            }
            data = self._request('/doc/calendar', params=params)
            df = self._to_df(data)
            if df.empty:
                return df
            # 确保 date 列存在
            if 'date' not in df.columns:
                return pd.DataFrame()
            return df
        except Exception as e:
            self.logger.warning(f"XTick 交易日历获取失败: {e}")
            return pd.DataFrame()
    # ========== 基金 K 线（ETF，type=20）==========
    def fetch_fund_daily(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        params = {'type': 20, 'code': code, 'period': '1d', 'fq': self._map_adjust(adjust),
                  'startDate': start_date, 'endDate': end_date}
        return self._to_df(self._request('/doc/market', params=params))

    def fetch_fund_1min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        params = {'type': 20, 'code': code, 'period': '1m', 'fq': self._map_adjust(adjust),
                  'startDate': self._date_only(start_date), 'endDate': self._date_only(end_date)}
        return self._to_df(self._request('/doc/market', params=params))

    def fetch_fund_5min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        params = {'type': 20, 'code': code, 'period': '5m', 'fq': self._map_adjust(adjust),
                  'startDate': self._date_only(start_date), 'endDate': self._date_only(end_date)}
        return self._to_df(self._request('/doc/market', params=params))

    def fetch_fund_15min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        params = {'type': 20, 'code': code, 'period': '15m', 'fq': self._map_adjust(adjust),
                  'startDate': self._date_only(start_date), 'endDate': self._date_only(end_date)}
        return self._to_df(self._request('/doc/market', params=params))

    def fetch_fund_30min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        params = {'type': 20, 'code': code, 'period': '30m', 'fq': self._map_adjust(adjust),
                  'startDate': self._date_only(start_date), 'endDate': self._date_only(end_date)}
        return self._to_df(self._request('/doc/market', params=params))

    def fetch_fund_60min(self, code: str, start_date: str, end_date: str, adjust: str = 'none') -> pd.DataFrame:
        params = {'type': 20, 'code': code, 'period': '1h', 'fq': self._map_adjust(adjust),
                  'startDate': self._date_only(start_date), 'endDate': self._date_only(end_date)}
        return self._to_df(self._request('/doc/market', params=params))

    def fetch_fund_realtime(self, code: str) -> pd.DataFrame:
        params = {'type': 20, 'code': code, 'period': 'tick'}
        return self._to_df(self._request('/doc/tick/time', params=params))

    # ========== 订阅模式 (WebSocket) ==========
    def subscribe_ws(self,
                     auth_codes: Optional[List[str]],
                     on_message: Callable[[dict], None],
                     headers: Optional[dict] = None,
                     reconnect: bool = True,
                     sslopt: Optional[dict] = None):
        """建立 WebSocket 订阅连接并在新消息到达时调用 `on_message` 回调。

        说明：
        - 本方法为可选功能，运行时才会尝试导入 `websocket`（websocket-client）。
        - 若未安装 websocket-client，调用时会抛出异常并提示安装。
        - 订阅时优先进行鉴权（若 token 可用），随后发送订阅消息（auth_codes）。

        参数:
            auth_codes: 订阅编码列表（如 ['minute.SZ.1', 'tick.SZ.000001']）。
            on_message: 收到消息时的回调函数，接收单条解析后的 dict。
            headers: 额外的 HTTP headers，键值对形式。
            reconnect: 是否自动重连（由 websocket-client 的 run_forever 处理）。
            sslopt: 传递给 run_forever 的 sslopt 字典。

        返回:
            WebSocketApp 对象（由 websocket-client 提供），可用于手动关闭。
        """
        try:
            import websocket  # websocket-client
        except Exception:
            raise RuntimeError("要使用订阅功能，请先安装 websocket-client: pip install websocket-client")

        ws_url = self.config.get('XTICK_WS_URL', 'wss://api.xtick.top/ws')

        # 将 headers dict 转为列表形式
        header_list = None
        if headers:
            header_list = [f"{k}: {v}" for k, v in headers.items()]

        def _on_open(ws):
            try:
                # 鉴权
                if self.token:
                    auth_msg = {'action': 'auth', 'token': self.token}
                    ws.send(json.dumps(auth_msg))
                # 订阅
                if auth_codes:
                    sub_msg = {'action': 'subscribe', 'codes': auth_codes}
                    ws.send(json.dumps(sub_msg))
                self.logger.info('XTick WS 已发送鉴权/订阅消息')
            except Exception as e:
                self.logger.warning(f'XTick WS on_open 发送消息失败: {e}')

        def _on_message(ws, message):
            try:
                payload = json.loads(message)
            except Exception:
                payload = {'raw': message}
            try:
                on_message(payload)
            except Exception as e:
                self.logger.warning(f'用户回调 on_message 失败: {e}')

        def _on_error(ws, error):
            self.logger.warning(f'XTick WS 错误: {error}')

        def _on_close(ws, close_status_code, close_msg):
            self.logger.info(f'XTick WS 已关闭: code={close_status_code} msg={close_msg}')

        # 创建 WebSocketApp
        self._ws_app = websocket.WebSocketApp(
            ws_url,
            header=header_list,
            on_open=_on_open,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
        )

        # 在后台线程运行
        def _run():
            try:
                self._ws_app.run_forever(sslopt=(sslopt or {}))
            except Exception as e:
                self.logger.warning(f'XTick WS 运行错误: {e}')

        self._ws_thread = threading.Thread(target=_run, daemon=True)
        self._ws_thread.start()
        self._ws_running = True

        self.logger.info('XTick WebSocket 订阅线程已启动')
        return self._ws_app

    def unsubscribe_ws(self):
        """关闭当前 WebSocket 订阅连接。"""
        try:
            if getattr(self, '_ws_app', None):
                try:
                    self._ws_app.close()
                except Exception:
                    pass
            if getattr(self, '_ws_thread', None):
                try:
                    self._ws_thread.join(timeout=5)
                except Exception:
                    pass
        finally:
            self._ws_app = None
            self._ws_thread = None
            self._ws_running = False
            self.logger.info('XTick WebSocket 已关闭')
