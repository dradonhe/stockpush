"""
MF05V2 多因子三级买卖信号 + 第四类RSI买卖点
源码对照: F51/docs/MF30v2.txt

用法:
  sig = mf05("601336")                           # symbol → 自动从 PostgreSQL 取数
  sig = mf05("601336", N1=40, SHORTP=30)         # 自定义参数
  sig["mabuy"], sig["masell"]

  # 或用预取 DataFrame
  from stockpush.userfunc import mf05_from_df
  sig = mf05_from_df(df_5m, df_30m)
"""

import sys
sys.path.insert(0, r"/opt/stockpush")

import numpy as np
import pandas as pd
from MyTT import EMA, WMA, HHV, LLV, SMA as _mytt_SMA
from MyTT import REF as _mytt_REF


# ── 底层辅助 ────────────────────────────────────────────────

def _P(df):
    """P := (O+REF(C,1)+MAX(REF(H,1),H)+MIN(REF(L,1),L))/4"""
    mh = np.maximum(_mytt_REF(df["high"], 1), df["high"])
    ml = np.minimum(_mytt_REF(df["low"], 1), df["low"])
    return (df["open"] + _mytt_REF(df["close"], 1) + mh + ml) / 4


def _REF(series, n=1):
    """REF 包装：MyTT 返回 ndarray，确保返回 Series"""
    return _S(_mytt_REF(series, n),
             index=series.index if hasattr(series, 'index') else None)


def _CROSS(A, B):
    """CROSS(A,B) — A 上穿 B"""
    return (A > B) & (_REF(A, 1) <= _REF(B, 1))


def _S(val, index=None):
    """MyTT 返回 ndarray（HHV/LLV/EMA/WMA/REF），包装回 Series"""
    s = pd.Series(val)
    if index is not None and len(s) == len(index):
        s.index = index

    return s


def _EMA(series, n):
    return _S(EMA(series, n), index=series.index if hasattr(series, 'index') else None)


def _WMA(series, n):
    return _S(WMA(series, n), index=series.index if hasattr(series, 'index') else None)


def _HHV(series, n):
    return _S(HHV(series, n), index=series.index if hasattr(series, 'index') else None)


def _LLV(series, n):
    return _S(LLV(series, n), index=series.index if hasattr(series, 'index') else None)


def _realign(s, target_index):
    """将30M线 Series 向前填充到主力周期索引 (跨周期 #30m 语义)"""
    df_tmp = pd.DataFrame({'val': s})
    df_tmp['idx'] = s.index
    df_target = pd.DataFrame({'key': target_index})
    result = pd.merge_asof(
        df_target, df_tmp, left_on='key', right_on='idx',
        direction='backward'
    )['val']
    result.index = target_index
    return result


# ── 合并公式函数（一次数据通道，带全部通达信参数）────────

def _hrama(series, N1, m1, MP1, N2, m2, MP2):
    """hrama — 一次数据通道算两组均线值
    TDX公式 (hrama.xx1):
      X1 = 2*WMA(P, ROUND(m/N*10)) - WMA(P, m)
      NN = ROUND(MP*m/10, 0)
      xx = (HHV(X, NN) + LLV(X, NN)) / 2
      rxx = REF(xx, 1)
    返回 xx1, rxx1, xx2, rxx2"""

    def _one(N, m, MP):
        w1 = _WMA(series, max(int(round(m / N * 10)), 1))
        w2 = _WMA(series, m)
        X = 2 * w1 - w2
        nn = max(int(round(MP * m / 10)), 1)
        xx = (_HHV(X, nn) + _LLV(X, nn)) / 2
        return xx, _REF(xx, 1)

    xx1, rxx1 = _one(N1, m1, MP1)
    xx2, rxx2 = _one(N2, m2, MP2)
    return xx1, rxx1, xx2, rxx2


def _ugpdx(price, low, high, N, m1, m2):
    """ugpdx — 通达信 Ugpdx 公式
    QSX = EMA((p-LLV(LOW,m1))/(HHV(HIGH,m2)-LLV(LOW,m1))*4, N) * 100
    返回 qsx, qsx > ref(qsx,1), qsx < ref(qsx,1)"""
    MINL = _LLV(low, m1)
    MAXH = _HHV(high, m2)
    qsx = _EMA((price - MINL) / (MAXH - MINL + 1e-10) * 4, N) * 100
    _rref = _REF(qsx, 1)
    return qsx, qsx > _rref, qsx < _rref


# ── 核心计算逻辑 (纯函数，不碰数据库) ─────────────────────

