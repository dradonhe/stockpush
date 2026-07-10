"""F51 Function Engine — 信号计算引擎

执行注册函数 → 信号归档 → 飞书推送。
"""
import logging
from datetime import datetime
from typing import Callable, Optional

from stockpush.services.function_registry import FunctionRegistry
from stockpush.services.signal_store import SignalStore
from stockpush.services.feishu_pusher import FeishuPusher

logger = logging.getLogger(__name__)


class FunctionEngine:
    """信号计算引擎——执行函数 + 归档 + 推送。

    只负责一轮执行，不管理状态。上层调度器(worker)控制何时运行。
    """

    def __init__(
        self,
        registry: FunctionRegistry,
        store: SignalStore,
        pusher: FeishuPusher,
        symbols_getter: Callable[[], list[str]],
    ):
        """
        Args:
            registry: FunctionRegistry 实例
            store: SignalStore 实例
            pusher: FeishuPusher 实例
            symbols_getter: 函数，返回 [symbol1, symbol2, ...] 列表
        """
        self._registry = registry
        self._store = store
        self._pusher = pusher
        self._symbols_getter = symbols_getter

    @property
    def registry(self) -> FunctionRegistry:
        return self._registry

    def run(self, start: str, end: str):
        """执行一次：遍历所有启用函数跑 [start, end]。

        - 调用 registry.get_enabled() 获取函数列表
        - 对每个函数调用 symbols_getter() 获取标的列表
        - 对每个标的调用 registry.execute()
        - 有信号时调用 store.write_signals() 归档
        - 每个函数的所有信号收集完毕后批量推送
        """
        functions = self._registry.get_enabled()
        if not functions:
            logger.info("No enabled functions to run.")
            return

        symbols = self._symbols_getter()
        if not symbols:
            logger.info("No symbols to process.")
            return

        for func_info in functions:
            logger.info(
                "Running function: %s (period=%s, param_set_id=%d)",
                func_info.name, func_info.period, func_info.param_set_id,
            )
            batch_signals = []  # 收集本函数所有新信号 (符号/名称/周期需外部补)

            for symbol in symbols:
                try:
                    result = self._registry.execute(
                        func_info.name,
                        symbol,
                        func_info.period,
                        start,
                        end,
                        func_info.param_set_id,
                    )
                except Exception:
                    logger.exception(
                        "Function %s failed for %s", func_info.name, symbol
                    )
                    continue

                signals = result.get("signals", [])
                if not signals:
                    logger.info(
                        "  %s: 补运行预警完成，无触发信号", symbol,
                    )
                    continue
                # 过滤：只保留与 end 同一天的信号，拒绝历史信号
                try:
                    end_date = datetime.strptime(end, "%Y-%m-%d %H:%M:%S").date()
                    filtered = []
                    for s in signals:
                        t = s.get('time')
                        if t is None:
                            continue
                        t_dt = t if isinstance(t, datetime) else datetime.strptime(str(t)[:19], "%Y-%m-%d %H:%M:%S")
                        if t_dt.date() == end_date:
                            filtered.append(s)
                    signals = filtered
                except Exception:
                    logger.warning("Signal date filter failed, keeping all signals")
                # 归档 → 返回实际新写入的信号
                try:
                    new_signals = self._store.write_signals(func_info.id, symbol, signals)
                except Exception:
                    logger.exception(
                        "Failed to write signals for %s %s",
                        func_info.name, symbol,
                    )
                    new_signals = []

                # 补充外部字段，收集到批量列表
                for sig in new_signals:
                    sig["symbol"] = symbol
                    sig["name"] = func_info.display_name
                    sig["period"] = func_info.period
                    batch_signals.append(sig)

            # 批量推送本函数的所有信号
            if batch_signals and func_info.push_enabled:
                try:
                    self._pusher.push_signal_batch(
                        batch_signals, func_name=func_info.display_name,
                    )
                except Exception:
                    logger.exception(
                        "Failed to push signal batch for %s", func_info.name,
                    )
    def backtest(
        self,
        func_name: str,
        symbol: str,
        period: str,
        start: str,
        end: str,
        param_set_id: int = 0,
    ) -> list[dict]:
        """回测：纯计算，不归档不推送。"""
        result = self._registry.execute(
            func_name, symbol, period, start, end, param_set_id,
        )
        return result.get("signals", [])

