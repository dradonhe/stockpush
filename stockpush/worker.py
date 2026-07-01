#!/usr/bin/env python
"""F5.1 实时监控推送 - 控制台入口"""

import sys
import os

# Windows GBK 终端兼容：强制 UTF-8
if sys.platform == 'win32':
    os.system('chcp 65001 > /dev/null 2>&1')
os.environ['PYTHONIOENCODING'] = 'utf-8'

VENV_PY = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '.venv', 'Scripts', 'python.exe'))
if os.path.exists(VENV_PY) and os.path.normpath(sys.executable) != VENV_PY:
    import subprocess
    result = subprocess.run([VENV_PY, __file__] + sys.argv[1:])
    sys.exit(result.returncode)

import signal
signal.signal(signal.SIGINT, lambda s, f: os._exit(0))
if hasattr(signal, 'SIGBREAK'):
    signal.signal(signal.SIGBREAK, lambda s, f: os._exit(0))

import argparse
from pathlib import Path
import yaml
import json

PROJECT_ROOT = Path(__file__).parent.parent
PACKAGE_ROOT = Path(__file__).parent
CONFIG_FILE = PACKAGE_ROOT / 'config.yaml'
LOCAL_CONFIG_FILE = PACKAGE_ROOT / 'config.local.yaml'
GONGSHI_DIR = PACKAGE_ROOT / 'userfunc'


def main():
    parser = argparse.ArgumentParser(description='F5.1 Realtime Monitor Console')
    parser.add_argument('--config', type=str, help='Config file path')
    parser.add_argument('--headless', action='store_true', help='Run in headless (systemd timer) mode')
    parser.add_argument('--hermes', type=str, const='status', nargs='?',
                        help='Hermes agent remote control: action name')
    parser.add_argument('--symbol', type=str, help='Stock symbol (for hermes actions)')
    parser.add_argument('--period', type=str, help='Kline period (for hermes actions)')
    parser.add_argument('--start', type=str, help='Start date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End date YYYY-MM-DD')
    parser.add_argument('--limit', type=int, default=20, help='Result limit')
    args = parser.parse_args()

    config_file = Path(args.config) if args.config else (LOCAL_CONFIG_FILE if LOCAL_CONFIG_FILE.exists() else CONFIG_FILE)
    if config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # 创建 gongshi/ 目录
    if not GONGSHI_DIR.exists():
        GONGSHI_DIR.mkdir(parents=True, exist_ok=True)
        (GONGSHI_DIR / '__init__.py').touch()

    config.setdefault('custom_functions', {}).setdefault('dir', str(GONGSHI_DIR))

    sys.path.insert(0, str(PROJECT_ROOT))

    if args.hermes:
        _run_hermes_mode(config, args)
        return

    if args.headless:
        _run_headless_mode(config)
    else:
        _run_interactive(config)


