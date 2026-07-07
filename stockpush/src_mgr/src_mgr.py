"""
数据源管理服务
提供数据源状态管理、能力筛选、数据接入接口封装
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
from stockpush.log_manager import LogManager
from .data_source_registry import get_registry
from .src_provider import BaseProvider


class SrcMgrService:
    """
    数据源管理服务
    负责数据源状态管理、能力筛选、数据接入
    """
    
    def __init__(self):
        """初始化数据源管理服务（使用 PostgreSQL 默认连接）"""
        self.logger = LogManager().get_logger('src_mgr')
        
        # 数据源实例缓存
        self._providers: Dict[str, BaseProvider] = {}
        
        # DataSourceRegistry 单例
        self.registry = get_registry()
        
        # 初始化Provider实例
        self._init_providers()
        
        self.logger.info("数据源管理服务初始化完成")
    
    def _init_providers(self):
        """从 DataSourceRegistry 动态加载 Provider 实例"""
        try:
            registry = get_registry()
            for item in registry.registry:
                pname = item['provider_name']
                try:
                    self._providers[pname] = registry._get_provider(pname)
                    self.logger.info(f"{item['display_name']} Provider 已加载")
                except Exception as e:
                    self.logger.warning(f"{item['display_name']} Provider 加载失败: {e}")
        except Exception as e:
            self.logger.warning(f"从注册表加载 Provider 失败，使用备用初始化: {e}")
            self._init_providers_fallback()

    def _init_providers_fallback(self):
        """备用初始化：当注册表不可用时使用硬编码"""
        try:
            from .src_provider import ByapiProvider
            self._providers['byapi'] = ByapiProvider()
        except Exception as e:
            self.logger.warning(f"Byapi Provider 加载失败: {e}")
        try:
            from .xtick_provider import XTickProvider
            self._providers['xtick'] = XTickProvider()
        except Exception as e:
            self.logger.warning(f"XTick Provider 加载失败: {e}")
    
    def _get_conn(self):
        """获取数据库连接"""
        from stockpush.pg_connector import PGConnector
        return PGConnector()
    
    # ========== 数据源状态管理接口 ==========
    
    def get_provider_status(self, provider: str) -> Optional[Dict[str, Any]]:
        """
        获取数据源状态
        
        Args:
            provider: 数据源名称 'byapi' / 'xtick'
        
        Returns:
            Dict 或 None: 状态信息
                {
                    'id': int,
                    'provider': str,
                    'is_active': bool,
                    'last_update': datetime,
                    'status_msg': str,
                    'updated_at': datetime
                }
        """
        provider = provider.lower()
        
        try:
            conn = self._get_conn()
            
            result = conn.execute(
                "SELECT * FROM tb_src_status WHERE provider = ?",
                (provider,)
            ).fetchone()
            
            conn.close()
            
            if result is None:
                self.logger.warning(f"数据源 {provider} 不存在于数据库")
                return None
            
            # 转换为字典
            columns = ['id', 'provider', 'is_active', 'last_update', 'status_msg', 'updated_at']
            status = dict(zip(columns, result))
            
            # 兼容字段名（L2文档中使用status）
            status['status'] = 'active' if status['is_active'] else 'inactive'
            
            self.logger.info(f"获取数据源状态: {provider} -> {status['status']}")
            return status
            
        except Exception as e:
            self.logger.error(f"获取数据源状态失败: {e}")
            raise
    
    def enable_provider(self, provider: str) -> bool:
        """
        启用数据源
        
        Args:
            provider: 数据源名称
        
        Returns:
            bool: 是否成功
        """
        provider = provider.lower()
        
        # 不再使用硬编码的白名单，允许启用任意 provider 名称（以便注册新数据源）
        
        try:
            conn = self._get_conn()
            
            # 检查记录是否存在
            exists = conn.execute(
                "SELECT COUNT(*) FROM tb_src_status WHERE provider = ?",
                (provider,)
            ).fetchone()[0]
            
            if exists:
                # 更新状态
                conn.execute(
                    """
                    UPDATE tb_src_status 
                    SET is_active = TRUE,
                        status_msg = 'enabled',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE provider = ?
                    """,
                    (provider,)
                )
            else:
                # 插入新记录
                # 获取下一个ID
                max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM tb_src_status").fetchone()[0]
                new_id = max_id + 1
                
                conn.execute(
                    """
                    INSERT INTO tb_src_status (id, provider, is_active, status_msg, updated_at)
                    VALUES (?, ?, TRUE, 'enabled', CURRENT_TIMESTAMP)
                    """,
                    (new_id, provider)
                )
            
            conn.close()
            
            self.logger.info(f"数据源已启用: {provider}")
            return True
            
        except Exception as e:
            self.logger.error(f"启用数据源失败: {e}")
            raise
    
    def disable_provider(self, provider: str) -> bool:
        """
        禁用数据源
        
        Args:
            provider: 数据源名称
        
        Returns:
            bool: 是否成功
        """
        provider = provider.lower()
        
        # 允许禁用任意已记录的数据源（移除硬编码白名单）
        
        try:
            conn = self._get_conn()
            
            # 更新状态
            conn.execute(
                """
                UPDATE tb_src_status 
                SET is_active = FALSE,
                    status_msg = 'disabled',
                    updated_at = CURRENT_TIMESTAMP
                WHERE provider = ?
                """,
                (provider,)
            )
            
            conn.close()
            
            self.logger.info(f"数据源已禁用: {provider}")
            return True
            
        except Exception as e:
            self.logger.error(f"禁用数据源失败: {e}")
            raise
    
    def update_provider_status(self, provider: str, status_msg: str, last_update: Optional[datetime] = None) -> bool:
        """
        更新数据源状态信息
        
        Args:
            provider: 数据源名称
            status_msg: 状态消息
            last_update: 最后更新时间，默认当前时间
        
        Returns:
            bool: 是否成功
        """
        provider = provider.lower()
        
        if last_update is None:
            last_update = datetime.now()
        
        try:
            conn = self._get_conn()
            
            conn.execute(
                """
                UPDATE tb_src_status 
                SET status_msg = ?,
                    last_update = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE provider = ?
                """,
                (status_msg, last_update, provider)
            )
            
            conn.close()
            
            self.logger.info(f"数据源状态已更新: {provider} -> {status_msg}")
            return True
            
        except Exception as e:
            self.logger.error(f"更新数据源状态失败: {e}")
            raise
    
    def get_all_provider_status(self) -> List[Dict[str, Any]]:
        """
        获取所有数据源状态
        
        Returns:
            List[Dict]: 所有数据源状态列表
        """
        try:
            conn = self._get_conn()
            
            results = conn.execute("SELECT * FROM tb_src_status ORDER BY id").fetchall()
            
            conn.close()
            
            columns = ['id', 'provider', 'is_active', 'last_update', 'status_msg', 'updated_at']
            status_list = []
            
            for result in results:
                status = dict(zip(columns, result))
                status['status'] = 'active' if status['is_active'] else 'inactive'
                status_list.append(status)
            
            self.logger.info(f"获取所有数据源状态，共 {len(status_list)} 个")
            return status_list
            
        except Exception as e:
            self.logger.error(f"获取所有数据源状态失败: {e}")
            raise
    
    # ========== 能力检测与筛选接口 ==========
    
    def check_capability(self, provider: str, capability: str) -> bool:
        """
        检查数据源能力
        
        Args:
            provider: 数据源名称
            capability: 能力标识
        
        Returns:
            bool: 是否支持
        """
        provider = provider.lower()
        
        if provider not in self._providers:
            self.logger.warning(f"数据源 {provider} 未加载")
            return False
        
        provider_instance = self._providers[provider]
        if hasattr(provider_instance, 'check_capability'):
            return provider_instance.check_capability(capability)
        return False
    
    def get_available_providers(self, capability: str, only_active: bool = True) -> List[str]:
        """
        获取支持指定能力的数据源列表
        
        Args:
            capability: 能力标识，如 'stock_realtime', 'stock_daily'
            only_active: 是否只返回已启用的数据源
        
        Returns:
            List[str]: 支持该能力的数据源列表
        """
        available = []
        
        for provider_name, provider_instance in self._providers.items():
            # 检查能力
            if not provider_instance.check_capability(capability):
                continue
            
            # 检查激活状态
            if only_active:
                status = self.get_provider_status(provider_name)
                if status is None or not status['is_active']:
                    continue
            
            available.append(provider_name)
        
        self.logger.info(f"支持 {capability} 的数据源: {available}")
        return available
    
    def get_provider_instance(self, provider: str) -> Optional[BaseProvider]:
        """
        获取Provider实例
        
        Args:
            provider: 数据源名称
        
        Returns:
            BaseProvider 或 None
        """
        provider = provider.lower()
        return self._providers.get(provider)
    
    # ========== 数据接入接口 ==========
    
    def fetch_data(self, provider: str, data_type: str, **kwargs) -> Any:
        """
        统一数据获取接口
        优先使用 fetch_kline/fetch_quote，回退到 call(api_id)
        """
        provider = provider.lower()
        code = kwargs.get('code', '')
        start = kwargs.get('start', '')
        end = kwargs.get('end', '')
        start_date = kwargs.get('start_date', start)
        end_date = kwargs.get('end_date', end)

        realtime_types = {'stock_realtime', 'stock_realtime_minute', 'fund_realtime', 'fund_realtime_minute'}
        daily_types = {'stock_daily', 'fund_daily'}
        minute_types = {
            'stock_1min', 'stock_5min', 'stock_15min', 'stock_30min', 'stock_60min',
            'fund_1min', 'fund_5min', 'fund_15min', 'fund_30min', 'fund_60min',
        }

        if data_type in realtime_types:
            asset_type = 'fund' if data_type.startswith('fund') else 'stock'
            return self.registry.fetch_quote(code, asset_type=asset_type, provider_name=provider)

        if data_type in daily_types or data_type in minute_types:
            asset_type = 'fund' if data_type.startswith('fund') else 'stock'
            if data_type in daily_types:
                period = '1d'
            else:
                period_num = kwargs.get('period', '')
                if not period_num:
                    period_num = data_type.split('_')[-1]
                period = period_num + 'm' if not period_num.endswith('m') else period_num
                if period in ('1m', '5m', '15m', '30m', '60m'):
                    pass
                else:
                    period = period_num.replace('m', '') + 'm' if 'm' not in period_num else period_num
            return self.registry.fetch_kline(
                code=code, period=period, start=start_date, end=end_date,
                adjust='qfq', asset_type=asset_type, provider_name=provider
            )

        # 回退到旧 call 接口
        type_to_api = {
            'stock_daily': 'api01', 'stock_1min': 'api02', 'stock_5min': 'api02',
            'stock_15min': 'api02', 'stock_30min': 'api02', 'stock_60min': 'api02',
            'stock_realtime': 'api03', 'stock_realtime_minute': 'api04',
            'fund_daily': 'api05', 'fund_1min': 'api06', 'fund_5min': 'api06',
            'fund_15min': 'api06', 'fund_30min': 'api06', 'fund_60min': 'api06',
            'fund_realtime': 'api07', 'fund_realtime_minute': 'api08',
            'stock_list': 'api09', 'fund_list': 'api10',
            'trade_calendar': 'api11',
        }
        api_id = type_to_api.get(data_type)
        if not api_id:
            self.logger.error(f"不支持的数据类型: {data_type}")
            return -1
        call_kwargs = {}
        if api_id in ('api01', 'api05'):
            call_kwargs = {'code': code, 'start': start, 'end': end}
        elif api_id in ('api02', 'api06'):
            period_num = kwargs.get('period', '5')
            call_kwargs = {'code': code, 'period': period_num, 'start': start, 'end': end}
        elif api_id in ('api03', 'api04', 'api07', 'api08'):
            call_kwargs = {'code': code}
        return self.registry.call(api_id, provider_name=provider, **call_kwargs)
