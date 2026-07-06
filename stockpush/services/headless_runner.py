"""F5.1 headless startup runner for systemd timer mode."""

import logging
import os
import signal
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

def run_headless(config: dict, pusher, fetcher, calendar, scheduler, job_func) -> None:
    """Headless startup flow — called by worker.py --headless."""

    # ── 2. Check trading day ──
    if not calendar.is_today_trading_day():
        msg = (
            "[F5.1 实时监控]\n"
            f"状态: 今日非交易日，已跳过\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        pusher.push(msg)
        logger.info("Not a trading day, exiting.")
        os._exit(0)

    # ── 3. Push startup notification ──
    watchlist = calendar.load_watchlist()
    ds_cfg = config.get("datasources", {})
    startup_msg = (
        "[F5.1 实时监控]\n"
        f"状态: 已启动\n"
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"自选股: {len(watchlist)} 只\n"
        f"数据源: {ds_cfg.get('primary', 'xtick')}"
    )
    pusher.push(startup_msg)

    # ── 4. Check dividends ──
    if watchlist:
        dividend_stocks = calendar.get_today_dividends(watchlist)
        for div in dividend_stocks:
            symbol = div.get("symbol", "")
            name = div.get("name", "")
            if symbol:
                pusher.push_dividend_notice(symbol, name)
                # [TODO] full download when implemented

    # ── 5. Late-start data integrity check ──
    now = datetime.now()
    nine_thirty = now.replace(hour=9, minute=30, second=0, microsecond=0)
    if now > nine_thirty:
        _check_and_fill_data(fetcher, watchlist, pusher)
    else:
        logger.info("Before 09:30, skipping data integrity check.")

    # ── 6. Register SIGTERM handler ──
    startup_time = datetime.now()
    shutdown_requested = False

    def _handle_sigterm(signum, frame):
        nonlocal shutdown_requested
        shutdown_requested = True
        logger.info("SIGTERM received, shutting down...")

    signal.signal(signal.SIGTERM, _handle_sigterm)

    # ── 7. Catchup signals after late start ──
    try:
        now = datetime.now()
        if now > nine_thirty:
            import threading
            from stockpush.services.function_engine import FunctionEngine
            from stockpush.services.function_registry import FunctionRegistry
            from stockpush.services.signal_store import SignalStore
            registry = FunctionRegistry()
            store = SignalStore()
            engine = FunctionEngine(registry, store, pusher, lambda: watchlist)
            today = now.strftime("%Y-%m-%d")
            catchup_start = today + " 09:25:00"
            catchup_end = now.strftime("%Y-%m-%d %H:%M:%S")
            logger.info("Signal catchup: %s -> %s", catchup_start, catchup_end)

            catchup_error = []
            def _run_catchup():
                try:
                    engine.run(catchup_start, catchup_end)
                except Exception as e:
                    catchup_error.append(e)

            thread = threading.Thread(target=_run_catchup, daemon=True)
            thread.start()
            thread.join(timeout=300)  # 5 minutes timeout
            if thread.is_alive():
                logger.warning("Signal catchup timeout after 5 minutes, continuing...")
                pusher.push("[F5.1 实时监控]\n⚠ 信号补检查超时（>5分钟），已跳过")
            elif catchup_error:
                logger.error("Signal catchup failed: %s", catchup_error[0])
    except Exception as e:
        logger.error("Signal catchup failed: %s", e)

    # ── 8. Start scheduler (blocking) ──
    logger.info("Headless mode: starting scheduler...")
    scheduler.start(job_func)
    # Block until scheduler auto-stops (past end time) or SIGTERM
    while scheduler.is_running():
        if shutdown_requested:
            stop_msg = (
                "[F5.1 实时监控]\n"
                f"状态: 已停止\n"
                f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"运行时长: {_calc_runtime(startup_time)}"
            )
            pusher.push(stop_msg)
            scheduler.stop()
            break
        __import__("time").sleep(1)


def _check_and_fill_data(fetcher, symbols: list, pusher) -> None:
    """Check data completeness for today and fill missing data."""
    results = []
    for symbol in symbols:
        for period in ['1m', '5m', '30m', '1d']:
            try:
                complete = fetcher.check_today_data_complete(symbol, period)
            except Exception:
                complete = False
            if not complete:
                try:
                    ok, saved, src = fetcher.fetch_and_save(symbol, period)
                    results.append((symbol, period, ok, saved, src))
                except Exception as e:
                    logger.warning("Failed to fetch %s %s: %s", symbol, period, e)
                    results.append((symbol, period, False, 0, ""))
            else:
                results.append((symbol, period, True, 0, ""))

    # Build summary message
    lines = ["[F5.1 实时监控]", "数据完整性检查完成"]
    for symbol, period, ok, cnt, src in results:
        if ok and cnt > 0:
            lines.append(f"{symbol} {period}: ✅ ({cnt}条, {src})")
        elif ok:
            lines.append(f"{symbol} {period}: ✅")
        else:
            lines.append(f"{symbol} {period}: ⚠ 缺失, 已补全 ({cnt}条, {src})" if cnt > 0 else f"{symbol} {period}: ⚠ 补全失败")

    msg = "\n".join(lines)
    pusher.push(msg)
    logger.info("Data integrity check done.")


def _calc_runtime(start: datetime) -> str:
    """Calculate human-readable runtime from start time to now."""
    delta = datetime.now() - start
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"{hours}h {minutes}m"
