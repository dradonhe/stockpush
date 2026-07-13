# MM2 I5 信号策略 设计文档 (L1)

> **对应模块**: `stockpush/userfunc/mm2_i5.py`（日线主策略）、`mm2_i5_min1.py`（分钟线变体）、`mm2_i5_tdx.txt`（通达信对照）
> **更新日期**: 2026-07-13
> **策略定位**: 五倍递进通道（MM1→MM4）+ 三级 MACD + RSIH 的复合多周期信号，共 10 个入场信号 + 2 个出场信号。

---

## 1. 概述

MM2 I5 是一套基于"通道 + MACD + RSI"三维度的信号策略，支持 1m / 5m / 30m / 1d 周期。

| 信号 | 级别/类型 | 方向 | 冷却 | 备注 |
|------|-----------|------|------|------|
| B1A / S1A | mm1 背离/共振 | 买 / 卖 | 3 | 需分离窗口 SEP1 |
| B1B / S1B | mm1 通道回踩/反弹 | 买 / 卖 | 3 | 顺势通道（上级判断） |
| B41 / S41 | mm1 RSI 型 | 买 / 卖 | 无 | 踩轨 + 通道分离 |
| B42 / S42 | mm2 RSI 型 | 买 / 卖 | 3 | 踩轨 + 通道分离 |
| B2 / S2   | mm2 踩轨 + 分离锚 | 买 / 卖 | 3 | 需分离窗口 SEP2 |
| B41_EXIT / S41_EXIT | 出场 | 卖 / 买 | — | BARSLAST 判定 |

> **出场范围说明**：当前仅实现 B41/S41 的出场信号（BARSLAST 算法）。B1B/S1B/B42/S42/B2 暂无独立出场信号。

---

## 2. 输入指标

### 2.1 五倍递进通道
```
MM1=30   MM2=150   MM3=750   MM4=3750
SG1=HHV(H,MM1)  XG1=LLV(L,MM1)     # mm1 上下轨
SG2=HHV(H,MM2)  XG2=LLV(L,MM2)     # mm2 上下轨
SG3=HHV(H,MM3)  XG3=LLV(L,MM3)     # mm3 上下轨
SG4=HHV(H,MM4)  XG4=LLV(L,MM4)     # mm4 上下轨
```

### 2.2 三级 MACD（合成价 P）
```
P1=(O+MAX(H,REF(H,1))+MIN(L,REF(L,1))+REF(C,1))/4;  P=SMA(P1,3,1)
DIF1=EMA(P,24)-EMA(P,84);    DEA1=EMA(DIF1,5);   MC1=2*(DIF1-DEA1)
DIF2=EMA(P,60)-EMA(P,210);   DEA2=EMA(DIF2,3);   MC2=2*(DIF2-DEA2)
DIF3=EMA(P,284)-EMA(P,620);  DEA3=EMA(DIF3,3);   MC3=2*(DIF3-DEA3)
```

### 2.3 RSIH（基于涨跌价的 RSI）
```
LC=REF(C,1);  DIFC=C-LC;
RSIH=SMA(MAX(DIFC,0),12,1)/SMA(ABS(DIFC),12,1)*100
```
阈值参数 `TH`（默认 23，个股；ETF 建议 25）。

---

## 3. 公共判定条件

### 3.1 三 MACD 多空背离（MIX_DIR）
```
MIX_DIR = (MC1>0 | MC2>0 | MC3>0) & (MC1<0 | MC2<0 | MC3<0)
```
即三根 MACD 至少有一根在零轴上、一根在零轴下（方向不一致）。

### 3.2 MACD 拐点窗口（N=5）
```
RB  = COUNT(MC1_BUY|MC2_BUY|MC3_BUY, 5) > 0     # 任一 MACD 拐头（买侧）
RS  = COUNT(MC1_SELL|MC2_SELL|MC3_SELL, 5) > 0  # 任一 MACD 拐头（卖侧）
RB3 = 三 MACD 同时拐头向上                       # 共振（买侧）
RS3 = 三 MACD 同时拐头向下                       # 共振（卖侧）
```

### 3.3 通道方向
每个级别（mm1~mm4）由上下轨同向变动判定：`CHx_UP`（上升）、`CHx_DN`（下降）、`CHx_ZD`（震荡）。