def _compute(df, df_daily, *,
            SHORTP=25, LONGP=75, M=9,
            N1=35, m1=9, MP1=2,
            N2=35, m2=15, MP2=2,
            N3=35, m3=9, MP3=2,
            N4=45, m4=27, MP4=2,
            LH=72, LL=30, PP=13):
    """
    MF05 核心计算。接收 5M + 30M DataFrame，返回信号 dict。
    参数含义同通达信 MF05V2 INPUT (N1..N4, m1..m4, MP1..MP4, LONGP, SHORTP, M, LH, LL, PP)。
    """
    # 1. 当前周期 (5M)
    P = _P(df)
    DIFF = _EMA(P, SHORTP) - _EMA(P, LONGP)
    MACD2 = DIFF - _EMA(DIFF, M)
    XX1, _, XX2, _ = _hrama(P, N1, m1, MP1, N2, m2, MP2)
    R1, _, _ = _ugpdx(P, df['low'], df['high'], 8, 10, 28)

    # 2. 30M线
    Pdf = _P(df_daily)
    DL = df_daily['low']
    DH = df_daily['high']
    XX3, RXX3, XX4, RXX4 = _hrama(Pdf, N3, m3, MP3, N4, m4, MP4)
    R2, R2UP, R2DOWN = _ugpdx(Pdf, DL, DH, 3, 10, 27)

    # 3. 对齐到主力周期
    XX3 = _realign(XX3, df.index)
    RXX3 = _realign(RXX3, df.index)
    XX4 = _realign(XX4, df.index)
    RXX4 = _realign(RXX4, df.index)
    R2 = _realign(R2, df.index)
    R2UP = _realign(R2UP, df.index)
    R2DOWN = _realign(R2DOWN, df.index)

    X3UP = XX3 > RXX3
    X3DOWN = XX3 < RXX3
    X4UP = XX4 > RXX4
    X4DOWN = XX4 < RXX4
    # 4b. 第四类买卖点 (RSI)
    LC = _REF(P, 1)
    RSI1_num = _S(_mytt_SMA(_S(np.maximum((P - LC).values, 0), index=P.index), PP, 1), index=P.index)
    RSI1_den = _S(_mytt_SMA(_S(np.abs(P - LC).values, index=P.index), PP, 1), index=P.index)
    RSI1 = RSI1_num / RSI1_den * 100
    # _CROSS(A, scalar) 不可用，因为 _REF(scalar,1) 返回错误 index 的 Series
    R1buy = (RSI1 > LL) & (_REF(RSI1, 1) <= LL) & (R2UP | X3UP | X4UP)
    R1sell = (LH > RSI1) & (LH <= _REF(RSI1, 1)) & (R2DOWN | X3DOWN | X4DOWN)

    # 4. 买卖信号
    T_B1 = (XX1 > XX3) & (XX1 > XX4) & (XX3 > XX4) & X3DOWN & X4DOWN
    T_S1 = (XX1 < XX3) & (XX1 < XX4) & (XX3 < XX4) & X3UP & X4UP

    B_MA_BASE = _CROSS(XX1, XX2) & ((R1 < 180) | T_B1) & (XX1 > _REF(XX1, 1)) & (MACD2 <= 0)
    S_MA_BASE = _CROSS(XX2, XX1) & ((R1 > 200) | T_S1) & (XX1 < _REF(XX1, 1)) & (MACD2 > 0)

    B_MA3 = B_MA_BASE & ((X3DOWN & (XX1 > XX3)) | X3UP)
    S_MA3 = S_MA_BASE & ((X3UP & (XX1 < XX3)) | X3DOWN)
    B_MA4 = B_MA_BASE & ((X4DOWN & (XX1 > XX4)) | X4UP)
    S_MA4 = S_MA_BASE & ((X4UP & (XX1 < XX4)) | X4DOWN)
    B_RSI = B_MA_BASE & (((R2 >= 60) & (R2 <= 320) & R2UP) | (R2 > 320))
    S_RSI = S_MA_BASE & (((R2 >= 60) & (R2 <= 320) & R2DOWN) | (R2 < 60))

    B_CNT = B_MA3.astype(int) + B_MA4.astype(int) + B_RSI.astype(int)
    S_CNT = S_MA3.astype(int) + S_MA4.astype(int) + S_RSI.astype(int)
    # 5. 买卖点类别标注: B_COUNT 直接就是数字, R1buy/R1sell = 第4类
    def _make_status(cnt, r4, suffix):
        """cnt>0 → '第N类{suffix}', r4=True → '+第4类{suffix}'"""
        c = cnt.astype(str).where(cnt > 0, "")
        c = c.where(c == "", "第" + c + "类")
        r = r4.astype(str).where(r4, "")
        r = r.where(r == "", "+第4类")
        raw = c.where(c == "", c + r)
        raw = raw.where(raw != "", r.str.lstrip("+"))
        return raw + suffix

    buy_status = _make_status(B_CNT, R1buy, "买点")
    sell_status = _make_status(S_CNT, R1sell, "卖点")

    return {
        "xx1": XX1, "xx2": XX2, "xx3": XX3, "xx4": XX4,
        "macd2": MACD2,
        "R1": R1, "R2": R2,
        "RSI1": RSI1,
        "B_MA_BASE": B_MA_BASE, "S_MA_BASE": S_MA_BASE,
        "B_MA3": B_MA3, "S_MA3": S_MA3,
        "B_MA4": B_MA4, "S_MA4": S_MA4,
        "B_RSI": B_RSI, "S_RSI": S_RSI,
        "R1buy": R1buy, "R1sell": R1sell,
        "B_COUNT": B_CNT, "S_COUNT": S_CNT,
        "mabuy": (B_CNT > 0) | R1buy, "masell": (S_CNT > 0) | R1sell,
        "buy_status": buy_status, "sell_status": sell_status,
        "open": df['open'],
        "close": df['close'],
    }


