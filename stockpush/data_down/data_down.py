from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Literal, List, Dict, Optional, Tuple
import uuid
import time
import threading

# 假设这些模块已经存在，但在测试环境中可能需要 Mock
try:
    from stockpush.db_connector import DBConnector
    from stockpush.log_manager import LogManager
    from .full_download_meta import FullDownloadMeta, check_dividend_update_needed
    from stockpush.src_mgr.src_mgr import SrcMgrService
except ImportError:
    # 为测试提供 Mock 桩
    class DBConnector: pass
    class LogManager: pass
    class SrcMgrService: pass
    FullDownloadMeta = None
    check_dividend_update_needed = None

class DataDownService:
    """F3.1 历史数据下载服务 (单任务串行版)"""
    
    def __init__(self, db: Optional[DBConnector] = None, logger=None, src_mgr=None):
        self.db = db or DBConnector()
        self.logger = logger or LogManager()
        self._src_mgr = src_mgr
        self.executor = ThreadPoolExecutor(max_workers=1) # 强制单线程
        
        # 任务状态控制
        self.current_task_id: Optional[str] = None
        self.pause_event = threading.Event()
        self.pause_event.set() # 初始为非暂停状态 (set=运行, clear=暂停)
        self.cancel_flag = False
        
        # 冲突处理同步机制
        self.conflict_event = threading.Event()

        # 线程安全的任务状态字典（替代 Qt Signal）
        self._task_state: Dict[str, dict] = {}
        self._state_lock = threading.Lock()
        self.user_conflict_policy: Optional[str] = None  # 'skip', 'overwrite'

    def _get_src_mgr(self):
        if self._src_mgr is None:
            self._src_mgr = SrcMgrService()
        return self._src_mgr

    @property
    def src_mgr(self):
        return self._get_src_mgr()

    @src_mgr.setter
    def src_mgr(self, value):
        self._src_mgr = value

    def download_history(
        self,
        symbol: str,
        period: Literal['1d', '1m', '5m', '15m', '30m', '60m'],
        start: date,
        end: date,
        provider: str,
        full_download: bool = False,
        monthly_batch: bool = True,
        overwrite_conflict: bool = False,
        progress_callback=None
    ) -> str:
        """
        创建单标的历史下载任务

        Args:
            symbol: 股票代码
            period: 周期 ('1d'/ '1m' / '5m' / '15m' / '30m' / '60m')
            start: 开始日期
            end: 结束日期
            provider: 数据源
            full_download: 是否全量下载（删除历史数据重新下载）
            monthly_batch: 是否按月分批下载（日线默认为 False）
            overwrite_conflict: 遇到冲突时是否删除旧数据并覆盖（默认False）
            progress_callback: 进度回调函数 callback(progress, current)
        """
        if self.current_task_id:
            raise RuntimeError("Task is already running. Please wait or cancel it.")

        task_id = str(uuid.uuid4())

        # 确定资产类型和周期有效性
        asset_type = self._get_asset_type(symbol)
        
        # 验证周期有效性
        valid_periods = ['1d', '1m', '5m', '15m', '30m', '60m']
        if period not in valid_periods:
            raise ValueError(f"周期不支持: {period}，支持的周期: {valid_periods}")
        
        # 日线不支持按月分批，直接全量下载
        if period == '1d':
            monthly_batch = False

        try:
            self.current_task_id = task_id
            self.cancel_flag = False
            self.pause_event.set()
            # 根据overwrite_conflict参数设置冲突策略
            self.user_conflict_policy = 'overwrite' if overwrite_conflict else None

            # 立即初始化任务状态，避免前端轮询时"任务不存在"
            self._update_state(task_id, 
                             status='running',
                             current=0,
                             total=0,
                             chunk='初始化中...',
                             logs=[],
                             preview=[])

            self.executor.submit(
                self._download_worker, task_id, symbol, period, start, end, provider, asset_type,
                full_download, monthly_batch, progress_callback
            )
            return task_id
        except Exception:
            if self.current_task_id == task_id:
                self.current_task_id = None
            raise

    def batch_download(
        self,
        symbols: List[str],
        periods: List[str],
        start: date,
        end: date,
        provider: str,
        full_download: bool = False,
        monthly_batch: bool = True,
        overwrite_conflict: bool = False,
        progress_callback=None
    ) -> str:
        """创建批量下载任务（串行遍历所有标的×周期组合）"""
        if self.current_task_id:
            raise RuntimeError("Task is already running. Please wait or cancel it.")

        task_id = str(uuid.uuid4())
        self.current_task_id = task_id
        self.cancel_flag = False
        self.pause_event.set()

        total = len(symbols) * len(periods)
        self._update_state(task_id, status='running', current=0, total=total,
                          chunk=f'Batch: 0/{total}', logs=[], preview=[])

        def batch_worker():
            completed = 0
            for symbol in symbols:
                for period in periods:
                    if self.cancel_flag:
                        self._update_state(task_id, status='cancelled')
                        self.current_task_id = None
                        return
                    self.pause_event.wait()
                    if self.cancel_flag:
                        self._update_state(task_id, status='cancelled')
                        self.current_task_id = None
                        return

                    try:
                        asset_type = self._get_asset_type(symbol)
                        self._log_info(task_id, f'[{completed+1}/{total}] 开始下载 {symbol} {period}')
                        self._download_worker(
                            task_id, symbol, period, start, end, provider, asset_type,
                            full_download, monthly_batch, progress_callback
                        )
                        self._log_info(task_id, f'[{completed+1}/{total}] 完成 {symbol} {period}')
                    except Exception as e:
                        self._log_error(task_id, f'{symbol} {period}: {e}')

                    completed += 1
                    pct = int(completed / total * 100)
                    self._update_state(task_id, current=completed, total=total,
                                      chunk=f'Batch: {completed}/{total}', status='running')

            self._log_info(task_id, f'批量下载完成: {completed}/{total}')
            self._update_state(task_id, status='completed', chunk=f'Batch completed: {completed}/{total}')
            self.current_task_id = None

        self.executor.submit(batch_worker)
        return task_id

    def pause_download(self, task_id: str = None) -> bool:
        """暂停当前任务"""
        if self.current_task_id and (task_id is None or self.current_task_id == task_id):
            self.pause_event.clear()
            self._log_info(self.current_task_id, "Task paused by user.")
            return True
        return False

    def resume_download(self, task_id: str = None) -> bool:
        """恢复当前任务"""
        if self.current_task_id and (task_id is None or self.current_task_id == task_id):
            self.pause_event.set()
            self._log_info(self.current_task_id, "Task resumed.")
            return True
        return False

    def cancel_download(self, task_id: str = None) -> bool:
        """取消当前任务"""
        if self.current_task_id and (task_id is None or self.current_task_id == task_id):
            self.cancel_flag = True
            self.pause_event.set() # 确保如果暂停中也能继续执行以响应取消
            self._log_info(self.current_task_id, "Task cancelling...")
            # 同样需要唤醒冲突等待
            self.conflict_event.set()
            return True
        return False

    def get_local_data_coverage(self, symbol: str, period: Literal['1d', '1m', '5m', '15m', '30m', '60m']) -> List[Tuple[str, str]]:
        table = self._table_for_period(period)
        try:
            res = self.db.execute_query(
                f"SELECT DISTINCT to_char(ts, 'YYYY-MM') AS ym FROM {table} WHERE symbol = %s ORDER BY ym",
                (str(symbol),)
            )
        except Exception:
            return []

        months = [row.get('ym') for row in res if row.get('ym')]
        return self._merge_month_ranges(months)

    def resolve_conflict(self, policy: Literal['skip', 'overwrite']):
        """UI 调用此方法设置冲突策略，并唤醒工作线程"""
        self.user_conflict_policy = policy
        self.conflict_event.set()

    def get_progress(self, task_id: str = None) -> dict:
        """获取任务进度"""
        tid = task_id or self.current_task_id
        if not tid:
            return {'status': 'idle', 'message': '无活动任务'}

        if task_id and task_id != self.current_task_id and task_id not in self._task_state:
            return {'status': 'unknown', 'message': '任务不存在'}

        with self._state_lock:
            state = dict(self._task_state.get(tid, {}))

        current = state.get('current', 0)
        total = state.get('total', 0)
        percent = round(current / total * 100, 1) if total > 0 else 0
        status = state.get('status', 'running')
        paused = not self.pause_event.is_set()

        return {
            'status': 'paused' if paused and status == 'running' else status,
            'task_id': tid,
            'message': state.get('chunk', '下载中...'),
            'percent': percent,
            'completed': current,
            'total': total,
            'preview_data': state.get('preview', []),
            'logs': state.get('logs', []),
            'conflict': state.get('conflict'),
        }

    def _update_state(self, task_id: str, **kwargs):
        """线程安全地更新任务状态"""
        with self._state_lock:
            if task_id not in self._task_state:
                self._task_state[task_id] = {'logs': [], 'preview': []}
            for k, v in kwargs.items():
                if k == 'preview' and v is not None:
                    # 序列化 datetime 对象
                    serialized = []
                    for row in v:
                        r = {}
                        for rk, rv in row.items():
                            r[rk] = rv.isoformat() if isinstance(rv, (datetime, date)) else rv
                        serialized.append(r)
                    self._task_state[task_id]['preview'] = serialized
                else:
                    self._task_state[task_id][k] = v

    def _append_log(self, task_id: str, level: str, msg: str):
        """追加日志到任务状态"""
        entry = {'level': level, 'msg': msg, 'ts': datetime.now().strftime('%H:%M:%S')}
        with self._state_lock:
            if task_id not in self._task_state:
                self._task_state[task_id] = {'logs': [], 'preview': []}
            logs = self._task_state[task_id].setdefault('logs', [])
            logs.append(entry)
            # 只保留最近 200 条
            if len(logs) > 200:
                self._task_state[task_id]['logs'] = logs[-200:]
        print(f"[{level}] [{task_id[:8]}] {msg}")

    def _table_for_period(self, period: str) -> str:
        table_map = {
            '1m':  'tb_raw_1m',
            '5m':  'tb_raw_5m',
            '15m': 'tb_raw_15m',
            '30m': 'tb_raw_30m',
            '60m': 'tb_raw_60m',
            '1d':  'tb_raw_1d',
        }
        table = table_map.get(period)
        if not table:
            raise ValueError(f"period不支持: {period}")
        return table

    def _ensure_period_table(self, period: str):
        """确保周期对应表存在（兼容历史库缺少新增周期表）。"""
        table = self._table_for_period(period)
        sql = f"""
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
        """
        self.db.execute_update(sql)

    def _merge_month_ranges(self, months: List[str]) -> List[Tuple[str, str]]:
        if not months:
            return []

        def _parse_ym(ym: str) -> Tuple[int, int]:
            y, m = ym.split('-')
            return int(y), int(m)

        def _next_ym(y: int, m: int) -> Tuple[int, int]:
            if m == 12:
                return y + 1, 1
            return y, m + 1

        unique_sorted = sorted(set(months))
        parsed = [_parse_ym(ym) for ym in unique_sorted]

        ranges: List[Tuple[str, str]] = []
        start_y, start_m = parsed[0]
        prev_y, prev_m = parsed[0]

        for y, m in parsed[1:]:
            exp_y, exp_m = _next_ym(prev_y, prev_m)
            if (y, m) == (exp_y, exp_m):
                prev_y, prev_m = y, m
                continue

            ranges.append((f"{start_y:04d}-{start_m:02d}", f"{prev_y:04d}-{prev_m:02d}"))
            start_y, start_m = y, m
            prev_y, prev_m = y, m

        ranges.append((f"{start_y:04d}-{start_m:02d}", f"{prev_y:04d}-{prev_m:02d}"))
        return ranges

    def _download_worker(self, task_id, symbol, period, start, end, provider, asset_type,
                         full_download=False, monthly_batch=True, progress_callback=None):
        """工作线程逻辑 - 使用标准 API"""
        self._update_state(task_id, status='running', symbol=symbol, current=0, total=0, chunk='', preview=[])
        self._log_info(task_id, f"Started downloading {symbol} ({start} ~ {end}) from {provider}, period={period}")

        # 用于记录进度
        def emit_progress(current, total, chunk_str=''):
            if progress_callback:
                progress_callback(current, total, chunk_str)
            self._update_state(task_id, current=current, total=total, chunk=chunk_str)

        try:
            self._ensure_period_table(period)

            # 1. 如果是全量下载，先删除该symbol在该周期表的全部数据
            if full_download:
                self._log_info(task_id, f"全量下载模式: 删除 {symbol} 的 {period} 全部数据")
                self._delete_all_for_symbol(symbol, period)

            # 2. 生成倒序分片
            if monthly_batch and period != '1d':
                chunks = self._generate_chunks(start, end, reverse=True)
            else:
                chunks = [(start, end)]

            total_chunks = len(chunks)

            # conflict_policy_cache: 缓存用户的选择，应用于后续所有分片
            conflict_policy_cache = None
            has_data_once = False

            for idx, (chunk_start, chunk_end) in enumerate(chunks):
                # 检查取消
                if self.cancel_flag:
                    self._update_state(task_id, status='cancelled')
                    return

                # 检查暂停
                if not self.pause_event.is_set():
                    self._update_state(task_id, status='paused')
                    self._log_info(task_id, "Waiting for resume...")
                    self.pause_event.wait()

                    if self.cancel_flag:
                        self._update_state(task_id, status='cancelled')
                        return
                    self._update_state(task_id, status='running')

                chunk_str = f"{chunk_start.strftime('%Y-%m')}"
                emit_progress(idx + 1, total_chunks, chunk_str)
                
                # 检查冲突
                if conflict_policy_cache is None:
                    has_conflict = self._check_conflict(symbol, period, chunk_start, chunk_end)
                    if has_conflict:
                        self._log_warn(task_id, f"Conflict detected in {chunk_str}")
                        
                        # 如果用户已设定冲突策略，直接使用；否则等待用户选择
                        if self.user_conflict_policy:
                            conflict_policy_cache = self.user_conflict_policy
                            self._log_info(task_id, f"Using preset policy: {conflict_policy_cache}")
                        else:
                            self.conflict_event.clear()
                            self._update_state(task_id, conflict=chunk_str)
                            self.conflict_event.wait(timeout=30)
                            
                            if self.cancel_flag: return
                            
                            conflict_policy_cache = self.user_conflict_policy or 'skip'
                            self._log_info(task_id, f"User selected policy: {conflict_policy_cache}")
                
                # 应用策略
                if conflict_policy_cache == 'skip':
                    if self._check_conflict(symbol, period, chunk_start, chunk_end):
                        self._log_info(task_id, f"Skipped {chunk_str} due to policy.")
                        continue
                
                # 3. 调用统一K线接口获取数据
                try:
                    if self.cancel_flag:
                        self._update_state(task_id, status='cancelled')
                        return

                    start_dt, end_dt = (chunk_start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d')) if period == '1d' else self._format_minute_range(chunk_start, chunk_end)
                    provider_obj = self._get_provider_instance(provider)
                    kline_period = period
                    
                    if hasattr(provider_obj, 'fetch_kline'):
                        df = provider_obj.fetch_kline(
                            code=symbol, period=kline_period, start=start_dt, end=end_dt,
                            adjust='qfq', asset_type=asset_type
                        )
                    else:
                        # 回退到旧接口
                        if asset_type == 'stock':
                            if period == '1d':
                                df = provider_obj.fetch_stock_history_daily(symbol, start_dt, end_dt, adjust='qfq')
                            else:
                                df = provider_obj.fetch_stock_history_minute(symbol, period.rstrip('m'), start_dt, end_dt, adjust='qfq')
                        elif asset_type == 'fund':
                            if period == '1d':
                                df = provider_obj.fetch_fund_history_daily(symbol, start_dt, end_dt, adjust='qfq')
                            else:
                                df = provider_obj.fetch_fund_history_minute(symbol, period.rstrip('m'), start_dt, end_dt, adjust='qfq')
                        else:
                            raise ValueError(f"不支持的资产类型: {asset_type}")
                    
                    # 检查返回值（标准 API 返回 DataFrame 或 -1）
                    if isinstance(df, int) and df == -1:
                        self._log_error(task_id, f"API error for {chunk_str}: provider returned -1")
                        continue
                    
                    # DataFrame 转 List[Dict]
                    if hasattr(df, 'empty') and not df.empty:
                        data = df.to_dict('records')
                    elif isinstance(df, list):
                        data = df
                    else:
                        data = []

                except Exception as e:
                    self._log_error(task_id, f"Fetch error for {chunk_str}: {e}")
                    continue
                finally:
                    # 释放 TdxOnline 连接
                    try:
                        if str(provider).lower() == 'tdxonline':
                            if hasattr(provider_obj, 'release_connection'):
                                provider_obj.release_connection()
                    except Exception:
                        pass

                # 4. 熔断策略：无数据处理
                if not data:
                    if monthly_batch and not has_data_once:
                        self._log_warn(task_id, f"No data found for {chunk_str}, skipping (not yet available).")
                        continue
                    self._log_warn(task_id, f"No data found for {chunk_str}. Stopping (Reverse Order Strategy).")
                    self._update_state(task_id, status='stopped')
                    return

                data = self._normalize_kline_rows(data, symbol, period)

                if not data:
                    if monthly_batch and not has_data_once:
                        self._log_warn(task_id, f"No valid rows for {chunk_str}, skipping.")
                        continue
                    self._log_warn(task_id, f"No valid rows for {chunk_str}. Stopping.")
                    self._update_state(task_id, status='stopped')
                    return

                if str(provider).lower() == 'tdxonline':
                    unique_ts = len({row.get('ts') for row in data if row.get('ts') is not None})
                    self._log_info(task_id, f"Chunk {chunk_str} normalized rows={len(data)}, unique_ts={unique_ts}")

                # 5. 入库
                if conflict_policy_cache == 'overwrite':
                    self._delete_range(symbol, period, chunk_start, chunk_end)

                saved_count = self._save_to_db(data, period)
                self._log_info(task_id, f"Saved {chunk_str}: {saved_count} records.")
                has_data_once = True
                
                # 6. 更新预览数据 (取10条)
                if data:
                    self._update_state(task_id, preview=data[:10])

            # 7. 下载完成后，更新全量下载元数据
            self._update_full_download_meta(symbol, provider)

            self._update_state(task_id, status='completed')

        except Exception as e:
            self._log_error(task_id, f"Unexpected error: {e}")
            self._update_state(task_id, status='failed')
        finally:
            self.current_task_id = None

    def _generate_chunks(self, start: date, end: date, reverse: bool = True) -> List[Tuple[date, date]]:
        """按自然月生成分片"""
        chunks = []
        
        # 规整 start 到当月第一天
        current_month_start = start.replace(day=1)
        
        while current_month_start <= end:
            # 计算当月最后一天
            # 下个月第一天 - 1天
            if current_month_start.month == 12:
                next_month = current_month_start.replace(year=current_month_start.year + 1, month=1, day=1)
            else:
                next_month = current_month_start.replace(month=current_month_start.month + 1, day=1)
            
            month_end = next_month - timedelta(days=1)
            
            # 取交集
            chunk_start = max(start, current_month_start)
            chunk_end = min(end, month_end)
            
            if chunk_start <= chunk_end:
                chunks.append((chunk_start, chunk_end))
            
            current_month_start = next_month
            
        if reverse:
            chunks.reverse()
        return chunks

    def _format_minute_range(self, start_day: date, end_day: date) -> Tuple[str, str]:
        start_dt = datetime.combine(start_day, datetime.min.time())
        end_dt = datetime.combine(end_day, datetime.max.time())
        return start_dt.strftime('%Y-%m-%d %H:%M:%S'), end_dt.strftime('%Y-%m-%d %H:%M:%S')

    def _get_provider_instance(self, provider: str):
        """获取 Provider 实例 - 使用标准 API"""
        try:
            src_mgr = self._get_src_mgr()
            provider_obj = src_mgr.get_provider_instance(provider)
            if provider_obj is None:
                raise ValueError(f"无法获取数据源实例: {provider}")
            return provider_obj
        except Exception as e:
            self._log_error('', f"Failed to get provider instance: {e}")
            raise

    def _get_asset_type(self, symbol: str) -> str:
        try:
            res = self.db.execute_query(
                "SELECT type FROM tb_stock_pool WHERE symbol = %s ORDER BY updated_at DESC LIMIT 1",
                (str(symbol),)
            )
            if res and res[0].get('type') in ('stock', 'fund'):
                return res[0]['type']
        except Exception:
            pass
        return 'stock'

    def _map_data_type(self, asset_type: str, period: str) -> str:
        asset_type = asset_type if asset_type in ('stock', 'fund') else 'stock'
        period_map = {
            '1m':  f"{asset_type}_1min",
            '5m':  f"{asset_type}_5min",
            '15m': f"{asset_type}_15min",
            '30m': f"{asset_type}_30min",
            '60m': f"{asset_type}_60min",
            '1d':  f"{asset_type}_daily",
        }
        result = period_map.get(period)
        if not result:
            raise ValueError(f"period不支持: {period}")
        return result

    def _normalize_fetch_code(self, provider: str, symbol: str, asset_type: str) -> str:
        provider = str(provider).lower()
        symbol = str(symbol).strip()

        if '.' in symbol:
            return symbol

        if provider in ('tdxonline', 'tdxlocal') and asset_type == 'fund':
            if symbol.startswith('5'):
                return f"{symbol}.SH"
            if symbol.startswith('1'):
                return f"{symbol}.SZ"

        return symbol

    def _check_conflict(self, symbol: str, period: str, start: date, end: date) -> bool:
        """检查数据库中是否存在该时间段的数据"""
        table = self._table_for_period(period)
        sql = f"SELECT COUNT(*) FROM {table} WHERE symbol = %s AND ts >= %s AND ts <= %s"
        
        # 构造 datetime 边界 (DuckDB/Postgres 通常需要 datetime)
        ts_start = datetime.combine(start, datetime.min.time())
        ts_end = datetime.combine(end, datetime.max.time())
        
        try:
            # result = [{'count_star()': 123}] or similar
            res = self.db.execute_query(sql, (symbol, ts_start, ts_end))
            if res and len(res) > 0:
                # 获取第一个值
                return list(res[0].values())[0] > 0
            return False
        except Exception:
            return False

    def _delete_range(self, symbol: str, period: str, start: date, end: date):
        """删除指定范围内的数据"""
        table = self._table_for_period(period)
        sql = f"DELETE FROM {table} WHERE symbol = %s AND ts >= %s AND ts <= %s"
        
        ts_start = datetime.combine(start, datetime.min.time())
        ts_end = datetime.combine(end, datetime.max.time())
        
        try:
            self.db.execute_update(sql, (symbol, ts_start, ts_end))
        except Exception as e:
            self._log_error(self.current_task_id or 'Unknown', f"Delete failed: {e}")

    def _delete_all_for_symbol(self, symbol: str, period: str):
        """删除指定symbol在指定周期表中的全部数据"""
        table = self._table_for_period(period)
        sql = f"DELETE FROM {table} WHERE symbol = %s"
        
        try:
            self.db.execute_update(sql, (symbol,))
        except Exception as e:
            self._log_error(self.current_task_id or 'Unknown', f"Delete all for {symbol} failed: {e}")

    def _save_to_db(self, data: List[Dict], period: str) -> int:
        """批量写入数据库"""
        if not data:
            return 0

        table = self._table_for_period(period)

        columns = ["ts", "symbol", "open", "high", "low", "close", "vol", "amount"]
        placeholders = ", ".join(["%s"] * len(columns))
        columns_str = ", ".join(columns)
        sql = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        params_list: List[Tuple] = []
        for item in data:
            params_list.append(tuple(item.get(col) for col in columns))

        if hasattr(self.db, 'execute_many'):
            affected = self.db.execute_many(sql, params_list)
            return affected if affected > 0 else len(params_list)
        return len(params_list)

    def _normalize_kline_rows(self, rows: List[Dict], symbol: str, period: str = '1d') -> List[Dict]:
        out: List[Dict] = []
        for row in rows:
            normalized = self._normalize_kline_row(row, symbol, period)
            if normalized is not None:
                out.append(normalized)
        return out

    def _normalize_kline_row(self, row: Dict, symbol: str, period: str = '1d') -> Optional[Dict]:
        ts_raw = row.get("ts")
        if ts_raw is None:
            ts_raw = row.get("datetime")

        if ts_raw is None:
            date_raw = row.get("date")
            time_raw = row.get("time")
            if date_raw is not None and time_raw is not None:
                time_text = str(time_raw).strip() if time_raw is not None else ""
                if time_text.isdigit() and len(time_text) >= 12:
                    ts_raw = time_text
                else:
                    date_dt = self._to_datetime(date_raw)
                    if date_dt is None:
                        return None

                    date_str = date_dt.strftime('%Y-%m-%d')
                    time_str = self._normalize_time_str(time_raw)
                    if time_str:
                        ts_raw = f"{date_str} {time_str}"
                    else:
                        ts_raw = date_raw
            else:
                ts_raw = date_raw

        if ts_raw is None:
            ts_raw = row.get("time")

        if ts_raw is None:
            return None

        ts = self._to_datetime(ts_raw)
        if ts is None:
            return None
        
        # 应用周期感知的时间戳对齐
        ts = self._align_timestamp_to_period(ts, period)

        def _num(key: str, alt_keys: List[str] = None, default: float = 0.0) -> float:
            if alt_keys is None:
                alt_keys = []
            val = row.get(key)
            if val is None:
                for k in alt_keys:
                    val = row.get(k)
                    if val is not None:
                        break
            if val is None:
                return default
            try:
                return float(val)
            except Exception:
                return default

        open_ = _num("open")
        high = _num("high")
        low = _num("low")
        close = _num("close")
        vol = _num("vol", ["volume", "成交量"], 0.0)
        amount = _num("amount", ["成交额"], 0.0)

        if any(v == 0.0 for v in (open_, high, low, close)):
            if not (open_ or high or low or close):
                return None

        return {
            "ts": ts,
            "symbol": str(symbol),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": amount,
        }

    def _normalize_time_str(self, value) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None

        if ':' in text:
            parts = text.split(':')
            if len(parts) == 2:
                return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:00"
            if len(parts) >= 3:
                return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:{parts[2].zfill(2)}"
            return text

        if text.isdigit():
            if len(text) == 6:
                return f"{text[0:2]}:{text[2:4]}:{text[4:6]}"
            if len(text) == 4:
                return f"{text[0:2]}:{text[2:4]}:00"

        return None

    def _to_datetime(self, value) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if hasattr(value, "to_pydatetime"):
            try:
                return value.to_pydatetime()
            except Exception:
                pass

        text = str(value).strip()
        if not text:
            return None

        if text.isdigit() and len(text) > 14:
            text = text[:14]
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y%m%d%H%M%S",
            "%Y%m%d%H%M",
            "%Y%m%d",
        ):
            try:
                dt = datetime.strptime(text, fmt)
                if fmt in ("%Y-%m-%d", "%Y%m%d"):
                    return datetime.combine(dt.date(), datetime.min.time())
                return dt
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    def _align_timestamp_to_period(self, ts: datetime, period: str) -> datetime:
        """
        根据周期对齐时间戳，确保时间戳落在正确的分钟边界上
        
        Args:
            ts: 原始时间戳
            period: 周期 ('1d', '1m', '5m', '15m', '30m', '60m')
        
        Returns:
            对齐后的时间戳
        """
        # 移除微秒精度，避免秒数溢出
        ts = ts.replace(microsecond=0)
        
        if period == '1d':
            # 日K应该在 00:00:00
            ts = ts.replace(hour=0, minute=0, second=0)
        elif period == '1m':
            # 1分钟线秒数应该是 0
            ts = ts.replace(second=0)
        elif period in ('5m', '15m', '30m', '60m'):
            # 提取周期数字
            period_minutes = int(period.replace('m', ''))
            
            # 对齐分钟到周期边界（只看分钟，不看秒数）
            minute = ts.minute
            aligned_minute = (minute // period_minutes) * period_minutes
            ts = ts.replace(minute=aligned_minute, second=0)
        
        return ts

    def _log_info(self, task_id, msg):
        if hasattr(self.logger, 'log_info'):
            self.logger.log_info(f"[{task_id}] {msg}")
        self._append_log(task_id, "INFO", msg)

    def _log_warn(self, task_id, msg):
        if hasattr(self.logger, 'log_warn'):
            self.logger.log_warn(f"[{task_id}] {msg}")
        self._append_log(task_id, "WARN", msg)

    def _log_error(self, task_id, msg):
        if hasattr(self.logger, 'log_error'):
            self.logger.log_error(f"[{task_id}] {msg}")
        self._append_log(task_id, "ERROR", msg)

    def _update_full_download_meta(self, symbol: str, provider: str):
        """下载完成后更新全量下载元数据"""
        try:
            # 获取资产类型
            asset_type = self._get_asset_type(symbol)

            # 获取证券名称（从db或通过provider获取）
            name = symbol  # 默认使用代码作为名称

            # 获取最新分红日期
            dividend_date = None
            try:
                src_mgr = self._get_src_mgr()
                if hasattr(src_mgr, 'fetch_data'):
                    # 调用API12获取最新分红日期
                    dividend_info = src_mgr.fetch_data(
                        provider=provider,
                        data_type='dividend',
                        code=symbol,
                        start_date='',
                        end_date=''
                    )
                    if dividend_info and isinstance(dividend_info, dict):
                        dividend_date = dividend_info.get('latest_dividend_date')
            except Exception as e:
                self._log_warn(symbol, f"获取分红日期失败: {e}")

            # 加载并更新元数据
            meta = FullDownloadMeta.load()
            meta.add_or_update_asset(symbol, name, asset_type, dividend_date)
            meta.update_full_download_date()
            meta.save()

            self._log_info(symbol, f"已更新全量下载元数据: 分红日期={dividend_date}")
        except Exception as e:
            self._log_error(symbol, f"更新全量下载元数据失败: {e}")
