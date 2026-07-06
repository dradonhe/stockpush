"""
TF05 v2 — 双均线 SID 状态字节买卖点系统
源码对照: F51/docs/TF05_v2.txt

基于 HMA + MACD 的跨周期状态字节（SID）信号系统。
5M 分析: 5M HMA × 2 + 30M HMA × 2 → SID5 → b51/b52/b53/s51/s52/s53
30M 分析: 30M HMA × 2 + 日线 HMA × 2 → SID30 → b31/b32/b33/s31/s32/s33
第四买卖点: RSI(close,PP) + 日线 HMA 趋势 → b4/s4

用法:
  sig = tf05("588200")                              # symbol → 自动取数
  sig = tf05("588200", N1=35, A0=9)                 # 自定义参数
  sig["mabuy"], sig["masell"]
  sig["b51"], sig["s51"]                            # 逐级信号
  sig["b4"], sig["s4"]                              # 第四买卖点

  # 或直接用 DataFrame
  sig = tf05_from_df(df_5m, df_30m, df_daily)
"""

import sys
sys.path.insert(0, r"/opt/stockpush")

import numpy as np
import pandas as pd
from MyTT import EMA, WMA, HHV, LLV, SMA
from MyTT import REF as _mytt_REF


# ── 底层辅助 ────────────────────────────────────────────────

def _S(val, index=None):
    """MyTT 返回 ndarray（HHV/LLV/EMA/WMA/REF），包装回 Series"""
    if isinstance(val, pd.Series):
        return val
    s = pd.Series(val, dtype=float)
    if index is not None:
        s.index = index
    return s


