# XTick 实时数据流说明（L1）

> **文档编号**: L1-XTICK-REALTIME
> **版本**: V1.0
> **更新日期**: 2026-07-07
> **用途**: 说明 XTick 实时5分钟K线数据的获取、存储和使用流程

---

## 1. 数据流概览

```
每60秒 tick
  │
  ├─→ fetcher.fetch_kline(symbol, "5m")  ← XTick API
  │     └─→ 返回今日所有5分钟bar（含当前未收盘bar）
  │
  ├─→ _filter_bar(df, "5m", now)  ← 筛选当前时刻对应的bar
  │     └─→ 返回1条：当前正在形成的5分钟K线
  │
  ├─→ log_downloads()  ← 记录到 tb_download_request_log
  │     └─→ request_time=当前时间, api_bar_time=XTick返回的时间戳
  │
  ├─→ save_to_db()  ← 写入/更新 tb_raw_5m
  │     └─→ INSERT ON CONFLICT UPDATE（同一bar覆盖更新）
  │
  └─→ 信号计算（FunctionEngine.run）
        └─→ 读取 tb_raw_5m（含最新实时数据）
```

---

## 2. 关键时间戳

| 字段 | 来源 | 含义 | 示例 |
|------|------|------|------|
| `request_time` | 程序发起请求时 | 当前系统时间 | `2026-07-07 14:03:37` |
| `api_bar_time` | XTick API返回 | bar的时间戳（END约定） | `2026-07-07 14:05:59` |
| `ts` | tb_raw_5m | bar的开始时间（START约定） | `2026-07-07 14:00:00` |

**时间戳对齐关系**：
- `api_bar_time` 是 bar 的**结束时间**（END约定）
- `ts` 是 bar 的**开始时间**（START约定）
- 同一根5分钟bar：`api_bar_time - 1秒 ≈ ts + 4分59秒`

**示例**：
```
api_bar_time = 14:05:59 → ts = 14:00:00（14:00-14:05 bar）
api_bar_time = 14:00:59 → ts = 13:55:00（13:55-14:00 bar）
```

---

## 3. 实时数据更新轨迹

以601336的5分钟K线为例，14:00前后的真实下载记录：

| request_time | api_bar_time | open | high | low | close | 状态 |
|--------------|--------------|------|------|-----|-------|------|
| 13:55:37 | 13:55:59 | 63.00 | 63.15 | 63.00 | 63.07 | **13:55 bar final** |
| 13:56:37 | 14:00:59 | 63.07 | 63.07 | 63.00 | 63.02 | 14:00 bar 更新中 |
| 13:57:37 | 14:00:59 | 63.07 | 63.07 | 62.98 | 62.99 | 14:00 bar 更新中 |
| 13:58:37 | 14:00:59 | 63.07 | 63.07 | 62.95 | 62.95 | 14:00 bar 更新中 |
| 13:59:37 | 14:00:59 | 63.07 | 63.07 | 62.94 | 62.96 | 14:00 bar 更新中 |
| 14:00:37 | 14:00:59 | 63.07 | 63.07 | 62.93 | 62.95 | **14:00 bar final** |
| 14:01:37 | 14:05:59 | 62.94 | 63.06 | 62.94 | 63.03 | 14:05 bar 更新中 |
| 14:02:37 | 14:05:59 | 62.94 | 63.06 | 62.94 | 63.04 | 14:05 bar 更新中 |
| 14:03:37 | 14:05:59 | 62.94 | 63.06 | 62.94 | 63.03 | 14:05 bar 更新中 |
| ... | ... | ... | ... | ... | ... | ... |
| 14:05:37 | 14:05:59 | 62.94 | 63.10 | 62.94 | 63.08 | **14:05 bar final** |

**关键观察**：
1. 每分钟下载一次，同一根bar的OHLC持续更新
2. bar在 `api_bar_time` 时刻变为 final（如14:00:59）
3. 下一根bar从下一分钟开始更新（如14:01:37开始更新14:05 bar）

---

## 4. _filter_bar 筛选逻辑

`_filter_bar(df, period, dt)` 从全天bar中筛选出当前时刻对应的那一根：

```python
# 优先END约定：bar_ts - period < dt <= bar_ts
matched = df[(bar_times - period_td < dt_ts) & (dt_ts <= bar_times)]

# 回退START约定：bar_ts <= dt < bar_ts + period
matched = df[(bar_times <= dt_ts) & (dt_ts < bar_times + period_td)]

# 仍无匹配 → 取dt前最近一根已完成bar
past = df[bar_times <= dt_ts]
matched = past.sort_values(ts_col, ascending=False).iloc[[0]]
```

---

## 5. tb_raw_* 表的数据更新

`save_to_db()` 使用 `INSERT ON CONFLICT UPDATE`：

```sql
INSERT INTO tb_raw_5m (ts, symbol, open, high, low, close, vol, amount)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (ts, symbol) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    vol = EXCLUDED.vol,
    amount = EXCLUDED.amount
```

**效果**：同一根bar（相同ts+symbol）每次更新都会覆盖前一条数据，表中始终保留最新值。

---

## 6. 对信号计算的影响

**当前行为**：
- `FunctionEngine.run()` 读取 `tb_raw_*` 表
- 表中已有最新实时数据（被覆盖更新）
- 信号计算使用的是实时OHLC，不是收盘价

**时间范围过滤**：
```python
# worker.py
if base == '5m':
    start = (now - timedelta(minutes=5)).strftime(...)
end = now.strftime(...)
engine.run(start, end)
```

这个过滤确保只检查最近5分钟内的信号，但数据本身已经是实时的。

---

## 7. 临时下载数据表（tb_download_request_log）

用于审计和调试，记录每次下载的详细信息：

| 字段 | 类型 | 说明 |
|------|------|------|
| request_time | TEXT | 程序发起请求的时间 |
| symbol | TEXT | 股票代码 |
| period | TEXT | 周期（1m/5m/30m/1d） |
| open/high/low/close | DOUBLE | OHLC数据 |
| volume/amount | DOUBLE | 成交量/成交额 |
| preclose | DOUBLE | 昨收价 |
| api_bar_time | TEXT | XTick返回的bar时间戳 |
| created_at | TIMESTAMP | 记录创建时间 |

**特点**：
- INSERT only，永不覆盖
- 每分钟每只股票每个周期一条记录
- 可用于追溯任意时刻的数据快照
