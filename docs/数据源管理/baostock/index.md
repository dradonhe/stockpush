# Baostock 数据源

> 免费开源 Python 金融数据平台（[www.baostock.com](https://www.baostock.com)）。
> 本机已安装 `baostock 0.9.1`，**已接入** stockpush `src_mgr/`（`BaostockProvider`，备用数据源，priority=20）。

---

## 接入位置（分层接口规范）

```
BaostockProvider(BaseProvider, StandardAPIAdapter)
  ├─ BaseProvider          能力矩阵 CAPABILITIES + 抽象方法（stockpush/src_mgr/src_provider.py）
  ├─ StandardAPIAdapter    12 个标准 API 统一接口（api01-api12）
  └─ DataSourceRegistry    tb_datasource_registry 注册表，按 priority 自动路由
```

- 文件：`stockpush/src_mgr/baostock_provider.py`
- 注册：`data_source_registry.py` `_seed_registry()`（增量补齐，仅插入缺失的 provider，不改已有记录）
- 能力位：api01/02/05/06/09/11/12 = True（股票/基金历史日线分钟线、股票列表、交易日历、股票分红）
- 路由：priority=20 低于 XTick(12)，`registry.call/fetch_kline` 自动路由先 XTick，失败兜底 Baostock；`DataFetcher` 主链路仍走 primary=XTick，不受影响
- 登录：baostock 全局会话，`_query()` 内部 `bs.login()` → 查询 → `bs.logout()`，`threading.Lock` 互斥

## 能力对照（实测 2026-08-07）

| 接口 | 实现 | 实测 |
|------|------|------|
| 股票日线/周线/月线 | `fetch_stock_daily/weekly/monthly` | ✅ qfq 前复权与 XTick 逐项一致 |
| 股票 5/15/30/60 分钟 | `fetch_stock_5min/15min/30min/60min` | ✅ 时间戳由 `date`+`time` 合成，与 XTick OHLC 一致 |
| 基金日线 | `fetch_fund_daily` | ✅ 588200 与 XTick 一致 |
| 基金 5/15/30/60 分钟 | `fetch_fund_5min/15min/30min/60min` | ✅ 588200 与 XTick OHLC 一致 |
| 股票列表 | `fetch_stock_list` | ✅ 5200 只（过滤指数与基金） |
| 交易日历 | `fetch_trade_calendar` | ✅ 含 is_trading_day 标记 |
| 股票分红 | `fetch_latest_dividend_date` | ✅ 601336 → 除息日 2026-08-07 |
| 1 分钟线 / 实时 | — | ❌ 不支持 |

> **复权语义**：baostock `adjustflag` = 1 后复权 / 2 前复权 / 3 不复权（与直觉相反，官方文档确认）。
> `_ADJUST_TO_FLAG = {'qfq': '2', 'hfq': '1', 'none': '3', '': '3'}`。
> **默认前复权**：所有 `fetch_*` 方法默认 `adjust='qfq'`，与标准接口（`StandardAPIAdapter.DEFAULT_ADJUST='qfq'`）一致。
> **volume 单位**：provider 已统一为「手」（baostock 原始返回股/份，除以 100），与 XTick 一致；跨源比较无需换算。
> **时间戳**：分钟线由 baostock `time` 字段（`YYYYMMDDHHMMSSmmm`，bar 起点）合成，经 `DataDownService._align_timestamp_to_period` 对齐后与 XTick（bar 终点）入库为同一时间戳（已验证 5m/30m/60m 对齐一致）。

## 访问方式

```python
import baostock as bs
bs.login()   # 免密登录
# ... 查询接口 ...
bs.logout()
```

接口通过 `query_*` 系列函数返回 `ResultData`（`error_code/error_msg` + 游标逐行读取）。

## 行情接口

### query_history_k_data_plus —— 历史 K 线（股票 + 基金/ETF）

- 代码格式：`sh.` / `sz.` 前缀 + 代码（如 `sh.588200`、`sz.159952`、`sh.601336`）
- `frequency`：`d`（日）、`w`（周）、`m`（月）、`5` / `15` / `30` / `60`（分钟）
  - **不支持 1 分钟线**（返回 `error 10004012 请求数据类型不正确`）
- `adjustflag`：`1` 前复权、`2` 不复权、`3` 后复权
- 常用字段：`date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST`

### 基金支持情况（2026-08-07 实测）

| 项目 | 结果 |
|------|------|
| 沪市 ETF 日线（sh.588200） | ✅ 返回数据 |
| 深市 ETF 日线（sz.159952） | ✅ 返回数据 |
| 5 分钟线（sh.588200） | ✅ 返回数据 |
| 1 分钟线 | ❌ 不支持 |
| 数据准确性 | ✅ 与 XTick 同日数据完全一致（open/high/low/close 逐项吻合） |
| 当日数据 | 盘中查询返回空，**盘后更新**（与股票行为一致） |
| 基金列表 | ❌ `query_all_stock` 不含基金代码 |

> 官方文档并未明确宣传基金支持，但实测 ETF K 线可直接按 `sh./sz.` 前缀查询，与股票同参数。
> 数据为交易所场内交易价格（非净值）。

## 其他接口

| 接口 | 说明 | 实测 |
|------|------|------|
| `query_all_stock(day)` | 股票列表 | ✅ 返回沪深 A 股（不含基金/ETF） |
| `query_trade_dates` | 交易日历 | ✅ |
| `query_dividend_data(code, year, yearType)` | 分红送配（除权除息） | ✅ 股票 `sh.601336` 返回 `2026-06-27` 公告日、`2026-08-06` 股权登记日、`2026-08-07` 除权除息日、`10派20.6元` 等；**基金/ETF 不覆盖**（实测 `sh.588200/sz.159952/sh.510050/sh.510300/sz.159919` 全部返回 0 行，即使 510050 实际有年度分红） |
| `query_adjust_factor` | 复权因子 | ✅ |
| `query_stock_basic` / `query_stock_industry` | 股票基本信息/行业 | ✅ |
| `query_balance_data` / `query_profit_data` 等 | 财务数据 | ✅ |

## 与 stockpush 的关系

- **已接入** `src_mgr/`（`BaostockProvider`，备用数据源，priority=20）。详见本文件顶部「接入位置」。
- 用途：
  - 历史 K 线兜底：`registry.call('api01'/'api02'/'api05'/'api06')` 自动路由 XTick 失败时 fallback 到 Baostock；
  - **股票除权除息数据源**：`fetch_latest_dividend_date`（API12）返回除息日/股权登记日，字段与 `calendar_checker.py` 检测逻辑天然匹配，可替代/补充 East Money F10 路径（XTick `/doc/core/chuquan` 仍因 token 无权限不可用）。**仅限股票，基金除息仍走东财/天天基金路径。**
- 局限：无实时行情（盘后更新）、无 1m 周期、基金列表缺失。
