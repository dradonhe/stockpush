"""F5.1 headless startup runner for systemd timer mode."""

import logging
import os
import signal
import sys
import time
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
        sys.exit(0)

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

    # ── 4. Check dividends & splits ──
    if watchlist:
        events = calendar.get_today_dividends(watchlist)
        for ev in events:
            symbol = ev.get("symbol", "")
            name = ev.get("name", "")
            event_type = ev.get("event_type", "dividend")
            detail = ev.get("detail", "")
            if symbol:
                if event_type == "split":
                    pusher.push_fund_split_notice(symbol, name, detail)
                else:
                    pusher.push_dividend_notice(symbol, name, detail)
                # 除权除息/拆分后删除旧数据并全量重下
                ok = _full_reload_symbol(fetcher, symbol)
                if ok:
                    pusher.push(
                        "[F5.1 监控通知]\n"
                        f"标的: {symbol} {name}\n"
                        f"事件: 今日除权除息/拆分，已删除旧数据并重新下载\n"
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    pusher.push(
                        "[F5.1 监控通知]\n"
                        f"标的: {symbol} {name}\n"
                        f"事件: 今日除权除息/拆分，但重新下载失败，请检查日志\n"
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )

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
        time.sleep(1)


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


# 除权除息后全量重下：周期 -> 回溯天数（用户确认）
_RELOAD_BACKDAYS = {
    '1m': 180,   # 半年
    '5m': 365,   # 1 年
    '30m': 730,  # 2 年
    '1d': 730,   # 2 年
}


def _full_reload_symbol(fetcher, symbol: str) -> bool:
    """删除标的历史数据并重新下载（除权除息/拆分后调用）。

    逐周期：先 DELETE tb_raw_{period} 中该 symbol 全部数据，
    再按各周期回溯天数 fetch_and_save_history 重下。

    Returns:
        True=全部周期成功；False=任一周期失败（不抛异常）
    """
    from datetime import date, timedelta
    ok = True
    for period, backdays in _RELOAD_BACKDAYS.items():
        try:
            from stockpush.pg_connector import PGConnector
            db = PGConnector()
            table = f"tb_raw_{period}"
            deleted = db.execute_update(
                f"DELETE FROM {table} WHERE symbol = %s", (symbol,)
            )
            db.close()
            start = (date.today() - timedelta(days=backdays)).isoformat()
            end = date.today().isoformat()
            ok_, saved, src = fetcher.fetch_and_save_history(symbol, period, start, end)
            if not ok_:
                logger.warning("reload %s %s: 下载失败", symbol, period)
                ok = False
            else:
                logger.info("reload %s %s: 删除%d条, 重下%d条 (%s)", symbol, period, deleted, saved, src)
        except Exception as e:
            logger.warning("reload %s %s 异常: %s", symbol, period, e)
            ok = False
    return ok


def _calc_runtime(start: datetime) -> str:
    """Calculate human-readable runtime from start time to now."""
    delta = datetime.now() - start
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"{hours}h {minutes}m"
