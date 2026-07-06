#!/usr/bin/env bash
# =============================================================================
# stockpush sysinit.sh — F5.1 实时监控推送系统 新环境初始化脚本
#
# 用法:
#   # 克隆 + 初始化（新机器）
#   bash <(curl -fsSL https://raw.githubusercontent.com/dradonhe/stockpush/main/sysinit.sh)
#
#   # 已有项目目录，仅初始化
#   cd /opt/stockpush && bash sysinit.sh
#
#   # 指定目标目录
#   bash sysinit.sh /opt/stockpush
# =============================================================================
set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
prompt(){ echo -e "${BOLD}[INPUT]${NC} $*"; }

# ── 默认值 ────────────────────────────────────────────────────────────────
GIT_REPO="${GIT_REPO:-https://github.com/dradonhe/stockpush.git}"
GIT_BRANCH="${GIT_BRANCH:-main}"
INSTALL_DIR="${1:-$(pwd)}"
PROJECT_DIR="$INSTALL_DIR"

# ── 阶段计数器 ────────────────────────────────────────────────────────────
STEP=0
TOTAL=10

step() { STEP=$((STEP + 1)); echo; echo -e "${BOLD}[${STEP}/${TOTAL}]${NC} $*"; }

# =============================================================================
# 阶段 1: 系统环境检查
# =============================================================================
step "检查系统依赖"

# Python 3.10+
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
    if awk "BEGIN {exit !($PY_VER >= 3.10)}"; then
        ok "Python $PY_VER"
    else
        err "需 Python ≥ 3.10，当前 $PY_VER"
        exit 1
    fi
else
    err "python3 未安装"
    exit 1
fi

# pip
if python3 -m pip --version &>/dev/null; then
    ok "pip $(python3 -m pip --version | grep -oP '\S+' | head -1)"
else
    err "pip 未安装（apt install python3-pip python3-venv）"
    exit 1
fi

# venv
if python3 -m venv --help &>/dev/null; then
    ok "python3-venv 可用"
else
    err "venv 模块缺失（apt install python3-venv）"
    exit 1
fi

# git
if command -v git &>/dev/null; then
    ok "git $(git --version | grep -oP '\d+\.\d+\.\d+')"
else
    err "git 未安装（apt install git）"
    exit 1
fi

# systemctl (可选)
HAVE_SYSTEMCTL=false
if command -v systemctl &>/dev/null; then
    HAVE_SYSTEMCTL=true
    ok "systemd 可用"
else
    warn "systemctl 未找到，跳过 systemd 部署"
fi

# psql (可选)
HAVE_PSQL=false
if command -v psql &>/dev/null; then
    HAVE_PSQL=true
    ok "psql $(psql --version | grep -oP '\d+\.\d+')"
else
    warn "psql 未安装，数据库连接由 PGConnector 内部管理"
fi

# ── 阶段 2: 克隆 / 更新项目 ──────────────────────────────────────────────
step "获取项目代码"

if [ -f "$PROJECT_DIR/stockpush/worker.py" ]; then
    warn "项目已存在于 $PROJECT_DIR，跳过克隆"
    cd "$PROJECT_DIR"
    if git rev-parse --git-dir &>/dev/null; then
        info "Git 仓库状态: $(git rev-parse --short HEAD) ($(git branch --show-current))"
        prompt "是否拉取最新代码? [Y/n]"
        read -r REPLY; REPLY="${REPLY:-Y}"
        if [[ "$REPLY" =~ ^[Yy] ]]; then
            git pull origin "$GIT_BRANCH" && ok "代码已更新"
        fi
    fi
else
    mkdir -p "$PROJECT_DIR"
    info "克隆 $GIT_REPO ($GIT_BRANCH) → $PROJECT_DIR"
    git clone --branch "$GIT_BRANCH" "$GIT_REPO" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
    ok "克隆完成 (commit: $(git rev-parse --short HEAD))"
fi

# ── 阶段 3: 创建虚拟环境 ─────────────────────────────────────────────────
step "创建 Python 虚拟环境"

VENV_DIR="$PROJECT_DIR/.venv"
if [ -d "$VENV_DIR" ]; then
    ok "虚拟环境已存在: $VENV_DIR"