### 3.4 级别多空（本级别 + 上级）
```
CH_B1_BULL = CH1_UP | (CH1_ZD & CH2_UP)
CH_B1_BEAR = CH1_DN | (CH1_ZD & CH2_DN)
CH_B2_BULL = CH2_UP | (CH2_ZD & (CH3_UP | (CH3_ZD & CH4_UP)))
CH_B2_BEAR = CH2_DN | (CH2_ZD & (CH3_DN | (CH3_ZD & CH4_DN)))
```

### 3.5 顺势通道（TREND，B1B/S1B 用）【2026-07-13 更新】
```
TREND_BULL = CH2_UP | (CH2_ZD & CH3_UP)      # 上级(mm2)多 或 (上级震 且 上2级(mm3)多)
TREND_BEAR = CH2_DN | (CH2_ZD & CH3_DN)      # 上级(mm2)空 或 (上级震 且 上2级(mm3)空)
```
> **变更点**：旧逻辑为 `CH1_UP | (CH1_ZD & CH2_UP)`（本级别判断），现改为以上级（mm2/mm3）判趋势，与本级别判定脱钩，使 B1B/S1B 更偏"顺大级别方向回踩"。

### 3.6 通道分离锚点
```
SEP1_B = REF(XG1==XG2,1) & (XG1>XG2);   T_SEP1  = BARSLAST(SEP1_B)   # mm1 脱离 mm2
SEP1_S = REF(SG1==SG2,1) & (SG1<SG2);   T_SEP1S = BARSLAST(SEP1_S)
SEP2_B = REF(XG2==XG3,1) & (XG2>XG3);   T_SEP2  = BARSLAST(SEP2_B)   # mm2 脱离 mm3
SEP2_S = REF(SG2==SG3,1) & (SG2<SG3);   T_SEP2S = BARSLAST(SEP2_S)
```

### 3.7 四态过滤（陷阱形态排除）
```
B1A_FLT = ~(MC3<0 & MC3↑ & MC2>0 & MC2↑ & MC1>0 & MC1↑)   # 排除 零下↑零上↑零上↑ 经典陷阱
S1A_FLT = ~(MC3>0 & MC3↓ & MC2<0 & MC2↓ & MC1<0 & MC1↓)
B1B_FLT = B1A_FLT
S1B_FLT = S1A_FLT
```
> **变更点【2026-07-13 更新】**：`_B1B` 现已补上 `B1B_FLT`（此前漏加，导致买侧 B1B 可能落在经典陷阱形态上，与卖侧 S1B 不对称）。S1B 一直带 `S1B_FLT`，无需改动。

### 3.8 CORE 条件
```
CORE_B = MIX_DIR & (RSIH < 45)
CORE_S = MIX_DIR & (RSIH > 50)
```

---

## 4. 十个入场信号判定

### 4.1 B1A / S1A — MACD 背离/共振（分离窗口 + 四态过滤）
```
_B1A = (CORE_B | RB3) & (T_SEP1>0) & (T_SEP1<=15) & B1A_FLT & (RSIH<50)
_S1A = (CORE_S | RS3) & (T_SEP1S>0) & (T_SEP1S<=15) & S1A_FLT & (RSIH>45)
```
含义：mm1 脱离 mm2 后 1~15 根内，MACD 共振或处于 CORE 区，买入/卖出背离。

### 4.2 B1B / S1B — 通道回踩/反弹（无分离窗口，顺势通道）
```
_B1B = CORE_B & TREND_BULL & (_LLV(L,10)==XG1) & B1B_FLT & (RSIH<50)
_S1B = CORE_S & TREND_BEAR & (_HHV(H,10)==SG1) & S1B_FLT & (RSIH>45)
```
含义：上级(mm2/mm3)趋势向上（TREND_BULL），价格回踩至 mm1 下轨（`_LLV(L,10)==XG1` 等价于 30 周期低点落在近 10 根内），买入；反向卖出。
> `_LLV(L,10)==XG1` 中 `XG1=LLV(L,30)`，比较两窗口最低值，属稳健"触轨"判定，非浮点相等。

