# 标准 API 文档（StandardAPIAdapter，API01–API12）

> **版本**: V1.0
> **更新日期**: 2026-08-07
> **用途**: 定义 stockpush 数据源层的 12 个标准 API 契约。所有 Provider 通过继承 `StandardAPIAdapter`（`stockpush/src_mgr/standard_api_adapter.py`）实现标准化访问，由 `DataSourceRegistry`（`stockpush/src_mgr/data_source_registry.py`）统一路由。

---

## 1. 架构定位

```
调用方 (DataFetcher / SrcMgrService / HermesAPI)
        │
        ▼
DataSourceRegistry.API_METHODS  ── api_id → 方法名 映射
        │
        ▼
Provider 实例（继承 StandardAPIAdapter）
        │
        ▼
底层数据源（XTick / Baostock / …）
```

- `DataSourceRegistry.API_METHODS` 是 api_id（`api01`~`api12`）→ 标准方法名的唯一映射。
- 每个 Provider 的注册记录通过 `capability_api01`~`capability_api12` 布尔列声明支持哪些 API。
- 调用方按能力标记路由：优先 `priority` 小的已启用 Provider，失败自动降级。

### 统一语义（所有 API 遵守）

| 约定 | 规则 |
|------|------|
| 默认复权 | 历史行情默认前复权 `adjust='qfq'`（`DEFAULT_ADJUST`）；`'hfq'` 后复权 / `''` 或 `'none'` 不复权 |
| 分钟线复权 | 分钟线通常不支持复权，Provider 不支持的复权方式忽略或报错 |
| 日期参数 | 统一截断为 `YYYY-MM-DD`（`_date_only`），Provider 不支持时间戳时安全 |
| 失败返回 | 所有 API 失败统一返回 `-1`（不抛异常，异常记录日志） |
| volume 单位 | K 线 DataFrame 的 `volume` 列统一为「手」（股/份 ÷100，Provider 出口换算） |
| 时间戳 | K 线 `ts` 统一为 bar 起点（START 约定），经 `_align_timestamp_to_period` 对齐 |

---

## 2. API 契约总表

| API ID | 方法名 | 参数 | 返回 | 能力列 |
|--------|--------|------|------|--------|
| API01 | `fetch_stock_history_daily` | `code, start, end, adjust='qfq'` | `DataFrame` / `-1` | `capability_api01` |
| API02 | `fetch_stock_history_minute` | `code, period, start, end, adjust='qfq'` | `DataFrame` / `-1` | `capability_api02` |
| API03 | `fetch_stock_realtime_daily` | `code` | `dict` / `-1` | `capability_api03` |
| API04 | `fetch_stock_realtime_minute` | `code` | `DataFrame` / `-1` | `capability_api04` |
| API05 | `fetch_fund_history_daily` | `code, start, end, adjust='qfq'` | `DataFrame` / `-1` | `capability_api05` |
| API06 | `fetch_fund_history_minute` | `code, period, start, end, adjust='qfq'` | `DataFrame` / `-1` | `capability_api06` |
| API07 | `fetch_fund_realtime_daily` | `code` | `dict` / `-1` | `capability_api07` |
| API08 | `fetch_fund_realtime_minute` | `code` | `DataFrame` / `-1` | `capability_api08` |
| API09 | `fetch_stock_list` | — | `DataFrame` / `-1` | `capability_api09` |
| API10 | `fetch_fund_list` | — | `DataFrame` / `-1` | `capability_api10` |
| API11 | `fetch_trade_calendar` | `start, end` | `DataFrame` / `-1` | `capability_api11` |
| API12 | `fetch_latest_dividend_date` | `code, asset_type='stock', **kwargs` | `dict` / `-1` | `capability_api12` |

### 各 API 契约明细

#### API01 股票历史日线
```python
def fetch_stock_history_daily(self, code: str, start: str, end: str,
                              adjust: str = 'qfq') -> Union[pd.DataFrame, int]:
```
内部委托 Provider 的 `fetch_stock_daily(code, start, end, adjust=...)`（不接收 adjust 的旧实现自动降级）。DataFrame 列：`date/ts, open, high, low, close, volume, amount`。

