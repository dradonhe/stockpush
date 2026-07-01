"""
数据库连接器（DuckDB 版本）

本地开发/测试统一使用 DuckDB，数据文件位于 data/zenith_quant.duckdb。
远端部署（F5.1、SysInit）请使用 src.pg_connector.PGConnector（PostgreSQL）。
"""

import os
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import duckdb

# 项目根目录（src/ 的上一级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "zenith_quant.duckdb"


class _QueryResult:
    """查询结果包装器

    支持链式调用:
    - conn.execute(sql).fetchone() -> dict
    - conn.execute(sql).fetchall() -> list[dict]
    """

    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self._index = 0
        self.rowcount = rowcount
        self.description = None

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        return self._rows

    def __getitem__(self, idx):
        if isinstance(idx, int):
            row = self.fetchone()
            if row is None:
                raise IndexError("no more rows")
            if isinstance(row, dict):
                vals = list(row.values())
                return vals[idx] if idx < len(vals) else row
            return row
        raise TypeError(f"unexpected index type: {type(idx)}")


class DBConnector:
    """DuckDB 数据库连接器（本地开发/测试用）

    接口与原 PostgreSQL 版本保持一致，SQL 中可用 ? 占位符。
    远端部署请改用 src.pg_connector.PGConnector。
    """

    def __init__(self, db_path: Optional[str] = None):
        """初始化 DuckDB 连接

        Args:
            db_path: DuckDB 文件路径，默认 data/zenith_quant.duckdb
        """
        self._db_path = str(db_path) if db_path else str(_DEFAULT_DB_PATH)
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        """建立 DuckDB 连接"""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self.conn = duckdb.connect(self._db_path)

    def _ensure_connection(self):
        """DuckDB 为本地文件，无需心跳，保留接口兼容"""
        pass

    def execute_query(self, query: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        """执行查询 SQL，返回字典列表"""
        try:
            with self._lock:
                cur = self.conn.execute(query, params or ())
                cols = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                if rows:
                    return [dict(zip(cols, row)) for row in rows]
                return []
        except Exception as e:
            print(f"[DBConnector] 查询失败: {query[:100]}... 错误: {e}",
                  file=__import__('sys').stderr)
            raise

    def execute_update(self, query: str, params: Optional[Tuple] = None) -> int:
        """执行更新/插入/删除 SQL，返回影响行数"""
        try:
            with self._lock:
                cur = self.conn.execute(query, params or ())
                return cur.rowcount if cur.rowcount >= 0 else 0
        except Exception as e:
            print(f"[DBConnector] 更新失败: {query[:100]}... 错误: {e}",
                  file=__import__('sys').stderr)
            raise

    def execute_many(self, query: str, params_list: List[Tuple]) -> int:
        """批量执行相同的 SQL 语句"""
        try:
            with self._lock:
                cur = self.conn.executemany(query, params_list)
                return cur.rowcount if cur.rowcount >= 0 else 0
        except Exception as e:
            print(f"[DBConnector] 批量更新失败: {query[:100]}... 错误: {e}",
                  file=__import__('sys').stderr)
            raise

    def execute(self, query: str, params: Optional[Tuple] = None):
        """通用 execute 方法，返回兼容接口"""
        query_upper = query.strip().upper()
        if query_upper.startswith('SELECT'):
            rows = self.execute_query(query, params)
            return _QueryResult(rows=rows, rowcount=len(rows))
        else:
            rowcount = self.execute_update(query, params)
            return _QueryResult(rows=[], rowcount=rowcount)

    def get_connection(self):
        """返回底层 DuckDB 连接（供需要直接操作 DuckDB 的场景使用）"""
        return self.conn

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