### 4.3 B41 / S41 — RSI 型 mm1 级（踩轨 + 通道分离，无冷却）
```
_B41 = CROSS(RSIH,TH) & (MC1<0|MC2<0|MC3<0) & CH_B1_BULL & (_LLV(L,10)==XG1) & (XG1>XG2)
_S41 = CROSS(75,RSIH) & (MC1>0|MC2>0|MC3>0) & CH_B1_BEAR & (_HHV(H,10)==SG1) & (SG1<SG2)
```
含义：RSI 上穿 TH（超卖反弹）且踩 mm1 下轨、mm1 已脱离 mm2（分离），买入；RSI 下穿 75（超买回落）反向卖出。**无冷却期**。

### 4.4 B42 / S42 — RSI 型 mm2 级（踩轨 + 通道分离）
```
_B42 = CROSS(RSIH,TH) & (MC1<0|MC2<0|MC3<0) & CH_B2_BULL & (_LLV(L,10)==XG2) & (XG2>XG3)
_S42 = CROSS(75,RSIH) & (MC1>0|MC2>0|MC3>0) & CH_B2_BEAR & (_HHV(H,10)==SG2) & (SG2<SG3)
```
含义：与 B41/S41 同构，但作用于 mm2 通道（XG2/SG2）与 CH_B2 方向。

### 4.5 B2 / S2 — 踩轨 + 分离锚
```
_B2 = CORE_B & (_LLV(L,10)==XG2) & CH_B2_BULL & (T_SEP2>0) & (RSIH<50)
_S2 = CORE_S & (_HHV(H,10)==SG2) & CH_B2_BEAR & (T_SEP2S>0) & (RSIH>45)
```
含义：mm2 踩轨 + mm2 已脱离 mm3（T_SEP2>0），顺 CH_B2 方向。

### 4.6 冷却期
```
CD = 3
B1A/B1B/B42/B2/S1A/S1B/S42/S2 均附加：  _X & (REF(COUNT(_X,CD),1)==0)
B41/S41 无冷却（直接使用）
```

---

## 5. 出场信号（BARSLAST 算法）

仅 B41/S41 实现出场。逻辑：入场后等待 RSI 反向穿越，并要求未开启新的同侧穿越（leg 对齐）。

```
CROSS_23 = CROSS(RSIH, TH)        # RSI 上穿 TH
CROSS_75 = CROSS(75, RSIH)        # RSI 下穿 75

B41_EXIT_RAW = (BARSLAST(B41) > BARSLAST(CROSS_75))   # 出场穿越发生在入场之后
            & (BARSLAST(B41) == BARSLAST(CROSS_23))    # 入场与最近一次 RSI 上穿 TH 同轮（leg 对齐）
B41_EXIT = B41_EXIT_RAW & (REF(B41_EXIT_RAW,1)=0)     # 取脉冲首根，避免连续触发

S41_EXIT_RAW = (BARSLAST(S41) > BARSLAST(CROSS_23))
            & (BARSLAST(S41) == BARSLAST(CROSS_75))
S41_EXIT = S41_EXIT_RAW & (REF(S41_EXIT_RAW,1)=0)
```
> **已知限制**：`BARSLAST(B41)==BARSLAST(CROSS_23)` 依赖"入场后无新的 RSI 上穿 TH"。若价格入场后短暂跌破 TH 又上穿（震仓），leg 被重置，可能吞掉后续真正应触发的 CROSS_75 出场。

---

## 6. 分钟线变体差异（mm2_i5_min1.py）

与日线版逻辑一致，额外引入 mm3/mm4 方向过滤（对应"上级"抑制）：
```
CH_FILT_BUY  = CH3_UP | (CH3_ZD & CH4_UP)
CH_FILT_SELL = CH3_DN | (CH3_ZD & CH4_DN)
```
所有入场/出场信号均追加 `& CH_FILT_BUY`（买侧）/ `& CH_FILT_SELL`（卖侧）。B1B 同样带 `B1B_FLT` 与上级 TREND 判断，与日线版同步。

---

## 7. 通达信对照（mm2_i5_tdx.txt）

`mm2_i5_tdx.txt` 为同一策略的通达信公式版，结构/信号与 `mm2_i5.py` 一一对应：
- `TREND_BULL/TREND_BEAR` 已同步改为上级(mm2/mm3)判断；
- `_B1B` 已同步补 `B1B_FLT`；
- 出场段 `B41_EXIT/S41_EXIT` 使用 `BARSLAST` 同构实现。

> 调试/可视化可直接在通达信加载该公式；`TH` 默认值 23，ETF 手动改为 25。
