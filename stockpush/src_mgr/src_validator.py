"""
双源共识校验器
提供数据源之间的数据一致性校验功能
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
from stockpush.log_manager import LogManager


class ConsensusValidator:
    """
    双源共识校验器
    计算两个数据源之间的数据偏离度，超过阈值时返回False
    """
    
    # 默认阈值配置
    DEFAULT_THRESHOLDS = {
        'price': 0.005,      # 价格偏离阈值：0.5%
        'volume': 0.10,      # 成交量偏离阈值：10%
        'amount': 0.10,      # 成交额偏离阈值：10%
    }
    
    def __init__(self, thresholds: Optional[Dict[str, float]] = None):
        """
        初始化共识校验器
        
        Args:
            thresholds: 自定义阈值配置，默认使用DEFAULT_THRESHOLDS
        """
        self.logger = LogManager().get_logger('consensus_validator')
        
        # 阈值配置
        if thresholds is None:
            self.thresholds = self.DEFAULT_THRESHOLDS.copy()
        else:
            self.thresholds = {**self.DEFAULT_THRESHOLDS, **thresholds}
        
        self.logger.info(f"共识校验器初始化完成，阈值配置: {self.thresholds}")
    
    def validate_consensus(self, data1: Dict[str, Any], data2: Dict[str, Any]) -> bool:
        """
        验证两个数据源的共识
        
        Args:
            data1: 第一个数据源的数据字典
            data2: 第二个数据源的数据字典
        
        Returns:
            bool: True表示数据一致（偏离度在阈值内），False表示偏离过大
        """
        try:
            # 验证数据格式
            if not isinstance(data1, dict) or not isinstance(data2, dict):
                self.logger.error("数据格式错误：必须是字典类型")
                return False
            
            # 验证关键字段
            required_fields = ['close']
            for field in required_fields:
                if field not in data1 or field not in data2:
                    self.logger.warning(f"缺少必需字段: {field}")
                    return False
            
            # 计算价格偏离度（使用收盘价）
            deviation = self._calculate_price_deviation(
                data1.get('close'),
                data2.get('close')
            )
            
            if deviation is None:
                self.logger.error("价格偏离度计算失败")
                return False
            
            # 判断是否超过阈值
            threshold = self.thresholds['price']
            
            if deviation > threshold:
                self.logger.warning(
                    f"价格偏离度超过阈值: {deviation:.4f} > {threshold:.4f} "
                    f"(价格1: {data1.get('close')}, 价格2: {data2.get('close')})"
                )
                return False
            
            self.logger.debug(
                f"共识校验通过: 偏离度 {deviation:.4f} <= 阈值 {threshold:.4f}"
            )
            return True
            
        except Exception as e:
            self.logger.error(f"共识校验异常: {e}")
            return False
    
    def validate_dataframe_consensus(
        self,
        df1: pd.DataFrame,
        df2: pd.DataFrame,
        key_field: str = 'date'
    ) -> Dict[str, Any]:
        """
        验证两个DataFrame的共识
        
        Args:
            df1: 第一个DataFrame
            df2: 第二个DataFrame
            key_field: 用于对齐的关键字段（如日期）
        
        Returns:
            Dict: 验证结果
                {
                    'passed': bool,              # 是否通过
                    'total_rows': int,           # 总行数
                    'match_rows': int,           # 匹配行数
                    'consensus_rows': int,       # 共识行数（偏离度在阈值内）
                    'consensus_rate': float,     # 共识率
                    'avg_price_deviation': float,  # 平均价格偏离度
                    'max_price_deviation': float,  # 最大价格偏离度
                    'failed_dates': List[str]    # 未通过共识的日期列表
                }
        """
        try:
            self.logger.info("开始DataFrame共识校验...")
            
            # 确保数据框不为空
            if df1.empty or df2.empty:
                self.logger.warning("数据框为空")
                return {'passed': False, 'error': '数据框为空'}
            
            # 基于关键字段合并
            if key_field not in df1.columns or key_field not in df2.columns:
                self.logger.error(f"缺少关键字段: {key_field}")
                return {'passed': False, 'error': f'缺少关键字段: {key_field}'}
            
            # 合并两个数据框
            merged = pd.merge(
                df1,
                df2,
                on=key_field,
                suffixes=('_1', '_2'),
                how='inner'
            )
            
            match_rows = len(merged)
            
            if match_rows == 0:
                self.logger.warning("没有匹配的数据行")
                return {'passed': False, 'error': '没有匹配的数据行'}
            
            # 计算每行的价格偏离度
            price_deviations = []
            failed_dates = []
            consensus_count = 0
            
            for idx, row in merged.iterrows():
                close1 = row.get('close_1')
                close2 = row.get('close_2')
                
                if pd.isna(close1) or pd.isna(close2):
                    continue
                
                deviation = self._calculate_price_deviation(float(close1), float(close2))
                
                if deviation is not None:
                    price_deviations.append(deviation)
                    
                    # 判断是否超过阈值
                    if deviation <= self.thresholds['price']:
                        consensus_count += 1
                    else:
                        # 记录未通过的日期
                        date_val = row.get(key_field)
                        if date_val is not None:
                            failed_dates.append(str(date_val))
            
            # 计算统计信息
            total_rows = max(len(df1), len(df2))
            avg_deviation = np.mean(price_deviations) if price_deviations else 0
            max_deviation = np.max(price_deviations) if price_deviations else 0
            consensus_rate = consensus_count / match_rows if match_rows > 0 else 0
            
            # 判断是否通过（共识率 > 95%）
            passed = consensus_rate >= 0.95
            
            result = {
                'passed': passed,
                'total_rows': total_rows,
                'match_rows': match_rows,
                'consensus_rows': consensus_count,
                'consensus_rate': consensus_rate,
                'avg_price_deviation': avg_deviation,
                'max_price_deviation': max_deviation,
                'failed_dates': failed_dates[:10]  # 最多返回10个失败日期
            }
            
            if passed:
                self.logger.info(
                    f"DataFrame共识校验通过: 共识率 {consensus_rate:.2%}, "
                    f"平均偏离度 {avg_deviation:.4f}"
                )
            else:
                self.logger.warning(
                    f"DataFrame共识校验失败: 共识率 {consensus_rate:.2%}, "
                    f"最大偏离度 {max_deviation:.4f}"
                )
            
            return result
            
        except Exception as e:
            self.logger.error(f"DataFrame共识校验异常: {e}")
            return {'passed': False, 'error': str(e)}
    
    def _calculate_price_deviation(self, price1: Any, price2: Any) -> Optional[float]:
        """
        计算两个价格之间的偏离度
        
        Args:
            price1: 第一个价格
            price2: 第二个价格
        
        Returns:
            float 或 None: 偏离度（百分比，0-1之间）
        """
        try:
            # 转换为浮点数
            p1 = float(price1)
            p2 = float(price2)
            
            # 验证价格有效性
            if p1 <= 0 or p2 <= 0:
                self.logger.warning(f"无效价格: {p1}, {p2}")
                return None
            
            # 计算偏离度：|price1 - price2| / average(price1, price2)
            avg_price = (p1 + p2) / 2
            deviation = abs(p1 - p2) / avg_price
            
            return deviation
            
        except (TypeError, ValueError) as e:
            self.logger.error(f"价格转换失败: {e}")
            return None
    
    def set_threshold(self, field: str, threshold: float):
        """
        设置字段阈值
        
        Args:
            field: 字段名称 ('price', 'volume', 'amount')
            threshold: 阈值（0-1之间）
        """
        if field not in ['price', 'volume', 'amount']:
            self.logger.warning(f"无效的字段名称: {field}")
            return
        
        if not 0 <= threshold <= 1:
            self.logger.warning(f"无效的阈值: {threshold}，应在0-1之间")
            return
        
        self.thresholds[field] = threshold
        self.logger.info(f"阈值已更新: {field} = {threshold}")
    
    def get_thresholds(self) -> Dict[str, float]:
        """
        获取当前阈值配置
        
        Returns:
            Dict[str, float]: 阈值配置
        """
        return self.thresholds.copy()
