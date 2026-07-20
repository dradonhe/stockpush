"""
数据源对比服务

提供双数据源历史数据对比、五维度校验、综合评分等功能
"""

from typing import List, Dict, Optional, Any, Tuple
import uuid
import json
import re
from datetime import datetime
from concurrent import futures
import numpy as np

from stockpush.pg_connector import PGConnector
from stockpush.log_manager import LogManager


# ==================== 异常类定义 ====================

class ComparatorError(Exception):
    """对比服务基础异常"""
    pass


class DataSourceError(ComparatorError):
    """数据源错误（连接失败、认证失败等）"""
    pass


class NoDataError(ComparatorError):
    """无数据返回错误"""
    pass


class ValidationError(ComparatorError):
    """参数验证错误"""
    pass


class IncompleteDataError(ComparatorError):
    """数据不完整错误"""
    pass


# ==================== 核心服务类 ====================

class SourceComparatorService:
    """数据源对比服务"""
    
    def __init__(self, db_connector=None):
        """
        初始化数据源对比服务
        
        Args:
            db_connector: PGConnector 实例，如无则使用 PostgreSQL 默认连接
        """
        if db_connector is not None:
            self.db_connector = db_connector
        else:
            from stockpush.pg_connector import PGConnector
            self.db_connector = PGConnector()
        self.logger = LogManager().get_logger("SourceComparator")
        self._init_table()
    
    def fetch_data_for_comparison(self, provider: str, api_id: str, **kwargs) -> Any:
        """获取数据用于对比（使用 DataSourceRegistry）"""
        from stockpush.src_mgr.data_source_registry import get_registry
        
        registry = get_registry()
        
        provider_info = next(
            (p for p in registry.registry if p['provider_name'] == provider),
            None
        )
        if not provider_info:
            raise ValueError(f"数据源不存在: {provider}")
        
        cap_field = f'capability_{api_id}'
        if not provider_info.get(cap_field):
            raise ValueError(f"[{provider}] 不支持 {api_id}")
        
        return registry.call(api_id, provider_name=provider, **kwargs)
    
    def _init_table(self) -> None:
        """初始化tb_compare_log表结构"""
        # 创建序列
        create_seq_sql = "CREATE SEQUENCE IF NOT EXISTS tb_compare_log_id_seq START 1"
        
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS tb_compare_log (
            id INTEGER PRIMARY KEY DEFAULT nextval('tb_compare_log_id_seq'),
            compare_id VARCHAR(50) NOT NULL UNIQUE,
            source_a VARCHAR(20) NOT NULL,
            source_b VARCHAR(20) NOT NULL,
            asset_type VARCHAR(10) NOT NULL,
            symbol VARCHAR(10) NOT NULL,
            period VARCHAR(10) NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            result_json TEXT NOT NULL,
            total_score DECIMAL(5,2),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            error_msg TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
        """
        
        # 创建索引
        create_idx_compare_id = """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_compare_id 
        ON tb_compare_log(compare_id)
        """
        
        create_idx_symbol_period = """
        CREATE INDEX IF NOT EXISTS idx_symbol_period 
        ON tb_compare_log(symbol, period)
        """
        
        create_idx_sources = """
        CREATE INDEX IF NOT EXISTS idx_sources 
        ON tb_compare_log(source_a, source_b)
        """
        
        create_idx_created_at = """
        CREATE INDEX IF NOT EXISTS idx_created_at 
        ON tb_compare_log(created_at)
        """
        
        try:
            self.db_connector.execute_update(create_seq_sql)
            self.db_connector.execute_update(create_table_sql)
            self.db_connector.execute_update(create_idx_compare_id)
            self.db_connector.execute_update(create_idx_symbol_period)
            self.db_connector.execute_update(create_idx_sources)
            self.db_connector.execute_update(create_idx_created_at)
            self.logger.info("tb_compare_log表初始化完成")
        except Exception as e:
            self.logger.error(f"tb_compare_log表初始化失败: {e}", exc_info=True)
            raise ComparatorError(f"表初始化失败: {e}")
    
    # ==================== 行级对比（按时间对齐逐条对比）====================
    
    def _align_and_compare_by_row(
        self,
        data_a: List[Dict],
        data_b: List[Dict],
        price_threshold: float = 1.0
    ) -> Dict[str, Any]:
        """
        按时间对齐，逐条记录对比
        
        实现新的行级对比策略：按时间排序，逐条对比两个数据源的数据
        
        Args:
            data_a: 数据源A的数据列表
            data_b: 数据源B的数据列表
            price_threshold: 价格差异阈值（%）
        
        Returns:
            {
                'matched_rows': int,           # 匹配的行数
                'only_in_a': int,              # 仅在A中的行数
                'only_in_b': int,              # 仅在B中的行数
                'mismatched_count': int,       # 价格不一致的行数
                'row_details': [               # 前50条行级对比结果
                    {
                        'date': str,           # 时间/日期
                        'status': str,         # 'matched', 'only_in_a', 'only_in_b', 'mismatch'
                        'a_close': float,      # A的收盘价
                        'b_close': float,      # B的收盘价
                        'diff_pct': float      # 价格差异百分比
                    }
                ]
            }
        """
        # 按时间戳构建字典
        data_a_dict = {item['ts']: item for item in data_a}
        data_b_dict = {item['ts']: item for item in data_b}
        
        all_ts = sorted(set(data_a_dict.keys()) | set(data_b_dict.keys()), reverse=True)
        
        matched_rows = 0
        only_in_a = 0
        only_in_b = 0
        mismatched_count = 0
        row_details = []
        
        for ts in all_ts:
            item_a = data_a_dict.get(ts)
            item_b = data_b_dict.get(ts)
            
            # 提取日期时间（用于显示）
            try:
                from datetime import datetime
                date_str = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                date_str = str(ts)
            
            if item_a and item_b:
                # 两边都有数据
                matched_rows += 1
                close_a = float(item_a.get('close', 0))
                close_b = float(item_b.get('close', 0))
                
                if close_a > 0:
                    diff_pct = abs((close_b - close_a) / close_a * 100)
                else:
                    diff_pct = 0
                
                status = 'matched' if diff_pct <= price_threshold else 'mismatch'
                if status == 'mismatch':
                    mismatched_count += 1
                
                row_details.append({
                    'date': date_str,
                    'status': status,
                    'a_close': round(close_a, 2),
                    'b_close': round(close_b, 2),
                    'diff_pct': round(diff_pct, 2)
                })
            
            elif item_a:
                # 仅在A中
                only_in_a += 1
                row_details.append({
                    'date': date_str,
                    'status': 'only_in_a',
                    'a_close': round(float(item_a.get('close', 0)), 2),
                    'b_close': None,
                    'diff_pct': None
                })
            
            else:
                # 仅在B中
                only_in_b += 1
                row_details.append({
                    'date': date_str,
                    'status': 'only_in_b',
                    'a_close': None,
                    'b_close': round(float(item_b.get('close', 0)), 2),
                    'diff_pct': None
                })
        
        return {
            'matched_rows': matched_rows,
            'only_in_a': only_in_a,
            'only_in_b': only_in_b,
            'mismatched_count': mismatched_count,
            'row_details': row_details[:50]  # 仅返回前50条
        }
    
    # ==================== 五维度校验算法 ====================
    
    def _check_completeness(
        self, 
        data_a: List[Dict], 
        data_b: List[Dict],
        expected_days: int
    ) -> Dict[str, Any]:
        """
        数据完整性校验（维度1）
        
        Args:
            data_a: 数据源A的数据列表
            data_b: 数据源B的数据列表
            expected_days: 预期数据天数（根据时间范围和周期计算）
            
        Returns:
            {
                'total_records_a': int,
                'total_records_b': int,
                'missing_in_a': List[str],  # 仅B存在的时间戳
                'missing_in_b': List[str],  # 仅A存在的时间戳
                'coverage_rate_a': float,   # 覆盖率%
                'coverage_rate_b': float,
                'score': float  # 0-30分
            }
        """
        # 提取时间戳
        ts_a = set([item['ts'] for item in data_a])
        ts_b = set([item['ts'] for item in data_b])
        
        # 计算差集
        missing_in_a = list(ts_b - ts_a)
        missing_in_b = list(ts_a - ts_b)
        
        # 计算覆盖率
        total_a = len(data_a)
        total_b = len(data_b)
        
        coverage_rate_a = (total_a / expected_days * 100) if expected_days > 0 else 0
        coverage_rate_b = (total_b / expected_days * 100) if expected_days > 0 else 0
        
        # 计算得分（满分30分）
        # 规则：覆盖率越高得分越高，缺失记录越多扣分越多
        avg_coverage = (coverage_rate_a + coverage_rate_b) / 2
        total_records = total_a + total_b
        missing_ratio = (len(missing_in_a) + len(missing_in_b)) / total_records if total_records > 0 else 0
        
        score = 30 * (min(avg_coverage, 100) / 100) * (1 - missing_ratio * 0.5)
        score = max(0, min(30, score))  # 限制在0-30范围
        
        return {
            'total_records_a': total_a,
            'total_records_b': total_b,
            'missing_in_a': missing_in_a[:10],  # 仅返回前10条示例
            'missing_in_b': missing_in_b[:10],
            'coverage_rate_a': round(coverage_rate_a, 2),
            'coverage_rate_b': round(coverage_rate_b, 2),
            'score': round(score, 2)
        }
    
    def _check_consistency(
        self, 
        data_a: List[Dict], 
        data_b: List[Dict],
        threshold: float = 1.0
    ) -> Dict[str, Any]:
        """
        数值一致性校验（维度2）
        
        NOTE: 不对比成交量，因为不同数据源的成交量单位可能不一致
        
        Args:
            data_a: 数据源A的数据列表
            data_b: 数据源B的数据列表
            threshold: 异常偏差阈值（%），默认1%
            
        Returns:
            {
                'avg_price_deviation': float,  # 均价偏差%
                'max_price_deviation': float,  # 最大价格偏差%
                'avg_vol_deviation': float,    # 成交量偏差%（已禁用，总为0）
                'outlier_count': int,          # 异常记录数
                'outlier_ratio': float,        # 异常记录占比%
                'score': float                 # 0-40分
            }
        """
        # 按时间戳对齐数据
        data_a_dict = {item['ts']: item for item in data_a}
        data_b_dict = {item['ts']: item for item in data_b}
        
        common_ts = set(data_a_dict.keys()) & set(data_b_dict.keys())
        
        if not common_ts:
            return {
                'avg_price_deviation': 0,
                'max_price_deviation': 0,
                'avg_vol_deviation': 0,
                'outlier_count': 0,
                'outlier_ratio': 0,
                'score': 0
            }
        
        price_deviations = []
        outlier_count = 0
        
        for ts in common_ts:
            item_a = data_a_dict[ts]
            item_b = data_b_dict[ts]
            
            # 计算价格偏差（以close为主）
            close_a = float(item_a.get('close', 0))
            close_b = float(item_b.get('close', 0))
            
            if close_a > 0:
                price_dev = abs((close_b - close_a) / close_a * 100)
                price_deviations.append(price_dev)
                
                if price_dev > threshold:
                    outlier_count += 1
        
        # 统计
        avg_price_dev = sum(price_deviations) / len(price_deviations) if price_deviations else 0
        max_price_dev = max(price_deviations) if price_deviations else 0
        outlier_ratio = (outlier_count / len(common_ts) * 100) if common_ts else 0
        
        # 计算得分（满分40分）
        # 规则：偏差越小得分越高，异常值越少得分越高
        price_score = 40 * (1 - min(avg_price_dev / 10, 1))  # 10%偏差扣完
        outlier_penalty = outlier_ratio * 0.2  # 异常占比扣分
        
        score = max(0, price_score - outlier_penalty)
        
        return {
            'avg_price_deviation': round(avg_price_dev, 2),
            'max_price_deviation': round(max_price_dev, 2),
            'avg_vol_deviation': 0,  # 禁用成交量对比（单位不一致）
            'outlier_count': outlier_count,
            'outlier_ratio': round(outlier_ratio, 2),
            'score': round(score, 2)
        }
    
    def _check_time_alignment(
        self, 
        data_a: List[Dict], 
        data_b: List[Dict]
    ) -> Dict[str, Any]:
        """
        时间对齐性校验（维度3）
        
        Returns:
            {
                'time_format_match': bool,
                'invalid_timestamps_a': List[str],
                'invalid_timestamps_b': List[str],
                'time_gap_anomalies': List[str],
                'alignment_rate': float,
                'score': float  # 0-20分
            }
        """
        # 检查时间格式
        time_format_regex = r'^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$'
        
        invalid_ts_a = []
        invalid_ts_b = []
        
        for item in data_a:
            ts = item.get('ts', '')
            if not re.match(time_format_regex, ts):
                invalid_ts_a.append(ts)
        
        for item in data_b:
            ts = item.get('ts', '')
            if not re.match(time_format_regex, ts):
                invalid_ts_b.append(ts)
        
        time_format_match = (len(invalid_ts_a) == 0 and len(invalid_ts_b) == 0)
        
        # 计算对齐率
        ts_a = set([item['ts'] for item in data_a])
        ts_b = set([item['ts'] for item in data_b])
        common_ts = ts_a & ts_b
        total_ts = ts_a | ts_b
        
        alignment_rate = (len(common_ts) / len(total_ts) * 100) if total_ts else 0
        
        # 计算得分（满分20分）
        score = 20 if time_format_match else 10
        score *= (alignment_rate / 100)
        
        return {
            'time_format_match': time_format_match,
            'invalid_timestamps_a': invalid_ts_a[:10],
            'invalid_timestamps_b': invalid_ts_b[:10],
            'time_gap_anomalies': [],  # 简化实现
            'alignment_rate': round(alignment_rate, 2),
            'score': round(score, 2)
        }
    
    def _detect_anomalies(
        self, 
        data_a: List[Dict], 
        data_b: List[Dict]
    ) -> Dict[str, Any]:
        """
        异常值检测（维度4）
        
        Returns:
            {
                'extreme_change_a': List[Dict],
                'extreme_change_b': List[Dict],
                'zero_value_a': int,
                'zero_value_b': int,
                'negative_value_a': int,
                'negative_value_b': int,
                'score': float  # 0-20分
            }
        """
        extreme_threshold = 20  # 涨跌幅超过±20%视为异常
        
        extreme_a = []
        extreme_b = []
        zero_a = 0
        zero_b = 0
        negative_a = 0
        negative_b = 0
        
        # 检查数据源A
        for i in range(1, len(data_a)):
            prev_close = float(data_a[i-1].get('close', 0))
            curr_close = float(data_a[i].get('close', 0))
            
            if curr_close == 0:
                zero_a += 1
            if curr_close < 0:
                negative_a += 1
            
            if prev_close > 0:
                change_pct = (curr_close - prev_close) / prev_close * 100
                if abs(change_pct) > extreme_threshold:
                    extreme_a.append({'ts': data_a[i]['ts'], 'change_pct': round(change_pct, 2)})
        
        # 检查数据源B
        for i in range(1, len(data_b)):
            prev_close = float(data_b[i-1].get('close', 0))
            curr_close = float(data_b[i].get('close', 0))
            
            if curr_close == 0:
                zero_b += 1
            if curr_close < 0:
                negative_b += 1
            
            if prev_close > 0:
                change_pct = (curr_close - prev_close) / prev_close * 100
                if abs(change_pct) > extreme_threshold:
                    extreme_b.append({'ts': data_b[i]['ts'], 'change_pct': round(change_pct, 2)})
        
        # 计算得分（满分20分）
        total_anomalies = len(extreme_a) + len(extreme_b) + zero_a + zero_b + negative_a + negative_b
        total_records = len(data_a) + len(data_b)
        anomaly_ratio = (total_anomalies / total_records) if total_records > 0 else 0
        
        score = 20 * (1 - min(anomaly_ratio * 5, 1))  # 异常占比每5%扣20分
        
        return {
            'extreme_change_a': extreme_a[:10],
            'extreme_change_b': extreme_b[:10],
            'zero_value_a': zero_a,
            'zero_value_b': zero_b,
            'negative_value_a': negative_a,
            'negative_value_b': negative_b,
            'score': round(score, 2)
        }
    
    def _compare_statistics(
        self, 
        data_a: List[Dict], 
        data_b: List[Dict]
    ) -> Dict[str, Any]:
        """
        统计特征对比（维度5）
        
        Returns:
            {
                'price_mean_a': float,
                'price_mean_b': float,
                'price_std_a': float,
                'price_std_b': float,
                'correlation_close': float,
                'correlation_vol': float,
                'similarity_score': float,
                'score': float  # 0-10分
            }
        """
        try:
            # 提取价格序列
            prices_a = [float(item.get('close', 0)) for item in data_a]
            prices_b = [float(item.get('close', 0)) for item in data_b]
            
            # 按时间戳对齐
            data_a_dict = {item['ts']: item for item in data_a}
            data_b_dict = {item['ts']: item for item in data_b}
            common_ts = sorted(set(data_a_dict.keys()) & set(data_b_dict.keys()))
            
            aligned_prices_a = [float(data_a_dict[ts].get('close', 0)) for ts in common_ts]
            aligned_prices_b = [float(data_b_dict[ts].get('close', 0)) for ts in common_ts]
            
            aligned_vols_a = [float(data_a_dict[ts].get('vol', 0)) for ts in common_ts]
            aligned_vols_b = [float(data_b_dict[ts].get('vol', 0)) for ts in common_ts]
            
            # 计算统计量
            price_mean_a = np.mean(prices_a) if prices_a else 0
            price_mean_b = np.mean(prices_b) if prices_b else 0
            price_std_a = np.std(prices_a) if prices_a else 0
            price_std_b = np.std(prices_b) if prices_b else 0
            
            # 计算相关系数
            if len(aligned_prices_a) > 1:
                correlation_close = float(np.corrcoef(aligned_prices_a, aligned_prices_b)[0, 1])
                correlation_vol = float(np.corrcoef(aligned_vols_a, aligned_vols_b)[0, 1])
            else:
                correlation_close = 0
                correlation_vol = 0
            
            # 处理NaN值
            if np.isnan(correlation_close):
                correlation_close = 0
            if np.isnan(correlation_vol):
                correlation_vol = 0
            
            # 计算相似度得分（0-100）
            # 相关系数范围[-1, 1]，我们将其映射到[0, 100]
            # 方法：(corr + 1) / 2 * 100，即corr=1时为100，corr=0时为50，corr=-1时为0
            similarity_close = (correlation_close + 1) / 2 * 100
            similarity_vol = (correlation_vol + 1) / 2 * 100
            similarity_score = (similarity_close + similarity_vol) / 2
            
            # 计算得分（满分10分）
            score = 10 * (similarity_score / 100)
            
            # 确保得分在0-10范围内
            score = max(0, min(10, score))
            
            return {
                'price_mean_a': round(float(price_mean_a), 2),
                'price_mean_b': round(float(price_mean_b), 2),
                'price_std_a': round(float(price_std_a), 2),
                'price_std_b': round(float(price_std_b), 2),
                'correlation_close': round(correlation_close, 4),
                'correlation_vol': round(correlation_vol, 4),
                'similarity_score': round(similarity_score, 2),
                'score': round(score, 2)
            }
        except Exception as e:
            self.logger.warning(f"统计特征对比失败: {e}")
            return {
                'price_mean_a': 0,
                'price_mean_b': 0,
                'price_std_a': 0,
                'price_std_b': 0,
                'correlation_close': 0,
                'correlation_vol': 0,
                'similarity_score': 0,
                'score': 0
            }
    
    # ==================== 参数验证与数据拉取 ====================
    
    def validate_compare_params(
        self,
        source_a: str,
        source_b: str,
        asset_type: str,
        period: str
    ) -> Tuple[bool, str]:
        """
        验证对比参数有效性
        
        Args:
            source_a: 数据源A
            source_b: 数据源B
            asset_type: 资产类型（stock/fund）
            period: 数据周期（1d/1m/5m等）
            
        Returns:
            (is_valid, error_message)
        """
        valid_sources = ['xtick']
        valid_asset_types = ['stock', 'fund']
        valid_periods = ['1d', '1m', '5m', '15m', '30m', '60m']
        
        if source_a not in valid_sources:
            return (False, f"数据源A无效: {source_a}")
        
        if source_b not in valid_sources:
            return (False, f"数据源B无效: {source_b}")
        
        if source_a == source_b:
            return (False, "数据源A和B不能相同")
        
        if asset_type not in valid_asset_types:
            return (False, f"资产类型无效: {asset_type}")
        
        if period not in valid_periods:
            return (False, f"数据周期无效: {period}")
        
        return (True, "")
    
    def _fetch_data_from_source(
        self,
        source_name: str,
        asset_type: str,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict]:
        """
        从指定数据源拉取数据（优先使用fetch_kline，回退到call接口）
        
        关键改进：先检查数据源能力矩阵，避免不必要的超时等待
        """
        try:
            from stockpush.src_mgr.data_source_registry import get_registry
            registry = get_registry()
            
            # 1. 先检查数据源是否支持该操作（快速失败）
            api_map = {
                '1d': 'api01' if asset_type == 'stock' else 'api05',
                '1m': 'api02' if asset_type == 'stock' else 'api06',
                '5m': 'api02' if asset_type == 'stock' else 'api06',
                '15m': 'api02' if asset_type == 'stock' else 'api06',
                '30m': 'api02' if asset_type == 'stock' else 'api06',
                '60m': 'api02' if asset_type == 'stock' else 'api06',
            }
            
            required_api = api_map.get(period)
            if not required_api:
                raise ValidationError(f"不支持的周期: {period}")
            
            # 查找该数据源的注册信息
            provider_info = next(
                (p for p in registry.registry if p['provider_name'] == source_name),
                None
            )
            
            if not provider_info:
                raise DataSourceError(f"数据源[{source_name}]未注册或不可用")
            
            # 检查能力矩阵
            capability_field = f'capability_{required_api}'
            if not provider_info.get(capability_field):
                raise DataSourceError(
                    f"数据源[{source_name}]不支持 {asset_type}/{period} 数据"
                    f"（能力矩阵检查失败）"
                )
            
            self.logger.debug(
                f"✅ [{source_name}] 能力矩阵检查通过: 支持 {asset_type}/{period}"
            )

            if period in ['1m', '5m', '15m', '30m', '60m', '1d']:
                kline_period = period
            else:
                kline_period = '1d'

            start_dt = start_date
            end_dt = end_date
            if kline_period != '1d':
                if len(start_dt) == 10:
                    start_dt = f"{start_dt} 00:00:00"
                if len(end_dt) == 10:
                    end_dt = f"{end_dt} 23:59:59"

            df = registry.fetch_kline(
                code=symbol, period=kline_period, start=start_dt, end=end_dt,
                adjust='qfq', asset_type=asset_type, provider_name=source_name
            )

            raise DataSourceError(f"数据源[{source_name}]不支持该能力或获取失败")

        except NoDataError:
            raise
        except DataSourceError:
            raise
        except ValidationError:
            raise
        except Exception as e:
            error_msg = str(e)
            if any(keyword in error_msg.lower() for keyword in ['timeout', 'connection', 'network', 'auth', 'licence', '503', '500']):
                raise DataSourceError(f"数据源[{source_name}]连接失败: {error_msg}")
            else:
                raise DataSourceError(f"数据源[{source_name}]错误: {error_msg}")
    
    def _classify_error(self, exception: Exception) -> str:
        """
        分类异常类型
        
        Returns:
            'CONNECTION_ERROR' | 'NO_DATA' | 'VALIDATION_ERROR' | 'TIMEOUT' | 'AUTH_ERROR' | 'UNKNOWN'
        """
        error_msg = str(exception).lower()
        
        # A类异常：连接失败
        if isinstance(exception, DataSourceError):
            if any(kw in error_msg for kw in ['不支持', 'unsupported', 'not supported']):
                return 'VALIDATION_ERROR'
            elif any(kw in error_msg for kw in ['数据不存在', '未获取到数据', 'no data', 'empty', '为空', '无数据']):
                return 'NO_DATA'
            elif any(kw in error_msg for kw in ['timeout', '超时']):
                return 'TIMEOUT'
            elif any(kw in error_msg for kw in ['auth', 'licence', 'token', '认证', '授权']):
                return 'AUTH_ERROR'
            elif any(kw in error_msg for kw in ['503', '500', 'unavailable', '不可用']):
                return 'SERVICE_UNAVAILABLE'
            else:
                return 'CONNECTION_ERROR'
        
        # B类异常：无数据
        elif isinstance(exception, NoDataError):
            return 'NO_DATA'
        
        # C类异常：数据不完整
        elif isinstance(exception, IncompleteDataError):
            return 'INCOMPLETE_DATA'
        
        # 参数错误
        elif isinstance(exception, ValidationError):
            return 'VALIDATION_ERROR'
        
        else:
            # 根据错误信息推断
            if any(kw in error_msg for kw in ['empty', '为空', 'no data', '无数据']):
                return 'NO_DATA'
            elif any(kw in error_msg for kw in ['network', 'connection', '网络', '连接']):
                return 'CONNECTION_ERROR'
            else:
                return 'UNKNOWN'
    
    def _calculate_expected_days(self, start_date: str, end_date: str, period: str) -> int:
        """
        计算预期数据天数
        
        简化实现：按自然日计算，实际应考虑交易日历
        """
        from datetime import datetime
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        days = (end - start).days + 1
        
        # 粗略估算交易日（去除周末）
        trading_days = int(days * 5 / 7)
        
        return trading_days
    
    def _generate_recommendation(
        self,
        total_score: float,
        completeness: Dict,
        consistency: Dict,
        statistics: Dict,
        source_a: str,
        source_b: str
    ) -> str:
        """
        生成推荐建议
        
        根据L1第12节定义的推荐规则
        """
        if total_score >= 90:
            return f"两源数据高度一致（相似度{statistics['similarity_score']}%），可互为主备份，建议优先使用{source_a}。"
        elif total_score >= 70:
            return f"两源数据基本一致，存在{consistency['avg_price_deviation']}%偏差，建议根据需求选择数据源。"
        elif total_score >= 50:
            return f"两源数据存在明显差异（偏差{consistency['avg_price_deviation']}%），建议谨慎使用，优先选择{source_a}。"
        else:
            return "两源数据严重不一致，建议排查数据源问题，或引入第三方数据源进行三方校验。"
    
    def _save_compare_log(
        self,
        compare_id: str,
        source_a: str,
        source_b: str,
        asset_type: str,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
        status: str = 'pending',
        result_json: str = '{}',
        total_score: float = None,
        error_msg: str = None
    ) -> None:
        """保存对比记录到数据库"""
        insert_sql = """
        INSERT INTO tb_compare_log 
        (compare_id, source_a, source_b, asset_type, symbol, period, 
         start_date, end_date, result_json, total_score, status, error_msg, 
         created_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, NULL)
        """
        
        self.db_connector.execute_update(
            insert_sql,
            (compare_id, source_a, source_b, asset_type, symbol, period,
             start_date, end_date, result_json, total_score, status, error_msg)
        )
    
    def _update_compare_log(
        self,
        compare_id: str,
        status: str = None,
        result_json: str = None,
        total_score: float = None,
        error_msg: str = None
    ) -> None:
        """更新对比记录"""
        # 确保 result_json 不为 None（满足 NOT NULL 约束）
        if result_json is None:
            result_json = '{}'
        
        update_sql = """
        UPDATE tb_compare_log
        SET status = ?, result_json = ?, total_score = ?, error_msg = ?, 
            completed_at = CURRENT_TIMESTAMP
        WHERE compare_id = ?
        """
        
        self.db_connector.execute_update(
            update_sql,
            (status, result_json, total_score, error_msg, compare_id)
        )
    
    # ==================== 核心对比接口 ====================
    
    def compare_history_data(
        self,
        source_a: str,
        source_b: str,
        asset_type: str,
        symbol: str,
        period: str,
        start_date: str,
        end_date: str,
        save_log: bool = True,
    ) -> Dict[str, Any]:
        """
        双源历史数据对比
        
        实现L1第5.1节定义的核心接口
        """
        compare_id = str(uuid.uuid4())
        
        try:
            # 1. 参数验证
            is_valid, error_msg = self.validate_compare_params(source_a, source_b, asset_type, period)
            if not is_valid:
                # 参数错误，直接返回失败结果
                error_result = {
                    'compare_id': compare_id,
                    'status': 'failed',
                    'error_msg': f'VALIDATION_ERROR: {error_msg}',
                    'source_a': source_a,
                    'source_b': source_b,
                    'asset_type': asset_type,
                    'symbol': symbol,
                    'period': period
                }
                if save_log:
                    self._save_compare_log(compare_id, source_a, source_b, asset_type, symbol,
                                          period, start_date, end_date, status='failed')
                    error_msg_json = json.dumps({'error': error_msg, 'type': 'VALIDATION_ERROR'})
                    self._update_compare_log(compare_id, status='failed', error_msg=error_msg_json)
                return error_result
            
            self.logger.info(f"开始对比任务: compare_id={compare_id}, {source_a} vs {source_b}, {symbol}")
            
            # 更新状态为running
            if save_log:
                self._save_compare_log(compare_id, source_a, source_b, asset_type, symbol, 
                                      period, start_date, end_date, status='running')
            
            # 2. 并行拉取数据（带安全的线程清理）
            data_a = None
            data_b = None
            error_a = None
            error_b = None
            
            executor = futures.ThreadPoolExecutor(max_workers=2)
            try:
                future_a = executor.submit(self._fetch_data_from_source, source_a, asset_type,
                                          symbol, period, start_date, end_date)
                future_b = executor.submit(self._fetch_data_from_source, source_b, asset_type,
                                          symbol, period, start_date, end_date)
                try:
                    data_a = future_a.result(timeout=60)
                except futures.TimeoutError:
                    error_a = {'type': 'timeout', 'message': '数据源A请求超时（>60秒）'}
                    self.logger.error(f"数据源A请求超时: {error_a}")
                    future_a.cancel()  # 尝试取消未完成的任务
                except Exception as e:
                    error_a = {'type': self._classify_error(e), 'message': str(e)}
                    self.logger.error(f"数据源A拉取失败: {e}", exc_info=True)
                
                try:
                    data_b = future_b.result(timeout=60)
                except futures.TimeoutError:
                    error_b = {'type': 'timeout', 'message': '数据源B请求超时（>60秒）'}
                    self.logger.error(f"数据源B请求超时: {error_b}")
                    future_b.cancel()  # 尝试取消未完成的任务
                except Exception as e:
                    error_b = {'type': self._classify_error(e), 'message': str(e)}
                    self.logger.error(f"数据源B拉取失败: {e}", exc_info=True)
            finally:
                # 立即关闭执行器，不等待线程完成（防止卡死）
                executor.shutdown(wait=False)
            
            # 3. 处理双源异常组合
            if error_a and error_b:
                # 场景3/4：两源都失败
                error_msg_json = json.dumps({
                    'source_a_error': error_a,
                    'source_b_error': error_b
                })
                
                if save_log:
                    self._update_compare_log(compare_id, status='failed', error_msg=error_msg_json)
                
                # 返回失败结果而不是抛出异常
                return {
                    'compare_id': compare_id,
                    'status': 'failed',
                    'error_msg': f"两个数据源都失败: A={error_a['type']}, B={error_b['type']}",
                    'source_a': source_a,
                    'source_b': source_b,
                    'asset_type': asset_type,
                    'symbol': symbol,
                    'period': period,
                    'details': error_msg_json
                }
            
            elif error_a:
                # 场景5：A失败，B成功
                error_msg_json = json.dumps({
                    'source_a_error': error_a,
                    'source_b': {'records': len(data_b)}
                })
                
                if save_log:
                    self._update_compare_log(compare_id, status='partial_failed', error_msg=error_msg_json)
                
                # 返回失败结果而不是抛出异常
                return {
                    'compare_id': compare_id,
                    'status': 'failed',
                    'error_msg': f"数据源A失败，无法完成对比: {error_a['type']} - {error_a['message']}",
                    'source_a': source_a,
                    'source_b': source_b,
                    'asset_type': asset_type,
                    'symbol': symbol,
                    'period': period,
                    'details': error_msg_json
                }
            
            elif error_b:
                # 场景1：A成功，B失败
                error_msg_json = json.dumps({
                    'source_a': {'records': len(data_a)},
                    'source_b_error': error_b
                })
                
                if save_log:
                    self._update_compare_log(compare_id, status='partial_failed', error_msg=error_msg_json)
                
                # 返回失败结果而不是抛出异常
                return {
                    'compare_id': compare_id,
                    'status': 'failed',
                    'error_msg': f"数据源B失败，无法完成对比: {error_b['type']} - {error_b['message']}",
                    'source_a': source_a,
                    'source_b': source_b,
                    'asset_type': asset_type,
                    'symbol': symbol,
                    'period': period,
                    'details': error_msg_json
                }
            
            # 4. 执行行级对比（新算法）
            row_comparison = self._align_and_compare_by_row(data_a, data_b, price_threshold=1.0)
            
            # 5. 执行五维度校验
            expected_days = self._calculate_expected_days(start_date, end_date, period)
            
            completeness = self._check_completeness(data_a, data_b, expected_days)
            consistency = self._check_consistency(data_a, data_b, threshold=1.0)
            time_alignment = self._check_time_alignment(data_a, data_b)
            anomalies = self._detect_anomalies(data_a, data_b)
            statistics = self._compare_statistics(data_a, data_b)
            
            # 6. 计算综合评分
            total_score = (
                completeness['score'] +
                consistency['score'] +
                time_alignment['score'] +
                anomalies['score'] +
                statistics['score']
            )
            
            # 7. 生成推荐建议
            recommendation = self._generate_recommendation(
                total_score, completeness, consistency, statistics, source_a, source_b
            )
            
            # 8. 构建结果
            result = {
                'compare_id': compare_id,
                'status': 'success',
                'source_a': source_a,
                'source_b': source_b,
                'symbol': symbol,
                'period': period,
                'start_date': start_date,
                'end_date': end_date,
                'data_a': data_a[:100],  # 仅返回前100条示例
                'data_b': data_b[:100],
                'row_comparison': row_comparison,  # 新增：行级对比结果
                'completeness': completeness,
                'consistency': consistency,
                'time_alignment': time_alignment,
                'anomaly_detection': anomalies,
                'statistics': statistics,
                'total_score': round(total_score, 2),
                'recommendation': recommendation,
                'created_at': datetime.now().isoformat(),
                'completed_at': datetime.now().isoformat()
            }
            
            # 9. 保存对比记录
            if save_log:
                self._update_compare_log(
                    compare_id,
                    status='completed',
                    result_json=json.dumps(result),
                    total_score=total_score
                )
            
            self.logger.info(f"对比任务完成: compare_id={compare_id}, score={total_score}")
            return result
            
        except (ValidationError, ComparatorError, NoDataError, DataSourceError) as e:
            # 业务异常，返回失败结果
            self.logger.error(f"对比任务失败: {e}", exc_info=True)
            
            error_type = type(e).__name__
            error_msg = str(e)
            
            if save_log:
                error_msg_json = json.dumps({'error': error_msg, 'type': error_type})
                self._update_compare_log(compare_id, status='failed', error_msg=error_msg_json)
            
            return {
                'compare_id': compare_id,
                'status': 'failed',
                'error_msg': f'{error_type}: {error_msg}',
                'source_a': source_a,
                'source_b': source_b,
                'asset_type': asset_type,
                'symbol': symbol,
                'period': period
            }
            
        except Exception as e:
            # 系统异常，记录日志后抛出
            self.logger.error(f"对比任务系统异常: {e}", exc_info=True)
            
            if save_log:
                error_msg_json = json.dumps({'error': str(e), 'type': 'SYSTEM_ERROR'})
                self._update_compare_log(compare_id, status='failed', error_msg=error_msg_json)
            
            raise
    
    # ==================== 对比记录管理 ====================
    
    def get_compare_history(
        self,
        symbol: str = None,
        source_a: str = None,
        source_b: str = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        查询历史对比记录
        """
        sql = "SELECT * FROM tb_compare_log WHERE 1=1"
        params = []
        
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        
        if source_a:
            sql += " AND source_a = ?"
            params.append(source_a)
        
        if source_b:
            sql += " AND source_b = ?"
            params.append(source_b)
        
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        result = self.db_connector.execute_query(sql, tuple(params))
        
        # 解析result_json字段
        for item in result:
            if item.get('result_json'):
                try:
                    item['result'] = json.loads(item['result_json'])
                except Exception:
                    pass
        
        return result
    
    def generate_compare_report(
        self,
        compare_id: str,
        report_format: str = 'markdown'
    ) -> str:
        """
        生成对比报告
        
        Args:
            compare_id: 对比任务ID
            report_format: 报告格式（markdown/json）
            
        Returns:
            报告内容
        """
        # 查询对比记录
        sql = "SELECT * FROM tb_compare_log WHERE compare_id = ?"
        result = self.db_connector.execute_query(sql, (compare_id,))
        
        if not result:
            raise ValueError(f"对比记录不存在: {compare_id}")
        
        record = result[0]
        result_data = json.loads(record['result_json']) if record.get('result_json') else {}
        
        if report_format == 'json':
            return json.dumps(result_data, indent=2, ensure_ascii=False)
        
        elif report_format == 'markdown':
            return self._generate_markdown_report(record, result_data)
        
        else:
            raise ValueError(f"不支持的报告格式: {report_format}")
    
    def _generate_markdown_report(self, record: Dict, result_data: Dict) -> str:
        """生成Markdown格式报告"""
        completeness = result_data.get('completeness', {})
        consistency = result_data.get('consistency', {})
        time_alignment = result_data.get('time_alignment', {})
        anomaly = result_data.get('anomaly_detection', {})
        statistics = result_data.get('statistics', {})
        
        report = f"""# 历史数据对比报告

## 基本信息
- **对比ID**: {record.get('compare_id', 'N/A')}
- **数据源A**: {record.get('source_a', 'N/A')}
- **数据源B**: {record.get('source_b', 'N/A')}
- **证券代码**: {record.get('symbol', 'N/A')}
- **数据周期**: {record.get('period', 'N/A')}
- **时间范围**: {record.get('start_date', 'N/A')} ~ {record.get('end_date', 'N/A')}
- **对比状态**: {record.get('status', 'N/A')}
- **综合评分**: {record.get('total_score', 0):.2f}分

## 校验结果

### 1. 数据完整性（{completeness.get('score', 0)}/30分）
- 数据源A记录数: {completeness.get('total_records_a', 0)}
- 数据源B记录数: {completeness.get('total_records_b', 0)}
- 覆盖率A: {completeness.get('coverage_rate_a', 0)}%
- 覆盖率B: {completeness.get('coverage_rate_b', 0)}%

### 2. 数值一致性（{consistency.get('score', 0)}/40分）
- 平均价格偏差: {consistency.get('avg_price_deviation', 0)}%
- 最大价格偏差: {consistency.get('max_price_deviation', 0)}%
- 异常记录数: {consistency.get('outlier_count', 0)}
- 异常占比: {consistency.get('outlier_ratio', 0)}%

### 3. 时间对齐性（{time_alignment.get('score', 0)}/20分）
- 时间格式匹配: {time_alignment.get('time_format_match', False)}
- 对齐率: {time_alignment.get('alignment_rate', 0)}%

### 4. 异常值检测（{anomaly.get('score', 0)}/20分）
- 异常涨跌A: {len(anomaly.get('extreme_change_a', []))}
- 异常涨跌B: {len(anomaly.get('extreme_change_b', []))}
- 零值记录A: {anomaly.get('zero_value_a', 0)}
- 负值记录A: {anomaly.get('negative_value_a', 0)}

### 5. 统计特征（{statistics.get('score', 0)}/10分）
- 相关系数（收盘价）: {statistics.get('correlation_close', 0):.4f}
- 相似度得分: {statistics.get('similarity_score', 0)}%

## 推荐建议

{result_data.get('recommendation', '无')}

---
*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        return report
