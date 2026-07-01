"""F51 Function Registry — 函数注册中心

管理自定义函数的注册、参数、动态加载和执行。
"""
import importlib
import inspect
import logging
import types
from dataclasses import dataclass
from typing import Optional

from stockpush.pg_connector import PGConnector

logger = logging.getLogger(__name__)


@dataclass
class FunctionInfo:
    id: int
    name: str
    display_name: str
    module_path: str
    func_name: str
    period: str
    param_set_id: int
    enabled: bool

SELECT_COLUMNS = ("id, name, display_name, module_path, func_name, "
                  "period, param_set_id, enabled")


class FunctionRegistry:
    """函数注册中心——管理注册表 + 动态加载执行"""

    def __init__(self, db: Optional[PGConnector] = None):
        self._db = db or PGConnector()
        self._module_cache: dict[str, types.ModuleType] = {}

    # ── helpers ──

    @staticmethod
    def _to_func_info(row: dict) -> FunctionInfo:
        return FunctionInfo(
            id=row['id'],
            name=row['name'],
            display_name=row['display_name'],
            module_path=row['module_path'],
            func_name=row['func_name'],
            period=row['period'],
            param_set_id=row['param_set_id'],
            enabled=row['enabled'],
        )

    # ── 查询 ──

    def get_all(self) -> list[FunctionInfo]:
        """获取所有注册函数"""
        rows = self._db.execute_query(
            f"SELECT {SELECT_COLUMNS} FROM tb_signal_functions ORDER BY name"
        )
        return [self._to_func_info(r) for r in rows]

    def get_by_period(self, period: str) -> list[FunctionInfo]:
        """按周期查询函数（支持 period 前缀匹配，如 '30m' 匹配 '30m:05'）"""
        rows = self._db.execute_query(
            f"SELECT {SELECT_COLUMNS} FROM tb_signal_functions "
            "WHERE period = ? OR period LIKE ? ORDER BY name",
            (period, f"{period}:%")
        )
        return [self._to_func_info(r) for r in rows]

    def get_by_name(self, name: str) -> Optional[FunctionInfo]:
        """按名称查询函数"""
        rows = self._db.execute_query(
            f"SELECT {SELECT_COLUMNS} FROM tb_signal_functions "
            "WHERE name = ? LIMIT 1",
            (name,)
        )
        return self._to_func_info(rows[0]) if rows else None

    def get_enabled(self) -> list[FunctionInfo]:
        """获取所有启用函数"""
        rows = self._db.execute_query(
            f"SELECT {SELECT_COLUMNS} FROM tb_signal_functions "
            "WHERE enabled = true ORDER BY name"
        )
        return [self._to_func_info(r) for r in rows]

    # ── 管理 ──

    def register(
        self,
        name: str,
        display_name: str,
        module_path: str,
        func_name: str,
        period: str,
        param_set_id: int = 0,
        enabled: bool = True,
    ) -> int:
        rows = self._db.execute_query(
            "INSERT INTO tb_signal_functions "
            "(name, display_name, module_path, func_name, period, param_set_id, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (name, display_name, module_path, func_name, period, param_set_id, enabled),
        )
        new_id = rows[0]['id']
        logger.info("Registered function #%d: %s", new_id, name)
        return new_id

    def remove(self, name: str):
        self._db.execute_update(
            "DELETE FROM tb_signal_functions WHERE name = ?",
            (name,),
        )
        logger.info("Removed function: %s", name)

    def set_enabled(self, name: str, enabled: bool):
        self._db.execute_update(
            "UPDATE tb_signal_functions SET enabled = ? WHERE name = ?",
            (enabled, name),
        )
        logger.info("Set enabled=%s for function: %s", enabled, name)

    # ── 参数 ──

    def get_params(self, func_name: str, set_id: int = 0) -> dict:
        rows = self._db.execute_query(
            "SELECT p.param_key, p.param_value "
            "FROM tb_signal_function_params p "
            "JOIN tb_signal_functions f ON f.id = p.func_id "
            "WHERE f.name = ? AND p.set_id = ?",
            (func_name, set_id),
        )
        return {r['param_key']: r['param_value'] for r in rows}
    def set_params(self, func_name: str, set_id: int = 0, params: dict = None):
        """设置函数参数集。先删除旧参数，再插入新参数。"""
        if params is None:
            return
        # Resolve func_id
        rows = self._db.execute_query(
            "SELECT id FROM tb_signal_functions WHERE name = ? LIMIT 1",
            (func_name,),
        )
        if not rows:
            raise ValueError(f"Function not found: {func_name}")
        func_id = rows[0]['id']

        # 事务：先删后插
        self._db.execute_update(
            "DELETE FROM tb_signal_function_params WHERE func_id = ? AND set_id = ?",
            (func_id, set_id),
        )
        for key, value in params.items():
            self._db.execute_update(
                "INSERT INTO tb_signal_function_params (func_id, set_id, param_key, param_value) "
                "VALUES (?, ?, ?, ?)",
                (func_id, set_id, key, str(value)),
            )
        logger.info("Set %d params for %s set_id=%d", len(params), func_name, set_id)

    # ── 验证 ──

    def validate(self, module_path: str, func_name: str) -> dict:
        try:
            module = importlib.import_module(module_path)
        except Exception as e:
            return {'valid': False, 'signature': '', 'error': f"Module load failed: {e}"}

        func = getattr(module, func_name, None)
        if func is None:
            return {
                'valid': False,
                'signature': '',
                'error': f"Function {func_name} not found in {module_path}",
            }

        try:
            sig = inspect.signature(func)
            params = sig.parameters
            required = {'symbol', 'period', 'start', 'end', 'param_set_id'}
            missing = required - set(params.keys())
            if missing:
                return {
                    'valid': False,
                    'signature': str(sig),
                    'error': f"Missing required parameters: {', '.join(sorted(missing))}",
                }
            return {'valid': True, 'signature': str(sig), 'error': ''}
        except (ValueError, TypeError) as e:
            return {
                'valid': False,
                'signature': '',
                'error': f"Signature inspection failed: {e}",
            }

    # ── 执行 ──

    def execute(
        self,
        func_name: str,
        symbol: str,
        period: str,
        start: str,
        end: str,
        param_set_id: int = 0,
    ) -> dict:
        info = self.get_by_name(func_name)
        if info is None:
            raise ValueError(f"Function not found: {func_name}")
        if not info.enabled:
            raise ValueError(f"Function is disabled: {func_name}")

        # Load module (cached)
        if info.module_path not in self._module_cache:
            try:
                self._module_cache[info.module_path] = importlib.import_module(
                    info.module_path
                )
            except Exception as e:
                raise ImportError(
                    f"Failed to load module {info.module_path}: {e}"
                ) from e

        module = self._module_cache[info.module_path]
        func = getattr(module, info.func_name, None)
        if func is None:
            raise AttributeError(
                f"Function {info.func_name} not found in {info.module_path}"
            )

        try:
            return func(
                symbol=symbol,
                period=period,
                start=start,
                end=end,
                param_set_id=param_set_id,
            )
        except Exception as e:
            raise RuntimeError(f"Execution failed for {func_name}: {e}") from e
