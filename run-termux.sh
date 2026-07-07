#!/usr/bin/env bash
# =============================================================================
# stockpush run-termux.sh — Termux 环境启动脚本
#
# 用法:
#   前台运行:  bash run-termux.sh
#   后台运行:  bash run-termux.sh --daemon
#   使用 daemon 管理: bash deploy/termux/stockpush-daemon.sh start
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PGDATA="${PGDATA:-$HOME/.pg/data}"
LOG_FILE="${LOG_FILE:-/tmp/stockpush.log}"
PID_FILE="${PID_FILE:-/tmp/stockpush.pid}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()    { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $*"; }
warn()  { echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} $*"; }

# ── 确保 PostgreSQL 运行 ──────────────────────────────────────────────────
ensure_pg() {
    if ! pg_ctl -D "$PGDATA" status &>/dev/null; then
        info "启动 PostgreSQL..."
        pg_ctl -D "$PGDATA" -l "$PGDATA/logfile" start
        ok "PostgreSQL 已启动"
    fi
}

# ── 获取 wake-lock ────────────────────────────────────────────────────────
acquire_wakelock() {
    if command -v termux-wake-lock &>/dev/null; then
        termux-wake-lock
        ok "wake-lock 已获取"
    else
        warn "termux-api 不可用，跳过 wake-lock"
    fi
}

# ── 释放 wake-lock ────────────────────────────────────────────────────────
release_wakelock() {
    if command -v termux-wake-lock &>/dev/null; then
        termux-wake-lock 2>/dev/null || true
        info "wake-lock 尝试释放"
    fi
}

# ── 清理函数 ──────────────────────────────────────────────────────────────
cleanup() {
    info "进程退出，清理资源..."
    release_wakelock
    rm -f "$PID_FILE"
    info "清理完成"
}
trap cleanup EXIT INT TERM

# ── 主流程 ────────────────────────────────────────────────────────────────
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Stockpush Termux 实时监控                          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo

# 1. 确保 PG 运行
ensure_pg

# 2. 获取 wake-lock
acquire_wakelock

# 3. 写入 PID（后台模式）
if [ "${1:-}" = "--daemon" ]; then
    echo $$ > "$PID_FILE"
    ok "PID $(cat "$PID_FILE") 已写入 $PID_FILE"
fi

# 4. 启动 worker（交易日检查、信号追赶、APScheduler 全由 Python 处理）
info "启动 worker --headless..."
cd "$PROJECT_DIR"
exec python3 -m stockpush.worker --headless