else
    python3 -m venv "$VENV_DIR"
    ok "虚拟环境已创建: $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
info "Python: $(which python3)"

# ── 阶段 4: 安装 Python 依赖 ─────────────────────────────────────────────
step "安装 Python 依赖"

REQ_FILE="$PROJECT_DIR/stockpush/requirements.txt"
if [ -f "$REQ_FILE" ]; then
    pip install -r "$REQ_FILE" -q && ok "requirements.txt 安装完成"
fi

if [ -f "$PROJECT_DIR/pyproject.toml" ]; then
    pip install -e "$PROJECT_DIR" -q && ok "pyproject.toml 安装完成"
fi

# ── 阶段 5: PostgreSQL 配置 ──────────────────────────────────────────────
step "配置 PostgreSQL 连接"

ENV_FILE="$PROJECT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    warn ".env 已存在，跳过配置（如需修改请编辑 $ENV_FILE）"
    cat "$ENV_FILE"
else
    echo ""
    prompt "PostgreSQL 连接信息（直接回车使用默认值）"
    echo ""

    read -r -p "  主机 [localhost]: " PG_HOST;    PG_HOST="${PG_HOST:-localhost}"
    read -r -p "  端口 [5432]:       " PG_PORT;    PG_PORT="${PG_PORT:-5432}"
    read -r -p "  数据库 [zenith_quant]: " PG_DB; PG_DB="${PG_DB:-zenith_quant}"
    read -r -p "  用户名 [postgres]: " PG_USER;   PG_USER="${PG_USER:-postgres}"
    read -r -s -p "  密码 [postgres]: " PG_PASS;  PG_PASS="${PG_PASS:-postgres}"
    echo ""

    cat > "$ENV_FILE" <<EOF
PG_HOST=$PG_HOST
PG_PORT=$PG_PORT
PG_DB=$PG_DB
PG_USER=$PG_USER
PG_PASSWORD=$PG_PASS
EOF
    chmod 600 "$ENV_FILE"
    ok ".env 已写入 $ENV_FILE"

    # 可选：验证连接
    if $HAVE_PSQL; then
        info "验证数据库连接..."
        if PGPASSWORD="$PG_PASS" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "SELECT 1 AS ok" &>/dev/null; then
            ok "PostgreSQL 连接成功"
        else
            warn "连接失败，请检查 PG 配置；后续可手动重试: source .venv/bin/activate && python -m stockpush.services.sys_init"
        fi
    fi
fi

# ── 阶段 6: 创建本地配置 ─────────────────────────────────────────────────
step "创建 config.local.yaml"

LOCAL_CFG="$PROJECT_DIR/stockpush/config.local.yaml"
BASE_CFG="$PROJECT_DIR/stockpush/config.yaml"

if [ -f "$LOCAL_CFG" ]; then
    warn "config.local.yaml 已存在，跳过"
