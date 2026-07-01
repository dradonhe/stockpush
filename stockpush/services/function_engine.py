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
        - 有信号时调用 store.write_signals() + pusher.push_signal()
        - 错误捕获和日志
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
                # 归档 → 返回实际新写入的信号
                try:
                    new_signals = self._store.write_signals(func_info.id, symbol, signals)
                except Exception:
                    logger.exception(
                        "Failed to write signals for %s %s",
                        func_info.name, symbol,
                    )
                    new_signals = []

                # 推送 — 只推新写入的信号（已去重）
                for sig in new_signals:
                    try:
                        raw_time = sig.get("time")
                        if hasattr(raw_time, "strftime"):
                            time_str = raw_time.strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            time_str = str(raw_time)

                        self._pusher.push_signal(
                            symbol=symbol,
                            name=func_info.display_name,
                            signal_type=sig["direction"],
                            time_str=time_str,
                            period=func_info.period,
                            open_price=sig.get("open_price", 0.0),
                            indicator=sig.get("indicator", ""),
                            buy_status=sig.get("buy_status", ""),
                            sell_status=sig.get("sell_status", ""),
                        )
                    except Exception:
                        logger.exception(
                            "Failed to push signal for %s %s",
                            func_info.name, symbol,
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