# ── 数据量指引 ──────────────────────────────────────────────

def mf05_min_bars():
    """返回 mf05 正确计算需要的最少数据量（行数），默认参数下。
    5M: MACD(EMA(75)需74行 + EMA(DIFF,9)需8行) = 83
         hrama(N1=35,m1=9) w2=WMA(9)=8行
         ugpdx(N=8,m1=10,m2=28) HHV(28)+EMA(8)=34行
         → max(83,9,34) = 83
    30M: hrama(N4=45,m4=27) w2=WMA(27)=26行 + HHV(X,5)=4行 = 30
         → 30
    安全系数 3x: 5M = 83*3=249, 30M = 30*3=90"""
    return {'main': 83 * 3, 'daily': 30 * 3}


# ── 从 PostgreSQL 取数 ──────────────────────────────────────

def _fetch_data(symbol, min_5m=None, min_daily=None):
    """从 PostgreSQL 获取 symbol 的 5M + 30M 数据。

    Args:
        symbol: 股票代码
        min_5m: 限制取尾部 N 行 5M 数据（None=全量）
        min_daily: 限制取尾部 N 行 30M 数据（None=全量）
    """
    from stockpush.pg_connector import PGConnector
    conn = PGConnector()

    sql = f"SELECT ts, open, high, low, close FROM tb_raw_5m WHERE symbol = '{symbol}' ORDER BY ts"
    if min_5m is not None:
        sql = f"SELECT * FROM ({sql} DESC LIMIT {min_5m}) sub ORDER BY ts"
    rows = conn.execute_query(sql)
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"tb_raw_5m 无 {symbol} 数据")
    for c in ['open', 'high', 'low', 'close']:
        df[c] = df[c].astype(float)
    df['ts'] = pd.to_datetime(df['ts'])
    df = df.set_index('ts')
    df.index.name = None

    sql_d = f"SELECT ts, open, high, low, close FROM tb_raw_30m WHERE symbol = '{symbol}' ORDER BY ts"
    if min_daily is not None:
        sql_d = f"SELECT * FROM ({sql_d} DESC LIMIT {min_daily}) sub ORDER BY ts"
    rows_d = conn.execute_query(sql_d)
    dfd = pd.DataFrame(rows_d)
    if dfd.empty:
        raise ValueError(f"tb_raw_30m 无 {symbol} 数据")
    for c in ['open', 'high', 'low', 'close']:
        dfd[c] = dfd[c].astype(float)
    dfd['ts'] = pd.to_datetime(dfd['ts'])
    dfd = dfd.set_index('ts')
    dfd.index.name = None

    conn.close()
    return df, dfd


# ── 公共入口 ────────────────────────────────────────────────

def mf05(symbol, *,
        N1=35, N2=35, N3=35, N4=45,
        m1=9, m2=15, m3=9, m4=27,
        MP1=2, MP2=2, MP3=2, MP4=2,
        LONGP=75, SHORTP=25, M=9,
        LH=72, LL=30, PP=13,
        min_5m=None, min_daily=None):
    """
    从 PostgreSQL 取 symbol 数据后计算 MF05V2 信号。

    参数:
        symbol — 股票代码，如 "601336"
        min_5m / min_daily — 限制取尾部行数（None=全量）
                              mf05_min_bars() 返回值可用作下限

    关键字参数 — 全部通达信 MF05V2 INPUT，默认值按原公式:
        N1..N4, m1..m4, MP1..MP4 — hrama 参数
        LONGP / SHORTP / M       — MACD 参数
        LH / LL / PP             — 第四类买卖点 RSI 参数

    返回 dict (见 mf05_from_df)
    """
    df, df_daily = _fetch_data(symbol, min_5m=min_5m, min_daily=min_daily)
    return mf05_from_df(df, df_daily, N1=N1, N2=N2, N3=N3, N4=N4,
                        m1=m1, m2=m2, m3=m3, m4=m4,
                        MP1=MP1, MP2=MP2, MP3=MP3, MP4=MP4,
                        LONGP=LONGP, SHORTP=SHORTP, M=M,
                        LH=LH, LL=LL, PP=PP)

