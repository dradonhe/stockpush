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
signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
if hasattr(signal, 'SIGBREAK'):
    signal.signal(signal.SIGBREAK, lambda s, f: sys.exit(0))

import argparse
from pathlib import Path
import yaml
import json
import datetime
import logging

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
    parser.add_argument('--output', type=str, choices=['json','text'], default='json',
                        help='Output format (default: json)')
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
    """Execute a Hermes API action and print result."""
    from stockpush.services.hermes_api import HermesAPI

    api = HermesAPI(config, PROJECT_ROOT, PACKAGE_ROOT)
    result = api.call(args.hermes,
                      symbol=args.symbol, period=args.period,
                      start=args.start, end=args.end, limit=args.limit)

    if args.output == "text":
        _print_text(args.hermes, result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def _print_text(action: str, result: dict):
    """Format a Hermes API result as a one-line human-readable summary."""
    ok = result.get("success", False)
    icon = "✅" if ok else "❌"
    msg = result.get("message", "")
    data = result.get("data", {})

    formatters = {
        "status": lambda: (
            f"{icon} 监控:{'运行中' if data.get('running') else '已停止'}"
            f" | 数据源:{data.get('datasource',{}).get('primary','?')}"
            f" | 自选:{data.get('watchlist',{}).get('count',0)}只"
            f" | 信号:{data.get('signal',{}).get('enabled_count',0)}/{data.get('signal',{}).get('function_count',0)}个启用"
            f" | 今日信号:{data.get('today_signals',{}).get('count',0)}个"
        ),
        "signals": lambda: (
            f"{icon} {msg}"
            + (f" ({data.get('count',0)}条)" if ok and data else "")
        ),
        "test": lambda: (
            f"{icon} {msg}"
            + (f" | 飞书:{data.get('feishu',{}).get('test','?')}"
               f" Telegram:{data.get('telegram',{}).get('test','?')}"
               if ok and data else "")
        ),
    }

    fmt = formatters.get(action, lambda: f"{icon} {msg}")
    print(fmt())
def _run_headless_mode(config: dict):
    """Run in headless mode — systemd timer driven."""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    from stockpush.services.feishu_pusher import FeishuPusher
    from stockpush.services.telegram_pusher import TelegramPusher
    from stockpush.services.push_manager import PushManager
    from stockpush.services.data_fetcher import DataFetcher
    from stockpush.services.calendar_checker import CalendarChecker
    from stockpush.services.scheduler import RealtimeScheduler
    from stockpush.services.pool_watcher import PoolWatcher

    from stockpush.services.credential_utils import decrypt_config_value
    feishu_cfg = config.get("feishu", {})
    raw_secret = feishu_cfg.get("sign_secret", "")
    sign_secret = decrypt_config_value(raw_secret) or None
    raw_webhook = feishu_cfg.get("webhook", "")
    webhook_url = decrypt_config_value(raw_webhook)
    feishu_pusher = FeishuPusher(
        webhook_url, feishu_cfg.get("enabled", False),
        sign_secret, feishu_cfg.get("sign_enabled", False)
    )

    telegram_cfg = config.get("telegram", {})
    raw_token = telegram_cfg.get("bot_token", "")
    raw_chat = telegram_cfg.get("chat_id", "")
    bot_token = decrypt_config_value(raw_token)
    chat_id = decrypt_config_value(raw_chat)
    telegram_pusher = TelegramPusher(
        bot_token, chat_id,
        telegram_cfg.get("enabled", False),
    )

    push_method = config.get("push_method", "feishu")
    pusher = PushManager(feishu_pusher, telegram_pusher, push_method)

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
                                                   lambda: symbols,
                                                   channel_states_enabled=True)
            engine = cache['engine']

            from datetime import datetime, timedelta
            now = datetime.now()
            for func in engine.registry.get_enabled():
                parts = func.period.split(':')
                base = parts[0]
                end = now.strftime("%Y-%m-%d %H:%M:%S")
                if base == '1m':
                    start = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
                elif base == '5m':
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

            now_dt = datetime.datetime.now()
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
