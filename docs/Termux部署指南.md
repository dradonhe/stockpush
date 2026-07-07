# Stockpush Termux 部署指南

将 stockpush 实时监控系统部署到 Android 手机的 Termux 环境。

---

## 目录

1. [架构对比](#1-架构对比)
2. [环境要求](#2-环境要求)
3. [安装步骤](#3-安装步骤)
4. [改动说明](#4-改动说明)
5. [定时任务方案](#5-定时任务方案)
6. [日常运维](#6-日常运维)
7. [故障排查](#7-故障排查)

---

## 1. 架构对比

| 组件 | Linux (原方案) | Termux (新方案) |
|------|---------------|-----------------|
| Python | 系统 python3 + venv | 系统 python3（无 venv） |
| 数据库 | PostgreSQL (系统服务) | PostgreSQL (Termux pkg) |
| 定时触发 | systemd timer | APScheduler 长驻进程 |
| 进程管理 | systemctl | PID 文件 + shell 脚本 |
| 防休眠 | 无需 | termux-wake-lock |
| 开机自启 | systemd enable | Hermes agent 管理 |
| 配置路径 | `/opt/stockpush/` | `$HOME/stockpush/` |

### 兼容性原则

- **Linux 现有部署完全不受影响**
- 所有 Termux 改动通过环境检测隔离
- 新增 Termux 专用文件，不修改 Linux 专用文件

---

## 2. 环境要求

### Termux 安装

从 F-Droid 安装 Termux（推荐 0.118+），避免使用 Google Play 版本（已停更）。

### 必需包

```bash
pkg update && pkg install -y \
    python \
    postgresql \
    git \
    rust \
    binutils
```

| 包 | 用途 |
|----|------|
| python | 运行环境 (3.11+) |
| postgresql | 数据库 |
| git | 拉取代码 |
| rust | 编译 cryptography 库 |

### Python 依赖

```bash
pip install -r stockpush/requirements.txt
pip install -e .
```

---

## 3. 安装步骤

### 3.1 克隆项目

```bash
cd $HOME
git clone https://github.com/dradonhe/stockpush.git
cd stockpush
```

### 3.2 运行初始化脚本

```bash
bash sysinit-termux.sh
```

该脚本自动完成：
1. 检查 Termux 环境
2. 安装系统包
3. 安装 Python 依赖
4. 初始化 PostgreSQL 数据库
5. 生成配置文件
6. 配置 termux-wake-lock

### 3.3 配置飞书 Webhook

编辑 `stockpush/config.local.yaml`：

```yaml
feishu:
  enabled: true
  webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook地址"
  sign_enabled: false
```

### 3.4 验证安装

```bash
# 测试飞书推送
python3 -m stockpush.worker --hermes feishu-test

# 测试数据库连接
python3 -m stockpush.services.sys_init

# 手动运行一次
python3 -m stockpush.worker --headless
```

---

## 4. 改动说明

### 4.1 userfunc/*.py 路径修复

**影响文件**: `MF05.py`, `MF30.py`, `TF05.py`, `mm2.py`

**改动内容**: 将硬编码的 `/opt/stockpush` 改为自动检测

```python
# 旧代码
sys.path.insert(0, r"/opt/stockpush")

# 新代码
import os as _os
_project_root = _os.path.normpath(
    _os.path.join(_os.path.dirname(__file__), '..', '..')
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
```

**兼容性**: Linux 下自动解析为 `/opt/stockpush`，行为等价。

### 4.2 console.py / hermes_api.py 守卫

**改动内容**: 在 systemctl 调用前检测命令是否存在

```python
import shutil

def _has_systemctl() -> bool:
    return shutil.which("systemctl") is not None

# 使用示例
if _has_systemctl():
    subprocess.run(["systemctl", "start", "f51-start.service"])
else:
    logger.warning("systemctl 不可用，跳过服务管理")
```

**兼容性**: Linux 下 `systemctl` 存在，逻辑不变。

### 4.3 新增文件

| 文件 | 说明 |
|------|------|
| `run-termux.sh` | Termux 启动脚本 |
| `sysinit-termux.sh` | Termux 初始化脚本 |
| `deploy/termux/stockpush-daemon.sh` | 后台进程管理 |

---

## 5. 定时任务方案

### 方案选择: APScheduler 长驻进程

Termux 无 systemd，采用 APScheduler 进程内调度 + termux-wake-lock 防休眠。

### 工作流程

```
启动脚本 (run-termux.sh)
    │
    ├── 检查是否交易日
    │   └── 非交易日 → 退出
    │
    ├── 获取 wake-lock
    │   └── termux-wake-lock
    │
    ├── 启动 worker --headless
    │   ├── 推送启动通知
    │   ├── 检查除权除息
    │   └── 启动 APScheduler
    │
    ├── APScheduler 调度
    │   ├── 09:25-11:35 每 60s 执行
    │   └── 13:00-15:05 每 60s 执行
    │
    └── 收盘后自动退出
        └── 释放 wake-lock
```

### 后台运行

```bash
# 启动（后台）
./deploy/termux/stockpush-daemon.sh start

# 查看状态
./deploy/termux/stockpush-daemon.sh status

# 停止
./deploy/termux/stockpush-daemon.sh stop

# 查看日志
tail -f /tmp/stockpush.log
```

### PID 文件

- 位置: `/tmp/stockpush.pid`
- 日志: `/tmp/stockpush.log`

---

## 6. 日常运维

### 手动启动/停止

```bash
# 启动
python3 -m stockpush.worker --headless &

# 停止
kill $(cat /tmp/stockpush.pid)
```

### 查看日志

```bash
# 实时日志
tail -f /tmp/stockpush.log

# 查看最近 50 行
tail -50 /tmp/stockpush.log
```

### 数据库管理

```bash
# 连接数据库
psql -U postgres -d stockpush

# 重启 PostgreSQL
pg_ctl -D $HOME/.pg/data restart
```

### 更新代码

```bash
cd $HOME/stockpush
git pull
pip install -e .  # 重新安装
```

---

## 7. 故障排查

### 常见问题

#### 1. cryptography 编译失败

**现象**: `pip install cryptography` 报错

**解决**:
```bash
pkg install rust binutils
CARGO_HOME=$PREFIX/bin pip install cryptography
```

#### 2. PostgreSQL 连接失败

**现象**: `psycopg.OperationalError`

**检查**:
```bash
# 确认 PG 正在运行
pg_ctl -D $HOME/.pg/data status

# 确认环境变量
echo $PGHOST $PGPORT $PGUSER $PGDATABASE
```

#### 3. 进程被杀

**现象**: worker 运行一段时间后消失

**原因**: Android 系统休眠或后台清理

**解决**:
```bash
# 确保 wake-lock 生效
termux-wake-lock

# 检查电池优化设置
# 设置 → 电池 → 后台限制 → 允许 Termux 后台运行
```

#### 4. 交易日未运行

**现象**: 交易日没有推送

**检查**:
```bash
# 查看日志
grep "非交易日" /tmp/stockpush.log

# 手动测试交易日判断
python3 -c "from stockpush.services.calendar_checker import CalendarChecker; print(CalendarChecker().is_today_trading_day())"
```

#### 5. 飞书推送失败

**现象**: 信号产生但未收到通知

**检查**:
```bash
# 测试 webhook
python3 -m stockpush.worker --hermes feishu-test

# 检查配置
grep webhook stockpush/config.local.yaml
```

---

## 附录

### A. Termux 环境变量

在 `~/.bashrc` 中添加：

```bash
# stockpush 环境
export STOCKPUSH_HOME=$HOME/stockpush
export PYTHONPATH=$STOCKPUSH_HOME:$PYTHONPATH

# PostgreSQL
export PGDATA=$HOME/.pg/data
export PGHOST=localhost
export PGPORT=5432
export PGUSER=postgres
export PGDATABASE=stockpush
```

### B. 文件结构对比

```
Linux:                          Termux:
/opt/stockpush/                 $HOME/stockpush/
├── stockpush/                  ├── stockpush/
│   ├── worker.py               │   ├── worker.py
│   ├── config.yaml             │   ├── config.yaml
│   ├── config.local.yaml       │   ├── config.local.yaml (覆盖)
│   └── userfunc/               │   └── userfunc/
│       └── MF30.py             │       └── MF30.py (路径修复)
├── run.sh                      ├── run-termux.sh (新增)
├── sysinit.sh                  ├── sysinit-termux.sh (新增)
└── deploy/systemd/             └── deploy/termux/ (新增)
```

### C. 依赖清单

| 包名 | 最低版本 | Termux 安装方式 |
|------|---------|----------------|
| numpy | 1.24.0 | pip (预编译 wheel) |
| pandas | 2.0.0 | pip (预编译 wheel) |
| MyTT | 2.9.0 | pip (纯 Python) |
| pyyaml | 6.0 | pip (纯 Python) |
| requests | 2.31.0 | pip (纯 Python) |
| apscheduler | 3.10.0 | pip (纯 Python) |
| psycopg | 3.1.0 | pip (纯 Python) |
| python-dotenv | 1.0.0 | pip (纯 Python) |
| cryptography | 41.0.0 | pip (需 rust 编译) |

---

## 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-07-07 | 1.0 | 初始版本，支持 Termux 部署 |