def mf05_from_df(df, df_daily, *,
                N1=35, N2=35, N3=35, N4=45,
                m1=9, m2=15, m3=9, m4=27,
                MP1=2, MP2=2, MP3=2, MP4=2,
                LONGP=75, SHORTP=25, M=9,
                LH=72, LL=30, PP=13):
    """
    接收预取的 5M / 30M DataFrame 计算 MF05V2 信号。

    参数:
        df       — 5M K 线 (须含 open/high/low/close, DateTimeIndex)
        df_daily — 30M K 线

    关键字参数同上。

    返回 dict:
        xx1..xx4      — 4 条均线 (xx1/xx2=5M, xx3/xx4=30M)
        macd2         — MACD 柱
        R1, R2, RSI1  — 摆动指标
        B_MA_BASE / S_MA_BASE       — 基础买卖点
        B_MA3..S_RSI               — 三级过滤信号
        R1buy / R1sell             — 第四类买卖点
        B_COUNT / S_COUNT          — 三级计数 (0-3)
        mabuy / masell             — 最终信号 (count > 0 或第四类)
    """
    return _compute(df, df_daily,
                    SHORTP=SHORTP, LONGP=LONGP, M=M,
                    N1=N1, m1=m1, MP1=MP1,
                    N2=N2, m2=m2, MP2=MP2,
                    N3=N3, m3=m3, MP3=MP3,
                    N4=N4, m4=m4, MP4=MP4,
                    LH=LH, LL=LL, PP=PP)


def mf05_calculate(symbol: str, period: str, start: str, end: str,
                   param_set_id: int = 0) -> dict:
    """MF05V2 信号计算（新契约）。

    自动从 PostgreSQL 取 5M+30M 数据，计算后返回标准信号格式。
    参数通过 param_set_id 从 tb_signal_function_params 获取。

    Returns:
        {'signals': [{'time': Timestamp, 'direction': 'buy'|'sell',
                      'price': float, 'indicator': str}, ...]}
    """
    # 取参数
    from stockpush.services.function_registry import FunctionRegistry
    registry = FunctionRegistry()
    params = registry.get_params('mf05', param_set_id)

    # 转换参数类型（数据库存储为字符串）
    int_keys = ['N1', 'N2', 'N3', 'N4', 'm1', 'm2', 'm3', 'm4',
                'MP1', 'MP2', 'MP3', 'MP4', 'LONGP', 'SHORTP', 'M',
                'LH', 'LL', 'PP']
    typed = {}
    for k in int_keys:
        v = params.get(k)
        if v is not None:
            typed[k] = int(v)

    # 取 5M + 30M 全量数据（用于预热）
    df, dfd = _fetch_data(symbol)

    # 调用原有计算
    result = mf05_from_df(df, dfd, **typed)

    # 提取 mabuy/masell 信号，过滤时间范围
    import pandas as pd
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end) + pd.Timedelta(days=1)
    signals = []

    mabuy = result.get("mabuy")
    masell = result.get("masell")
    close = result.get("close")
    buy_status = result.get("buy_status")
    open_ser = result.get("open")
    sell_status = result.get("sell_status")
    if mabuy is not None and hasattr(mabuy, "index"):
        for idx_val in mabuy.index:
            if idx_val < start_dt or idx_val >= end_dt:
                continue
            if mabuy.at[idx_val]:
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
            if masell is not None and masell.at[idx_val]:
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

def MF05(symbol_or_df=None):
    """自定义函数系统适配入口。兼容两种调用：

    1) 测试 (4.4): MF05(df) — df 被忽略，自动取第一只自选股计算
    2) 正式: MF05("601336") — 指定 symbol 计算

    返回 {buy_point, buy_status, sell_point, sell_status}
    buy_status/sell_status 为 "第N类买点"/"第N类卖点" 文本，无信号时为空串。
    """
    if isinstance(symbol_or_df, str):
        symbol = symbol_or_df
    else:
        # 测试场景：取第一只自选股
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
        result = mf05_calculate(symbol, "5m", "", "")
        signals = result.get("signals", [])
    except Exception:
        signals = []

    buy_status = ""
    sell_status = ""
    for s in signals:
        if s["direction"] == "buy" and not buy_status:
            buy_status = s.get("buy_status", "买入")
        elif s["direction"] == "sell" and not sell_status:
            sell_status = s.get("sell_status", "卖出")
    return {
        "buy_point": bool(buy_status),
        "buy_status": buy_status,
        "sell_point": bool(sell_status),
        "sell_status": sell_status,
    }
