# 数据库表定义索引文档（L1）

> **文档编号**: L1-DATABASE-TABLES
> **版本**: V1.0
> **更新日期**: 2026-07-01
> **用途**: 覆盖 stockpush 项目所有 PostgreSQL 表的完整定义，包括字段、约束、索引及所属功能模块

---

## 1. 文档概述

本文档汇总 stockpush 项目中所有已知的 PostgreSQL 数据库表定义，提供统一的字段/约束/索引参考。

**数据库连接**：通过 `PGConnector`(`stockpush/pg_connector.py`) 连接，配置取自环境变量：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `PG_HOST` | `127.0.0.1` | 数据库主机 |
| `PG_PORT` | `5432` | 数据库端口 |
| `PG_DB` | `stockpush` | 数据库名 |
| `PG_USER` | `stockpush` | 用户名 |
| `PG_PASSWORD` | — | 密码 |

---

## 2. 核心数据表（F5.1 系统初始化）

以下表由 `F51SysInit`(`stockpush/services/sys_init.py`) 在 VPS 首次部署时创建，F5.1 持有写入与重置权限。

### 2.1 tb_sys_cfg — 系统配置表

运行期系统配置键值存储（区别于 `config.yaml` 静态配置）。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| key | VARCHAR(100) | NOT NULL, UNIQUE | 配置键名 |
| value | TEXT | NOT NULL | 配置值 |
| description | VARCHAR(200) | — | 配置项说明 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最后更新时间 |

**索引**：
- UNIQUE(key)

**拥有权**：F5.1（系统初始化），本模块拥有写入与重置权限。

---

### 2.2 tb_stock_codes — 股票代码主表

A 股市场股票基本信息。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| symbol | VARCHAR(10) | PRIMARY KEY | 股票代码（如 `000001`） |
| name | VARCHAR(50) | — | 股票名称 |
| market | VARCHAR(10) | — | 所属市场（`SH`/`SZ`/`BJ`） |
| list_date | DATE | — | 上市日期 |
| status | VARCHAR(10) | DEFAULT `'active'` | 状态（`active`/`delisted`/`suspended`） |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最后更新时间 |

**索引**：
- PRIMARY KEY(symbol)

**拥有权**：F5.1，本模块拥有写入与重置权限。

---

### 2.3 tb_fund_codes — 基金代码主表

基金产品基本信息。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| symbol | VARCHAR(10) | PRIMARY KEY | 基金代码 |
| name | VARCHAR(100) | — | 基金名称 |
| type | VARCHAR(20) | — | 基金类型（如 `ETF`/`LOF`/`货币`） |
| list_date | DATE | — | 上市日期 |
| status | VARCHAR(10) | DEFAULT `'active'` | 状态 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最后更新时间 |

**索引**：
- PRIMARY KEY(symbol)

**拥有权**：F5.1，本模块拥有写入与重置权限。

---

### 2.4 tb_stock_pool — 自选股池

用户自选股列表，支持按分组归类。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| symbol | VARCHAR(10) | NOT NULL | 股票代码 |
| name | VARCHAR(50) | — | 股票名称 |
| type | VARCHAR(10) | — | 类型（`stock`/`fund`/`index`） |
| market | VARCHAR(10) | — | 所属市场 |
| group_name | VARCHAR(50) | — | 分组名称（如 `自选`/`ETF组合`） |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- UNIQUE(symbol, group_name)

**拥有权**：F5.1，本模块拥有写入与重置权限。

---

### 2.5 tb_calendar — 交易日历

A 股交易日历，按自然日粒度记录。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| date | DATE | PRIMARY KEY | 日历日期 |
| is_trading_day | BOOLEAN | NOT NULL | 是否为交易日 |
| year | INTEGER | — | 年份（冗余，便于分区查询） |
| month | INTEGER | — | 月份 |
| weekday | INTEGER | — | 星期几（0=周日, 6=周六） |

**索引**：
- PRIMARY KEY(date)

**拥有权**：F5.1，本模块拥有写入与重置权限。

---

### 2.6 K 线原始数据表（tb_raw_1m / tb_raw_5m / tb_raw_30m / tb_raw_1d）

四种周期的 K 线数据，表结构完全一致，仅表名区分周期。

**表名对照**：

| 表名 | 周期 | 说明 |
|------|------|------|
| tb_raw_1m | 1 分钟 | 分钟级原始 K 线 |
| tb_raw_5m | 5 分钟 | 分钟级原始 K 线 |
| tb_raw_30m | 30 分钟 | 分钟级原始 K 线 |
| tb_raw_1d | 日线 | 日线原始 K 线 |

