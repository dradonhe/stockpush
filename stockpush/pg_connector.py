"""
PostgreSQL 连接器（F5.1 + SysInit 专用）

远端部署使用 psycopg 3 驱动连接 PostgreSQL。
"""

import os
import sys
import threading
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
import psycopg

load_dotenv()


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
                if idx >= len(vals):
                    raise IndexError(f"column index {idx} out of range (max {len(vals)-1})")
                return vals[idx]
            return row
        raise TypeError(f"unexpected index type: {type(idx)}")


class PGConnector:
    """PostgreSQL 数据库连接器（使用 psycopg 3）

    仅供 F5.1 (远端监控) 和 SysInit (系统初始化) 使用。
    """

    _DEFAULT_CFG = {
        'host': '127.0.0.1',
        'port': 5432,
        'dbname': 'zenith_quant',
        'user': 'zenith_quant',
    }

    @classmethod
    def _parse_port(cls, val) -> int:
        try:
            return int(val)
        except (ValueError, TypeError):
            raise ValueError(f"PG_PORT must be an integer, got: {val}")

    @classmethod
    def _get_config(cls) -> dict:
        password = os.getenv('PG_PASSWORD')
        if not password:
            raise RuntimeError(
                "PG_PASSWORD environment variable is not set. "
                "Database password is required for PostgreSQL connection."
            )
        return {
            'host': os.getenv('PG_HOST', cls._DEFAULT_CFG['host']),
            'port': cls._parse_port(os.getenv('PG_PORT', cls._DEFAULT_CFG['port'])),
            'dbname': os.getenv('PG_DB', cls._DEFAULT_CFG['dbname']),
            'user': os.getenv('PG_USER', cls._DEFAULT_CFG['user']),
            'password': password,
        }

    def __init__(self):
        """初始化 PostgreSQL 连接"""
        self._cfg = self._get_config()
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        """建立 PostgreSQL 连接（autocommit 模式）"""
        try:
            self.conn = psycopg.connect(
                host=self._cfg['host'],
                port=self._cfg['port'],
                dbname=self._cfg['dbname'],
                user=self._cfg['user'],
                password=self._cfg['password'],
                client_encoding='utf8',
                autocommit=True,
            )
        except Exception as e:
            print(f"[PGConnector] 连接失败: {e}", file=sys.stderr)
            raise

    def _ensure_connection(self):
        """检查连接状态，断开时自动重连"""
        try:
            with self.conn.cursor() as cur:
                cur.execute('SELECT 1')
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self._connect()

    def execute_query(self, query: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        """执行查询 SQL，返回字典列表"""
        self._ensure_connection()
        query = query.replace('?', '%s')
        try:
            with self._lock:
                with self.conn.cursor() as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()
                    if rows:
                        cols = [desc[0] for desc in cur.description]
                        return [dict(zip(cols, row)) for row in rows]
                    return []
        except Exception as e:
            print(f"[PGConnector] 查询失败: {query[:100]}... 错误: {e}",
                  file=sys.stderr)
            raise

    def execute_update(self, query: str, params: Optional[Tuple] = None) -> int:
        """执行更新/插入/删除 SQL，返回影响行数"""
        self._ensure_connection()
        query = query.replace('?', '%s')
        try:
            with self._lock:
                with self.conn.cursor() as cur:
                    cur.execute(query, params)
                    self.conn.commit()
                    return cur.rowcount
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            print(f"[PGConnector] 更新失败: {query[:100]}... 错误: {e}",
                  file=sys.stderr)
            raise

    def execute_many(self, query: str, params_list: List[Tuple]) -> int:
        """批量执行相同的 SQL 语句"""
        self._ensure_connection()
        query = query.replace('?', '%s')
        try:
            with self._lock:
                with self.conn.cursor() as cur:
                    cur.executemany(query, params_list)
                    self.conn.commit()
                    return cur.rowcount
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            print(f"[PGConnector] 批量更新失败: {query[:100]}... 错误: {e}",
                  file=sys.stderr)
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
