"""
MM2 I5 v3 — 通道5倍递进 + 10信号买卖点系统
源码对照: userfunc/mm2_i5_tdx.txt

四通道(5倍递进): mm1(30)/mm2(150)/mm3(750)/mm4(3750)
合成价格P → 三级MACD + RSIH(12)
10信号:
  .B1A/.S1A  CORE OR 三MACD共振 + 分离窗口 + 四态过滤
  .B1B/.S1B  通道回踩/反弹 + 顺势通道 + RSI
  .B41/.S41   RSI型mm1级 (需分离窗口, 无冷却)
  .B42/.S42   RSI型mm2级
  .B2/.S2     踩轨+分离锚
同一bar买卖点合并输出 (direction='both').

用法:
  sig = mm2_i5("601336")
  sig = mm2_i5("601336", TH=23)
  sig["buy"], sig["sell"]

  # 或用预取 DataFrame
  from stockpush.userfunc import mm2_i5_from_df
  sig = mm2_i5_from_df(df_daily)
"""

import sys
import os as _os
_project_root = _os.path.normpath(
    _os.path.join(_os.path.dirname(__file__), '..', '..')
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import numpy as np
import pandas as pd
from MyTT import EMA, HHV, LLV, SMA as _mytt_SMA
from MyTT import REF as _mytt_REF
import logging
log = logging.getLogger(__name__)


# —— 底层辅助 ————————————————————————————————————————————————

def _S(val, index=None):
    """MyTT 返回 ndarray（HHV/LLV/EMA/WMA/REF），包装回 Series"""
    if isinstance(val, pd.Series):
        s = val
    else:
        s = pd.Series(val)
    if index is not None and len(s) == len(index):
        s.index = index
    return s


def _REF(series, n=1):
    """REF 包装：MyTT 返回 ndarray，确保返回 Series"""
    return _S(_mytt_REF(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _CROSS(A, B):
    """CROSS(A, B) — A 上穿 B。A/B 可为标量或 Series。"""
    if np.isscalar(A) and np.isscalar(B):
        return False
    if np.isscalar(A):
        A_val = A
        A_arr = np.full(len(B), A_val) if hasattr(B, '__len__') else None
        if A_arr is not None:
            A = pd.Series(A_arr, index=B.index)
    if np.isscalar(B):
        B_val = B
        B_arr = np.full(len(A), B_val) if hasattr(A, '__len__') else None
        if B_arr is not None:
            B = pd.Series(B_arr, index=A.index)
    return (A > B) & (_REF(A, 1) <= _REF(B, 1))


def _EMA(series, n):
    return _S(EMA(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _HHV(series, n):
    """HHV — n > len(series) 时退化为 expanding max"""
    if n > len(series):
        return _S(series.expanding(min_periods=1).max(),
                  index=series.index if hasattr(series, 'index') else None)
    return _S(HHV(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _LLV(series, n):
    """LLV — n > len(series) 时退化为 expanding min"""
    if n > len(series):
        return _S(series.expanding(min_periods=1).min(),
                  index=series.index if hasattr(series, 'index') else None)
    return _S(LLV(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _SMA(series, n, m):
    """SMA(X, N, M) — 移动平均, M/N 为权重"""
    return _S(_mytt_SMA(series, n, m),
              index=series.index if hasattr(series, 'index') else None)


def _BARSLAST(cond):
    """BARSLAST(cond) — 距最近一次 cond 为真的周期数"""
    c_arr = cond.values.astype(np.bool_)
    n = len(c_arr)
    result = np.empty(n, dtype=np.float64)
    last_true = -1
    for i in range(n):
        if c_arr[i]:
            last_true = i
        if last_true >= 0:
            result[i] = float(i - last_true)
        else:
            result[i] = np.nan
    return pd.Series(result, index=cond.index)


def _REF_VAR(series, n_series):
    """REF(X, N) — N 为 Series 时逐元素变长回溯。

    对每个 bar i，取 series[i - n_series[i]] 的值。
    n_series 为 NaN 或回溯越界时结果为 NaN。
    使用 numpy fancy-indexing 向量化实现。
    """
    vals = series.values.astype(np.float64)
    ns = n_series.values.astype(np.float64)
    n = len(vals)
    target = np.arange(n) - ns
    valid = ~np.isnan(ns) & (target >= 0) & (target < n)
    result = np.full(n, np.nan)
    result[valid] = vals[target[valid].astype(int)]
    return pd.Series(result, index=series.index)

def _COUNT(cond, n):
    """COUNT(cond, N) — 最近 N 个周期内 cond 为真的次数。

    N 可为标量或 Series。N 为 NaN/≤0 时返回 0。
    使用前缀和，O(n) 时间复杂度。
    """
    if isinstance(n, pd.Series):
        c = cond.astype(int).values
        ns = n.values.astype(float)
        prefix = np.empty(len(c) + 1, dtype=np.int64)
        prefix[0] = 0
        np.cumsum(c, out=prefix[1:])
        idx = np.arange(len(c))
        ni = np.where(np.isnan(ns) | (ns <= 0), 0, ns).astype(int)
        starts = np.maximum(0, idx - ni + 1)
        result = (prefix[idx + 1] - prefix[starts]).astype(float)
        return pd.Series(result, index=cond.index)
    else:
        return cond.astype(int).rolling(int(n), min_periods=1).sum().astype(float)

def _channel_dir(SG, XG):
    """返回 (CH_UP, CH_DN, CH_ZD) — 通道方向判断。

    对每个 bar，比较 SG/XG 上一次跳变前与跳变时的值，
    判断通道是扩张(ch_up)、收缩(ch_dn)还是震荡(ch_zd)。
    每个 SG/XG 各仅调用 _REF_VAR 两次（而非之前每次比较都调用）。
    """
    sg_n  = _BARSLAST(SG != _REF(SG, 1))
    sg_ref  = _REF_VAR(SG, sg_n)
    sg_ref1 = _REF_VAR(SG, sg_n + 1)
    sg_up = sg_ref > sg_ref1
    sg_dn = sg_ref < sg_ref1

    xg_n  = _BARSLAST(XG != _REF(XG, 1))
    xg_ref  = _REF_VAR(XG, xg_n)
    xg_ref1 = _REF_VAR(XG, xg_n + 1)
    xg_up = xg_ref > xg_ref1
    xg_dn = xg_ref < xg_ref1

    ch_up = sg_up & xg_up
    ch_dn = sg_dn & xg_dn
    ch_zd = ~ch_up & ~ch_dn
    return ch_up, ch_dn, ch_zd


# —— 核心计算逻辑 (纯函数，不碰数据库) —————————————————————

def _compute(df, *,
             MM1=30, MM2=150, MM3=750, MM4=3750,
             TH=23):
    """
    MM2 I5 核心计算。接收日线 DataFrame，返回信号 dict。

    参数:
        df:   日线 DataFrame，columns = [open, high, low, close]
        MM1:  短通道周期 (默认 30)
        MM2:  中通道周期 (默认 150)
        MM3:  长通道周期 (默认 750)
        MM4:  超长通道周期 (默认 3750)
        TH:   RSI 买入阈值 (默认 23, ETF 请用 25)
    """
    H = df['high']
    L = df['low']
    O = df['open']
    C = df['close']

    # —— 一、四通道(5倍递进): SG=HHV 上轨, XG=LLV 下轨 —————
    SG1 = _HHV(H, MM1);  XG1 = _LLV(L, MM1)
    SG2 = _HHV(H, MM2);  XG2 = _LLV(L, MM2)
    SG3 = _HHV(H, MM3);  XG3 = _LLV(L, MM3)
    SG4 = _HHV(H, MM4);  XG4 = _LLV(L, MM4)

    # —— 二、合成价格 P, 三级MACD, RSI —————————————————————
    # H11:=MAX(H,REF(H,1)); L11:=MIN(L,REF(L,1))
    # P1:=(O+H11+L11+REF(C,1))/4; P:=SMA(P1,3,1)
    H11 = np.maximum(H.values, np.asarray(_mytt_REF(H, 1)))
    L11 = np.minimum(L.values, np.asarray(_mytt_REF(L, 1)))
    P1 = (O.values + H11 + L11 + np.asarray(_mytt_REF(C, 1))) / 4.0
    P = _SMA(_S(P1, index=C.index), 3, 1)

    # 三级MACD (柱子=2*(DIF-DEA))
    DIF1 = _EMA(P, 24)  - _EMA(P, 84);   DEA1 = _EMA(DIF1, 5);  MC1 = 2 * (DIF1 - DEA1)
    DIF2 = _EMA(P, 60)  - _EMA(P, 210);  DEA2 = _EMA(DIF2, 3);  MC2 = 2 * (DIF2 - DEA2)
    DIF3 = _EMA(P, 284) - _EMA(P, 620);  DEA3 = _EMA(DIF3, 3);  MC3 = 2 * (DIF3 - DEA3)

    # RSIH: RSI(12) — 基于 CLOSE (非 P1, 与 mm2_system 不同)
    # LC:=REF(C,1); DIFC:=C-LC; RSIH:=SMA(MAX(DIFC,0),12,1)/SMA(ABS(DIFC),12,1)*100
    C_prev = _REF(C, 1)
    diff_c = C - C_prev
    RSIH_num = _S(_mytt_SMA(_S(np.maximum(diff_c.values, 0), index=C.index), 12, 1),
                  index=C.index)
    RSIH_den = _S(_mytt_SMA(_S(np.abs(diff_c.values), index=C.index), 12, 1),
                  index=C.index)
    RSIH = RSIH_num / RSIH_den * 100

    # —— 三、MACD拐点 ——————————————————————————————————————
    # 连续两段上升/下降
    MC1_BUY  = (_REF(MC1, 2) > _REF(MC1, 1)) & (MC1 > _REF(MC1, 1))
    MC1_SELL = (_REF(MC1, 2) < _REF(MC1, 1)) & (MC1 < _REF(MC1, 1))
    MC2_BUY  = (_REF(MC2, 2) > _REF(MC2, 1)) & (MC2 > _REF(MC2, 1))
    MC2_SELL = (_REF(MC2, 2) < _REF(MC2, 1)) & (MC2 < _REF(MC2, 1))
    MC3_BUY  = (_REF(MC3, 2) > _REF(MC3, 1)) & (MC3 > _REF(MC3, 1))
    MC3_SELL = (_REF(MC3, 2) < _REF(MC3, 1)) & (MC3 < _REF(MC3, 1))

    # —— 四、三MACD多空背离(MIX_DIR) ———————————————————————
    MIX_DIR = ((MC1 > 0) | (MC2 > 0) | (MC3 > 0)) & ((MC1 < 0) | (MC2 < 0) | (MC3 < 0))

    # —— 五、MACD拐点窗口 ——————————————————————————————————
    N = 5
    # 任一MACD拐点 — B1B/S1B用 (注: 当前公式未直接使用RB/RS于信号, 保留供参考)
    RB = _COUNT(MC1_BUY | MC2_BUY | MC3_BUY, N) > 0
    RS = _COUNT(MC1_SELL | MC2_SELL | MC3_SELL, N) > 0
    # 三MACD共振(三柱同时拐头) — B1A/S1A用
    RB3 = (_COUNT(MC1_BUY, N) > 0) & (_COUNT(MC2_BUY, N) > 0) & (_COUNT(MC3_BUY, N) > 0)
    RS3 = (_COUNT(MC1_SELL, N) > 0) & (_COUNT(MC2_SELL, N) > 0) & (_COUNT(MC3_SELL, N) > 0)

    # —— 六、动态周期T —————————————————————————————————————
    T1 = _BARSLAST(H >= SG2)
    T2 = _BARSLAST(L <= XG2)
    # M_T_B / M_T_S — 公式定义但未在信号中使用，保留供参考
    M_T_B = ((T1 < 30) & MC1_BUY & (MC1 < 0)) \
        | ((T1 >= 30) & (T1 < 80) & MC2_BUY & (MC2 < 0)) \
        | ((T1 >= 80) & MC3_BUY & (MC3 < 0))
    M_T_S = ((T2 < 30) & MC1_SELL & (MC1 > 0)) \
        | ((T2 >= 30) & (T2 < 80) & MC2_SELL & (MC2 > 0)) \
        | ((T2 >= 80) & MC3_SELL & (MC3 > 0))

    # —— 七、通道方向 ——————————————————————————————————————

    CH1_UP, CH1_DN, CH1_ZD = _channel_dir(SG1, XG1)
    CH2_UP, CH2_DN, CH2_ZD = _channel_dir(SG2, XG2)
    CH3_UP, CH3_DN, CH3_ZD = _channel_dir(SG3, XG3)
    CH4_UP, CH4_DN, CH4_ZD = _channel_dir(SG4, XG4)

    # —— 八、通道多空 ——————————————————————————————————————
    # 级别判断: 本级上升 或(震荡且上级上升)
    CH_B1_BULL = CH1_UP | (CH1_ZD & CH2_UP)
    CH_B1_BEAR = CH1_DN | (CH1_ZD & CH2_DN)
    CH_B2_BULL = CH2_UP | (CH2_ZD & (CH3_UP | (CH3_ZD & CH4_UP)))
    CH_B2_BEAR = CH2_DN | (CH2_ZD & (CH3_DN | (CH3_ZD & CH4_DN)))

    # 顺势通道(B1B/S1B用)
    TREND_BULL = CH1_UP | (CH1_ZD & CH2_UP)
    TREND_BEAR = CH1_DN | (CH1_ZD & CH2_DN)

    # —— 九、通道分离锚点 ——————————————————————————————————
    # SEP1: mm1脱离mm2 (B1A/S1A/B41/S41用)
    SEP1_B = _REF(XG1 == XG2, 1) & (XG1 > XG2)
    T_SEP1 = _BARSLAST(SEP1_B)
    SEP1_S = _REF(SG1 == SG2, 1) & (SG1 < SG2)
    T_SEP1S = _BARSLAST(SEP1_S)

    # SEP2: mm2脱离mm3 (B42/S42/B2/S2用, 含流产)
    SEP2_B = _REF(XG2 == XG3, 1) & (XG2 > XG3)
    T_SEP2 = _BARSLAST(SEP2_B)
    ABORT_B = _COUNT(XG2 == XG3, T_SEP2) > 0
    SEP2_S = _REF(SG2 == SG3, 1) & (SG2 < SG3)
    T_SEP2S = _BARSLAST(SEP2_S)
    ABORT_S = _COUNT(SG2 == SG3, T_SEP2S) > 0

    # —— 十、MACD四态过滤 ——————————————————————————————————
    # B1A/B1B: 排除 MC3零下↑MC2零上↑MC1零上↑ (经典陷阱形态)
    B1A_FLT = ~((MC3 < 0) & (MC3 > _REF(MC3, 1))
                & (MC2 > 0) & (MC2 > _REF(MC2, 1))
                & (MC1 > 0) & (MC1 > _REF(MC1, 1)))
    B1B_FLT = B1A_FLT
    # S1A/S1B: 排除 MC3零上↓MC2零下↓MC1零下↓
    S1A_FLT = ~((MC3 > 0) & (MC3 < _REF(MC3, 1))
                & (MC2 < 0) & (MC2 < _REF(MC2, 1))
                & (MC1 < 0) & (MC1 < _REF(MC1, 1)))
    S1B_FLT = S1A_FLT

    # —— 十一、CORE 条件 ———————————————————————————————————
    # CORE: MACD三线方向不一致 + RSI超买超卖区域内
    CORE_B = MIX_DIR & (RSIH < 45)
    CORE_S = MIX_DIR & (RSIH > 50)

    # —— 十二、B1A/S1A — MACD背离/共振 (分离窗口+四态过滤) ——
    _B1A = (CORE_B | RB3) & (T_SEP1 > 0) & (T_SEP1 <= 15) & B1A_FLT & (RSIH < 50)
    _S1A = (CORE_S | RS3) & (T_SEP1S > 0) & (T_SEP1S <= 15) & S1A_FLT & (RSIH > 45)

    # —— 十三、B1B/S1B — 通道回踩/反弹 (无分离窗口, 顺势通道) ——
    _B1B = CORE_B & TREND_BULL & (_LLV(L, 10) == XG1) & (RSIH < 50)
    _S1B = CORE_S & TREND_BEAR & (_HHV(H, 10) == SG1) & S1B_FLT & (RSIH > 45)

    # —— 十四、B41/S41 — RSI型mm1级 (需分离窗口, 无冷却) ———
    _B41 = _CROSS(RSIH, TH) & ((MC1 < 0) | (MC2 < 0) | (MC3 < 0)) & CH_B1_BULL & (T_SEP1 > 0)
    _S41 = _CROSS(75, RSIH) & ((MC1 > 0) | (MC2 > 0) | (MC3 > 0)) & CH_B1_BEAR & (T_SEP1S > 0)
    B41 = _B41
    S41 = _S41

    # —— 十五、B42/S42 — RSI型mm2级 ———————————————————————
    _B42 = _CROSS(RSIH, TH) & ((MC1 < 0) | (MC2 < 0) | (MC3 < 0)) & CH_B2_BULL & (T_SEP2 > 0)
    _S42 = _CROSS(75, RSIH) & ((MC1 > 0) | (MC2 > 0) | (MC3 > 0)) & CH_B2_BEAR & (T_SEP2S > 0)

    # —— 十六、B2/S2 — 踩轨+分离锚 ————————————————————————
    _B2 = CORE_B & (_LLV(L, 10) == XG2) & CH_B2_BULL & (T_SEP2 > 0) & (RSIH < 50)
    _S2 = CORE_S & (_HHV(H, 10) == SG2) & CH_B2_BEAR & (T_SEP2S > 0) & (RSIH > 45)

    # —— 十七、冷却期 ——————————————————————————————————————
    CD = 3
    # B41/S41 无冷却; 其余信号: REF(COUNT(_X, CD), 1) == 0 确保前CD根无信号
    B1A = _B1A & (_REF(_COUNT(_B1A, CD), 1) == 0)
    B1B = _B1B & (_REF(_COUNT(_B1B, CD), 1) == 0)
    # B41 无冷却 — 直接使用
    B42 = _B42 & (_REF(_COUNT(_B42, CD), 1) == 0)
    B2  = _B2  & (_REF(_COUNT(_B2,  CD), 1) == 0)

    S1A = _S1A & (_REF(_COUNT(_S1A, CD), 1) == 0)
    S1B = _S1B & (_REF(_COUNT(_S1B, CD), 1) == 0)
    # S41 无冷却 — 直接使用
    S42 = _S42 & (_REF(_COUNT(_S42, CD), 1) == 0)
    S2  = _S2  & (_REF(_COUNT(_S2,  CD), 1) == 0)

    # —— 综合买卖信号 ——————————————————————————————————————
    buy  = B1A | B1B | B41 | B42 | B2
    sell = S1A | S1B | S41 | S42 | S2

    # —— 信号标签 (多信号同bar用 + 拼接) ——————————————————
    buy_label = (
        B1A.map({True: '.B1A', False: ''})
        + B1B.map({True: '+.B1B', False: ''})
        + B41.map({True: '+.B41', False: ''})
        + B42.map({True: '+.B42', False: ''})
        + B2.map({True: '+.B2', False: ''})
    ).str.lstrip('+')

    sell_label = (
        S1A.map({True: '.S1A', False: ''})
        + S1B.map({True: '+.S1B', False: ''})
        + S41.map({True: '+.S41', False: ''})
        + S42.map({True: '+.S42', False: ''})
        + S2.map({True: '+.S2', False: ''})
    ).str.lstrip('+')

    return {
        # 通道
        "sg1": SG1, "xg1": XG1,
        "sg2": SG2, "xg2": XG2,
        "sg3": SG3, "xg3": XG3,
        "sg4": SG4, "xg4": XG4,
        # MACD
        "dif1": DIF1, "dif2": DIF2, "dif3": DIF3,
        "mc1": MC1, "mc2": MC2, "mc3": MC3,
        # RSI
        "rsih": RSIH,
        # 通道方向
        "ch1_up": CH1_UP, "ch1_dn": CH1_DN, "ch1_zd": CH1_ZD,
        "ch2_up": CH2_UP, "ch2_dn": CH2_DN, "ch2_zd": CH2_ZD,
        "ch3_up": CH3_UP, "ch3_dn": CH3_DN, "ch3_zd": CH3_ZD,
        "ch4_up": CH4_UP, "ch4_dn": CH4_DN, "ch4_zd": CH4_ZD,
        # 逐级信号
        "B1A": B1A, "S1A": S1A,
        "B1B": B1B, "S1B": S1B,
        "B41": B41, "S41": S41,
        "B42": B42, "S42": S42,
        "B2":  B2,  "S2":  S2,
        # 综合
        "buy": buy, "sell": sell,
        "buy_label": buy_label, "sell_label": sell_label,
        # CORE/MIX
        "core_b": CORE_B, "core_s": CORE_S,
        "mix_dir": MIX_DIR,
        # OHLC
        "open": df['open'], "close": df['close'],
    }


# —— 数据量指引 ——————————————————————————————————————————————

def mm2_i5_min_bars():
    """返回 mm2_i5 正确计算需要的最少数据量（行数），默认参数下。

    最长 EMA(620) 需约 1550 根日线预热; 最长通道 3750 根。
    为稳定计算，日线需 4000 根以上。
    """
    return {'daily': 4000}


# —— 从 PostgreSQL 取数 ——————————————————————————————————————

def _fetch_data(symbol, min_daily=None, period="1d"):
    """从 PostgreSQL 获取 symbol 的 OHLC 数据。

    period: "1m" / "5m" / "30m" / "1d"
    1m/5m/30m 时自动限制数据量避免慢计算：
      1m  → 最多4000根 (~16个交易日)
      5m  → 最多4000根 (~83个交易日)
      30m → 最多4000根 (~500个交易日)
      1d  → 全量拉取
    """
    from stockpush.pg_connector import PGConnector

    table_map = {"1m": "tb_raw_1m", "5m": "tb_raw_5m", "30m": "tb_raw_30m", "1d": "tb_raw_1d"}
    table = table_map.get(period, "tb_raw_1d")

    limit_map = {"1m": 4000, "5m": 4000, "30m": 4000}
    limit = limit_map.get(period)
    if min_daily is not None:
        limit = min_daily

    conn = PGConnector()

    if limit is not None:
        sql = (f"SELECT * FROM ("
               f"SELECT ts, open, high, low, close FROM {table} "
               f"WHERE symbol = ? ORDER BY ts DESC LIMIT {limit}"
               f") sub ORDER BY ts")
        params = (symbol,)
    else:
        sql = (f"SELECT ts, open, high, low, close FROM {table} "
               f"WHERE symbol = ? ORDER BY ts")
        params = (symbol,)
    rows = conn.execute_query(sql, params)

    if not rows:
        raise ValueError(f"{table} 无 {symbol} 数据")
    df = pd.DataFrame(rows)
    for c in ['open', 'high', 'low', 'close']:
        df[c] = df[c].astype(float)
    df['ts'] = pd.to_datetime(df['ts'])
    df = df.set_index('ts')
    df.index.name = None

    conn.close()
    return df


# —— 公共入口 ——————————————————————————————————————————————————

def mm2_i5(symbol, *, MM1=30, MM2=150, MM3=750, MM4=3750, TH=23, min_daily=None):
    """一站式入口：取日线 + 计算。

    Args:
        symbol:     股票代码
        MM1-MM4:    通道周期 (默认 30/150/750/3750)
        TH:         RSI买入阈值 (默认 23, ETF请用 25)
        min_daily:  限制取尾部 N 行日线数据（None=全量）
    """
    df = _fetch_data(symbol, min_daily=min_daily)
    return _compute(df, MM1=MM1, MM2=MM2, MM3=MM3, MM4=MM4, TH=TH)


def mm2_i5_from_df(df, *, MM1=30, MM2=150, MM3=750, MM4=3750, TH=23):
    """从预取 DataFrame 计算"""
    return _compute(df, MM1=MM1, MM2=MM2, MM3=MM3, MM4=MM4, TH=TH)


def mm2_i5_calculate(symbol: str, period: str, start: str, end: str,
                     param_set_id: int = 0) -> dict:
    """MM2 I5 信号计算（新契约）。

    自动从 PostgreSQL 取数据（支持 1m/5m/1d），计算后返回标准信号格式。
    参数通过 param_set_id 从 tb_signal_function_params 获取。

    同一 bar 同时有买卖信号时，合并为 direction='both' 的单条信号，
    buy_status 和 sell_status 均填充。

    Returns:
        {'signals': [{'time': Timestamp, 'direction': 'buy'|'sell'|'both',
                      'price': float, 'indicator': str,
                      'buy_status': str, 'sell_status': str}, ...]}
    """
    from stockpush.services.function_registry import FunctionRegistry
    registry = FunctionRegistry()
    params = registry.get_params('mm2_i5', param_set_id)

    int_keys = ['MM1', 'MM2', 'MM3', 'MM4']
    typed = {}
    for k in int_keys:
        v = params.get(k)
        if v is not None:
            typed[k] = int(v)
    # TH 保持为数值 (可为 float)
    if 'TH' in params and params['TH'] is not None:
        typed['TH'] = float(params['TH'])

    df = _fetch_data(symbol, period=period)
    result = _compute(df, **typed)

    # 解析时间窗口
    start_ts = None
    end_ts = None
    if start:
        try:
            start_ts = pd.to_datetime(start)
        except Exception:
            pass
    if end:
        try:
            end_ts = pd.to_datetime(end)
            if end_ts == end_ts.normalize() and len(str(end).strip()) <= 10:
                end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        except Exception:
            pass

    signals = []

    buy       = result.get("buy")
    sell      = result.get("sell")
    buy_label = result.get("buy_label")
    sell_label = result.get("sell_label")
    close     = result.get("close")
    open_ser  = result.get("open")

    if buy is not None and hasattr(buy, "index"):
        for idx_val in buy.index:
            if start_ts is not None and idx_val < start_ts:
                continue
            if end_ts is not None and idx_val > end_ts:
                continue

            is_buy = bool(buy.at[idx_val])
            is_sell = bool(sell is not None and sell.at[idx_val])

            if not is_buy and not is_sell:
                continue

            price_val = (float(close.at[idx_val])
                         if close is not None and idx_val in close.index else 0.0)
            open_val = (float(open_ser.at[idx_val])
                        if open_ser is not None and idx_val in open_ser.index else 0.0)

            b_label = (str(buy_label.at[idx_val])
                       if buy_label is not None and idx_val in buy_label.index
                          and buy_label.at[idx_val] else "")
            s_label = (str(sell_label.at[idx_val])
                       if sell_label is not None and idx_val in sell_label.index
                          and sell_label.at[idx_val] else "")

            if is_buy and is_sell:
                # —— 同一bar买卖点合并输出 —————————————————
                combined_indicator = f"{b_label}+{s_label}" if b_label and s_label else (b_label or s_label)
                signals.append({
                    'time': idx_val,
                    'direction': 'both',
                    'price': price_val,
                    'open_price': open_val,
                    'indicator': combined_indicator,
                    'buy_status': b_label,
                    'sell_status': s_label,
                })
            elif is_buy:
                signals.append({
                    'time': idx_val,
                    'direction': 'buy',
                    'price': price_val,
                    'open_price': open_val,
                    'indicator': b_label,
                    'buy_status': b_label,
                    'sell_status': '',
                })
            elif is_sell:
                signals.append({
                    'time': idx_val,
                    'direction': 'sell',
                    'price': price_val,
                    'open_price': open_val,
                    'indicator': s_label,
                    'buy_status': '',
                    'sell_status': s_label,
                })

    return {'signals': signals}


# —— 自定义函数系统 (4.x) 适配 ———————————————————————————————

def MM2_I5(symbol=None, *, period="1d", start="", end="", param_set_id=0, **_kw):
    """自定义函数系统适配入口。

    正式调用: MM2_I5(symbol="601336", period="1d", ...)
    测试场景: MM2_I5() — 自动取第一只自选股

    返回 {buy_point, buy_status, sell_point, sell_status}
    处理 direction='both' 的合并信号。
    """
    if symbol is None:
        try:
            from stockpush.pg_connector import PGConnector
            db = PGConnector()
            rows = db.execute_query(
                "SELECT symbol FROM tb_stock_pool ORDER BY symbol LIMIT 1"
            )
            db.close()
            symbol = rows[0]['symbol'] if rows else "601336"
        except Exception:
            symbol = "601336"

    try:
        result = mm2_i5_calculate(symbol, period, start, end, param_set_id)
        signals = result.get("signals", [])
    except Exception as e:
        log.warning("MM2_I5(%s) 计算失败: %s", symbol, e)
        signals = []

    buy_status  = ""
    sell_status = ""
    for s in signals:
        d = s.get("direction", "")
        if d in ("buy", "both") and not buy_status:
            buy_status = s.get("buy_status", "买点")
        if d in ("sell", "both") and not sell_status:
            sell_status = s.get("sell_status", "卖点")
        # 两个都拿到了就提前退出
        if buy_status and sell_status:
            break
    return {
        "buy_point":  bool(buy_status),
        "buy_status": buy_status,
        "sell_point": bool(sell_status),
        "sell_status": sell_status,
    }


def get_channel_state_summary(symbol: str, param_set_id: int = 0) -> str:
    """获取 symbol 在 1m/5m/30m 三个周期的通道状态汇总。

    返回 8 状态字符串，格式:
        1m_mm1/1m_mm2/5m_mm1/5m_mm2/30m_mm1/30m_mm2/30m_mm3/30m_mm4
    例: "多/震/空/多/多/空/震/多"
    数据不足或计算失败时对应位置返回 "?"。
    """
    from stockpush.services.function_registry import FunctionRegistry

    # 获取参数（与 mm2_i5_calculate 相同逻辑）
    registry = FunctionRegistry()
    params = registry.get_params('mm2_i5', param_set_id)

    int_keys = ['MM1', 'MM2', 'MM3', 'MM4']
    typed = {}
    for k in int_keys:
        v = params.get(k)
        if v is not None:
            typed[k] = int(v)
    if 'TH' in params and params['TH'] is not None:
        typed['TH'] = float(params['TH'])

    states = []

    for period in ["1m", "5m", "30m"]:
        try:
            df = _fetch_data(symbol, period=period)
            result = _compute(df, **typed)

            # mm1
            ch1_up = result.get("ch1_up")
            ch1_dn = result.get("ch1_dn")
            if ch1_up is not None and len(ch1_up) > 0:
                idx = ch1_up.index[-1]
                if ch1_up.at[idx]:
                    states.append("多")
                elif ch1_dn is not None and ch1_dn.at[idx]:
                    states.append("空")
                else:
                    states.append("震")
            else:
                states.append("?")

            # mm2
            ch2_up = result.get("ch2_up")
            ch2_dn = result.get("ch2_dn")
            if ch2_up is not None and len(ch2_up) > 0:
                idx = ch2_up.index[-1]
                if ch2_up.at[idx]:
                    states.append("多")
                elif ch2_dn is not None and ch2_dn.at[idx]:
                    states.append("空")
                else:
                    states.append("震")
            else:
                states.append("?")

            # mm3, mm4 仅 30m
            if period == "30m":
                for ch_key in ["ch3", "ch4"]:
                    ch_up = result.get(f"{ch_key}_up")
                    ch_dn = result.get(f"{ch_key}_dn")
                    if ch_up is not None and len(ch_up) > 0:
                        idx = ch_up.index[-1]
                        if ch_up.at[idx]:
                            states.append("多")
                        elif ch_dn is not None and ch_dn.at[idx]:
                            states.append("空")
                        else:
                            states.append("震")
                    else:
                        states.append("?")
        except Exception:
            # 此周期计算失败，填充 ?
            fill_count = 4 if period == "30m" else 2
            states.extend(["?"] * fill_count)

    return "/".join(states)