**字段结构**：

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| ts | TIMESTAMP | NOT NULL, PK(ts, symbol) | K 线时间戳（周期起点） |
| symbol | VARCHAR(10) | NOT NULL, PK(ts, symbol) | 股票代码 |
| open | DECIMAL(10,3) | NOT NULL | 开盘价 |
| high | DECIMAL(10,3) | NOT NULL | 最高价 |
| low | DECIMAL(10,3) | NOT NULL | 最低价 |
| close | DECIMAL(10,3) | NOT NULL | 收盘价 |
| vol | BIGINT | NOT NULL | 成交量（股数） |
| amount | DECIMAL(20,2) | NOT NULL | 成交金额（元） |

**索引**：
- PRIMARY KEY(ts, symbol)

**拥有权**：F5.1，本模块拥有写入与重置权限。

---

### 2.7 tb_signal_functions — 信号函数注册表

注册可被信号引擎调用的自定义函数。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| name | VARCHAR(100) | NOT NULL, UNIQUE | 函数名称标识（全局唯一） |
| display_name | VARCHAR(200) | — | 显示名称 |
| module_path | VARCHAR(500) | NOT NULL | Python 模块路径 |
| func_name | VARCHAR(100) | NOT NULL | 模块内的函数名 |
| period | VARCHAR(10) | — | 建议运行周期（如 `1d`/`30m`） |
| param_set_id | INTEGER | DEFAULT 0 | 默认参数集 ID |
| enabled | BOOLEAN | DEFAULT TRUE | 是否启用 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- UNIQUE(name)

**拥有权**：F5.1（sys_init 创建核心结构），F5.2（信号引擎）负责行级写入与维护。

> **补充**：迁移脚本 `sql/001_signal_functions.sql` 定义相同表，字段长度略有差异（此处以 `sys_init.py` 生产版本为准）。

---

### 2.8 tb_signal_function_params — 信号函数参数集

存储每个函数的参数键值对，支持多参数集（通过 `set_id` 分组）。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| func_id | INTEGER | NOT NULL, PK(func_id, set_id, param_key), FK → tb_signal_functions(id) ON DELETE CASCADE | 所属函数 ID |
| set_id | INTEGER | DEFAULT 0, PK(func_id, set_id, param_key) | 参数集编号（0=默认集） |
| param_key | VARCHAR(100) | NOT NULL, PK(func_id, set_id, param_key) | 参数键名 |
| param_value | TEXT | — | 参数值 |

**索引**：
- PRIMARY KEY(func_id, set_id, param_key)

**拥有权**：同 tb_signal_functions，F5.2 负责行级维护。

---

### 2.9 tb_signal_log — 信号日志表

记录信号引擎产生的所有买卖信号。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| func_id | INTEGER | NOT NULL, FK → tb_signal_functions(id) | 产生信号的函数 ID |
| direction | VARCHAR(10) | NOT NULL | 信号方向（`buy`/`sell`） |
| symbol | VARCHAR(10) | NOT NULL | 标的代码 |
| signal_time | TIMESTAMP | NOT NULL | 信号产生时间 |
| price | DOUBLE PRECISION | — | 信号触发时价格 |
| indicator | VARCHAR(100) | — | 触发指标值（JSON 字符串） |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 记录创建时间 |

**索引**（由 `sql/001_signal_functions.sql` 补充创建）：
- INDEX(idx_signal_log_symbol) ON (symbol)
- INDEX(idx_signal_log_time) ON (signal_time)
- INDEX(idx_sl_func_time) ON (func_id, signal_time DESC)
- INDEX(idx_sl_symbol) ON (symbol)

**拥有权**：F5.2（信号引擎）负责写入与查询。

> **注意**：`sql/001_signal_functions.sql` 定义了更完整的版本（`BIGSERIAL` 主键、`CHECK(direction IN ('buy','sell'))`、`pushed_at` 字段、`ON DELETE CASCADE`），可作为生产环境的迁移升级目标。

---

### 2.10 tb_download_request_log — 下载请求审计日志

记录每次数据下载请求的详细内容，用于审计与调试。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | BIGINT | PRIMARY KEY, DEFAULT nextval('seq_tb_download_request_log_id') | 主键（序列生成） |
| request_time | TEXT | NOT NULL | 请求时间 |
| symbol | TEXT | NOT NULL | 股票/基金代码 |
| period | TEXT | NOT NULL | 请求周期 |
| open | DOUBLE PRECISION | — | 开盘价 |
| high | DOUBLE PRECISION | — | 最高价 |
| low | DOUBLE PRECISION | — | 最低价 |
| close | DOUBLE PRECISION | — | 收盘价 |
| volume | DOUBLE PRECISION | — | 成交量 |
| amount | DOUBLE PRECISION | — | 成交金额 |
| preclose | DOUBLE PRECISION | — | 昨收价 |
| api_bar_time | TEXT | — | API 返回的 bar 时间 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 记录创建时间 |