#### API02 股票历史分钟线
```python
def fetch_stock_history_minute(self, code: str, period: str, start: str, end: str,
                               adjust: str = 'qfq') -> Union[pd.DataFrame, int]:
```
`period` 支持 `'1m'/'5m'/'15m'/'30m'/'60m'`（按 Provider 能力）。内部委托 `fetch_stock_5min/15min/30min/60min` 或 `fetch_stock_minute`。

#### API03 股票实时行情（日线级别）
```python
def fetch_stock_realtime_daily(self, code: str) -> Union[dict, int]:
```
返回 dict：`code, name, price, open, high, low, preclose, volume, amount, timestamp` 等。

#### API04 股票实时分钟线
```python
def fetch_stock_realtime_minute(self, code: str) -> Union[pd.DataFrame, int]:
```
返回当日分钟 K 线 DataFrame（含当前未收盘 bar）。

#### API05 / API06 基金历史日线 / 分钟线
与 API01/02 同构，委托 `fetch_fund_daily` / `fetch_fund_*min`。

#### API07 / API08 基金实时行情（日线级别 / 分钟线）
与 API03/04 同构，作用于基金代码。

#### API09 股票代码列表
```python
def fetch_stock_list(self) -> Union[pd.DataFrame, int]:
```
DataFrame 列：`symbol, name, market`（如 `sh.600000` 或 `600000`，按 Provider 约定）。

#### API10 基金代码列表
```python
def fetch_fund_list(self) -> Union[pd.DataFrame, int]:
```
DataFrame 列：`symbol, name, type`（ETF/LOF 等）。

#### API11 交易日历
```python
def fetch_trade_calendar(self, start: str, end: str) -> Union[pd.DataFrame, int]:
```
DataFrame 列：`date, is_trading_day`。

#### API12 最新分红日期
```python
def fetch_latest_dividend_date(self, code: str, asset_type: str = 'stock',
                               **kwargs) -> Union[dict, int]:
```
返回 dict：`code, ex_date`（除权除息日）、`record_date`（股权登记日）、`description`（分红方案描述）等；无分红记录返回空内容。

---

## 3. 已注册 Provider 能力对照

| API | XTick (primary, priority=12) | Baostock (备用, priority=20) |
|-----|:---:|:---:|
| API01 股票历史日线 | ✅ | ✅ |
| API02 股票历史分钟线 | ✅ | ✅（5/15/30/60，无 1m） |
| API03 股票实时日线 | ✅ | ❌（盘后更新） |
| API04 股票实时分钟线 | ✅ | ❌ |
| API05 基金历史日线 | ✅ | ✅ |
| API06 基金历史分钟线 | ✅ | ✅（5/15/30/60，无 1m） |
| API07 基金实时日线 | ✅ | ❌ |
| API08 基金实时分钟线 | ✅ | ❌ |
| API09 股票列表 | ✅ | ✅ |
| API10 基金列表 | ✅ | ❌（query_all_stock 不含基金） |
| API11 交易日历 | ✅ | ✅ |
| API12 最新分红日期 | ✅（token 有权限时） | ✅（query_dividend_data，仅股票） |

> 注册表路由：同 API 多 Provider 支持时按 `priority` 升序选择，失败自动降级到下一个。
> 当前 XTick API12 实际无 token 权限（`/doc/core/chuquan`），股票除息由东财 F10 兜底（`stockpush/src_mgr/xtick_provider.py` 实现细节），Baostock API12 为股票分红补充源。

---

## 4. 相关文件

| 文件 | 职责 |
|------|------|
| `stockpush/src_mgr/standard_api_adapter.py` | `StandardAPIAdapter` Mixin：12 个标准 API 的默认实现与委托 |
| `stockpush/src_mgr/data_source_registry.py` | `DataSourceRegistry`：`API_METHODS` 映射、能力标记、Provider 实例管理 |
| `stockpush/services/src_mgr.py` | `SrcMgrService`：对外暴露 Provider 获取与状态查询 |
| `stockpush/src_mgr/xtick_provider.py` | XTick Provider 实现 |
| `stockpush/src_mgr/baostock_provider.py` | Baostock Provider 实现（`CAPABILITIES` 声明能力） |

各数据源原始接口文档见本目录对应子目录（`xtick/`、`baostock/`）；数据源能力矩阵见 [数据源能力对比.md](./数据源能力对比.md)。