def _run_hermes_mode(config: dict, args):
    """Execute a Hermes API action and print JSON result."""
    from stockpush.services.hermes_api import HermesAPI

    api = HermesAPI(config, PROJECT_ROOT, PACKAGE_ROOT)

    actions = {
        "menu":         lambda: api.menu(),
        "status":       lambda: api.status(),
        "start":        lambda: api.start_monitor(),
        "stop":         lambda: api.stop_monitor(),
        "fill-today":   lambda: api.fill_today(args.symbol, args.period),
        "fill-history": lambda: api.fill_history(args.symbol, args.period, args.start, args.end),
        "signals":      lambda: api.today_signals(args.symbol),
        "pool-list":    lambda: api.pool_list(),
        "pool-add":     lambda: api.pool_add(args.symbol),
        "pool-remove":  lambda: api.pool_remove(args.symbol),
        "data-summary": lambda: api.data_summary(args.symbol, args.start, args.end, args.period),
        "data-detail":  lambda: api.data_detail(args.symbol, args.period, args.start, args.end, args.limit),
        "dividends":    lambda: api.dividend_view(),
        "config-show":  lambda: api.config_show(),
        "feishu-test":  lambda: api.feishu_test(),
        "push-status":  lambda: api.push_status(),
        "push-pool":    lambda: api.push_pool(),
        "push-menu":    lambda: api.push_menu(),
    }

    handler = actions.get(args.hermes)
    if handler is None:
        result = {"success": False, "data": None, "message": f"未知操作: {args.hermes}",
                  "available": list(actions.keys())}
    else:
        result = handler()

    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_headless_mode(config: dict):
    """Run in headless mode — systemd timer driven."""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    from stockpush.services.feishu_pusher import FeishuPusher
    from stockpush.services.data_fetcher import DataFetcher
    from stockpush.services.calendar_checker import CalendarChecker
    from stockpush.services.scheduler import RealtimeScheduler
    from stockpush.services.pool_watcher import PoolWatcher

    feishu_cfg = config.get("feishu", {})
    raw_secret = feishu_cfg.get("sign_secret", "")
    sign_secret = None
    if raw_secret:
        try:
            from stockpush.credential_store import decrypt_value
            sign_secret = decrypt_value(raw_secret)
        except Exception:
            sign_secret = raw_secret
    raw_webhook = feishu_cfg.get("webhook", "")
    webhook_url = ""
    if raw_webhook:
        try:
            from stockpush.credential_store import decrypt_value
            webhook_url = decrypt_value(raw_webhook)
        except Exception:
            webhook_url = raw_webhook
    pusher = FeishuPusher(
        webhook_url, feishu_cfg.get("enabled", False),
        sign_secret, feishu_cfg.get("sign_enabled", False)
    )

    ds = config.get("datasources", {})
    fetcher = DataFetcher(ds.get("primary", "xtick"))

    calendar = CalendarChecker()

    sc = config.get("schedule", {})
    scheduler = RealtimeScheduler(
        morning_start=sc.get("morning_start", "09:25"),
        morning_end=sc.get("morning_end", "11:35"),
        afternoon_start=sc.get("afternoon_start", "13:00:05"),
        afternoon_end=sc.get("afternoon_end", "15:05"),
        interval_seconds=sc.get("interval_seconds", 65),
    )

    _job_logger = logging.getLogger("f51.headless.job")

    watcher = PoolWatcher()

    _signal_engine_cache = {}

    def _run_signals_for_tick(symbols, now_str, logger):
        """Run FunctionEngine for all enabled functions."""
        try:
            cache = _signal_engine_cache
            if 'engine' not in cache:
                from stockpush.services.function_registry import FunctionRegistry
                from stockpush.services.signal_store import SignalStore
                from stockpush.services.function_engine import FunctionEngine
                registry = FunctionRegistry()
                store = SignalStore()
                cache['engine'] = FunctionEngine(registry, store, pusher,
                                                   lambda: symbols)
            engine = cache['engine']

            from datetime import datetime, timedelta
            now = datetime.now()
            for func in engine.registry.get_enabled():
                parts = func.period.split(':')
                base = parts[0]
                end = now.strftime("%Y-%m-%d %H:%M:%S")
                if base == '5m':
                    start = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
                elif base == '30m':
                    start = (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
                elif base == '1d':
                    start = now.strftime("%Y-%m-%d") + " 09:25:00"
                else:
                    continue
                engine.run(start, end)
        except Exception as e:
            logger.error("Signal engine run failed: %s", e)

    def job_func():
        try:
            symbols = watcher.get_symbols()
            if not symbols:
                _job_logger.warning("Watchlist is empty, skipping job.")
                return

            now_dt = __import__("datetime").datetime.now()
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            from stockpush.pg_connector import PGConnector as _DBC
            _log_db = _DBC()

            def _filter_bar(df, period, dt):
                """从全天bar中，筛选出覆盖dt的那一根（同时兼容START/END两种时间戳约定）"""
                if df is None or df.empty:
                    return df
                import pandas as _pd
                if period == '1d':
                    target = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                    ts_col = next((c for c in ('ts', 'date', 'datetime') if c in df.columns), None)
                    if ts_col is None:
                        return df
                    return df[_pd.to_datetime(df[ts_col]) == target]
                period_m = int(period.replace('m', ''))
                ts_col = next((c for c in ('ts', 'date', 'datetime') if c in df.columns), None)
                if ts_col is None:
                    return df
                bar_times = _pd.to_datetime(df[ts_col])
                dt_ts = _pd.Timestamp(dt)
                period_td = _pd.Timedelta(minutes=period_m)
                # 优先END约定（bar_ts为结束时间）：bar_ts - period < dt <= bar_ts
                matched = df[(bar_times - period_td < dt_ts) & (dt_ts <= bar_times)]
                if matched.empty:
                    # 回退START约定（bar_ts为开始时间）：bar_ts <= dt < bar_ts + period
                    matched = df[(bar_times <= dt_ts) & (dt_ts < bar_times + period_td)]
                if matched.empty:
                    # 仍无匹配 → 取dt前最近一根已完成bar
                    past = df[bar_times <= dt_ts]
                    if not past.empty:
                        matched = past.sort_values(ts_col, ascending=False).iloc[[0]]
                elif len(matched) > 1:
                    matched = matched.sort_values(ts_col, ascending=False).iloc[[0]]
                return matched

            try:
                for symbol in symbols:
                    for period in ["1m", "5m", "30m", "1d"]:
                        _sym, _per = symbol, period
                        def _log_cb(df):
                            try:
                                from stockpush.services.download_logger import log_downloads
                                filtered = _filter_bar(df, _per, now_dt)
                                log_downloads(_log_db, now_str, _sym, _per, filtered)
                            except Exception:
                                pass
                        ok, saved, src = fetcher.fetch_and_save(symbol, period, log_callback=_log_cb)
                        if saved:
                            _job_logger.info("%s %s (%s): %d 条", symbol, period, src, saved)

                # ── 信号计算 ──
                _run_signals_for_tick(symbols, now_str, _job_logger)
            finally:
                _log_db.close()
        except Exception as e:
            _job_logger.error("Job failed: %s", e)

    from stockpush.services.headless_runner import run_headless
    run_headless(config, pusher, fetcher, calendar, scheduler, job_func)


def _run_interactive(config: dict):
    """Run in interactive console mode."""
    from stockpush.console import Console
    console = Console(config, PROJECT_ROOT, PACKAGE_ROOT)
    console.run()


if __name__ == '__main__':
    main()
