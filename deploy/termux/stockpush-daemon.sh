#!/usr/bin/env bash
# =============================================================================
# stockpush-daemon.sh — Termux 后台进程管理
#
# 用法:
#   bash deploy/termux/stockpush-daemon.sh start     启动后台监控
#   bash deploy/termux/stockpush-daemon.sh stop      停止后台监控
#   bash deploy/termux/stockpush-daemon.sh status    查看运行状态
#   bash deploy/termux/stockpush-daemon.sh restart   重启
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PID_FILE="${PID_FILE:-/tmp/stockpush.pid}"
LOG_FILE="${LOG_FILE:-/tmp/stockpush.log}"
PGDATA="${PGDATA:-$HOME/.pg/data}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }

# ── 检查进程是否存活 ──────────────────────────────────────────────────────
is_running() {
    if [ ! -f "$PID_FILE" ]; then
        return 1
    fi
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -z "$pid" ]; then
        return 1
    fi
    kill -0 "$pid" 2>/dev/null
}

# ── 确保 PostgreSQL 运行 ──────────────────────────────────────────────────
ensure_pg() {
    if pg_ctl -D "$PGDATA" status &>/dev/null; then
        return 0
    fi
    info "PostgreSQL 未运行，正在启动..."
    pg_ctl -D "$PGDATA" -l "$PGDATA/logfile" start
    ok "PostgreSQL 已启动"
}

# ── start ─────────────────────────────────────────────────────────────────
cmd_start() {
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        warn "监控已在运行中 (PID: $pid)"
        return 0
    fi

    # 清理残留 PID 文件
    if [ -f "$PID_FILE" ]; then
        warn "发现残留 PID 文件（进程已不存在），已清理"
        rm -f "$PID_FILE"
    fi

    ensure_pg

    info "启动监控进程..."
    cd "$PROJECT_DIR"

    # 获取 wake-lock
    if command -v termux-wake-lock &>/dev/null; then
        termux-wake-lock
        info "wake-lock 已获取"
    fi

    # 后台启动
    nohup python3 -m stockpush.worker --headless >> "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    # 确认启动成功
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        ok "监控已启动 (PID: $pid)"
        info "日志: tail -f $LOG_FILE"
    else
        err "进程启动失败，请检查日志: cat $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

# ── stop ──────────────────────────────────────────────────────────────────
cmd_stop() {
    if ! is_running; then
        warn "监控未运行"
        if [ -f "$PID_FILE" ]; then
            rm -f "$PID_FILE"
        fi
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")
    info "停止监控 (PID: $pid)..."

    # 优雅停止 (SIGTERM → headless_runner.py 有处理)
    kill "$pid" 2>/dev/null || true

    # 等待最多 10 秒
    local waited=0
    while kill -0 "$pid" 2>/dev/null && [ $waited -lt 10 ]; do
        sleep 1
        waited=$((waited + 1))
    done

    # 如果还没死，强制 kill
    if kill -0 "$pid" 2>/dev/null; then
        warn "进程未响应 SIGTERM，强制终止..."
        kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi

    rm -f "$PID_FILE"

    # 释放 wake-lock
    if command -v termux-wake-unlock &>/dev/null; then
        termux-wake-unlock
        info "wake-lock 已释放"
    fi

    ok "监控已停止"
}

# ── status ────────────────────────────────────────────────────────────────
cmd_status() {
    echo "═══════════════════════════════════════════"
    echo "  Stockpush Termux 监控状态"
    echo "═══════════════════════════════════════════"

    # 进程状态
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        echo -e "  状态:     ${GREEN}运行中${NC}"
        echo "  PID:      $pid"
        # 运行时长
        local elapsed
        elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | xargs || echo "?")
        echo "  运行时长: $elapsed"
    else
        echo -e "  状态:     ${RED}未运行${NC}"
    fi

    # PID 文件
    if [ -f "$PID_FILE" ]; then
        echo "  PID 文件: $PID_FILE ($(cat "$PID_FILE"))"
    else
        echo "  PID 文件: 无"
    fi

    # PostgreSQL
    if pg_ctl -D "$PGDATA" status &>/dev/null; then
        echo -e "  PostgreSQL: ${GREEN}运行中${NC}"
    else
        echo -e "  PostgreSQL: ${RED}未运行${NC}"
    fi

    # Wake-lock
    if command -v termux-wake-lock &>/dev/null; then
        echo "  Wake-lock: 可用"
    else
        echo "  Wake-lock: 不可用"
    fi

    # 日志
    echo "  日志文件: $LOG_FILE"
    if [ -f "$LOG_FILE" ]; then
        echo "  日志大小: $(du -h "$LOG_FILE" | cut -f1)"
        echo "  ─── 最近 5 行 ───"
        tail -5 "$LOG_FILE" 2>/dev/null | sed 's/^/    /' || echo "    (空)"
    fi
    echo "═══════════════════════════════════════════"
}

# ── restart ───────────────────────────────────────────────────────────────
cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

# ── 入口 ──────────────────────────────────────────────────────────────────
case "${1:-}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    restart) cmd_restart ;;
    *)
        echo "用法: $(basename "$0") {start|stop|status|restart}"
        echo ""
        echo "  start   启动后台监控（含 PostgreSQL + wake-lock）"
        echo "  stop    停止后台监控"
        echo "  status  查看运行状态和日志"
        echo "  restart 重启监控"
        exit 1
        ;;
esac