else
    echo ""
    prompt "飞书推送配置（留空可后续编辑 $LOCAL_CFG 补充）"
    echo ""
    read -r -p "  飞书 Webhook URL: " FEISHU_URL
    read -r -p "  签名密钥（可选）: " SIGN_SECRET
    read -r -p "  启用签名? [y/N]:  " SIGN_ENABLED; SIGN_ENABLED="${SIGN_ENABLED:-n}"

    # 从 config.yaml 读取默认 schedule（兼容带/不带引号的值）
    MORNING_START=$(grep -oP "morning_start:\\s*'?\\K[\\d:]+" "$BASE_CFG" 2>/dev/null || echo "09:25")
    MORNING_END=$(grep -oP "morning_end:\\s*'?\\K[\\d:]+" "$BASE_CFG" 2>/dev/null || echo "11:35")
    AFTERNOON_START=$(grep -oP "afternoon_start:\\s*'?\\K[\\d:]+" "$BASE_CFG" 2>/dev/null || echo "13:00:05")
    AFTERNOON_END=$(grep -oP "afternoon_end:\\s*'?\\K[\\d:]+" "$BASE_CFG" 2>/dev/null || echo "15:05")
    INTERVAL=$(grep -oP 'interval_seconds:\s*\K\d+' "$BASE_CFG" 2>/dev/null || echo "60")

    echo ""
    prompt "交易时段配置（直接回车使用默认值）"
    read -r -p "  早上开盘 [$MORNING_START]: " ms; ms="${ms:-$MORNING_START}"
    read -r -p "  早上收盘 [$MORNING_END]:   " me; me="${me:-$MORNING_END}"
    read -r -p "  下午开盘 [$AFTERNOON_START]: " as; as="${as:-$AFTERNOON_START}"
    read -r -p "  下午收盘 [$AFTERNOON_END]:   " ae; ae="${ae:-$AFTERNOON_END}"
    read -r -p "  执行间隔秒数 [$INTERVAL]:      " iv; iv="${iv:-$INTERVAL}"

    if [[ "$SIGN_ENABLED" =~ ^[Yy] ]]; then
        SIGN_ENABLED_BOOL=true
    else
        SIGN_ENABLED_BOOL=false
    fi

    # 加密 webhook / secret（如果提供）
    ENC_WEBHOOK=""
    ENC_SECRET=""
    if [ -n "$FEISHU_URL" ]; then
        info "加密飞书凭据..."
        ENC_WEBHOOK=$(cd "$PROJECT_DIR" && source "$VENV_DIR/bin/activate" && \
            python3 -c "from stockpush.credential_store import encrypt_value; print(encrypt_value('$FEISHU_URL'))" 2>/dev/null || echo "")
        if [ -n "$SIGN_SECRET" ]; then
            ENC_SECRET=$(cd "$PROJECT_DIR" && source "$VENV_DIR/bin/activate" && \
                python3 -c "from stockpush.credential_store import encrypt_value; print(encrypt_value('$SIGN_SECRET'))" 2>/dev/null || echo "")
        fi
    fi

    # 写入 config.local.yaml
    cat > "$LOCAL_CFG" <<CFGEOF
custom_functions:
  dir: ${PROJECT_DIR}/stockpush/userfunc
  functions:
  - desc: MF30多因子信号
    dir: ${PROJECT_DIR}/stockpush/userfunc
    file: MF30.py
    func: MF30
    name: MF30
  - desc: 5分分钟预警
    dir: ${PROJECT_DIR}/stockpush/userfunc
    file: MF05.py
    func: MF05
    name: MF05
  - desc: TF05双均线SID状态字节(5M)
    dir: ${PROJECT_DIR}/stockpush/userfunc
    file: TF05.py
    func: TF05
    name: TF05
datasources:
  primary: xtick
feishu:
  enabled: ${FEISHU_URL:+true}${FEISHU_URL:-false}
  sign_enabled: ${SIGN_ENABLED_BOOL}
  sign_secret: "${ENC_SECRET}"
  webhook: "${ENC_WEBHOOK}"
schedule:
  afternoon_end: '${ae}'
  afternoon_start: '${as}'
  interval_seconds: ${iv}
  morning_end: '${me}'
  morning_start: '${ms}'
CFGEOF
    ok "config.local.yaml 已创建"
fi

# ── 阶段 7: 加密凭据目录 ────────────────────────────────────────────────
step "初始化凭据存储"

# credential_store.py 首次导入时自动生成 config/telegram_credentials.key
if [ ! -f "$PROJECT_DIR/config/telegram_credentials.key" ]; then
    cd "$PROJECT_DIR" && source "$VENV_DIR/bin/activate"
    python3 -c "from stockpush.credential_store import encrypt_value; print(encrypt_value('init'))" 2>/dev/null || true
    if [ -f "$PROJECT_DIR/config/telegram_credentials.key" ]; then
        chmod 600 "$PROJECT_DIR/config/telegram_credentials.key"
        ok "加密密钥已生成: config/telegram_credentials.key"
    fi
else
    ok "加密密钥已存在"
fi

# ── 阶段 8: 数据库初始化 ─────────────────────────────────────────────────
step "初始化数据库表"

cd "$PROJECT_DIR"
source "$VENV_DIR/bin/activate"

if python3 -m stockpush.services.sys_init; then
    ok "数据库表初始化完成"
