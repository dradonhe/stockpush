"""
自选股池管理服务模块
负责管理用户自选股票与基金池，支持分组管理、代码库同步等功能
"""
import json
import os
from typing import List, Dict, Optional, Any
from stockpush.pg_connector import PGConnector
from stockpush.log_manager import LogManager


# ==================== 异常类定义 ====================

class PoolMgrError(Exception):
    """自选股管理基础异常"""
    pass


class SymbolNotFoundError(PoolMgrError):
    """标的不存在于代码库"""
    pass


class DuplicateSymbolError(PoolMgrError):
    """标的已存在于分组中"""
    pass


class GroupNotFoundError(PoolMgrError):
    """分组不存在"""
    pass


class SyncError(PoolMgrError):
    """同步失败"""
    pass


# ==================== 主服务类 ====================

class PoolMgrService:
    """自选股池管理服务"""
    
    def __init__(self, db_connector=None):
        """
        初始化自选股管理服务
        
        Args:
            db_connector: 外部传入的 DBConnector 实例（可选）。
                传入时直接复用，不再新建连接，避免文件锁冲突。
        """
        if db_connector is not None:
            self.db_connector = db_connector
        else:
            from stockpush.pg_connector import PGConnector
            self.db_connector = PGConnector()
        self.logger = LogManager.get_logger("PoolMgr")
        self.config = self._load_config()
        # 表由 sys_init.py 统一创建
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        import os  # 将import语句移到方法开头
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.logger.info("配置文件加载成功")
                return config
            else:
                # 仅在调试模式下显示警告
                if os.getenv('DEBUG_MODE', '').lower() == 'true':
                    self.logger.warning("配置文件不存在，使用默认配置")
                return self._get_default_config()
        except Exception as e:
            self.logger.error(f"配置文件加载失败: {e}", exc_info=True)
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "default_group": "default",
            "max_symbols_per_group": 500,
            "auto_sync": {
                "enabled": True,
                "interval_hours": 24,
                "retry_on_failure": True
            },
            "validation": {
                "check_code_exists": True,
                "allow_delisted": False
            }
        }

    def _normalize_group_name(self, group_name: Optional[str]) -> str:
        """规范化分组名（去除首尾空白）"""
        if group_name is None:
            return ''
        return str(group_name).strip()

    def _symbol_exists_in_group(self, symbol: str, group_name: str) -> bool:
        """检查symbol是否已存在于指定分组（使用规范化比较）"""
        sql = """
        SELECT COUNT(*) as cnt
        FROM tb_stock_pool
        WHERE symbol = %s AND TRIM(group_name) = TRIM(%s)
        """
        result = self.db_connector.execute_query(sql, (symbol, group_name))
        return bool(result and result[0].get('cnt', 0) > 0)
    
    def _check_symbol_exists(self, symbol: str) -> tuple:
        """
        检查symbol是否在代码库中存在
        
        Args:
            symbol: 标的代码
        
        Returns:
            tuple: (exists: bool, symbol_type: str), symbol_type为'stock'或'fund'
        """
        # 检查股票代码库
        sql_stock = "SELECT COUNT(*) as cnt FROM tb_stock_codes WHERE symbol = %s"
        result_stock = self.db_connector.execute_query(sql_stock, (symbol,))
        
        if result_stock[0]['cnt'] > 0:
            return (True, 'stock')
        
        # 检查基金代码库
        sql_fund = "SELECT COUNT(*) as cnt FROM tb_fund_codes WHERE symbol = %s"
        result_fund = self.db_connector.execute_query(sql_fund, (symbol,))
        
        if result_fund[0]['cnt'] > 0:
            return (True, 'fund')
        
        return (False, None)
    
    def _get_symbol_info_from_codes(self, symbol: str) -> Dict[str, Any]:
        """
        从代码库获取symbol基础信息
        
        Args:
            symbol: 标的代码
        
        Returns:
            dict: 包含name, type, market等信息
        
        Raises:
            SymbolNotFoundError: symbol不存在
        """
        exists, symbol_type = self._check_symbol_exists(symbol)
        
        if not exists:
            raise SymbolNotFoundError(f"标的代码不存在: {symbol}")
        
        if symbol_type == 'stock':
            sql = "SELECT symbol, name, market FROM tb_stock_codes WHERE symbol = %s"
        else:
            sql = "SELECT symbol, name, type as market FROM tb_fund_codes WHERE symbol = %s"
        
        result = self.db_connector.execute_query(sql, (symbol,))
        
        if not result:
            raise SymbolNotFoundError(f"无法获取标的信息: {symbol}")
        
        info = result[0]
        info['type'] = symbol_type
        return info
    
    # ==================== Export API ====================
    
    def add_symbol(self, symbol: str, group_name: str = 'default') -> bool:
        """
        添加自选股/基金到指定分组
        
        Args:
            symbol: 标的代码(纯数字)
            group_name: 分组名称, 默认为'default'
        
        Returns:
            bool: 添加成功返回True, 失败返回False
        
        Raises:
            ValueError: symbol不存在于代码库或格式错误
            DuplicateSymbolError: symbol在该分组已存在
        """
        # 参数验证
        symbol = str(symbol).strip()

        if not symbol or not symbol.isdigit():
            raise ValueError(f"symbol格式错误，必须为纯数字: {symbol}")
        
        group_name = self._normalize_group_name(group_name)

        if not group_name or len(group_name) > 50:
            raise ValueError(f"group_name长度必须在1-50字符之间: {group_name}")
        
        try:
            # 预检查：避免重复写入
            if self._symbol_exists_in_group(symbol, group_name):
                self.logger.warning(f"自选股已存在: symbol={symbol}, group={group_name}")
                raise DuplicateSymbolError(f"标的已在分组中: {symbol} in {group_name}")

            # 获取symbol信息
            info = self._get_symbol_info_from_codes(symbol)
            
            # 插入记录
            insert_sql = """
            INSERT INTO tb_stock_pool (symbol, name, type, market, group_name, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
            
            self.db_connector.execute_update(
                insert_sql,
                (symbol, info['name'], info['type'], info.get('market'), group_name)
            )
            
            self.logger.info(f"添加自选股成功: symbol={symbol}, group={group_name}")
            return True
            
        except Exception as e:
            if isinstance(e, DuplicateSymbolError):
                raise
            if "UNIQUE constraint" in str(e) or "duplicate" in str(e).lower():
                self.logger.warning(f"自选股已存在: symbol={symbol}, group={group_name}")
                raise DuplicateSymbolError(f"标的已在分组中: {symbol} in {group_name}")
            else:
                self.logger.error(f"添加自选股失败: {e}", exc_info=True)
                raise
    
    def remove_symbol(self, symbol: str, group_name: str = None) -> bool:
        """
        删除自选股/基金
        
        Args:
            symbol: 标的代码
            group_name: 分组名称, 为None时删除所有分组中的该symbol
        
        Returns:
            bool: 删除成功返回True, 不存在返回False
        
        Raises:
            ValueError: 参数格式错误
        """
        # 参数验证
        if not symbol or not symbol.isdigit():
            raise ValueError(f"symbol格式错误: {symbol}")
        
        try:
            if group_name:
                group_name = self._normalize_group_name(group_name)
                # 先检查是否存在
                check_sql = "SELECT COUNT(*) as cnt FROM tb_stock_pool WHERE symbol = %s AND TRIM(group_name) = TRIM(%s)"
                result = self.db_connector.execute_query(check_sql, (symbol, group_name))
                exists = result and result[0]['cnt'] > 0
                
                # 删除指定分组中的记录
                delete_sql = "DELETE FROM tb_stock_pool WHERE symbol = %s AND TRIM(group_name) = TRIM(%s)"
                self.db_connector.execute_update(delete_sql, (symbol, group_name))
                
                if exists:
                    self.logger.info(f"删除自选股成功: symbol={symbol}, group={group_name}")
                    return True
                else:
                    self.logger.warning(f"自选股不存在: symbol={symbol}, group={group_name}")
                    return False
            else:
                # 先检查是否存在
                check_sql = "SELECT COUNT(*) as cnt FROM tb_stock_pool WHERE symbol = %s"
                result = self.db_connector.execute_query(check_sql, (symbol,))
                count = result[0]['cnt'] if result else 0
                
                # 删除所有分组中的记录
                delete_sql = "DELETE FROM tb_stock_pool WHERE symbol = %s"
                self.db_connector.execute_update(delete_sql, (symbol,))
                
                if count > 0:
                    self.logger.info(f"删除自选股成功(所有分组): symbol={symbol}, 删除{count}条记录")
                    return True
                else:
                    self.logger.warning(f"自选股不存在: symbol={symbol}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"删除自选股失败: {e}", exc_info=True)
            raise
    
    def get_pool(self, group_name: str = None, symbol_type: str = None) -> List[Dict[str, Any]]:
        """
        获取自选股池
        
        Args:
            group_name: 分组名称, 为None返回所有分组
            symbol_type: 类型过滤('stock'/'fund'), 为None返回所有类型
        
        Returns:
            list: 自选股列表, 每项为dict包含id/symbol/name/type/market/group_name
        
        Raises:
            ValueError: 参数格式错误
        """
        try:
            # 构建SQL查询
            sql = "SELECT id, symbol, name, type, market, group_name, created_at, updated_at FROM tb_stock_pool WHERE 1=1"
            params = []
            
            if group_name:
                group_name = self._normalize_group_name(group_name)
                sql += " AND TRIM(group_name) = TRIM(%s)"
                params.append(group_name)
            
            if symbol_type:
                if symbol_type not in ['stock', 'fund']:
                    raise ValueError(f"无效的symbol_type: {symbol_type}, 必须为'stock'或'fund'")
                sql += " AND type = %s"
                params.append(symbol_type)
            
            sql += " ORDER BY created_at DESC"
            
            result = self.db_connector.execute_query(sql, tuple(params) if params else None)
            
            self.logger.info(f"查询自选池成功: group={group_name}, type={symbol_type}, count={len(result)}")
            return result
            
        except Exception as e:
            self.logger.error(f"查询自选池失败: {e}", exc_info=True)
            raise
    
    def get_groups(self) -> List[str]:
        """
        获取所有分组名称列表
        
        Returns:
            list: 分组名称列表
        """
        try:
            sql = "SELECT DISTINCT TRIM(group_name) AS group_name FROM tb_stock_pool ORDER BY group_name"
            result = self.db_connector.execute_query(sql)
            groups = [row['group_name'] for row in result]
            
            self.logger.info(f"获取分组列表成功: count={len(groups)}")
            return groups
            
        except Exception as e:
            self.logger.error(f"获取分组列表失败: {e}", exc_info=True)
            raise
    
    def rename_group(self, old_name: str, new_name: str) -> bool:
        """
        重命名分组
        
        Args:
            old_name: 原分组名称
            new_name: 新分组名称
        
        Returns:
            bool: 重命名成功返回True
        
        Raises:
            ValueError: 分组不存在或新分组名已存在
            GroupNotFoundError: 分组不存在
        """
        # 参数验证
        if not old_name or not new_name:
            raise ValueError("分组名称不能为空")

        old_name = self._normalize_group_name(old_name)
        new_name = self._normalize_group_name(new_name)
        
        if len(new_name) > 50:
            raise ValueError(f"分组名称长度不能超过50字符: {new_name}")
        
        try:
            # 检查原分组是否存在
            check_old_sql = "SELECT COUNT(*) as cnt FROM tb_stock_pool WHERE TRIM(group_name) = TRIM(%s)"
            result_old = self.db_connector.execute_query(check_old_sql, (old_name,))
            
            if result_old[0]['cnt'] == 0:
                raise GroupNotFoundError(f"分组不存在: {old_name}")
            
            # 检查新分组名是否已存在
            check_new_sql = "SELECT COUNT(*) as cnt FROM tb_stock_pool WHERE TRIM(group_name) = TRIM(%s)"
            result_new = self.db_connector.execute_query(check_new_sql, (new_name,))
            
            if result_new[0]['cnt'] > 0:
                raise ValueError(f"新分组名已存在: {new_name}")
            
            # 执行重命名
            update_sql = "UPDATE tb_stock_pool SET group_name = %s, updated_at = CURRENT_TIMESTAMP WHERE TRIM(group_name) = TRIM(%s)"
            affected = self.db_connector.execute_update(update_sql, (new_name, old_name))
            
            self.logger.info(f"重命名分组成功: {old_name} -> {new_name}, 更新{affected}条记录")
            return True
            
        except Exception as e:
            self.logger.error(f"重命名分组失败: {e}", exc_info=True)
            raise
    
    def delete_group(self, group_name: str) -> bool:
        """
        删除整个分组(删除该分组下所有记录)
        
        Args:
            group_name: 分组名称
        
        Returns:
            bool: 删除成功返回True
        
        Raises:
            ValueError: 分组不存在或为'default'分组
            GroupNotFoundError: 分组不存在
        """
        # 禁止删除default分组
        if group_name == 'default':
            raise ValueError("不能删除'default'分组")

        group_name = self._normalize_group_name(group_name)
        
        try:
            # 检查分组是否存在
            check_sql = "SELECT COUNT(*) as cnt FROM tb_stock_pool WHERE TRIM(group_name) = TRIM(%s)"
            result = self.db_connector.execute_query(check_sql, (group_name,))
            
            if result[0]['cnt'] == 0:
                raise GroupNotFoundError(f"分组不存在: {group_name}")
            
            # 删除分组
            delete_sql = "DELETE FROM tb_stock_pool WHERE TRIM(group_name) = TRIM(%s)"
            affected = self.db_connector.execute_update(delete_sql, (group_name,))
            
            self.logger.info(f"删除分组成功: {group_name}, 删除{affected}条记录")
            return True
            
        except Exception as e:
            self.logger.error(f"删除分组失败: {e}", exc_info=True)
            raise
    
    def get_symbol_detail(self, symbol: str) -> Dict[str, Any]:
        """
        获取自选池中指定symbol的信息(所有分组)
        
        Args:
            symbol: 标的代码
        
        Returns:
            dict: 包含symbol基础信息和所属分组列表
        
        Raises:
            ValueError: symbol不在自选池中
        """
        try:
            sql = "SELECT symbol, name, type, market, group_name FROM tb_stock_pool WHERE symbol = %s"
            result = self.db_connector.execute_query(sql, (symbol,))
            
            if not result:
                raise ValueError(f"symbol不在自选池中: {symbol}")
            
            # 提取基础信息和分组列表
            info = {
                'symbol': result[0]['symbol'],
                'name': result[0]['name'],
                'type': result[0]['type'],
                'market': result[0]['market'],
                'groups': [row['group_name'] for row in result]
            }
            
            self.logger.info(f"获取symbol信息成功: {symbol}")
            return info
            
        except Exception as e:
            self.logger.error(f"获取symbol信息失败: {e}", exc_info=True)
            raise
    
    def import_stock_codes(self, df) -> int:
        """
        从 DataFrame 导入股票代码到 tb_stock_codes

        Args:
            df: 包含 code 列的 DataFrame（name / market 可选）

        Returns:
            int: 导入的记录数
        """
        if df is None or (hasattr(df, 'empty') and df.empty):
            self.logger.warning("import_stock_codes: 数据为空，跳过")
            return 0

        has_name = 'name' in df.columns
        has_market = 'market' in df.columns
        count = 0
        for _, row in df.iterrows():
            code = str(row.get('code', '')).strip()
            if not code:
                continue
            name = str(row.get('name', '')).strip() if has_name else ''
            market = str(row.get('market', '')).strip() if has_market else ''
            try:
                if name:
                    self.db_connector.execute_update(
                        """INSERT INTO tb_stock_codes (symbol, name, market, updated_at)
                           VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                           ON CONFLICT (symbol) DO UPDATE SET
                               name = EXCLUDED.name,
                               market = EXCLUDED.market,
                               updated_at = CURRENT_TIMESTAMP""",
                        (code, name, market))
                else:
                    # 无名称时不覆盖已有名称
                    self.db_connector.execute_update(
                        """INSERT INTO tb_stock_codes (symbol, name, market, updated_at)
                           VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                           ON CONFLICT (symbol) DO UPDATE SET
                               market = EXCLUDED.market,
                               updated_at = CURRENT_TIMESTAMP""",
                        (code, name, market))
                count += 1
            except Exception as e:
                self.logger.warning(f"导入股票代码失败 {code}: {e}")

        self.logger.info(f"股票代码导入完成: {count} 条")
        return count

    def import_fund_codes(self, df) -> int:
        """
        从 DataFrame 导入基金代码到 tb_fund_codes

        Args:
            df: 包含 code 列的 DataFrame（name / type 可选）

        Returns:
            int: 导入的记录数
        """
        if df is None or (hasattr(df, 'empty') and df.empty):
            self.logger.warning("import_fund_codes: 数据为空，跳过")
            return 0

        has_name = 'name' in df.columns
        has_type = 'type' in df.columns
        count = 0
        for _, row in df.iterrows():
            code = str(row.get('code', '')).strip()
            if not code:
                continue
            name = str(row.get('name', '')).strip() if has_name else ''
            ftype = str(row.get('type', '')).strip() if has_type else ''
            try:
                if name:
                    self.db_connector.execute_update(
                        """INSERT INTO tb_fund_codes (symbol, name, type, updated_at)
                           VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                           ON CONFLICT (symbol) DO UPDATE SET
                               name = EXCLUDED.name,
                               type = EXCLUDED.type,
                               updated_at = CURRENT_TIMESTAMP""",
                        (code, name, ftype))
                else:
                    # 无名称时不覆盖已有名称
                    self.db_connector.execute_update(
                        """INSERT INTO tb_fund_codes (symbol, name, type, updated_at)
                           VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                           ON CONFLICT (symbol) DO UPDATE SET
                               type = EXCLUDED.type,
                               updated_at = CURRENT_TIMESTAMP""",
                        (code, name, ftype))
                count += 1
            except Exception as e:
                self.logger.warning(f"导入基金代码失败 {code}: {e}")

        self.logger.info(f"基金代码导入完成: {count} 条")
        return count

    def sync_from_codes(self, symbol: str = None) -> int:
        """
        从代码库同步标的基础信息(name/market)
        
        Args:
            symbol: 指定symbol同步单个, 为None则同步所有
        
        Returns:
            int: 同步更新的记录数
        
        Raises:
            SyncError: 同步失败
        """
        try:
            update_count = 0
            
            if symbol:
                # 同步单个symbol
                symbols = [symbol]
            else:
                # 获取所有待同步的symbol
                sql = "SELECT DISTINCT symbol, type FROM tb_stock_pool"
                result = self.db_connector.execute_query(sql)
                symbols = [(row['symbol'], row['type']) for row in result]
            
            for item in symbols:
                if isinstance(item, tuple):
                    sym, sym_type = item
                else:
                    sym = item
                    # 获取当前type
                    sql_type = "SELECT type FROM tb_stock_pool WHERE symbol = %s LIMIT 1"
                    result_type = self.db_connector.execute_query(sql_type, (sym,))
                    sym_type = result_type[0]['type'] if result_type else None
                
                # 从代码库获取最新信息
                if sym_type == 'stock':
                    sql_codes = "SELECT name, market FROM tb_stock_codes WHERE symbol = %s"
                elif sym_type == 'fund':
                    sql_codes = "SELECT name, type as market FROM tb_fund_codes WHERE symbol = %s"
                else:
                    self.logger.warning(f"未知的symbol类型: {sym}, type={sym_type}")
                    continue
                
                result_codes = self.db_connector.execute_query(sql_codes, (sym,))
                
                if not result_codes:
                    self.logger.warning(f"代码库中不存在: {sym}")
                    continue
                
                # 检查是否需要更新
                check_sql = "SELECT name, market FROM tb_stock_pool WHERE symbol = %s LIMIT 1"
                current_info = self.db_connector.execute_query(check_sql, (sym,))
                
                if current_info and (current_info[0]['name'] != result_codes[0]['name'] or 
                    current_info[0].get('market') != result_codes[0]['market']):
                    # 更新自选池信息
                    update_sql = """
                    UPDATE tb_stock_pool 
                    SET name = %s, market = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE symbol = %s
                    """
                    self.db_connector.execute_update(
                        update_sql,
                        (result_codes[0]['name'], result_codes[0]['market'], sym)
                    )
                    update_count += 1
            
            self.logger.info(f"同步完成: 更新{update_count}条记录")
            return update_count
            
        except Exception as e:
            self.logger.error(f"同步失败: {e}", exc_info=True)
            raise SyncError(f"同步代码库信息失败: {e}")
    
    def update_symbol(self, symbol: str) -> bool:
        """
        更新单个标的信息(从代码库)
        
        Args:
            symbol: 标的代码
        
        Returns:
            bool: 更新成功返回True, symbol不存在返回False
        
        Raises:
            ValueError: symbol格式错误
        """
        if not symbol or not symbol.isdigit():
            raise ValueError(f"symbol格式错误: {symbol}")
        
        try:
            # 检查symbol是否在自选池中
            check_sql = "SELECT COUNT(*) as cnt FROM tb_stock_pool WHERE symbol = %s"
            result = self.db_connector.execute_query(check_sql, (symbol,))
            
            if result[0]['cnt'] == 0:
                self.logger.warning(f"symbol不在自选池中: {symbol}")
                return False
            
            # 调用sync_from_codes同步单个
            self.sync_from_codes(symbol)
            
            # 只要symbol存在就返回True（表示已检查并同步）
            return True
            
        except Exception as e:
            self.logger.error(f"更新symbol信息失败: {e}", exc_info=True)
            raise
    
    def reset(self, mode: str = 'soft', confirm: bool = False) -> bool:
        """
        重置自选股管理模块
        
        Args:
            mode: 'soft' | 'hard'
                - 'soft': 清缓存、刷新同步状态
                - 'hard': 删除tb_stock_pool表和配置文件
            confirm: 是否需要二次确认(Hard Reset强制要求)
        
        Returns:
            bool: 重置成功返回True, 用户取消或失败返回False
        
        Raises:
            ValueError: mode参数错误
            PermissionError: Hard Reset未确认
        """
        if mode not in ['soft', 'hard']:
            raise ValueError(f"无效的mode参数: {mode}, 必须为'soft'或'hard'")
        
        if mode == 'hard' and not confirm:
            raise PermissionError("Hard Reset必须confirm=True")
        
        try:
            if mode == 'soft':
                # 软重置: 清理缓存、刷新状态
                self.logger.info("执行软重置")
                
                # 如果有缓存，清理缓存
                # (本实现暂无缓存，预留扩展)
                
                # 刷新同步状态
                sync_count = self.sync_from_codes()
                
                # 重新加载配置
                self.config = self._load_config()
                
                self.logger.info(f"软重置完成: 同步{sync_count}条记录")
                return True
                
            elif mode == 'hard':
                # 硬重置: 删除表和配置
                self.logger.warning("⚠️ 执行硬重置: 将删除所有自选股数据")
                
                # 删除tb_stock_pool表
                drop_table_sql = "DROP TABLE IF EXISTS tb_stock_pool"
                self.db_connector.execute_update(drop_table_sql)
                
                # 删除配置文件
                config_path = os.path.join(os.path.dirname(__file__), "config.json")
                if os.path.exists(config_path):
                    os.remove(config_path)
                
                self.logger.warning("硬重置完成: tb_stock_pool已删除, 配置文件已删除")
                
                # 重新初始化
                self._init_table()
                self.config = self._load_config()
                
                return True
                
        except Exception as e:
            self.logger.error(f"Reset失败: {e}", exc_info=True)
            return False
