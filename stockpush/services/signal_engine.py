"""
Signal Engine - 动态加载并执行自定义信号计算函数

功能：
- 动态加载自定义函数（使用 importlib）
- 缓存已加载的函数，避免重复导入
- 执行信号计算
- 提取买卖信号

Example:
    from stockpush.services.signal_engine import init_signal_engine, get_signal_engine

    # 初始化信号引擎
    init_signal_engine("stockpush.userfunc.MF05", "mf05_from_df", {"N1": 40, "M1": 27, "MP1": 3})

    # 获取引擎实例
    engine = get_signal_engine()

    # 计算信号
    result = engine.calculate(df)

    # 提取信号
    signals = engine.extract_signals(result, "600000")
"""

import importlib
import logging
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class SignalEngine:
    """信号计算引擎"""

    def __init__(self):
        self._func: Optional[Any] = None
        self._module_path: Optional[str] = None
        self._func_name: Optional[str] = None
        self._params: Dict[str, Any] = {}
        self._signal_type: str = "fma"  # "fma" | "mf30"

    @property
    def signal_type(self) -> str:
        """当前信号类型: 'fma'（单DF）或 'mf30'（30M+日线）"""
        return self._signal_type

    @staticmethod
    def _detect_type(module_path: str, func_name: str) -> str:
        """根据 module_path/func_name 识别信号类型"""
        if module_path == "stockpush.userfunc.MF30" and func_name in ("mf30_from_df", "mf30"):
            return "mf30"
        return "fma"

    def load_function(
        self, module_path: str, func_name: str, params: Dict[str, Any]
    ) -> bool:
        """
        动态加载信号计算函数
        Args:
            module_path: 模块路径，如 "stockpush.userfunc.MF05"
            func_name: 函数名，如 "calculate"
            params: 函数参数字典
        Returns:
            是否加载成功
        """
        try:
            module = importlib.import_module(module_path)
            self._func = getattr(module, func_name)
            self._module_path = module_path
            self._func_name = func_name
            self._params = params
            self._signal_type = self._detect_type(module_path, func_name)
            logger.info(
                f"Signal function loaded: {module_path}.{func_name}, "
                f"type={self._signal_type}, params={params}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load signal function: {e}")
            self._func = None
            return False

    def calculate(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        执行已加载的信号计算函数。
        MF30 模式需额外传入 df_daily:
            engine.calculate(df_30m, df_daily=df_daily)
        Args:
            df: 主周期 K 线 DataFrame
            **kwargs: MF30 模式传入 df_daily=...
        Returns:
            计算结果 DataFrame
        Raises:
            RuntimeError: 如果未加载函数
        """
        if self._func is None:
            raise RuntimeError("Signal function not loaded.")
        return self._func(df, **self._params, **kwargs)

    def extract_signals(
        self, result_df: pd.DataFrame, symbol: str
    ) -> list:
        """
        从计算结果中提取买卖信号。
        FMA 模式: 查找 turnup/turndown 列
        MF30 模式: 查找 mabuy/masell 列
        Returns:
            信号列表 [{signal, symbol, time, type}, ...]
        """
        signals = []

        if self._signal_type == "mf30":
            # MF30: bool Series
            if "mabuy" in result_df.columns:
                for t in result_df.index[result_df["mabuy"]]:
                    signals.append({"signal": "buy", "symbol": symbol, "time": t, "type": "mabuy"})
            if "masell" in result_df.columns:
                for t in result_df.index[result_df["masell"]]:
                    signals.append({"signal": "sell", "symbol": symbol, "time": t, "type": "masell"})
        else:
            # FMA: int 0/1 列
            for col, sig in [("turnup", "buy"), ("turndown", "sell")]:
                if col in result_df.columns:
                    for idx in result_df.index[result_df[col] == 1]:
                        tv = result_df.at[idx, "time"] if "time" in result_df.columns else idx
                        signals.append({"signal": sig, "symbol": symbol, "time": tv, "type": col})

        return signals

    def test_function(
        self,
        module_path: str,
        func_name: str,
        params: Dict[str, Any],
        test_df: pd.DataFrame = None,
    ) -> dict:
        """
        加载并测试信号函数

        Args:
            module_path: 模块路径
            func_name: 函数名
            params: 函数参数
            test_df: 测试数据，None 时自动生成 OHLC 示例数据

        Returns:
            {success, result, signals, message}
        """
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
        except Exception as e:
            return {"success": False, "message": f"函数加载失败: {e}"}

        if test_df is None:
            import pandas as pd
            import numpy as np
            dates = pd.date_range(end=pd.Timestamp.today(), periods=200, freq='D')
            test_df = pd.DataFrame({
                'open': np.random.randn(200).cumsum() + 100,
                'high': np.random.randn(200).cumsum() + 102,
                'low': np.random.randn(200).cumsum() + 98,
                'close': np.random.randn(200).cumsum() + 100,
                'volume': np.abs(np.random.randn(200) * 1000000),
                'amount': np.abs(np.random.randn(200) * 10000000),
            }, index=dates)

        try:
            result_df = func(test_df, **params)
            signals = self.extract_signals(result_df, "")
            result_dict = {}
            if not result_df.empty:
                for col in result_df.columns:
                    result_dict[col] = result_df[col].tolist()
            return {
                "success": True,
                "result": result_dict,
                "signals": signals,
            }
        except Exception as e:
            return {"success": False, "message": f"函数执行失败: {e}"}

    @property
    def is_loaded(self) -> bool:
        """检查函数是否已加载"""
        return self._func is not None

    @property
    def current_config(self) -> Dict[str, Any]:
        """获取当前加载的配置"""
        return {
            "module_path": self._module_path,
            "func_name": self._func_name,
            "params": self._params.copy(),
            "signal_type": self._signal_type,
        }


# 全局单例
_signal_engine: Optional[SignalEngine] = None


def get_signal_engine() -> SignalEngine:
    """
    获取 SignalEngine 单例实例

    Returns:
        SignalEngine 实例
    """
    global _signal_engine
    if _signal_engine is None:
        _signal_engine = SignalEngine()
    return _signal_engine


def init_signal_engine(
    module_path: str, func_name: str, params: Dict[str, Any]
) -> bool:
    """
    初始化全局信号引擎（单例模式）

    Args:
            module_path: 模块路径，如 "stockpush.userfunc.MF05"
        func_name: 函数名，如 "calculate"
        params: 函数参数字典

    Returns:
        是否初始化成功
    """
    engine = get_signal_engine()
    return engine.load_function(module_path, func_name, params)
