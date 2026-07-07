#!/usr/bin/env bash
# =============================================================================
# stockpush sysinit-termux.sh — Termux 环境一键初始化脚本
#
# 用法:
#   cd $HOME/stockpush && bash sysinit-termux.sh
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
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
STOCKPUSH_DIR="$PROJECT_DIR/stockpush"
PGDATA="${PGDATA:-$HOME/.pg/data}"

STEP=0
TOTAL=8

step() { STEP=$((STEP + 1)); echo; echo -e "${BOLD}[${STEP}/${TOTAL}]${NC} $*"; }

echo
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Stockpush Termux 初始化                            ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo

# =============================================================================
# 阶段 1: Termux 环境检查
# =============================================================================
step "检查 Termux 环境"

if [ -z "${TERMUX_VERSION:-}" ] && [ ! -d /data/data/com.termux ]; then
    warn "未检测到 Termux 环境，但继续执行..."
fi

if command -v termux-wake-lock &>/dev/null; then
    ok "termux-api 已安装"
else
    warn "termux-api 未安装，wake-lock 不可用"
    warn "建议: pkg install termux-api"
fi

if command -v termux-setup-storage &>/dev/null; then
    ok "termux-storage 已配置"
fi

# =============================================================================
# 阶段 2: 安装系统包
# =============================================================================
step "安装系统包"

PACKAGES="python postgresql git rust binutils"

if command -v pkg &>/dev/null; then
    info "更新包列表..."
    pkg update -y
    info "安装: $PACKAGES"
    pkg install -y python postgresql git rust binutils
    ok "系统包安装完成"
else
    warn "pkg 不可用，跳过系统包安装（请手动安装: $PACKAGES）"
fi

# =============================================================================
# 阶段 3: Python 版本检查
# =============================================================================
step "检查 Python 版本"

PY_VER=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' || echo "0.0")
if awk "BEGIN {exit !($PY_VER >= 3.11)}" 2>/dev/null; then
    ok "Python $PY_VER"
else
    warn "Python $PY_VER（建议 ≥ 3.11），继续..."
fi

# =============================================================================
# 阶段 4: 安装 Python 依赖
# =============================================================================
step "安装 Python 依赖"

cd "$PROJECT_DIR"

if [ -f requirements.txt ]; then
    info "pip install -r requirements.txt"
    pip install -r requirements.txt
    ok "requirements.txt 安装完成"
else
    warn "requirements.txt 未找到，跳过"
fi

info "pip install -e ."
pip install -e .
ok "项目包安装完成"

# =============================================================================
# 阶段 5: 初始化 PostgreSQL
# =============================================================================
step "初始化 PostgreSQL"

if ! command -v pg_ctl &>/dev/null; then
    err "pg_ctl 未找到，请先安装 postgresql"
    exit 1
fi

# 初始化数据目录
if [ ! -f "$PGDATA/postgresql.conf" ]; then
    info "初始化 PostgreSQL 数据目录: $PGDATA"
    initdb "$PGDATA"
    ok "数据库初始化完成"
else
    ok "PostgreSQL 数据目录已存在"
fi

# 启动 PostgreSQL
if pg_ctl -D "$PGDATA" status &>/dev/null; then
    ok "PostgreSQL 已在运行"
else
    info "启动 PostgreSQL..."
    pg_ctl -D "$PGDATA" -l "$PGDATA/logfile" start
    ok "PostgreSQL 已启动"
fi

# 创建 stockpush 数据库
if psql -U postgres -lqt 2>/dev/null | grep -qw stockpush; then
    ok "数据库 stockpush 已存在"
else
    info "创建数据库 stockpush..."
    createdb -U postgres stockpush
    ok "数据库 stockpush 已创建"
fi

# =============================================================================
# 阶段 6: 生成配置文件
# =============================================================================
step "创建 config.local.yaml"

LOCAL_CFG="$STOCKPUSH_DIR/config.local.yaml"

if [ -f "$LOCAL_CFG" ]; then
    ok "config.local.yaml 已存在，跳过"
else
    # Postgres 连接信息
    cat > "$LOCAL_CFG" << 'YAMLEOF'
# Termux PostgreSQL 本地连接
postgres:
  host: localhost
  port: 5432
  user: postgres
  password: postgres
  database: stockpush

# 飞书推送（请替换为你的 webhook 地址）
feishu:
  enabled: true
  webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook地址"
  sign_enabled: false

# 启用推送
push_enabled: true
YAMLEOF
    ok "config.local.yaml 已创建（请编辑飞书 webhook 地址）"
fi

# =============================================================================
# 阶段 7: 数据库表初始化
# =============================================================================
step "初始化数据库表"

if python3 -m stockpush.services.sys_init 2>&1; then
    ok "数据库表初始化完成"
else
    warn "数据库表初始化失败（可稍后重试: python3 -m stockpush.services.sys_init）"
fi

# =============================================================================
# 阶段 8: 环境变量配置
# =============================================================================
step "配置环境变量"

BASHRC="$HOME/.bashrc"
MARKER="# stockpush env"

if grep -qF "$MARKER" "$BASHRC" 2>/dev/null; then
    ok "环境变量已配置"
else
    cat >> "$BASHRC" << 'EOF'

# stockpush env
export STOCKPUSH_HOME=$HOME/stockpush
export PYTHONPATH=$STOCKPUSH_HOME:$PYTHONPATH
# PostgreSQL
export PGDATA=$HOME/.pg/data
export PGHOST=localhost
export PGPORT=5432
export PGUSER=postgres
export PGDATABASE=stockpush
EOF
    ok "环境变量已写入 ~/.bashrc（请执行 source ~/.bashrc 使其生效）"
fi

# =============================================================================
# 完成
# =============================================================================
echo
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Termux 初始化完成！                                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo
echo -e "  后续步骤:"
echo -e "  1. ${BOLD}source ~/.bashrc${NC}                        # 加载环境变量"
echo -e "  2. ${BOLD}编辑飞书 webhook${NC}"
echo -e "     vi stockpush/config.local.yaml"
echo -e "  3. ${BOLD}测试飞书推送${NC}"
echo -e "     python3 -m stockpush.worker --hermes test"
echo -e "  4. ${BOLD}启动监控${NC}"
echo -e "     bash run-termux.sh"
echo