def _REF(series, n=1):
    """REF 包装：MyTT 返回 ndarray，确保返回 Series"""
    return _S(_mytt_REF(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _CROSS(A, B):
    """CROSS(A,B) — A 上穿 B：A>B 且 REF(A,1) <= REF(B,1)"""
    return (A > B) & (_REF(A, 1) <= _REF(B, 1))


def _EMA(series, n):
    return _S(EMA(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _WMA(series, n):
    return _S(WMA(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _HHV(series, n):
    return _S(HHV(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _LLV(series, n):
    return _S(LLV(series, n),
              index=series.index if hasattr(series, 'index') else None)


def _SMA(series, n, m):
    """SMA(X, N, M) — 移动平均, M/N为权重"""
    return _S(SMA(series, n, m),
              index=series.index if hasattr(series, 'index') else None)


def _P(df):
    """P := (O+REF(C,1)+MAX(REF(H,1),H)+MIN(REF(L,1),L))/4"""
    mh = np.maximum(_mytt_REF(df["high"], 1), df["high"].values)
    ml = np.minimum(_mytt_REF(df["low"], 1), df["low"].values)
    return _S(
        (df["open"] + _mytt_REF(df["close"], 1) + mh + ml) / 4,
        index=df.index,
    )


def _realign(s, target_index):
    """将跨周期 Series 向前填充到主力周期索引 (#period 语义)"""
    df_tmp = pd.DataFrame({'val': s})
    df_tmp['idx'] = s.index
    df_target = pd.DataFrame({'key': target_index})
    result = pd.merge_asof(
        df_target, df_tmp, left_on='key', right_on='idx',
        direction='backward'
    )['val']
    result.index = target_index
    return result


# ── hrama 单线 ────────────────────────────────────────────────

def _hrama_one(series, N, m, MP):
    """hrama.xx1(N, m, MP) — 单条 HMA 线

    TDX 对应:
      X1 = 2*WMA(P, ROUND(m/N*10)) - WMA(P, m)
      NN = ROUND(MP*m/10, 0)
      xx = (HHV(X, NN) + LLV(X, NN)) / 2
      rxx = REF(xx, 1)
    返回 (xx, rxx)
    """
    w1 = _WMA(series, max(int(round(m / N * 10)), 1))
    w2 = _WMA(series, m)
    X = 2 * w1 - w2
    nn = max(int(round(MP * m / 10)), 1)
    xx = (_HHV(X, nn) + _LLV(X, nn)) / 2
    return xx, _REF(xx, 1)


def _macd(close, shortp, longp, m):
    """标准 MACD 计算：返回 DIFF, DEA, MACD_BAR"""
    diff = _EMA(close, shortp) - _EMA(close, longp)
    dea = _EMA(diff, m)
    bar = (diff - dea) * 2
    return diff, dea, bar


def _state_byte(P1, H3, H4, H3P, H4P):
    """计算 SID 状态字节

    TDX:
      B4 = IF(P1>=H3, 16, 0)
      B3 = IF(P1>=H4, 8, 0)
      B2 = IF(H3>=H4, 4, 0)
      B1 = IF(H3>H3P, 2, 0)
      B0 = IF(H4>H4P, 1, 0)
      SID = B4+B3+B2+B1+B0
    """
    return (
        (P1 >= H3).astype(int) * 16
        + (P1 >= H4).astype(int) * 8
        + (H3 >= H4).astype(int) * 4
        + (H3 > H3P).astype(int) * 2
        + (H4 > H4P).astype(int) * 1
    )


# ── 核心计算逻辑 ────────────────────────────────────────────

def _compute(df_5m, df_30m, df_daily, *,
             N1=35, N2=40, N3=35, N4=45,
             A0=9, B0=17, C0=9, D0=27,
             MP1=2, MP2=2, MP3=2, MP4=2,
             LONGP=75, SHORTP=25, M=9,
             PP=12, LL=25, LH=75):
    """
    TF05 核心计算（v2）。

    参数含义同 TF05_v2.txt INPUT:
      N1..N4 — hrama N 参数
      A0..D0 — hrama m 参数
      MP1..MP4 — hrama MP 参数
      LONGP, SHORTP — MACD 长/短周期
      M — MACD 信号线周期
      PP — RSI 周期（第四买卖点）
      LL — RSI 超卖线（第四买点触发阈值）
      LH — RSI 超买线（第四卖点触发阈值）
    """
    # ════════════════════════════════════════════════════════════
    # 1. 5M 分析
    # ════════════════════════════════════════════════════════════

    P5 = _P(df_5m)                          # 5M P 值 (P = (O+h11+L11+ref(c,1))/4)
    C5 = df_5m['close']                     # 5M 收盘价

    # 1a. 5M MACD（使用 CLOSE）
    _, _, macd2 = _macd(C5, SHORTP, LONGP, M)

    # 1b. 5M HMA 双线
    h1, rh1 = _hrama_one(P5, N1, A0, MP1)   # 5M 快线
    h2, rh2 = _hrama_one(P5, N1, B0, MP1)   # 5M 慢线

    # 1c. 30M 跨周期 HMA 双线（对齐到 5M）
    P30 = _P(df_30m)                         # 30M P 值
    h3_raw, rh3_raw = _hrama_one(P30, N2, C0, MP2)
    h4_raw, rh4_raw = _hrama_one(P30, N2, D0, MP2)
    h3  = _realign(h3_raw,  P5.index)
    rh3 = _realign(rh3_raw, P5.index)
    h4  = _realign(h4_raw,  P5.index)
    rh4 = _realign(rh4_raw, P5.index)

    # 1d. 5M 状态字节 SID5
    P1_5 = rh2                              # P1_5 = REF(h2,1)
    H3_5 = h3
    H4_5 = h4
    H3P_5 = rh3
    H4P_5 = rh4
    sid5 = _state_byte(P1_5, H3_5, H4_5, H3P_5, H4P_5)

    # 1e. 5M 交叉信号
    cross_up5 = _CROSS(h1, h2)              # h1 上穿 h2
    cross_dn5 = _CROSS(h2, h1)              # h2 上穿 h1

    # 1f. 5M 买卖点
    b51 = cross_up5 & (macd2 < 0) & sid5.isin([16, 20, 12, 28])
    b52 = cross_up5 & (macd2 < 0) & sid5.isin([17, 25])
    b53 = cross_up5 & (macd2 < 0) & sid5.isin([29, 7])
    # s51/s52/s53 在 30M 日线 HMA 计算之后执行

    # 1g. 5M 止损/止盈参考位
    bp5 = _LLV(df_5m['low'], 10) * 0.98
    sp5 = _HHV(df_5m['high'], 10) * 1.02

    # ════════════════════════════════════════════════════════════
    # 2. 30M 分析
    # ════════════════════════════════════════════════════════════

    C30 = df_30m['close']                   # 30M 收盘价

    # 2a. 30M MACD
    _, _, macd30 = _macd(C30, SHORTP, LONGP, M)

    # 2b. 30M HMA 双线
    h1_30, rh1_30 = _hrama_one(P30, N2, A0, MP2)
    h2_30, rh2_30 = _hrama_one(P30, N2, B0, MP2)

    # 2c. 日线跨周期 HMA 双线（对齐到 30M）
    Pd = _P(df_daily)                        # 日线 P 值
    h3_30_raw, rh3_30_raw = _hrama_one(Pd, N3, C0, MP3)
    h4_30_raw, rh4_30_raw = _hrama_one(Pd, N3, D0, MP3)
    h3_30  = _realign(h3_30_raw,  P30.index)
    rh3_30 = _realign(rh3_30_raw, P30.index)
    h4_30  = _realign(h4_30_raw,  P30.index)
    rh4_30 = _realign(rh4_30_raw, P30.index)
    h3_30_at_5m = _realign(h3_30_raw, P5.index)     # 日线 HMA 对齐到 5M
    rh3_30_at_5m = _realign(rh3_30_raw, P5.index)   # 前一日日线 HMA (rxx1 = REF at daily level)
    h4_30_at_5m = _realign(h4_30_raw, P5.index)
    rh4_30_at_5m = _realign(rh4_30_raw, P5.index)

    # 2d. 30M 状态字节 SID30
    P1_30 = rh2_30
    H3P_30 = rh3_30
    H4P_30 = rh4_30
    sid30 = _state_byte(P1_30, h3_30, h4_30, H3P_30, H4P_30)

    # 2e. 30M 交叉信号
    cross_up30 = _CROSS(h1_30, h2_30)
    cross_dn30 = _CROSS(h2_30, h1_30)

    # 2f. 30M 买卖点
    b31 = cross_up30 & (macd30 < 0) & sid30.isin([16, 20, 12, 28])
    b32 = cross_up30 & (macd30 < 0) & sid30.isin([17, 25])
    b33 = cross_up30 & (macd30 < 0) & sid30.isin([29, 7])
    s31 = cross_dn30 & (macd30 > 0) & sid30.isin([11, 15, 3, 19])
    s32 = cross_dn30 & (macd30 > 0) & sid30.isin([6, 14])
    s33 = cross_dn30 & (macd30 > 0) & sid30.isin([2, 25])

    # 2g. 30M 止损/止盈参考位
    bp30 = bp5 * 0.98   # 在 30M 上进一步缩窄
    sp30 = sp5 * 1.02

    # 2h. 5M 卖点（依赖日线 HMA，故在 30M 分析之后计算）
    s51 = cross_dn5 & (macd2 > 0) & sid5.isin([11, 15, 3, 19]) & ((h3_30_at_5m < rh3_30_at_5m) | (h4_30_at_5m < rh4_30_at_5m) | (h3_30_at_5m <= h4_30_at_5m))
    s52 = cross_dn5 & (macd2 > 0) & sid5.isin([6, 14])
    s53 = cross_dn5 & (macd2 > 0) & sid5.isin([2, 25])

    # ════════════════════════════════════════════════════════════
    # 3. 统一买卖信号
    # ════════════════════════════════════════════════════════════

    def _sig_status(cond_b1, cond_b2, cond_b3, cond_s1, cond_s2, cond_s3):
        """生成信号状态文本"""
        buy = pd.Series("", index=cond_b1.index)
        buy[cond_b1] = "第1类买点"
        buy[cond_b2] = "第2类买点"
        buy[cond_b3] = "第3类买点"
        # 优先级: 高类覆盖低类
        buy[cond_b3 & cond_b2] = "第2类买点"
        buy[cond_b2 & cond_b1] = "第1类买点"
        buy[cond_b3 & cond_b1] = "第1类买点"
        sell = pd.Series("", index=cond_s1.index)
        sell[cond_s1] = "第1类卖点"
        sell[cond_s2] = "第2类卖点"
        sell[cond_s3] = "第3类卖点"
        sell[cond_s3 & cond_s2] = "第2类卖点"
        sell[cond_s2 & cond_s1] = "第1类卖点"
        sell[cond_s3 & cond_s1] = "第1类卖点"
        return buy, sell

    buy5_status, sell5_status = _sig_status(b51, b52, b53, s51, s52, s53)
    buy30_status, sell30_status = _sig_status(b31, b32, b33, s31, s32, s33)

    # ════════════════════════════════════════════════════════════
    # 3b. 第四买卖点 (RSI + 日线 HMA 趋势)
    # ════════════════════════════════════════════════════════════
    # TDX v2: RSIH = SMA(MAX(C-REF(C,1),0),PP,1)/SMA(ABS(C-REF(C,1)),PP,1)*100
    rsih = (_SMA(np.maximum(C5 - _REF(C5, 1), 0), PP, 1)
            / _SMA(np.abs(C5 - _REF(C5, 1)), PP, 1) * 100)
    ll_ser = pd.Series(LL, index=rsih.index)
    lh_ser = pd.Series(LH, index=rsih.index)
    b4 = _CROSS(rsih, ll_ser) & (
        (h3_30_at_5m >= rh3_30_at_5m) | (h4_30_at_5m >= rh4_30_at_5m)
    )
    s4 = _CROSS(lh_ser, rsih) & (
        (h3_30_at_5m < rh3_30_at_5m) | (h4_30_at_5m < rh4_30_at_5m)
    )
    bp4 = bp30 * 0.98
    sp4 = sp30 * 1.02

    mabuy_5 = b51 | b52 | b53 | b4
    masell_5 = s51 | s52 | s53 | s4
    mabuy_30 = b31 | b32 | b33
    masell_30 = s31 | s32 | s33


    # ════════════════════════════════════════════════════════════
    # 4. 返回结果
    # ════════════════════════════════════════════════════════════

    return {
        # === 5M ===
        "h1": h1, "h2": h2,
        "h3": h3, "h4": h4,
        "macd2": macd2,
        "sid5": sid5,
        "b51": b51, "b52": b52, "b53": b53,
        "s51": s51, "s52": s52, "s53": s53,
        "bp5": bp5, "sp5": sp5,
        "buy5_status": buy5_status,
        "sell5_status": sell5_status,
        "mabuy_5": mabuy_5, "masell_5": masell_5,
        # === 30M ===
        "h1_30": h1_30, "h2_30": h2_30,
        "h3_30": h3_30, "h4_30": h4_30,
        "macd30": macd30,
        "sid30": sid30,
        "b31": b31, "b32": b32, "b33": b33,
        "s31": s31, "s32": s32, "s33": s33,
        "bp30": bp30, "sp30": sp30,
        "buy30_status": buy30_status,
        "sell30_status": sell30_status,
        "mabuy_30": mabuy_30, "masell_30": masell_30,
        # === 第四买卖点 ===
        "b4": b4, "s4": s4,
        "bp4": bp4, "sp4": sp4,
        "rsih": rsih,
        # === 综合 ===
        "mabuy": mabuy_5 | mabuy_30,
        "masell": masell_5 | masell_30,
        # === 原始数据 ===
        "open": df_5m['open'],
        "close": df_5m['close'],
    }


# ── 数据量指引 ──────────────────────────────────────────────

def tf05_min_bars():
    """返回 tf05 正确计算需要的最少数据量（行数），默认参数下。
    5M: MACD(EMA(75)需74行 + EMA(DIFF,9)需8行) = 83
         hrama(N1=35,A0=9) w2=WMA(9)=8行
         → max(83, 9) = 83
    30M: hrama(N2=40,C0=9) = 9 行
         标准 6x 安全系数
    日线: hrama(N3=35,C0=9) w2=WMA(9)=8行
          hrama(N4=45,D0=27) w2=WMA(27)=26行
          → 30
    """
    return {'m5': 83 * 6, 'm30': 9 * 6, 'daily': 30 * 6}


# ── 从 PostgreSQL 取数 ──────────────────────────────────────

def _fetch_data(symbol, min_5m=None, min_30m=None, min_daily=None):
    """从 PostgreSQL 获取 symbol 的 5M + 30M + 日线数据。

    Args:
        symbol: 股票代码
        min_5m: 限制取尾部 N 行 5M 数据（None=全量）
        min_30m: 限制取尾部 N 行 30M 数据
        min_daily: 限制取尾部 N 行日线数据
    """
    from stockpush.pg_connector import PGConnector
    conn = PGConnector()

    def _fetch(table, limit=None):
        sql = (
            f"SELECT ts, open, high, low, close FROM {table} "
            f"WHERE symbol = '{symbol}' ORDER BY ts"
        )
        if limit is not None:
            sql = f"SELECT * FROM ({sql} DESC LIMIT {limit}) sub ORDER BY ts"
        rows = conn.execute_query(sql)
        if not rows:
            raise ValueError(f"{table} 无 {symbol} 数据")
        df = pd.DataFrame(rows)
        for c in ['open', 'high', 'low', 'close']:
            df[c] = df[c].astype(float)
        df['ts'] = pd.to_datetime(df['ts'])
        df = df.set_index('ts')
        df.index.name = None
        return df

    df5 = _fetch("tb_raw_5m", min_5m)
    df30 = _fetch("tb_raw_30m", min_30m)
    dfd = _fetch("tb_raw_1d", min_daily)

    conn.close()
    return df5, df30, dfd


# ── 公共入口 ────────────────────────────────────────────────

def tf05(symbol, *,
         N1=35, N2=40, N3=35, N4=45,
         A0=9, B0=17, C0=9, D0=27,
         MP1=2, MP2=2, MP3=2, MP4=2,
         LONGP=75, SHORTP=25, M=9,
         PP=12, LL=25, LH=75,
         min_5m=None, min_30m=None, min_daily=None):
    """一站式入口：取数 + 计算

    Args:
        symbol: 股票代码（如 "588200"）
        可选覆盖参数见 _compute() 签名
        min_*: 限制取尾部的行数（None=全量）

    Returns:
        _compute() 返回的完整结果 dict
    """
    df_5m, df_30m, df_daily = _fetch_data(symbol, min_5m, min_30m, min_daily)
    return _compute(
        df_5m, df_30m, df_daily,
        N1=N1, N2=N2, N3=N3, N4=N4,
        A0=A0, B0=B0, C0=C0, D0=D0,
        MP1=MP1, MP2=MP2, MP3=MP3, MP4=MP4,
        LONGP=LONGP, SHORTP=SHORTP, M=M,
        PP=PP, LL=LL, LH=LH,
    )


def tf05_from_df(df_5m, df_30m, df_daily, *,
                 N1=35, N2=40, N3=35, N4=45,
                 A0=9, B0=17, C0=9, D0=27,
                 MP1=2, MP2=2, MP3=2, MP4=2,
                 LONGP=75, SHORTP=25, M=9,
                 PP=12, LL=25, LH=75):
    """从预取 DataFrame 计算

    Args:
        df_5m: 5M DataFrame（需含 open, close, high, low）
        df_30m: 30M DataFrame
        df_daily: 日线 DataFrame
    """
    return _compute(
        df_5m, df_30m, df_daily,
        N1=N1, N2=N2, N3=N3, N4=N4,
        A0=A0, B0=B0, C0=C0, D0=D0,
        MP1=MP1, MP2=MP2, MP3=MP3, MP4=MP4,
        LONGP=LONGP, SHORTP=SHORTP, M=M,
        PP=PP, LL=LL, LH=LH,
    )


def tf05_calculate(symbol: str, period: str, start: str, end: str,
                   param_set_id: int = 0) -> dict:
    """TF05 信号计算（新契约）。

    自动从 PostgreSQL 取 5M+30M+日线 数据，计算后返回标准信号格式。
    参数通过 param_set_id 从 tb_signal_function_params 获取。

    Args:
        symbol: 股票代码
        period: 周期（"5m" 或 "30m"，影响输出信号筛选）
        start: 起始日期 "YYYY-MM-DD"
        end: 截止日期 "YYYY-MM-DD"
        param_set_id: 参数集 ID

    Returns:
        {'signals': [...]}
    """
    from stockpush.services.function_registry import FunctionRegistry
    registry = FunctionRegistry()
    params = registry.get_params('tf05', param_set_id)
    int_keys = ['N1', 'N2', 'N3', 'N4', 'A0', 'B0', 'C0', 'D0',
                'MP1', 'MP2', 'MP3', 'MP4', 'LONGP', 'SHORTP', 'M',
                'PP', 'LL', 'LH']
    typed = {}
    for k in int_keys:
        v = params.get(k)
        if v is not None:
            typed[k] = int(v)

    df5, df30, dfd = _fetch_data(symbol)
    result = _compute(df5, df30, dfd, **typed)

    import pandas as pd
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end) + pd.Timedelta(days=1)
    signals = []

    close = result.get("close")

    # 按 period 筛选输出时间维度
    if period in ("5m", "5M"):
        buy_flags = result.get("mabuy_5")
        sell_flags = result.get("masell_5")
        buy_status = result.get("buy5_status")
        sell_status = result.get("sell5_status")
    else:
        buy_flags = result.get("mabuy_30")
        sell_flags = result.get("masell_30")
        buy_status = result.get("buy30_status")
        sell_status = result.get("sell30_status")

    open_ser = result.get("open")
    if buy_flags is not None and hasattr(buy_flags, "index"):
        for idx_val in buy_flags.index:
            if idx_val < start_dt or idx_val >= end_dt:
                continue
            if buy_flags.at[idx_val]:
                status = buy_status.at[idx_val] if buy_status is not None else "买点"
                price = float(close.at[idx_val]) if close is not None and idx_val in close.index else 0.0
                signals.append({
                    'time': idx_val,
                    'direction': 'buy',
                    'price': price,
                    'open_price': float(open_ser.at[idx_val]) if open_ser is not None and idx_val in open_ser.index else 0.0,
                    'indicator': status,
                    'buy_status': status,
                })
            if sell_flags is not None and sell_flags.at[idx_val]:
                status = sell_status.at[idx_val] if sell_status is not None else "卖点"
                price = float(close.at[idx_val]) if close is not None and idx_val in close.index else 0.0
                signals.append({
                    'time': idx_val,
                    'direction': 'sell',
                    'price': price,
                    'open_price': float(open_ser.at[idx_val]) if open_ser is not None and idx_val in open_ser.index else 0.0,
                    'indicator': status,
                    'sell_status': status,
                })

    return {'signals': signals}


# ── 自定义函数系统 (4.x) 适配 ──────────────────────────────

def TF05(symbol_or_df=None):
    """自定义函数系统适配入口。兼容两种调用：

    1) 测试 (4.4): TF05(df) — df 被忽略，自动取第一只自选股计算
    2) 正式: TF05("588200") — 指定 symbol 计算

    返回 {buy_point, buy_status, sell_point, sell_status}
    buy_status/sell_status 为 "第N类买点/卖点" 文本，无信号时为空串。
    """
    if isinstance(symbol_or_df, str):
        symbol = symbol_or_df
    else:
        try:
            from stockpush.pg_connector import PGConnector
            db = PGConnector()
            rows = db.execute_query(
                "SELECT symbol FROM tb_stock_pool ORDER BY symbol LIMIT 1"
            )
            db.close()
            symbol = rows[0]['symbol'] if rows else "588200"
        except Exception:
            symbol = "588200"

    try:
        result = tf05(symbol)
        close = result.get("close", pd.Series(dtype=float))
    except Exception:
        return {
            "buy_point": False, "buy_status": "",
            "sell_point": False, "sell_status": "",
        }

    # 取最后一个有效信号
    mabuy = result.get("mabuy", pd.Series(dtype=bool))
    masell = result.get("masell", pd.Series(dtype=bool))
    buy5_status = result.get("buy5_status", pd.Series(dtype=str))
    sell5_status = result.get("sell5_status", pd.Series(dtype=str))
    b4 = result.get("b4", pd.Series(dtype=bool))
    s4 = result.get("s4", pd.Series(dtype=bool))

    buy_status = ""
    sell_status = ""
    if not mabuy.empty:
        # 取最近一个买入信号
        buy_idx = mabuy[mabuy].index
        if len(buy_idx) > 0:
            last_buy = buy_idx[-1]
            # 先查是否已有分类买卖点状态
            raw = buy5_status.at[last_buy] if buy5_status is not None and last_buy in buy5_status.index else ""
            if raw:
                buy_status = raw
            elif b4.at[last_buy] if last_buy in b4.index else False:
                buy_status = "第4类买点"

        sell_idx = masell[masell].index
        if len(sell_idx) > 0:
            last_sell = sell_idx[-1]
            raw = sell5_status.at[last_sell] if sell5_status is not None and last_sell in sell5_status.index else ""
            if raw:
                sell_status = raw
            elif s4.at[last_sell] if last_sell in s4.index else False:
                sell_status = "第4类卖点"

    return {
        "buy_point": bool(buy_status),
        "buy_status": buy_status,
        "sell_point": bool(sell_status),
        "sell_status": sell_status,
    }