else
    warn "数据库初始化失败（可稍后重试: source .venv/bin/activate && python -m stockpush.services.sys_init）"
fi

# ── 阶段 9: 部署 systemd 服务（可选）────────────────────────────────────
step "部署 systemd 服务"

if $HAVE_SYSTEMCTL; then
    echo ""
    prompt "是否部署 systemd 定时器（生产推荐）? [Y/n]"
    read -r REPLY; REPLY="${REPLY:-Y}"
    if [[ "$REPLY" =~ ^[Yy] ]]; then
        SYSTEMD_SRC="$PROJECT_DIR/stockpush/deploy/systemd"
        if [ -d "$SYSTEMD_SRC" ]; then
            # 替换 service 中的路径为实际安装路径
            mkdir -p /etc/systemd/system
            for f in "$SYSTEMD_SRC"/*.service "$SYSTEMD_SRC"/*.timer; do
                [ ! -f "$f" ] && continue
                BASE=$(basename "$f")
                if [[ "$BASE" == *.service ]]; then
                    sed "s|/opt/stockpush/.venv|${VENV_DIR}|g; s|/opt/stockpush|${PROJECT_DIR}|g" "$f" > "/etc/systemd/system/$BASE"
                else
                    cp "$f" "/etc/systemd/system/$BASE"
                fi
                ok "  部署 $BASE"
            done

            # 部署 stop service（如果 timer 存在但 service 不存在）
            if [ -f /etc/systemd/system/f51-stop.timer ] && [ ! -f /etc/systemd/system/f51-stop.service ]; then
                cat > /etc/systemd/system/f51-stop.service <<'EOF'
[Unit]
Description=F5.1 Realtime Monitor Stop
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl stop f51-start.service
RemainAfterExit=false
EOF
                ok "  创建 f51-stop.service"
            fi

            systemctl daemon-reload

            # 启用 timers
            for t in f51-start.timer f51-stop.timer; do
                if [ -f "/etc/systemd/system/$t" ]; then
                    systemctl enable "$t" 2>/dev/null && ok "  启用 $t"
                fi
            done

            echo ""
            info "systemd 定时器状态:"
            systemctl list-timers --all 2>/dev/null | grep f51 || true
        else
            warn "systemd 部署文件不存在: $SYSTEMD_SRC"
        fi
    else
        info "跳过 systemd 部署"
    fi
else
    info "无 systemd，跳过服务部署"
fi

# ── 阶段 10: 完成 ────────────────────────────────────────────────────────
step "初始化完成"

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║        F5.1 stockpush 初始化完成                        ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  项目目录:  ${CYAN}$PROJECT_DIR${NC}"
echo -e "  虚拟环境:  ${CYAN}$VENV_DIR${NC}"
echo -e "  Python:    ${CYAN}$(python3 --version 2>/dev/null)${NC}"
echo ""
echo -e "${BOLD}常用命令:${NC}"
echo ""
echo -e "  ${GREEN}交互控制台${NC}        cd $PROJECT_DIR && ./run.sh"
echo -e "  ${GREEN}Headless 模式${NC}     cd $PROJECT_DIR && ./run.sh --headless"
echo -e "  ${GREEN}Hermes API${NC}        cd $PROJECT_DIR && ./run.sh --hermes status"
echo -e "  ${GREEN}初始化数据库${NC}      cd $PROJECT_DIR && source .venv/bin/activate && python -m stockpush.services.sys_init"
echo -e "  ${GREEN}查看定时器${NC}        systemctl list-timers --all | grep f51"
echo ""

if $HAVE_SYSTEMCTL; then
    TIMER_STATUS=$(systemctl is-active f51-start.timer 2>/dev/null || echo "inactive")
    if [ "$TIMER_STATUS" = "active" ]; then
        info "systemd 定时器 ${GREEN}已运行${NC}，每日 09:00 自动启动监控"
        echo ""
        info "立即启动监控: systemctl start f51-start.service"
    fi
fi

echo -e "${YELLOW}提示:${NC} 编辑 ${CYAN}$PROJECT_DIR/stockpush/config.local.yaml${NC} 调整飞书 webhook 等配置"
echo ""
