"""
MM2 多周期通道 + 多周期MACD 买卖点系统
源码对照: userfunc/mm2_system.txt

日线主图叠加指标。通道: mm1(60)/mm2(180)/mm3(360)
三级 MACD (柱子=2*(DIF-DEA)) + 通道方向 + 动态周期选择信号:
  .B2.1/.S2.1  本级1     .B2.2/.S2.2  本级2
  .B2.21/.S2.21 次级2    .B2.3z/.S2.3z 零轴
  .B1.3s/.S1.3s 顺势     .B2.11/.S2.11 精细1
  .B2.12/.S2.12 精细2

用法:
  sig = mm2("601336")                           # symbol → 自动取日线
  sig = mm2("601336", MM1=60, MM2=180)          # 自定义通道周期
  sig["buy"], sig["sell"]

  # 或用预取 DataFrame
  from stockpush.userfunc import mm2_from_df
  sig = mm2_from_df(df_daily)
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


# ── 底层辅助 ────────────────────────────────────────────────

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
    a_scalar = np.isscalar(A)
    b_scalar = np.isscalar(B)
    if a_scalar and b_scalar:
        return False
    if a_scalar:
        # scalar 上穿 Series: A > B[i] 且 A <= B[i-1]
        return (A > B) & (A <= _REF(B, 1))
    if b_scalar:
        # Series 上穿标量: A[i] > B 且 A[i-1] <= B
        return (A > B) & (_REF(A, 1) <= B)
    return (A > B) & (_REF(A, 1) <= _REF(B, 1))


def _EMA(series, n):
    return _S(EMA(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _HHV(series, n):
    return _S(HHV(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _LLV(series, n):
    return _S(LLV(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _SMA(series, n, m):
    """SMA(X, N, M) — 移动平均, M/N 为权重"""
    return _S(_mytt_SMA(series, n, m),
              index=series.index if hasattr(series, 'index') else None)


def _BARSLAST(cond):
    """BARSLAST(cond) — 距最近一次 cond 为真的周期数。

    返回 float Series；若 cond 从未为真则为 NaN。
    使用 numpy 数组迭代，O(n) 且无 pandas iloc 开销。
    """
    c = cond.values.astype(bool)
    result = np.empty(len(c), dtype=float)
    last_true = -1
    for i in range(len(c)):
        if c[i]:
            last_true = i
        if last_true >= 0:
            result[i] = i - last_true
        else:
            result[i] = np.nan
    return pd.Series(result, index=cond.index)


def _REF_VAR(series, n_series):
    """REF(X, N) — N 为 Series 时逐元素变长回溯。

    对每个 bar i，取 series[i - n_series[i]] 的值。
    n_series 为 NaN 或回溯越界时结果为 NaN。
    使用 numpy 数组迭代，O(n) 且无 pandas iloc 开销。
    """
    vals = series.values
    ns = n_series.values.astype(float)
    result = np.full(len(vals), np.nan, dtype=float)
    for i in range(len(vals)):
        n_val = ns[i]
        if np.isnan(n_val):
            continue
        j = i - int(n_val)
        if 0 <= j < len(vals):
            result[i] = vals[j]
    return pd.Series(result, index=series.index)


def _COUNT(cond, n):
    """COUNT(cond, N) — 最近 N 个周期内 cond 为真的次数。

    N 可为标量或 Series。N 为 NaN/≤0 时返回 0。
    使用前缀和，O(n) 时间复杂度。
    """
    if isinstance(n, pd.Series):
        c = cond.astype(int).values
        ns = n.values.astype(float)
        # 前缀和: prefix[i] = sum(c[0:i])
        prefix = np.empty(len(c) + 1, dtype=np.int64)
        prefix[0] = 0
        np.cumsum(c, out=prefix[1:])
        # 向量化计算每个 bar 的 COUNT
        idx = np.arange(len(c))
        ni = np.where(np.isnan(ns) | (ns <= 0), 0, ns).astype(int)
        starts = np.maximum(0, idx - ni + 1)
        result = (prefix[idx + 1] - prefix[starts]).astype(float)
        return pd.Series(result, index=cond.index)
    else:
        return cond.astype(int).rolling(int(n), min_periods=1).sum().astype(float)


# ── 核心计算逻辑 (纯函数，不碰数据库) ─────────────────────

def _compute(df, *,
             MM1=60, MM2=180, MM3=360):
    """
    MM2 核心计算。接收日线 DataFrame，返回信号 dict。

    参数:
        df:  日线 DataFrame，columns = [open, high, low, close]
        MM1: 短通道周期 (默认 60)
        MM2: 中通道周期 (默认 180)
        MM3: 长通道周期 (默认 360)
    """
    H = df['high']
    L = df['low']
    O = df['open']
    C = df['close']

    # ── 一、通道: SG=HHV 上轨, XG=LLV 下轨 ─────────────────
    SG1 = _HHV(H, MM1);  XG1 = _LLV(L, MM1)
    SG2 = _HHV(H, MM2);  XG2 = _LLV(L, MM2)
    SG3 = _HHV(H, MM3);  XG3 = _LLV(L, MM3)

    # ── 二、基础价格 P (代替 CLOSE) ──────────────────────────
    # H11:=MAX(H,REF(H,1)); L11:=MIN(L,REF(L,1))
    # P1:=(O+H11+L11+REF(C,1))/4; P:=SMA(P1,3,1)
    H11 = np.maximum(H.values, np.asarray(_mytt_REF(H, 1)))
    L11 = np.minimum(L.values, np.asarray(_mytt_REF(L, 1)))
    P1 = (O.values + H11 + L11 + np.asarray(_mytt_REF(C, 1))) / 4.0
    P = _SMA(_S(P1, index=C.index), 3, 1)

    # ── 三、三级 MACD (柱子=2*(DIF-DEA)) ───────────────────
    DIF1 = _EMA(P, 15)  - _EMA(P, 55);   DEA1 = _EMA(DIF1, 5);   MC1 = 2 * (DIF1 - DEA1)
    DIF2 = _EMA(P, 45)  - _EMA(P, 150);  DEA2 = _EMA(DIF2, 3);   MC2 = 2 * (DIF2 - DEA2)
    DIF3 = _EMA(P, 90)  - _EMA(P, 300);  DEA3 = _EMA(DIF3, 3);   MC3 = 2 * (DIF3 - DEA3)

    # ── RSI(14) ──────────────────────────────────────────────
    LC = _REF(C, 1)
    diff_cl = C - LC
    RSIV_num = _S(_mytt_SMA(_S(np.maximum(diff_cl.values, 0), index=C.index), 14, 1),
                  index=C.index)
    RSIV_den = _S(_mytt_SMA(_S(np.abs(diff_cl.values), index=C.index), 14, 1),
                  index=C.index)
    RSIV = RSIV_num / RSIV_den * 100
    # ── RSIH: RSI(12) ────────────────────────────────────────
    # RSIH := SMA(MAX(CLOSE-LC1,0),12,1) / SMA(ABS(CLOSE-LC1),12,1) * 100
    LC1 = _REF(C, 1)
    diff_c1 = C - LC1
    RSIH_num = _S(_mytt_SMA(_S(np.maximum(diff_c1.values, 0), index=C.index), 12, 1),
                  index=C.index)
    RSIH_den = _S(_mytt_SMA(_S(np.abs(diff_c1.values), index=C.index), 12, 1),
                  index=C.index)
    RSIH = RSIH_num / RSIH_den * 100

    # ── 四、前置硬闸门 (按信号级别区分) ─────────────────────
    # GB1/GS1: 本级1 踩mm2轨;  Gb3/Gs3: 顺势 踩mm1轨
    GB1 = _LLV(L, 10) == XG2;  GS1 = _HHV(H, 10) == SG2
    GB2 = _LLV(L, 10) == XG2;  GS2 = _HHV(H, 10) == SG2
    Gb3 = _LLV(L, 15) == XG1;  Gs3 = _HHV(H, 15) == SG1
    # ── RSI 信号踩轨闸门 ────────────────────────────────────
    # Gb4_1: 踩mm1轨; Gb4_2: 踩mm2轨; Gb4_3: 踩mm3轨
    Gb4_1 = _LLV(L, 15) == XG1;  Gs4_1 = _HHV(H, 15) == SG1
    Gb4_2 = _LLV(L, 10) == XG2;  Gs4_2 = _HHV(H, 10) == SG2
    Gb4_3 = _LLV(L, 10) == XG3;  Gs4_3 = _HHV(H, 10) == SG3

    # ── 五、动态周期 T ──────────────────────────────────────
    # 买: 从 H>=SG2 变 H<SG2 起计数;  卖反向
    T_BUY  = _BARSLAST(H >= SG2)
    T_SELL = _BARSLAST(L <= XG2)

    # ── 六、MACD 拐点触发 ───────────────────────────────────
    # 连续两段上升/下降
    MC1_BUY  = (_REF(MC1, 2) > _REF(MC1, 1)) & (MC1 > _REF(MC1, 1))
    MC1_SELL = (_REF(MC1, 2) < _REF(MC1, 1)) & (MC1 < _REF(MC1, 1))
    MC2_BUY  = (_REF(MC2, 2) > _REF(MC2, 1)) & (MC2 > _REF(MC2, 1))
    MC2_SELL = (_REF(MC2, 2) < _REF(MC2, 1)) & (MC2 < _REF(MC2, 1))
    MC3_BUY  = (_REF(MC3, 2) > _REF(MC3, 1)) & (MC3 > _REF(MC3, 1))
    MC3_SELL = (_REF(MC3, 2) < _REF(MC3, 1)) & (MC3 < _REF(MC3, 1))

    # ── 七、按动态周期 T 选择 MACD 判断周期 ─────────────────
    # 0<=T<75 → m1, 75<=T<175 → m2, T>=175 → m3
    USE1_BUY  = T_BUY < 75
    USE2_BUY  = (T_BUY >= 75) & (T_BUY < 175)
    USE3_BUY  = T_BUY >= 175
    USE1_SELL = T_SELL < 75
    USE2_SELL = (T_SELL >= 75) & (T_SELL < 175)
    USE3_SELL = T_SELL >= 175

    MACD_BUY  = (USE1_BUY  & MC1_BUY)  | (USE2_BUY  & MC2_BUY)  | (USE3_BUY  & MC3_BUY)
    MACD_SELL = (USE1_SELL & MC1_SELL) | (USE2_SELL & MC2_SELL) | (USE3_SELL & MC3_SELL)

    # ── 八、三线多空过滤 ────────────────────────────────────
    # 全多/全空 → 丢弃; 至少一多一空才通过
    ALL_LONG  = (MC1 > 0) & (MC2 > 0) & (MC3 > 0)
    ALL_SHORT = (MC1 < 0) & (MC2 < 0) & (MC3 < 0)
    FLT_OK = ~ALL_LONG & ~ALL_SHORT

    # ── 九、通道方向 (BARSLAST 纯跳变点比较) ────────────────
    def _channel_dir(SG, XG):
        """返回 (CH_UP, CH_DN, CH_ZD)"""
        sg_n  = _BARSLAST(SG != _REF(SG, 1))
        sg_up = _REF_VAR(SG, sg_n) > _REF_VAR(SG, sg_n + 1)
        sg_dn = _REF_VAR(SG, sg_n) < _REF_VAR(SG, sg_n + 1)
        xg_n  = _BARSLAST(XG != _REF(XG, 1))
        xg_up = _REF_VAR(XG, xg_n) > _REF_VAR(XG, xg_n + 1)
        xg_dn = _REF_VAR(XG, xg_n) < _REF_VAR(XG, xg_n + 1)
        ch_up = sg_up & xg_up
        ch_dn = sg_dn & xg_dn
        ch_zd = ~ch_up & ~ch_dn
        return ch_up, ch_dn, ch_zd

    CH1_UP, CH1_DN, CH1_ZD = _channel_dir(SG1, XG1)
    CH2_UP, CH2_DN, CH2_ZD = _channel_dir(SG2, XG2)
    CH3_UP, CH3_DN, CH3_ZD = _channel_dir(SG3, XG3)

    # ── 十、mm2 买卖点分类 ─────────────────────────────────
    HAS_POS = (MC1 > 0) | (MC2 > 0) | (MC3 > 0)
    HAS_NEG = (MC1 < 0) | (MC2 < 0) | (MC3 < 0)
    MIX_DIR  = HAS_POS & HAS_NEG       # 1=方向不一致, 混合
    SAME_DIR = ~MIX_DIR                 # 1=方向一致(含零轴)

    # ── B2_1/S2_1 本级1: 方向不一致, 踩mm2轨 ──────────────
    B2_1 = GB1 & MACD_BUY  & FLT_OK & MIX_DIR
    S2_1 = GS1 & MACD_SELL & FLT_OK & MIX_DIR

    # ── 本级分离锚点: ref(xg2=xg3,1) and xg2>xg3 ──────────
    MAIN_BUY_T0  = _REF(XG2 == XG3, 1) & (XG2 > XG3)
    MAIN_SELL_T0 = _REF(SG2 == SG3, 1) & (SG2 < SG3)
    T_MB = _BARSLAST(MAIN_BUY_T0)
    T_MS = _BARSLAST(MAIN_SELL_T0)
    # 流产: 锚点启动后、拐点出现前轨缩回相等则作废
    ABORT_B = _COUNT(XG2 == XG3, T_MB) > 0
    ABORT_S = _COUNT(SG2 == SG3, T_MS) > 0

    # ── B2_2/S2_2 本级2: 分离锚点后首个 MACD 拐点 ─────────
    B2_2 = (GB2 & MACD_BUY & FLT_OK & SAME_DIR
            & (T_MB > 0)
            & (_COUNT(MACD_BUY, T_MB + 1) == 1)
            & ~ABORT_B)
    S2_2 = (GS2 & MACD_SELL & FLT_OK & SAME_DIR
            & (T_MS > 0)
            & (_COUNT(MACD_SELL, T_MS + 1) == 1)
            & ~ABORT_S)

    # ── 十一、次级分离 T0 锚点 (mm1 脱离 mm2) ─────────────
    SUB_BUY_T0  = _REF(XG1 == XG2, 1) & (XG1 > XG2)
    SUB_SELL_T0 = _REF(SG1 == SG2, 1) & (SG1 < SG2)
    T_SUBMB = _BARSLAST(SUB_BUY_T0)
    T_SUBMS = _BARSLAST(SUB_SELL_T0)
    SUBABORT_B = _COUNT(XG1 == XG2, T_SUBMB) > 0
    SUBABORT_S = _COUNT(SG1 == SG2, T_SUBMS) > 0

    # ── B2_21/S2_21 次级2: 次级分离锚点后首个 MACD 拐点 ───
    B2_21 = (GB2 & MACD_BUY & FLT_OK & SAME_DIR
             & (T_SUBMB > 0)
             & (_COUNT(MACD_BUY, T_SUBMB + 1) == 1)
             & ~SUBABORT_B)
    S2_21 = (GS2 & MACD_SELL & FLT_OK & SAME_DIR
             & (T_SUBMS > 0)
             & (_COUNT(MACD_SELL, T_SUBMS + 1) == 1)
             & ~SUBABORT_S)

    # ── B1_3s/S1_3s mm1 顺势 ──────────────────────────────
    # 踩mm1轨 + 通道方向 + XG1>XG2 + m1 上穿/下穿零轴
    B1_3s = (Gb3 & _CROSS(MC1, 0)
             & (CH1_UP | (CH1_ZD & CH2_UP))
             & (XG1 > XG2) & FLT_OK)
    S1_3s = (Gs3 & _CROSS(0, MC1)
             & (CH1_DN | (CH1_ZD & CH2_DN))
             & (SG1 < SG2) & FLT_OK)

    # ── B2_3z/S2_3z 零轴买卖点: 方向一致 + 轨未分离 ───────
    B2_3z = (GB1 & MACD_BUY & FLT_OK & SAME_DIR
             & (XG2 <= XG3) & (XG1 <= XG2))
    S2_3z = (GS1 & MACD_SELL & FLT_OK & SAME_DIR
             & (SG2 >= SG3) & (SG1 >= SG2))

    # ── 十二、mm2 精细触发 ─────────────────────────────────
    M3_CROSS_UP = _CROSS(DIF3, 0)
    M3_CROSS_DN = _CROSS(0, DIF3)
    T_M3UP = _BARSLAST(M3_CROSS_UP)
    T_M3DN = _BARSLAST(M3_CROSS_DN)

    # B2_11: xg1=xg2, m3 上穿零轴后首个 m1 一类买点
    #        MC2>-0.02 且 MC1>0, 不要求踩轨
    B2_11 = ((XG1 == XG2)
             & (T_M3UP > 0)
             & (_COUNT(MC1_BUY,  T_M3UP + 1) == 1) & MC1_BUY
             & (_COUNT(MC3_SELL, T_M3UP + 1) == 0)
             & (MC2 > -0.02) & (MC1 > 0) & FLT_OK)

    # S2_11: sg1=sg2, m3 下穿零轴后首个 m1 一类卖点
    #        MC2<0.02 且 MC1<0, 不要求踩轨
    S2_11 = ((SG1 == SG2)
             & (T_M3DN > 0)
             & (_COUNT(MC1_SELL, T_M3DN + 1) == 1) & MC1_SELL
             & (_COUNT(MC3_BUY,  T_M3DN + 1) == 0)
             & (MC2 < 0.02) & (MC1 < 0) & FLT_OK)

    # B2_12: xg1=xg2, m3<0 且一类买且 m1>0, MC2>-0.02
    B2_12 = ((XG1 == XG2)
             & (MC3 < 0) & MC3_BUY
             & (MC2 > -0.02) & (MC1 > 0) & FLT_OK)

    # S2_12: sg1=sg2, m3>0 且一类卖且 m1<0, MC2<0.02
    S2_12 = ((SG1 == SG2)
             & (MC3 > 0) & MC3_SELL
             & (MC2 < 0.02) & (MC1 < 0) & FLT_OK)
    # ── b4/s4 RSI 顺势 ─────────────────────────────────────
    # b4: RSIH上穿23 + 踩轨 + (本级升 或 (本级震且上级升))
    b4 = (((Gb4_1 & (CH1_UP | (CH1_ZD & CH2_UP)))
           | (Gb4_2 & (CH2_UP | (CH2_ZD & CH3_UP)))
           | (Gb4_3 & (CH3_UP | CH3_ZD)))
          & _CROSS(RSIH, 23))
    # s4: RSIH下穿78 + 踩轨 + (本级跌 或 (本级震且上级跌))
    s4 = (((Gs4_1 & (CH1_DN | (CH1_ZD & CH2_DN)))
           | (Gs4_2 & (CH2_DN | (CH2_ZD & CH3_DN)))
           | (Gs4_3 & (CH3_DN | CH3_ZD)))
          & _CROSS(78, RSIH))

    # ── 综合买卖信号 ────────────────────────────────────────
    buy  = B2_1 | B2_2 | B2_21 | B1_3s | B2_3z | B2_11 | B2_12 | b4
    sell = S2_1 | S2_2 | S2_21 | S1_3s | S2_3z | S2_11 | S2_12 | s4

    # ── 信号标签 (多信号同bar用 + 拼接) ────────────────────
    buy_label = (
        B2_1.map({True: '.B2.1', False: ''})
        + B2_2.map({True: '+.B2.2', False: ''})
        + B2_21.map({True: '+.B2.21', False: ''})
        + B1_3s.map({True: '+.B1.3s', False: ''})
        + B2_3z.map({True: '+.B2.3z', False: ''})
        + B2_11.map({True: '+.B2.11', False: ''})
        + B2_12.map({True: '+.B2.12', False: ''})
        + b4.map({True: '+.b4', False: ''})
    ).str.lstrip('+')

    sell_label = (
        S2_1.map({True: '.S2.1', False: ''})
        + S2_2.map({True: '+.S2.2', False: ''})
        + S2_21.map({True: '+.S2.21', False: ''})
        + S1_3s.map({True: '+.S1.3s', False: ''})
        + S2_3z.map({True: '+.S2.3z', False: ''})
        + S2_11.map({True: '+.S2.11', False: ''})
        + S2_12.map({True: '+.S2.12', False: ''})
        + s4.map({True: '+.s4', False: ''})
    ).str.lstrip('+')

    return {
        # 通道
        "sg1": SG1, "xg1": XG1,
        "sg2": SG2, "xg2": XG2,
        "sg3": SG3, "xg3": XG3,
        # MACD
        "dif1": DIF1, "dif2": DIF2, "dif3": DIF3,
        "mc1": MC1, "mc2": MC2, "mc3": MC3,
        # RSI
        "rsiv": RSIV, "rsih": RSIH,
        # 通道方向
        "ch1_up": CH1_UP, "ch1_dn": CH1_DN, "ch1_zd": CH1_ZD,
        "ch2_up": CH2_UP, "ch2_dn": CH2_DN, "ch2_zd": CH2_ZD,
        "ch3_up": CH3_UP, "ch3_dn": CH3_DN, "ch3_zd": CH3_ZD,
        # 逐级信号
        "B2_1": B2_1,   "S2_1": S2_1,
        "B2_2": B2_2,   "S2_2": S2_2,
        "B2_21": B2_21, "S2_21": S2_21,
        "B1_3s": B1_3s, "S1_3s": S1_3s,
        "B2_3z": B2_3z, "S2_3z": S2_3z,
        "B2_11": B2_11, "S2_11": S2_11,
        "B2_12": B2_12, "S2_12": S2_12,
        "b4": b4, "s4": s4,
        # 综合
        "buy": buy, "sell": sell,
        "buy_label": buy_label, "sell_label": sell_label,
        # OHLC
        "open": df['open'], "close": df['close'],
    }


# ── 数据量指引 ──────────────────────────────────────────────

def mm2_min_bars():
    """返回 mm2 正确计算需要的最少数据量（行数），默认参数下。

    最长 EMA(300) 需约 750 根日线预热; 最长通道 360 根。
    """
    return {'daily': 800}


# ── 从 PostgreSQL 取数 ──────────────────────────────────────

def _fetch_data(symbol, min_daily=None, period="1d"):
    """从 PostgreSQL 获取 symbol 的 OHLC 数据。

    period: "1m" / "5m" / "1d"
    1m/5m 时自动限制数据量避免慢计算：
      1m → 最多1500根 (约6个交易日, 足够 EMA(300) 稳定)
      5m → 最多1200根 (约10个交易日)
      1d → 全量拉取 (原有行为)
    """
    from stockpush.pg_connector import PGConnector

    table_map = {"1m": "tb_raw_1m", "5m": "tb_raw_5m", "1d": "tb_raw_1d"}
    table = table_map.get(period, "tb_raw_1d")

    limit_map = {"1m": 1500, "5m": 1200}
    limit = limit_map.get(period)
    if min_daily is not None:
        limit = min_daily

    conn = PGConnector()

    if limit is not None:
        sql = (f"SELECT * FROM ("
               f"SELECT ts, open, high, low, close FROM {table} "
               f"WHERE symbol = '{symbol}' ORDER BY ts DESC LIMIT {limit}"
               f") sub ORDER BY ts")
    else:
        sql = (f"SELECT ts, open, high, low, close FROM {table} "
               f"WHERE symbol = '{symbol}' ORDER BY ts")

    rows = conn.execute_query(sql)
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


# ── 公共入口 ────────────────────────────────────────────────

def mm2(symbol, *, MM1=60, MM2=180, MM3=360, min_daily=None):
    """一站式入口：取日线 + 计算。

    Args:
        symbol:    股票代码
        MM1:       短通道周期 (默认 60)
        MM2:       中通道周期 (默认 180)
        MM3:       长通道周期 (默认 360)
        min_daily: 限制取尾部 N 行日线数据（None=全量）
    """
    df = _fetch_data(symbol, min_daily=min_daily)
    return _compute(df, MM1=MM1, MM2=MM2, MM3=MM3)


def mm2_from_df(df, *, MM1=60, MM2=180, MM3=360):
    """从预取 DataFrame 计算"""
    return _compute(df, MM1=MM1, MM2=MM2, MM3=MM3)


def mm2_calculate(symbol: str, period: str, start: str, end: str,
                  param_set_id: int = 0) -> dict:
    """MM2 信号计算（新契约）。

    自动从 PostgreSQL 取日线数据，计算后返回标准信号格式。
    参数通过 param_set_id 从 tb_signal_function_params 获取。

    Returns:
        {'signals': [{'time': Timestamp, 'direction': 'buy'|'sell',
                      'price': float, 'indicator': str}, ...]}
    """
    from stockpush.services.function_registry import FunctionRegistry
    registry = FunctionRegistry()
    params = registry.get_params('mm2', param_set_id)

    int_keys = ['MM1', 'MM2', 'MM3']
    typed = {}
    for k in int_keys:
        v = params.get(k)
        if v is not None:
            typed[k] = int(v)

    df = _fetch_data(symbol, period=period)
    result = _compute(df, **typed)

    start_dt = pd.Timestamp(start) if start else pd.Timestamp.min
    end_dt   = (pd.Timestamp(end) + pd.Timedelta(days=1)) if end else pd.Timestamp.max
    signals  = []

    buy       = result.get("buy")
    sell      = result.get("sell")
    buy_label = result.get("buy_label")
    sell_label = result.get("sell_label")
    close     = result.get("close")
    open_ser  = result.get("open")

    if buy is not None and hasattr(buy, "index"):
        for idx_val in buy.index:
            if idx_val < start_dt or idx_val >= end_dt:
                continue
            if buy.at[idx_val]:
                label = buy_label.at[idx_val] if buy_label is not None else "买点"
                price = (float(close.at[idx_val])
                         if close is not None and idx_val in close.index else 0.0)
                signals.append({
                    'time': idx_val,
                    'direction': 'buy',
                    'price': price,
                    'open_price': (float(open_ser.at[idx_val])
                                   if open_ser is not None and idx_val in open_ser.index
                                   else 0.0),
                    'indicator': label,
                    'buy_status': label,
                })
            if sell is not None and sell.at[idx_val]:
                label = sell_label.at[idx_val] if sell_label is not None else "卖点"
                price = (float(close.at[idx_val])
                         if close is not None and idx_val in close.index else 0.0)
                signals.append({
                    'time': idx_val,
                    'direction': 'sell',
                    'price': price,
                    'open_price': (float(open_ser.at[idx_val])
                                   if open_ser is not None and idx_val in open_ser.index
                                   else 0.0),
                    'indicator': label,
                    'sell_status': label,
                })

    return {'signals': signals}


# ── 自定义函数系统 (4.x) 适配 ──────────────────────────────

def MM2(symbol=None, *, period="1d", start="", end="", param_set_id=0, **_kw):
    """自定义函数系统适配入口。

    正式调用: MM2(symbol="601336", period="1d", ...)
    测试场景: MM2() — 自动取第一只自选股

    返回 {buy_point, buy_status, sell_point, sell_status}
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
        result = mm2_calculate(symbol, period, start, end, param_set_id)
        signals = result.get("signals", [])
    except Exception:
        signals = []

    buy_status  = ""
    sell_status = ""
    for s in signals:
        if s["direction"] == "buy" and not buy_status:
            buy_status = s.get("buy_status", "买点")
        elif s["direction"] == "sell" and not sell_status:
            sell_status = s.get("sell_status", "卖点")
    return {
        "buy_point":  bool(buy_status),
        "buy_status": buy_status,
        "sell_point": bool(sell_status),
        "sell_status": sell_status,
    }