**索引**：无显式索引（日志型表）。

**序列**：
- `seq_tb_download_request_log_id`：用于生成 `id` 主键值

**拥有权**：F5.1（数据下载模块），本模块拥有写入与重置权限。

---

## 3. 数据源注册表

### 3.1 tb_datasource_registry — 数据源注册表（F2.1）

数据提供方的注册信息与运行时统计。由 `stockpush/services/data_source_registry.py` 在 F5.1 启动时幂等创建。

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | INTEGER | PRIMARY KEY | 主键 |
| provider_name | VARCHAR(50) | NOT NULL, UNIQUE | 数据源唯一名称（如 `xtick`） |
| display_name | VARCHAR(100) | NOT NULL | 显示名称 |
| provider_class | VARCHAR(200) | NOT NULL | 提供方实现类的全限定名 |
| enabled | BOOLEAN | NOT NULL DEFAULT TRUE | 是否启用 |
| priority | INTEGER | NOT NULL DEFAULT 50 | 优先级（越小越优先） |
| config_json | VARCHAR | — | 扩展配置（JSON 格式） |
| timeout | INTEGER | NOT NULL DEFAULT 30 | 请求超时（秒） |
| retry | INTEGER | NOT NULL DEFAULT 3 | 失败重试次数 |
| capability_api01~api12 | BOOLEAN | NOT NULL DEFAULT FALSE | 12 项 API 能力标记（具体映射见代码） |
| last_test_time | TIMESTAMP | — | 最后一次连通性测试时间 |
| test_result | VARCHAR(20) | — | 测试结果（`ok`/`fail`/`timeout`） |
| test_details | VARCHAR | — | 测试详情 |
| error_msg | VARCHAR | — | 错误信息 |
| call_count | INTEGER | NOT NULL DEFAULT 0 | 累计调用次数 |
| success_count | INTEGER | NOT NULL DEFAULT 0 | 成功次数 |
| fail_count | INTEGER | NOT NULL DEFAULT 0 | 失败次数 |
| avg_response_time | REAL | — | 平均响应时间（秒） |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- UNIQUE(provider_name)

**拥有权**：F2.1（数据源管理层），F5.1 仅在启动时做幂等初始化。

---

## 4. 其他模块关联表（参考清单）

以下表在代码中被引用，但其 DDL 由对应功能模块自行管理，本文档仅列出名称与所属模块。详细定义参见对应模块的 L1 文档。

| 表名 | 所属功能 | 说明 |
|------|----------|------|
| tb_alert_log | F4.6（报警） | 报警日志 |
| tb_bt_results | F5.6（回测） | 回测结果 |
| tb_compare_history | F6.1（数据比对） | 数据比对历史 |
| tb_compare_log | F6.1（数据比对） | 数据比对日志 |
| tb_custom_func_def | F4.0（自定义函数） | 自定义函数定义 |
| tb_download_history | F3.1（下载历史） | 下载历史记录 |
| tb_f61_operation_log | F6.1（操作日志） | 比对操作日志 |
| tb_func_map | F4.2（函数映射） | 函数映射表 |
| tb_logic_cfg | F4.6（逻辑配置） | 逻辑配置（矩阵规则） |
| tb_logic_var_cfg | F4.6（逻辑变量配置） | 逻辑变量配置 |
| tb_manual_pts | F4.6（手动标注） | 手动标注点 |
| tb_matrix_pts | F4.1（矩阵标注） | 矩阵标注点 |
| tb_mc_scan_job | F6.2（MC 策略扫描） | MC 策略扫描任务 |
| tb_rt_test_run | F3.2（实时测试） | 实时测试运行记录 |
| tb_src_status | F2.1（数据源状态） | 数据源状态 |
| tb_zigzag_pts | F3.6（高低点标注） | Zigzag 高低点标注 |

---

## 5. 数据库初始化流程

```
F51SysInit.__init__()
  └─ _init_tables()
       ├─ 创建 F51_TABLE_SQLS 中 13 个表（含序列）
       │   (sys_init.py 第 28-208 行)
       └─ 不执行 UNRELATED_TABLES（仅用于兼容性标记）
```

额外索引由 `sql/001_signal_functions.sql` 在表创建后择机执行。

---

## 6. 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| V1.0 | 2026-07-01 | 初始版本，覆盖 F5.1 核心表 + F2.1 数据源注册表 |
