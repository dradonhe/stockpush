"""
数据源注册表 - 统一管理和调用所有数据源
创建日期: 2026-02-15
设计目标: 解耦界面与数据源实现，提供统一调用接口，支持动态扩展
"""
import json
import time
import importlib
from typing import Union, List, Dict, Optional, Any
import pandas as pd
from stockpush.pg_connector import PGConnector
from stockpush.log_manager import LogManager


class DataSourceRegistry:
    """
    数据源注册表
    - 从数据库加载数据源配置
    - 提供12个标准API统一调用接口
    - 自动路由到合适的数据源
    - 统计调用性能
    
    API分类：
    - 股票：历史日线(api01)、历史分钟(api02)、实时日线(api03)、实时分钟(api04)
    - 基金：历史日线(api05)、历史分钟(api06)、实时日线(api07)、实时分钟(api08)
    - 代码：股票列表(api09)、基金列表(api10)
    - 日历：交易日历(api11)
    - 其他：分红查询(api12)
    """
    
    # 12个标准API接口映射（明确区分历史/实时）
    API_METHODS = {
        'api01': 'fetch_stock_history_daily',      # 股票历史日线
        'api02': 'fetch_stock_history_minute',     # 股票历史分钟线
        'api03': 'fetch_stock_realtime_daily',     # 股票实时行情（日线级别）
        'api04': 'fetch_stock_realtime_minute',    # 股票实时分钟线
        'api05': 'fetch_fund_history_daily',       # 基金历史日线
        'api06': 'fetch_fund_history_minute',      # 基金历史分钟线
        'api07': 'fetch_fund_realtime_daily',      # 基金实时行情（日线级别）
        'api08': 'fetch_fund_realtime_minute',     # 基金实时分钟线
        'api09': 'fetch_stock_list',               # 股票代码列表
        'api10': 'fetch_fund_list',                # 基金代码列表
        'api11': 'fetch_trade_calendar',           # 交易日历
        'api12': 'fetch_latest_dividend_date',     # 最新分红日期
    }
    
    def __init__(self):
        self.db = PGConnector()
        self.logger = LogManager().get_logger('DataSourceRegistry')
        self.providers = {}  # 缓存Provider实例 {provider_name: provider_instance}
        self.registry = []   # 注册表数据
        self._load_registry()
    
    def _load_registry(self):
        """从数据库加载数据源注册表（每次启动都重新播种，确保与代码一致）"""
        try:
            conn = self.db
            # 每次启动都重新播种，确保 enabled 状态与代码种子数据一致
            self._seed_registry(conn)
            # 加载所有数据源（含禁用的，以便 UI 完整显示）
            rows = self.db.execute_query(
                "SELECT * FROM tb_datasource_registry ORDER BY priority"
            )
            self.registry = rows
            self.logger.info(f"✅ 加载数据源注册表成功：{len(self.registry)}个数据源")
            for item in self.registry:
                capabilities = [
                    api_id for api_id in self.API_METHODS.keys()
                    if item.get(f'capability_{api_id}')
                ]
                self.logger.info(
                    f"  [{item['display_name']}] "
                    f"优先级={item['priority']}, "
                    f"支持API=[{','.join(capabilities)}]"
                )
        except Exception as e:
            self.logger.error(f"❌ 加载数据源注册表失败: {e}")
            self.registry = []

    def _seed_registry(self, conn):
        """自动初始化 tb_datasource_registry 表和数据"""
        # Check if table already has data before seeding
        existing = conn.execute_query(
            "SELECT COUNT(*) as cnt FROM tb_datasource_registry"
        )
        if existing and existing[0].get('cnt', 0) > 0:
            self.logger.info(f"数据源注册表已存在（{existing[0]['cnt']}条记录），跳过初始化")
            return
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tb_datasource_registry (
                id INTEGER PRIMARY KEY,
                provider_name VARCHAR(50) NOT NULL UNIQUE,
                display_name VARCHAR(100) NOT NULL,
                provider_class VARCHAR(200) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                priority INTEGER NOT NULL DEFAULT 50,
                config_json VARCHAR,
                timeout INTEGER NOT NULL DEFAULT 30,
                retry INTEGER NOT NULL DEFAULT 3,
                capability_api01 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api02 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api03 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api04 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api05 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api06 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api07 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api08 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api09 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api10 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api11 BOOLEAN NOT NULL DEFAULT FALSE,
                capability_api12 BOOLEAN NOT NULL DEFAULT FALSE,
                last_test_time TIMESTAMP, test_result VARCHAR(20),
                test_details VARCHAR, error_msg VARCHAR,
                call_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                avg_response_time REAL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        providers = [
            ('byapi', '币赢API', 'stockpush.src_mgr.src_provider.ByapiProvider', False, 15,
             '{"licence":"","timeout":10,"retry":2}', 10, 2,
             False,False,False,False, False,False,False,False, False,False,False,False),
            ('xtick', 'XTick', 'stockpush.src_mgr.xtick_provider.XTickProvider', True, 12,
             '{"timeout":15}', 15, 2,
             True,True,True,True, True,True,True,True, True,True,True,False),
        ]
        for i, p in enumerate(providers, 1):
            conn.execute("""
                INSERT INTO tb_datasource_registry VALUES (
                    ?,?,?,?,?,?,
                    ?,?,?,
                    ?,?,?,?, ?,?,?,?,
                    ?,?,?,?,
                    NULL,NULL,NULL,NULL,
                    0,0,0,NULL,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """, (i,) + p)
        self.logger.info(f"✅ 自动初始化数据源注册表完成：{len(providers)}个数据源")

    def _get_provider(self, provider_name: str):
        """
        获取Provider实例（带缓存）
        
        Args:
            provider_name: 数据源名称
        
        Returns:
            Provider实例 or None
        """
        # 检查缓存
        if provider_name in self.providers:
            return self.providers[provider_name]
        
        # 查找注册信息
        provider_info = next(
            (p for p in self.registry if p['provider_name'] == provider_name), 
            None
        )
        
        if not provider_info:
            self.logger.error(f"数据源 '{provider_name}' 未注册或未启用")
            return None
        
        try:
            # 动态加载Provider类
            class_path = provider_info['provider_class']
            module_path, class_name = class_path.rsplit('.', 1)
            
            self.logger.debug(f"动态加载: {module_path}.{class_name}")
            module = importlib.import_module(module_path)
            provider_class = getattr(module, class_name)
            
            # 解析配置（过滤 registry 级别字段，只保留 Provider 专属配置）
            config_json = provider_info.get('config_json', '{}')
            config = json.loads(config_json) if config_json else {}
            config.pop('timeout', None)
            config.pop('retry', None)
            
            # 实例化Provider
            if config:
                provider = provider_class(**config)
            else:
                provider = provider_class()
            
            # 缓存实例
            self.providers[provider_name] = provider
            self.logger.info(f"✅ 实例化数据源 '{provider_name}' 成功")
            
            return provider
        
        except Exception as e:
            self.logger.error(f"❌ 实例化数据源 '{provider_name}' 失败: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None
    
    def get_available_providers(self, api_id: str) -> List[str]:
        """
        获取支持指定API的数据源列表
        
        Args:
            api_id: API编号，如 'api01', 'api07'
        
        Returns:
            数据源名称列表，按优先级排序
        """
        capability_field = f'capability_{api_id}'
        available = [
            p['provider_name'] 
            for p in self.registry 
            if p.get(capability_field)
        ]
        return available
    
    def call(self, api_id: str, provider_name: Optional[str] = None, **kwargs) -> Any:
        """
        统一调用接口
        
        Args:
            api_id: API编号，如 'api01'（股票日线）, 'api07'（代码列表）
            provider_name: 指定数据源，如果为None则自动选择优先级最高的
            **kwargs: API参数
        
        Returns:
            成功: 返回数据（DataFrame/list/dict）
            失败: 返回 -1
        
        Examples:
            # 自动选择数据源获取股票历史日线
            df = registry.call('api01', code='000001', start='2024-01-01', end='2024-02-01')
            
            # 获取股票实时行情
            quote = registry.call('api03', code='000001')
            
            # 指定使用Byapi获取基金列表
            funds = registry.call('api10', provider_name='byapi')
            
            # 获取交易日历
            dates = registry.call('api11', start='2024-01-01', end='2024-12-31')
        """
        start_time = time.time()
        
        try:
            # 1. 检查API编号是否已知
            method_name = self.API_METHODS.get(api_id)
            if not method_name:
                self.logger.error(f"❌ 未知的API编号: {api_id}")
                return -2
            
            # 2. 确定使用哪个数据源
            if provider_name:
                # 能力矩阵预检查：指定provider时先检查是否支持该API
                provider_info = next(
                    (p for p in self.registry if p['provider_name'] == provider_name),
                    None
                )
                if not provider_info:
                    self.logger.warning(f"⚠️ 数据源不存在: {provider_name}")
                    return -1
                
                capability_field = f'capability_{api_id}'
                if not provider_info.get(capability_field):
                    self.logger.warning(
                        f"⚠️ [{provider_name}] 不支持 {api_id} "
                        f"(能力矩阵预检查失败)"
                    )
                    return -1
                
                providers_to_try = [provider_name]
            else:
                providers_to_try = self.get_available_providers(api_id)
            
            if not providers_to_try:
                self.logger.warning(f"⚠️ 没有数据源支持 {api_id}")
                return -1
            
            # 依次尝试数据源
            last_error = None
            for pname in providers_to_try:
                provider = self._get_provider(pname)
                if not provider:
                    continue
                
                try:
                    # 检查方法是否存在
                    method = getattr(provider, method_name, None)
                    if not method:
                        self.logger.warning(f"⚠️ [{pname}] 未实现 {method_name}")
                        continue
                    
                    # 调用Provider方法
                    self.logger.info(f"🔄 调用 [{pname}].{method_name}({self._format_params(kwargs)})")
                    result = method(**kwargs)
                    
                    # 检查结果（DataFrame 不能用 == -1 比较）
                    if result is None:
                        self.logger.warning(f"⚠️ [{pname}] 返回空/失败")
                        continue
                    if not isinstance(result, pd.DataFrame) and result == -1:
                        self.logger.warning(f"⚠️ [{pname}] 返回空/失败")
                        continue
                    
                    # 验证数据有效性
                    is_valid = False
                    if isinstance(result, pd.DataFrame):
                        is_valid = len(result) > 0
                    elif isinstance(result, list):
                        is_valid = len(result) > 0
                    elif isinstance(result, dict):
                        is_valid = bool(result)
                    
                    if is_valid:
                        elapsed = (time.time() - start_time) * 1000
                        row_count = self._count_rows(result)
                        self.logger.info(
                            f"✅ [{pname}] {api_id} 成功 "
                            f"(耗时{elapsed:.0f}ms, {row_count}行)"
                        )
                        self._update_stats(pname, success=True, response_time=elapsed)
                        return result
                    else:
                        self.logger.warning(f"⚠️ [{pname}] 返回数据无效")
                
                except Exception as e:
                    last_error = e
                    self.logger.error(f"❌ [{pname}] 调用失败: {str(e)[:100]}")
                    self._update_stats(pname, success=False)
                    continue
            
            # 所有数据源都失败
            elapsed = (time.time() - start_time) * 1000
            self.logger.error(
                f"❌ {api_id} 所有数据源都失败 "
                f"(尝试了{len(providers_to_try)}个数据源, 耗时{elapsed:.0f}ms)"
            )
            return -1
        
        except Exception as e:
            self.logger.error(f"❌ 统一调用接口异常: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return -1
    
    def fetch_kline(self, code: str, period: str, start: str, end: str,
                    adjust: str = 'qfq', asset_type: str = 'stock',
                    provider_name: Optional[str] = None) -> Any:
        """
        统一K线数据接口
        
        Args:
            code: 证券代码，如 '000001'
            period: K线周期，'1d'/'1m'/'5m'/'15m'/'30m'/'60m'
            start: 起始时间，日线:'YYYY-MM-DD'，分钟线:'YYYY-MM-DD HH:MM:SS'
            end: 结束时间，同上
            adjust: 复权方式，'qfq'(前复权)/'hfq'(后复权)/'none'(不复权)
            asset_type: 资产类型，'stock'/'fund'
            provider_name: 指定数据源，None=自动路由
            
        Returns:
            成功: DataFrame（字段: datetime/date, open, high, low, close, volume, amount, code）
            失败: -1
        """
        start_time = time.time()
        
        try:
            if provider_name:
                providers_to_try = [provider_name]
            else:
                # 周期 -> API号的映射（用于能力矩阵查询）
                api_map = {
                    '1d': 'api01' if asset_type == 'stock' else 'api05',      # 股票/基金日线
                    '1m': 'api02' if asset_type == 'stock' else 'api06',      # 股票/基金1分钟线
                    '5m': 'api02' if asset_type == 'stock' else 'api06',      # 5分钟也用api02/06
                    '15m': 'api02' if asset_type == 'stock' else 'api06',     # 15分钟也用api02/06
                    '30m': 'api02' if asset_type == 'stock' else 'api06',     # 30分钟也用api02/06
                    '60m': 'api02' if asset_type == 'stock' else 'api06',     # 60分钟也用api02/06
                }
                
                api_id = api_map.get(period)
                if not api_id:
                    self.logger.error(f"❌ 不支持的周期: {period}")
                    return -1
                
                # 获取支持该API的数据源列表（按优先级排序）
                providers_to_try = self.get_available_providers(api_id)
            
            if not providers_to_try:
                self.logger.warning(f"⚠️ 没有数据源支持 {asset_type}/{period}")
                return -1
            
            last_error = None
            for pname in providers_to_try:
                provider = self._get_provider(pname)
                if not provider:
                    continue
                
                try:
                    if hasattr(provider, 'fetch_kline'):
                        result = provider.fetch_kline(
                            code=code, period=period, start=start, end=end,
                            adjust=adjust, asset_type=asset_type
                        )
                    else:
                        result = self._call_legacy_kline(
                            provider, code, period, start, end, adjust, asset_type
                        )
                    
                    if result is None or (isinstance(result, pd.DataFrame) and result.empty):
                        self.logger.warning(f"⚠️ [{pname}] 返回空数据")
                        continue
                    if not isinstance(result, pd.DataFrame) and result == -1:
                        continue
                    
                    elapsed = (time.time() - start_time) * 1000
                    row_count = self._count_rows(result)
                    self.logger.info(f"✅ [{pname}] fetch_kline({code},{period}) 成功 ({row_count}行, {elapsed:.0f}ms)")
                    self._update_stats(pname, success=True, response_time=elapsed)
                    return result
                
                except Exception as e:
                    last_error = e
                    self.logger.error(f"❌ [{pname}] fetch_kline 失败: {str(e)[:100]}")
                    self._update_stats(pname, success=False)
                    continue
            
            self.logger.error(f"❌ fetch_kline 所有数据源失败")
            return -1
        
        except Exception as e:
            self.logger.error(f"❌ fetch_kline 异常: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return -1
    
    def _call_legacy_kline(self, provider, code: str, period: str,
                           start: str, end: str, adjust: str, asset_type: str):
        """回退到旧的标准API接口"""
        if period == '1d':
            if asset_type == 'fund':
                return provider.fetch_fund_history_daily(code, start, end, adjust=adjust)
            else:
                return provider.fetch_stock_history_daily(code, start, end, adjust=adjust)
        else:
            period_num = period.rstrip('m')
            if asset_type == 'fund':
                return provider.fetch_fund_history_minute(code, period_num, start, end, adjust=adjust)
            else:
                return provider.fetch_stock_history_minute(code, period_num, start, end, adjust=adjust)
    
    def fetch_quote(self, code: str, asset_type: str = 'stock',
                    provider_name: Optional[str] = None) -> Any:
        """统一实时行情接口"""
        cap = f'{asset_type}_realtime'
        if provider_name:
            providers_to_try = [provider_name]
        else:
            providers_to_try = self.get_available_providers(cap)
        
        if not providers_to_try:
            self.logger.warning(f"⚠️ 没有数据源支持 {cap}")
            return -1
        
        for pname in providers_to_try:
            provider = self._get_provider(pname)
            if not provider:
                continue
            try:
                if hasattr(provider, 'fetch_quote'):
                    return provider.fetch_quote(code, asset_type=asset_type)
                elif asset_type == 'fund':
                    return provider.fetch_fund_realtime(code)
                else:
                    return provider.fetch_stock_realtime(code)
            except Exception as e:
                self.logger.error(f"❌ [{pname}] fetch_quote 失败: {e}")
                continue
        return -1
    
    def _count_rows(self, result: Any) -> int:
        """统计返回数据的行数（dict 视为单条记录）"""
        if isinstance(result, pd.DataFrame):
            return len(result)
        elif isinstance(result, list):
            return len(result)
        elif isinstance(result, dict):
            return 1 if result else 0
        return 0

    def _format_params(self, params: dict) -> str:
        """格式化参数用于日志输出"""
        if not params:
            return ""
        
        # 缩短长参数
        formatted = []
        for k, v in params.items():
            if isinstance(v, str) and len(v) > 20:
                formatted.append(f"{k}={v[:17]}...")
            else:
                formatted.append(f"{k}={v}")
        
        return ", ".join(formatted)
    
    def _update_stats(self, provider_name: str, success: bool, response_time: float = 0):
        """
        更新数据源调用统计
        
        Args:
            provider_name: 数据源名称
            success: 是否成功
            response_time: 响应时间（毫秒）
        """
        try:
            conn = self.db.get_conn()
            cursor = conn.cursor()
            
            if success:
                cursor.execute("""
                    UPDATE tb_datasource_registry
                    SET call_count = call_count + 1,
                        success_count = success_count + 1,
                        avg_response_time = CASE 
                            WHEN avg_response_time IS NULL THEN ?
                            ELSE (avg_response_time * success_count + ?) / (success_count + 1)
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE provider_name = ?
                """, (response_time, response_time, provider_name))
            else:
                cursor.execute("""
                    UPDATE tb_datasource_registry
                    SET call_count = call_count + 1,
                        fail_count = fail_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE provider_name = ?
                """, (provider_name,))
            
            conn.commit()
        
        except Exception as e:
            self.logger.debug(f"更新统计信息失败: {e}")
    
    def get_stats(self, provider_name: Optional[str] = None) -> Union[dict, List[dict]]:
        """
        获取数据源统计信息
        
        Args:
            provider_name: 数据源名称，为None时返回所有
        
        Returns:
            统计信息字典或列表
        """
        try:
            if provider_name:
                rows = self.db.execute_query(
                    """SELECT provider_name, display_name, call_count, success_count, 
                              fail_count, avg_response_time 
                       FROM tb_datasource_registry 
                       WHERE provider_name = ?""",
                    (provider_name,)
                )
                if not rows:
                    return {}
                return rows[0]
            else:
                rows = self.db.execute_query(
                    """SELECT provider_name, display_name, call_count, success_count, 
                              fail_count, avg_response_time, priority
                       FROM tb_datasource_registry 
                       WHERE enabled = 1
                       ORDER BY priority"""
                )
                return rows
        
        except Exception as e:
            self.logger.error(f"获取统计信息失败: {e}")
            return [] if provider_name is None else {}
    
    def list_providers(self) -> List[dict]:
        """
        列出所有已注册的数据源
        
        Returns:
            数据源信息列表
        """
        return [
            {
                'provider_name': p['provider_name'],
                'display_name': p['display_name'],
                'enabled': p['enabled'],
                'priority': p['priority'],
                'capabilities': [
                    api_id for api_id in self.API_METHODS.keys()
                    if p.get(f'capability_{api_id}')
                ]
            }
            for p in self.registry
        ]
    
    def _build_capability_dict(self, row: dict) -> dict:
        """将数据库行转换为12API能力字典"""
        return {
            'provider': row['provider_name'],
            'display_name': row['display_name'],
            'enabled': row['enabled'],
            'api01': row.get('capability_api01', False),
            'api02': row.get('capability_api02', False),
            'api03': row.get('capability_api03', False),
            'api04': row.get('capability_api04', False),
            'api05': row.get('capability_api05', False),
            'api06': row.get('capability_api06', False),
            'api07': row.get('capability_api07', False),
            'api08': row.get('capability_api08', False),
            'api09': row.get('capability_api09', False),
            'api10': row.get('capability_api10', False),
            'api11': row.get('capability_api11', False),
            'api12': row.get('capability_api12', False),
        }

    def get_capability_matrix(self) -> List[dict]:
        """
        获取12API × N数据源 完整能力矩阵
        直接从数据库读取（含已禁用的数据源），确保矩阵完整

        Returns:
            List[dict]: 每个数据源的能力信息
        """
        try:
            rows = self.db.execute_query(
                "SELECT * FROM tb_datasource_registry ORDER BY priority"
            )
            return [self._build_capability_dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"获取能力矩阵失败: {e}")
            return [self._build_capability_dict(p) for p in self.registry]

    def get_provider_capabilities(self, provider_name: str) -> Optional[dict]:
        """
        获取单个数据源的12API能力

        Args:
            provider_name: 数据源名称

        Returns:
            dict 或 None: 能力信息
        """
        try:
            rows = self.db.execute_query(
                "SELECT * FROM tb_datasource_registry WHERE provider_name = ?",
                (provider_name,)
            )
            if not rows:
                return None
            return self._build_capability_dict(rows[0])
        except Exception as e:
            self.logger.error(f"获取数据源能力失败: {e}")
            provider_info = next(
                (p for p in self.registry if p['provider_name'] == provider_name),
                None
            )
            if not provider_info:
                return None
            return self._build_capability_dict(provider_info)

    def _set_provider_enabled(self, provider_name: str, enabled: bool) -> bool:
        """启用或禁用数据源"""
        try:
            r = self.db.execute("""
                UPDATE tb_datasource_registry
                SET enabled = ?, updated_at = CURRENT_TIMESTAMP
                WHERE provider_name = ?
            """, (enabled, provider_name))
            affected = r.rowcount
            if affected == 0:
                self.logger.warning(f"数据源不存在: {provider_name}")
                return False
            status = "启用" if enabled else "禁用"
            self.logger.info(f"数据源已{status}: {provider_name}")
            for p in self.registry:
                if p['provider_name'] == provider_name:
                    p['enabled'] = enabled
                    break
            self.providers.pop(provider_name, None)
            return True
        except Exception as e:
            self.logger.error(f"设置数据源状态失败: {e}")
            return False

    def enable_provider(self, provider_name: str) -> bool:
        """启用数据源"""
        return self._set_provider_enabled(provider_name, True)

    def disable_provider(self, provider_name: str) -> bool:
        """禁用数据源"""
        return self._set_provider_enabled(provider_name, False)
    
    def reload(self):
        """重新加载注册表（用于配置变更后）"""
        self.logger.info("重新加载数据源注册表...")
        self.providers.clear()
        self._load_registry()


# ========== 全局单例 ==========
_registry_instance = None


def get_registry() -> DataSourceRegistry:
    """
    获取数据源注册表单例
    
    Returns:
        DataSourceRegistry实例
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = DataSourceRegistry()
    return _registry_instance


# ========== 便捷函数 ==========
def call_api(api_id: str, provider_name: Optional[str] = None, **kwargs):
    """
    便捷调用函数
    
    Examples:
        from stockpush.src_mgr.data_source_registry import call_api
        
        # 获取股票历史日线
        df = call_api('api01', code='000001', start='2024-01-01', end='2024-02-01')
        
        # 获取股票实时行情
        quote = call_api('api03', code='000001')
        
        # 获取股票列表（指定数据源）
        stocks = call_api('api09', provider_name='byapi')
    """
    registry = get_registry()
    return registry.call(api_id, provider_name, **kwargs)
