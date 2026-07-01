"""
数据映射模块
定义API标准字段到数据库表字段的完整映射关系
"""
import pandas as pd
from typing import Dict, Optional
from datetime import datetime


class DataMapper:
    """数据映射器：API标准字段 → 数据库表字段"""
    
    # API标准字段 → 数据库表字段映射
    STANDARD_TO_DB = {
        'date': 'ts',           # 日期时间
        'code': 'symbol',       # 股票/基金代码
        'open': 'open',         # 开盘价
        'high': 'high',         # 最高价
        'low': 'low',           # 最低价
        'close': 'close',       # 收盘价
        'volume': 'vol',        # 成交量
        'amount': 'amount',     # 成交额
    }
    
    # 数据库表字段 → API标准字段映射（反向）
    DB_TO_STANDARD = {v: k for k, v in STANDARD_TO_DB.items()}
    
    # 数据类型映射（数据库字段类型）
    DB_FIELD_TYPES = {
        'ts': 'TIMESTAMP',
        'symbol': 'VARCHAR(10)',
        'open': 'DECIMAL(10, 3)',
        'high': 'DECIMAL(10, 3)',
        'low': 'DECIMAL(10, 3)',
        'close': 'DECIMAL(10, 3)',
        'vol': 'BIGINT',
        'amount': 'DECIMAL(20, 2)',
    }
    
    # 必需字段
    REQUIRED_FIELDS = ['ts', 'symbol', 'open', 'high', 'low', 'close', 'vol', 'amount']
    
    @classmethod
    def to_database_format(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        将API标准格式DataFrame转换为数据库格式
        
        Args:
            df: 标准格式DataFrame（字段：date, code, open, high, low, close, volume, amount）
        
        Returns:
            数据库格式DataFrame（字段：ts, symbol, open, high, low, close, vol, amount）
        """
        df_db = df.copy()
        
        # 重命名字段
        rename_mapping = {}
        for std_field, db_field in cls.STANDARD_TO_DB.items():
            if std_field in df_db.columns:
                rename_mapping[std_field] = db_field
        
        df_db = df_db.rename(columns=rename_mapping)
        
        # 日期时间处理
        if 'ts' in df_db.columns:
            df_db['ts'] = pd.to_datetime(df_db['ts'], errors='coerce')
        
        # 数据类型转换
        if 'symbol' in df_db.columns:
            df_db['symbol'] = df_db['symbol'].astype(str)
        
        numeric_fields = ['open', 'high', 'low', 'close', 'vol', 'amount']
        for field in numeric_fields:
            if field in df_db.columns:
                df_db[field] = pd.to_numeric(df_db[field], errors='coerce')
        
        # 检查必需字段
        missing_fields = [f for f in cls.REQUIRED_FIELDS if f not in df_db.columns]
        if missing_fields:
            raise ValueError(f"缺少必需字段: {missing_fields}")
        
        # 选择并排序字段
        df_db = df_db[cls.REQUIRED_FIELDS]
        
        return df_db
    
    @classmethod
    def from_database_format(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        将数据库格式DataFrame转换为API标准格式
        
        Args:
            df: 数据库格式DataFrame（字段：ts, symbol, open, high, low, close, vol, amount）
        
        Returns:
            标准格式DataFrame（字段：date, code, open, high, low, close, volume, amount）
        """
        df_std = df.copy()
        
        # 重命名字段
        rename_mapping = {}
        for db_field, std_field in cls.DB_TO_STANDARD.items():
            if db_field in df_std.columns:
                rename_mapping[db_field] = std_field
        
        df_std = df_std.rename(columns=rename_mapping)
        
        return df_std
    
    @classmethod
    def get_insert_sql(cls, table_name: str, df: pd.DataFrame) -> tuple[str, list]:
        """
        生成批量插入SQL
        
        Args:
            table_name: 表名（tb_raw_1m, tb_raw_5m等）
            df: 数据库格式DataFrame
        
        Returns:
            (SQL语句, 参数列表)
        """
        fields = ', '.join(cls.REQUIRED_FIELDS)
        placeholders = ', '.join(['?' for _ in cls.REQUIRED_FIELDS])
        
        sql = f"""
            INSERT OR REPLACE INTO {table_name} ({fields})
            VALUES ({placeholders})
        """
        
        # 转换为参数列表
        data_tuples = []
        for _, row in df.iterrows():
            data_tuple = tuple(row[field] for field in cls.REQUIRED_FIELDS)
            data_tuples.append(data_tuple)
        
        return sql, data_tuples
    
    @classmethod
    def validate_database_format(cls, df: pd.DataFrame) -> tuple[bool, Optional[str]]:
        """
        验证DataFrame是否符合数据库格式
        
        Args:
            df: 待验证DataFrame
        
        Returns:
            (是否有效, 错误消息)
        """
        # 检查必需字段
        missing = [f for f in cls.REQUIRED_FIELDS if f not in df.columns]
        if missing:
            return False, f"缺少必需字段: {missing}"
        
        # 检查空值
        null_counts = df[cls.REQUIRED_FIELDS].isnull().sum()
        if null_counts.any():
            null_fields = null_counts[null_counts > 0].to_dict()
            return False, f"存在空值: {null_fields}"
        
        # 检查数据类型
        if 'ts' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['ts']):
                return False, "ts字段必须是datetime类型"
        
        if 'symbol' in df.columns:
            if not pd.api.types.is_string_dtype(df['symbol']) and not pd.api.types.is_object_dtype(df['symbol']):
                return False, "symbol字段必须是字符串类型"
        
        numeric_fields = ['open', 'high', 'low', 'close', 'vol', 'amount']
        for field in numeric_fields:
            if field in df.columns:
                if not pd.api.types.is_numeric_dtype(df[field]):
                    return False, f"{field}字段必须是数值类型"
        
        return True, None


# 使用示例
if __name__ == '__main__':
    # 示例1：API标准格式 → 数据库格式
    api_data = pd.DataFrame({
        'date': ['2024-01-01', '2024-01-02'],
        'code': ['000001', '000001'],
        'open': [10.0, 10.1],
        'high': [10.5, 10.6],
        'low': [9.9, 10.0],
        'close': [10.2, 10.3],
        'volume': [1000000, 1100000],
        'amount': [10200000, 11330000],
    })
    
    db_data = DataMapper.to_database_format(api_data)
    print("数据库格式:")
    print(db_data)
    print(db_data.dtypes)
    
    # 示例2：验证数据库格式
    is_valid, error = DataMapper.validate_database_format(db_data)
    print(f"\n验证结果: {is_valid}, 错误: {error}")
    
    # 示例3：生成插入SQL
    sql, params = DataMapper.get_insert_sql('tb_raw_1m', db_data)
    print(f"\nSQL: {sql}")
    print(f"参数数量: {len(params)}")
