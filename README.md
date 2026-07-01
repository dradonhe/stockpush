# stockpush —— 实时监控推送系统

基于 F51 的股票信号实时监控与飞书推送系统。

## 快速开始

### 1. 安装依赖

```bash
pip install -r stockpush/requirements.txt
# 或
pip install -e .
```

### 2. 配置

编辑 `stockpush/config.local.yaml`：

- `datasources.primary`: 数据源（xtick / akshare / byapi 等）
- `feishu.webhook`: 飞书 Webhook URL（首次运行会自动生成加密密钥）
  ```bash
  # 加密 webhook URL
  python -c "from stockpush.credential_store import encrypt_value; print(encrypt_value('https://open.feishu.cn/open-apis/bot/v2/hook/xxx'))"
  ```
- `schedule`: 交易时段配置

### 3. 运行

```bash
# Headless 模式（用于 systemd 定时器）
python -m stockpush.worker --headless

# 交互式控制台
python -m stockpush.worker

# Hermes API 模式
python -m stockpush.worker --hermes status
```

### 4. Systemd 部署（可选）

```bash
cp stockpush/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable f51-start.timer f51-stop.timer
systemctl start f51-start.timer
```

## 项目结构

```
stockpush/
├── stockpush/              # Python 包
│   ├── worker.py           # 入口
│   ├── console.py          # 交互式控制台
│   ├── services/           # 核心服务
│   │   ├── feishu_pusher.py
│   │   ├── scheduler.py
│   │   ├── data_fetcher.py
│   │   ├── headless_runner.py
│   │   └── ...
│   ├── src_mgr/            # 数据源提供商
│   ├── userfunc/           # 用户函数（信号策略）
│   ├── pg_connector.py     # PostgreSQL 连接器
│   ├── credential_store.py # 凭据加密
│   └── config.yaml         # 配置文件
├── config/                 # 密钥文件（自动生成）
└── pyproject.toml
```
