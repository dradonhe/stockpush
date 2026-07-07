"""F5.1 Hermes Agent 远程控制 API

所有方法返回 JSON-serializable dict，不依赖终端交互。
供 worker.py --hermes <action> 调用。
"""

import logging
import shutil
import subprocess
from datetime import datetime, date
from pathlib import Path
from typing import Any


def _has_systemctl() -> bool:
    return shutil.which("systemctl") is not None

import yaml
from stockpush.services.feishu_pusher import FeishuPusher
from stockpush.services.data_fetcher import DataFetcher
from stockpush.services.calendar_checker import CalendarChecker
from stockpush.services.pool_watcher import PoolWatcher
from stockpush.services.scheduler import RealtimeScheduler
from stockpush.services.function_registry import FunctionRegistry
from stockpush.services.signal_store import SignalStore
from stockpush.services.function_engine import FunctionEngine

logger = logging.getLogger(__name__)


class HermesAPI:
    """F5.1 Hermes Agent 远程控制 API"""

    def __init__(self, config: dict, project_root: Path, f51_root: Path):
        self.config = config
        self.project_root = project_root
        self.f51_root = f51_root
        self._init_services()

    def _init_services(self):
        """Reuse Console's exact service init pattern (see console.py _init_services)."""
        feishu = self.config.get("feishu", {})
        raw_secret = feishu.get("sign_secret", "")
        raw_webhook = feishu.get("webhook", "")
        webhook_url = ""
        if raw_webhook:
            try:
                from stockpush.credential_store import decrypt_value
                webhook_url = decrypt_value(raw_webhook)
            except Exception:
                webhook_url = raw_webhook
        sign_secret = None
        if raw_secret:
            try:
                from stockpush.credential_store import decrypt_value
                sign_secret = decrypt_value(raw_secret)
            except Exception:
                sign_secret = raw_secret
        self.pusher = FeishuPusher(
            webhook_url,
            feishu.get("enabled", False),
            sign_secret,
            feishu.get("sign_enabled", False),
        )

        ds = self.config.get("datasources", {})
        self.fetcher = DataFetcher(ds.get("primary", "xtick"))
        self.calendar = CalendarChecker()
        self.watcher = PoolWatcher()
        from stockpush.pg_connector import PGConnector
        self.db = PGConnector()
        self.registry = FunctionRegistry(self.db)
        self.store = SignalStore(self.db)
        self.engine = FunctionEngine(self.registry, self.store, self.pusher,
                                      lambda: self._get_symbols())

        sc = self.config.get("schedule", {})
        self.scheduler = RealtimeScheduler(
            sc.get("morning_start", "09:25"),
            sc.get("morning_end", "11:35"),
            sc.get("afternoon_start", "13:00:05"),
            sc.get("afternoon_end", "15:05"),
            sc.get("interval_seconds", 65),
        )

        get = "GET"
        post = "POST"
        self.dispatch = {
            (get, "/api/signals/functions"): self.handle_list_functions,
            (get, "/api/signals/today"): self.handle_today_signals,
            (get, "/api/backtest/<func_name>/<symbol>"): self.handle_backtest,
            (post, "/api/admin/function/validate"): self.handle_validate_func,
            (post, "/api/admin/function/register"): self.handle_register_func,
            (post, "/api/admin/function/remove/<name>"): self.handle_remove_func,
            (post, "/api/admin/function/toggle/<name>"): self.handle_toggle_func,
        }

    # ── Validators ──────────────────────────────────────────

    def _validate_symbol(self, symbol: Any) -> str:
        """Validate 6-digit stock code."""
        if not isinstance(symbol, str):
            symbol = str(symbol)
        symbol = symbol.strip()
        if not symbol.isdigit() or len(symbol) != 6:
            raise ValueError(f"股票代码格式错误: '{symbol}'，需要6位数字")
        return symbol

    def _validate_date(self, date_str: Any, default: str = None) -> str:
        """Validate YYYY-MM-DD date format."""
        if not date_str:
            return default or datetime.now().strftime("%Y-%m-%d")
        if isinstance(date_str, (datetime, date)):
            return date_str.strftime("%Y-%m-%d")
        try:
            datetime.strptime(str(date_str).strip(), "%Y-%m-%d")
            return str(date_str).strip()
        except ValueError:
            raise ValueError(f"日期格式错误: '{date_str}'，需要 YYYY-MM-DD")

    def _validate_period(self, period: Any) -> str:
        """Validate kline period."""
        valid = {"1m", "5m", "30m", "1d"}
        p = str(period).strip().lower() if period else "5m"
        if p not in valid:
            raise ValueError(f"周期 '{period}' 无效，可选: {', '.join(sorted(valid))}")
        return p

    def _validate_bool(self, value: Any) -> bool:
        """Lenient bool conversion."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "y", "是", "开", "启用")
        return False

    # ── Helpers ─────────────────────────────────────────────

    def _get_stock_name(self, symbol: str) -> str:
        """Look up stock name from watchlist."""
        pool = {
            s["symbol"]: s.get("name", "")
            for s in self.watcher.load_watchlist()
        }
        return pool.get(symbol, symbol)

    def _get_symbols(self) -> list[str]:
        """Get watchlist symbols for FunctionEngine."""
        return self.watcher.get_symbols()

    @staticmethod
    def _ok(data: Any = None, message: str = "OK") -> dict:
        return {"success": True, "data": data, "message": message}

    @staticmethod
    def _fail(message: str, errors: list = None) -> dict:
        r = {"success": False, "data": None, "message": message}
        if errors:
            r["errors"] = errors
        return r

    def _save_config(self):
        """Persist current config to config.local.yaml (always, never overwrite config.yaml template)"""
        path = self.f51_root / "config.local.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)

    # ── Menu ────────────────────────────────────────────────

    def menu(self) -> dict:
        """Return complete menu tree with natural language keywords."""
        return self._ok({
            "menu": [
                {
                    "section": "监控管理",
                    "items": [
                        {"id": "1.1", "name": "查看状态", "action": "status", "keywords": ["状态", "摘要", "运行情况"]},
                        {"id": "1.2", "name": "启动监控", "action": "start", "keywords": ["启动", "开始监控", "开"]},
                        {"id": "1.3", "name": "停止监控", "action": "stop", "keywords": ["停止", "关闭", "停"]},
                        {"id": "1.4", "name": "数据补全", "action": "fill-today", "keywords": ["补全", "补数据", "补今日"],
                         "args": [{"name": "symbol", "optional": True, "desc": "股票代码"}]},
                        {"id": "1.5", "name": "今日信号", "action": "signals", "keywords": ["信号", "今日信号", "触发"],
                         "args": [{"name": "symbol", "optional": True, "desc": "股票代码"}]},
                    ],
                },
                {
                    "section": "数据查询",
                    "items": [
                        {"id": "2.1", "name": "数据概览", "action": "data-summary", "keywords": ["数据", "下载概览"]},
                        {"id": "2.2", "name": "数据明细", "action": "data-detail", "keywords": ["明细", "K线", "详情"],
                         "args": [{"name": "symbol", "optional": False, "desc": "股票代码"}]},
                        {"id": "2.3", "name": "除权除息", "action": "dividends", "keywords": ["除权", "除息", "分红"]},
                        {"id": "2.4", "name": "历史回填", "action": "fill-history",
                         "keywords": ["回填", "历史", "补历史"],
                         "args": [
                             {"name": "symbol", "optional": True, "desc": "股票代码（留空=全部自选）"},
                             {"name": "period", "optional": True, "desc": "周期"},
                             {"name": "start", "optional": True, "desc": "开始日期 YYYY-MM-DD"},
                             {"name": "end", "optional": True, "desc": "结束日期 YYYY-MM-DD"},
                         ]},
                    ],
                },
                {
                    "section": "自选股管理",
                    "items": [
                        {"id": "6.1", "name": "添加自选", "action": "pool-add", "keywords": ["加自选", "添加", "加入"],
                         "args": [{"name": "symbol", "optional": False, "desc": "股票代码"}]},
                        {"id": "6.2", "name": "删除自选", "action": "pool-remove", "keywords": ["删自选", "删除", "移除"],
                         "args": [{"name": "symbol", "optional": False, "desc": "股票代码"}]},
                        {"id": "6.3", "name": "自选列表", "action": "pool-list", "keywords": ["自选股", "持仓", "列表"]},
                    ],
                },
                {
                    "section": "配置 & 工具",
                    "items": [
                        {"id": "3.1", "name": "查看配置", "action": "config-show", "keywords": ["配置", "设置", "查看配置"]},
                        {"id": "5.1", "name": "测试飞书", "action": "feishu-test", "keywords": ["测试", "飞书测试"]},
                    ],
                },
            ]
        })

    # ── Status ──────────────────────────────────────────────

    def status(self) -> dict:
        """Return full status report."""
        if _has_systemctl():
            r = subprocess.run(["systemctl", "is-active", "f51-start.service"],
                               capture_output=True, text=True)
            running = r.stdout.strip() == "active"
        else:
            running = False
        nxt = None
        symbols = self.watcher.get_symbols()
        signals_today = self._get_today_signals(symbols)

        return self._ok({
            "running": running,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "schedule": {
                "morning": f"{self.scheduler.morning_start}-{self.scheduler.morning_end}",
                "afternoon": f"{self.scheduler.afternoon_start}-{self.scheduler.afternoon_end}",
                "interval_seconds": self.scheduler.interval_seconds,
                "next_run": nxt.strftime("%Y-%m-%d %H:%M:%S") if nxt else None,
            },
            "feishu": {
                "enabled": self.pusher.enabled,
                "sign_enabled": self.pusher.sign_enabled,
                "webhook_configured": bool(self.pusher.webhook_url),
            },
            "datasource": {
                "primary": self.fetcher.primary,
            },
            "watchlist": {
                "count": len(symbols),
                "symbols": symbols[:20],
            },
            "signal": {
                "loaded": True,
                "function_count": len(self.registry.get_all()),
                "enabled_count": len(self.registry.get_enabled()),
            },
            "today_signals": {
                "count": len(signals_today),
                "latest": signals_today[:5],
            },
        })

    def _get_today_signals(self, symbols: list = None) -> list:
        """Get today's signals from store."""
        rows = self.store.get_today()
        result = []
        for r in rows:
            symbol = r.get("symbol", "")
            result.append({
                "symbol": symbol,
                "name": self._get_stock_name(symbol),
                "signal": r.get("direction", ""),
                "time": str(r.get("signal_time", "")),
                "type": r.get("direction", ""),
            })
        return sorted(result, key=lambda x: x.get("time", ""), reverse=True)
    # ── Monitor Control ─────────────────────────────────────

    def start_monitor(self) -> dict:
        """Start monitor via systemctl (or direct on Termux)."""
        if not _has_systemctl():
            return self._fail("systemctl 不可用，请使用 deploy/termux/stockpush-daemon.sh start 启动")
        r = subprocess.run(["systemctl", "is-active", "f51-start.service"],
                           capture_output=True, text=True)
        if r.stdout.strip() == "active":
            return self._fail("监控已在运行中")

        now = datetime.now()
        nine_thirty = now.replace(hour=9, minute=30, second=0, microsecond=0)
        fill_results = []
        if now > nine_thirty:
            symbols = self.watcher.get_symbols()
            for symbol in symbols:
                for period in ["1m", "5m", "30m", "1d"]:
                    try:
                        complete = self.fetcher.check_today_data_complete(symbol, period)
                    except Exception:
                        complete = False
                    if not complete:
                        try:
                            ok, saved, src = self.fetcher.fetch_and_save(symbol, period)
                            fill_results.append({
                                "symbol": symbol, "period": period,
                                "result": f"{saved}条 ({src})" if ok else "补全失败",
                            })
                        except Exception as e:
                            fill_results.append({
                                "symbol": symbol, "period": period,
                                "result": f"出错: {e}",
                            })


        sc = self.config.get("schedule", {})
        return self._ok({
            "status": "已启动",
            "schedule": {
                "morning": f"{sc.get('morning_start', '09:25')}-{sc.get('morning_end', '11:35')}",
                "afternoon": f"{sc.get('afternoon_start', '13:00:05')}-{sc.get('afternoon_end', '15:05')}",
                "interval": f"{sc.get('interval_seconds', 65)}s",
            },
            "data_fill": fill_results if fill_results else None,
        }, "监控已启动")

    def stop_monitor(self) -> dict:
        """Stop monitor via systemctl (or direct on Termux)."""
        if not _has_systemctl():
            return self._fail("systemctl 不可用，请使用 deploy/termux/stockpush-daemon.sh stop 停止")
        r = subprocess.run(["systemctl", "is-active", "f51-start.service"],
                           capture_output=True, text=True)
        if r.stdout.strip() != "active":
            return self._fail("监控未运行")
        subprocess.run(["systemctl", "stop", "f51-start.service"])
        return self._ok({"status": "已停止"}, "监控已停止")

    def _job_func(self):
        """Job function for scheduler — fetch data and log to temp table."""
        try:
            symbols = self.watcher.get_symbols()
            if not symbols:
                return
            now_dt = datetime.now()
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

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

            db = None
            for symbol in symbols:
                for period in ["1m", "5m", "30m", "1d"]:
                    try:
                        df = self.fetcher.fetch_kline(symbol, period)
                        df_log = _filter_bar(df, period, now_dt)
                        if df is None or df.empty:
                            continue
                        records = self.fetcher._normalize_data(df, symbol)
                        if records:
                            self.fetcher.save_to_db(records, period)
                        # 记录下载日志到临时表（只记当前时刻对应的那根bar）
                        try:
                            if db is None:
                                from stockpush.pg_connector import PGConnector
                                db = PGConnector()
                            from stockpush.services.download_logger import log_downloads
                            log_downloads(db, now_str, symbol, period, df_log)
                        except Exception:
                            pass
                    except Exception:
                        continue
            if db:
                db.close()
        except Exception:
            pass

    def fill_today(self, symbol: str = None, period: str = None) -> dict:
        """Fill today's data for given symbol(s) and period(s)."""
        try:
            sym = self._validate_symbol(symbol) if symbol else None
            per = self._validate_period(period) if period else None
        except ValueError as e:
            return self._fail(str(e))

        symbols = [sym] if sym else self.watcher.get_symbols()
        periods = [per] if per else ["1m", "5m", "30m", "1d"]

        results = []
        for s in symbols:
            for p in periods:
                try:
                    ok, saved, src = self.fetcher.fetch_and_save(s, p)
                    results.append({
                        "symbol": s, "period": p,
                        "success": ok, "saved": saved, "source": src,
                    })
                except Exception as e:
                    results.append({
                        "symbol": s, "period": p,
                        "success": False, "error": str(e),
                    })
        signal_results = self._run_signals_for_symbols(symbols)
        return self._ok({
            "results": results,
            "signals": signal_results,
        }, f"数据补全完成，共 {len(results)} 项，信号 {sum(s['signals'] for s in signal_results)} 个")

    def _run_signals_for_symbols(self, symbols: list) -> list:
        """Run all enabled signal functions for given symbols with today's range."""
        from datetime import date
        today = date.today().isoformat()
        functions = self.registry.get_enabled()
        results = []
        for func_info in functions:
            for symbol in symbols:
                try:
                    r = self.registry.execute(
                        func_info.name, symbol, func_info.period,
                        today, today, func_info.param_set_id,
                    )
                    sigs = r.get("signals", [])
                    self.store.write_signals(func_info.id, symbol, sigs)
                    results.append({
                        "symbol": symbol, "function": func_info.display_name,
                        "signals": len(sigs),
                    })
                except Exception as e:
                    results.append({
                        "symbol": symbol, "function": func_info.display_name,
                        "signals": 0, "error": str(e),
                    })
        return results

    def fill_history(self, symbol: str = None, period: str = None,
                     start: str = None, end: str = None) -> dict:
        """Backfill historical kline data for given symbol(s) and period(s).

        Unlike fill_today (today only), this fetches the full date range.
        """
        try:
            sym = self._validate_symbol(symbol) if symbol else None
            per = self._validate_period(period) if period else None
            start_dt = self._validate_date(start) if start else None
            end_dt = self._validate_date(end) if end else None
        except ValueError as err:
            return self._fail(str(err))

        symbols = [sym] if sym else self.watcher.get_symbols()
        periods = [per] if per else ["1m", "5m", "30m", "1d"]

        results = []
        for s_code in symbols:
            for p in periods:
                try:
                    ok, saved, src = self.fetcher.fetch_and_save_history(
                        s_code, p, start=start_dt, end=end_dt
                    )
                    results.append({
                        "symbol": s_code, "period": p,
                        "success": ok, "saved": saved, "source": src,
                    })
                except Exception as exc:
                    results.append({
                        "symbol": s_code, "period": p,
                        "success": False, "error": str(exc),
                    })
        return self._ok({"results": results}, f"历史数据回填完成，共 {len(results)} 项")

    def today_signals(self, symbol: str = None) -> dict:
        """Return today's signals from store."""
        try:
            sym = self._validate_symbol(symbol) if symbol else None
        except ValueError as e:
            return self._fail(str(e))

        signals = self.store.get_today()
        if sym:
            signals = [s for s in signals if s.get("symbol") == sym]

        result = []
        for s in signals:
            result.append({
                "symbol": s.get("symbol"),
                "name": self._get_stock_name(s.get("symbol", "")),
                "signal": s.get("direction", ""),
                "time": str(s.get("signal_time", "")),
                "type": s.get("direction", ""),
            })

        return self._ok({
            "count": len(result),
            "signals": result,
        })

    # ── Pool (Watchlist) Operations ─────────────────────────

    def pool_list(self) -> dict:
        """Return all watchlist stocks."""
        wl = self.watcher.load_watchlist()
        seen = set()
        unique = []
        for item in wl:
            s = item["symbol"]
            if s not in seen:
                seen.add(s)
                unique.append({
                    "symbol": item["symbol"],
                    "name": item.get("name", ""),
                    "type": item.get("type", ""),
                    "group_name": item.get("group_name", ""),
                })
        return self._ok({
            "count": len(unique),
            "stocks": unique,
        })

    def pool_add(self, symbol: str) -> dict:
        """Add stock to watchlist."""
        try:
            sym = self._validate_symbol(symbol)
        except ValueError as e:
            return self._fail(str(e))

        try:
            from stockpush.pool_mgr.pool_mgr import PoolMgrService
            svc = PoolMgrService()
            exists, sym_type = svc._check_symbol_exists(sym)
            if not exists:
                return self._fail(f"代码 {sym} 不在代码库中")
            info = svc._get_symbol_info_from_codes(sym)
            name = info.get("name", "未知")
            svc.add_symbol(sym)
            return self._ok({"symbol": sym, "name": name, "type": sym_type},
                            f"已添加: {sym} {name} ({sym_type})")
        except Exception as e:
            return self._fail(f"添加失败: {e}")

    def pool_remove(self, symbol: str) -> dict:
        """Remove stock from watchlist."""
        try:
            sym = self._validate_symbol(symbol)
        except ValueError as e:
            return self._fail(str(e))

        try:
            from stockpush.pool_mgr.pool_mgr import PoolMgrService
            svc = PoolMgrService()
            ok = svc.remove_symbol(sym)
            if ok:
                return self._ok({"symbol": sym}, f"已删除: {sym}")
            return self._fail(f"未找到: {sym}")
        except Exception as e:
            return self._fail(f"删除失败: {e}")

    def pool_import_codes(self) -> dict:
        """从 XTick 拉取股票+基金/ETF代码列表并导入代码库"""
        try:
            from stockpush.src_mgr.xtick_provider import XTickProvider
            from stockpush.pool_mgr.pool_mgr import PoolMgrService

            xtick = XTickProvider()
            svc = PoolMgrService(db_connector=self.db)

            # 一次调用获取所有代码（type-code 格式）
            # type 1=股票, 30=ETF, 20=LOF, 10=指数, 3=其他
            raw = xtick._request('/doc/codes', params={})
            df = xtick._to_df(raw)

            if df is None or df.empty:
                return self._fail("XTick 返回空数据")

            # _to_df 解析后含 type/code 列（无 name）
            if 'code' not in df.columns or 'type' not in df.columns:
                return self._fail("XTick 返回格式异常")

            stock_df = df[df['type'] == 1][['code', 'type']].copy()
            fund_df = df[df['type'] != 1][['code', 'type']].copy()

            stock_count = svc.import_stock_codes(stock_df)
            fund_count = svc.import_fund_codes(fund_df)

            total = stock_count + fund_count
            return self._ok(
                {"stock": stock_count, "fund": fund_count, "total": total, "provider": "xtick"},
                f"XTick 导入完成: 股票 {stock_count}, 基金/ETF {fund_count}, 合计 {total}")
        except Exception as e:
            return self._fail(f"导入代码失败: {e}")


    # ── Data Query ──────────────────────────────────────────

    def _get_db(self):
        from stockpush.pg_connector import PGConnector
        return PGConnector()

    PERIOD_TABLE_MAP = {
        "1m": "tb_raw_1m", "5m": "tb_raw_5m",
        "30m": "tb_raw_30m", "1d": "tb_raw_1d",
    }

    def data_summary(self, symbol: str = None, start: str = None,
                     end: str = None, period: str = None) -> dict:
        """Return data download summary."""
        try:
            sym = self._validate_symbol(symbol) if symbol else None
            start_dt = self._validate_date(start)
            end_dt = self._validate_date(end, start_dt)
            per = self._validate_period(period) if period else None
        except ValueError as err:
            return self._fail(str(err))

        symbols = [sym] if sym else self.watcher.get_symbols()
        periods = [per] if per else ["1m", "5m", "30m", "1d"]
        db = self._get_db()
        results = []

        for p in periods:
            table = self.PERIOD_TABLE_MAP.get(p)
            if not table:
                continue
            for sym in symbols:
                try:
                    sql = (
                        f"SELECT ts FROM {table} WHERE symbol = ? "
                        f"AND ts >= ? AND ts <= ? ORDER BY ts"
                    )
                    rows = db.execute_query(sql, (sym, start_dt + " 00:00:00", end_dt + " 23:59:59"))
                    results.append({
                        "symbol": sym, "period": p,
                        "timestamps": [str(r["ts"])[:19] for r in rows] if rows else [],
                        "count": len(rows) if rows else 0,
                    })
                except Exception as exc:
                    results.append({"symbol": sym, "period": p, "error": str(exc)})
        db.close()
        return self._ok({"results": results})

    def data_detail(self, symbol: str, period: str = "5m",
                    start: str = None, end: str = None, limit: int = 20) -> dict:
        """Return detailed kline data."""
        try:
            sym = self._validate_symbol(symbol)
            per = self._validate_period(period)
            s = self._validate_date(start)
            e = self._validate_date(end, s)
        except ValueError as err:
            return self._fail(str(err))

        table = self.PERIOD_TABLE_MAP.get(per)
        if not table:
            return self._fail(f"未知周期: {period}")

        db = self._get_db()
        try:
            sql = (
                f"SELECT ts, open, high, low, close, vol "
                f"FROM {table} WHERE symbol = ? AND ts >= ? AND ts <= ? "
                f"ORDER BY ts DESC LIMIT ?"
            )
            rows = db.execute_query(sql, (sym, s + " 00:00:00", e + " 23:59:59", limit))
            candles = [
                {"time": str(r.get("ts", "")),
                 "open": float(r.get("open", 0)),
                 "high": float(r.get("high", 0)),
                 "low": float(r.get("low", 0)),
                 "close": float(r.get("close", 0)),
                 "vol": float(r.get("vol", 0))}
                for r in rows
            ]
            name = self._get_stock_name(sym)
            return self._ok({
                "symbol": sym, "name": name, "period": per,
                "start": s, "end": e, "count": len(candles),
                "candles": candles,
            })
        except Exception as e:
            return self._fail(f"查询失败: {e}")
        finally:
            db.close()

    def dividend_view(self) -> dict:
        """Return dividend/ex-right date for each watchlist stock.

        Uses tb_calendar / tb_signal_log data instead.
        """
        symbols = self.watcher.get_symbols()
        if not symbols:
            return self._fail("自选股池为空")

        results = []
        for symbol in symbols:
            try:
                from stockpush.pg_connector import PGConnector
                db = PGConnector()
                rows = db.execute_query(
                    "SELECT ex_date FROM tb_calendar WHERE symbol = %s "
                    "AND ex_date IS NOT NULL ORDER BY ex_date DESC LIMIT 1",
                    (symbol,)
                )
                db.close()
                date_val = str(rows[0]['ex_date']) if rows else None
            except Exception:
                date_val = None
            name = self._get_stock_name(symbol)
            results.append({"symbol": symbol, "name": name, "dividend_date": date_val})
        return self._ok({"results": results})

    # ── Temp Download Log ──────────────────────────────────

    def data_download_log(self, symbol: str = None,
                          start: str = None, end: str = None,
                          period: str = None, limit: int = 50,
                          desc: bool = False) -> dict:
        """查询临时下载日志表 tb_download_request_log。"""
        try:
            sym = self._validate_symbol(symbol) if symbol else None
            s = self._validate_date(start) if start else None
            e = self._validate_date(end) if end else None
        except ValueError as err:
            return self._fail(str(err))

        db = self._get_db()
        try:
            conditions = []
            params = []
            if sym:
                conditions.append("symbol = %s")
                params.append(sym)
            if s:
                conditions.append("request_time >= %s")
                params.append(s + " 00:00:00")
            if e:
                conditions.append("request_time <= %s")
                params.append(e + " 23:59:59")
            if period:
                conditions.append("period = %s")
                params.append(period)

            where = " AND ".join(conditions) if conditions else "TRUE"

            order_dir = "DESC" if desc else "ASC"
            sql = f"""SELECT request_time, symbol, period, api_bar_time,
                             open, high, low, close, volume, amount, preclose
                      FROM tb_download_request_log
                      WHERE {where}
                      ORDER BY request_time {order_dir},
                        CASE period WHEN '1m' THEN 1 WHEN '5m' THEN 2
                                    WHEN '30m' THEN 3 WHEN '1d' THEN 4 END
                      LIMIT %s"""
            params.append(limit)

            rows = db.execute_query(sql, tuple(params))
            records = [
                {
                    "time": str(r.get("request_time", "")),
                    "api_bar_time": str(r.get("api_bar_time", "")) if r.get("api_bar_time") else "",
                    "symbol": r.get("symbol", ""),
                    "period": r.get("period", ""),
                    "open": float(r["open"]) if r.get("open") is not None else None,
                    "high": float(r["high"]) if r.get("high") is not None else None,
                    "low": float(r["low"]) if r.get("low") is not None else None,
                    "close": float(r["close"]) if r.get("close") is not None else None,
                    "volume": float(r["volume"]) if r.get("volume") is not None else None,
                    "amount": float(r["amount"]) if r.get("amount") is not None else None,
                    "preclose": float(r["preclose"]) if r.get("preclose") is not None else None,
                }
                for r in rows
            ]
            return self._ok({
                "symbol": sym or "全部",
                "start": s or "不限",
                "end": e or "不限",
                "period": period or "全部",
                "count": len(records),
                "records": records,
            })
        except Exception as e:
            return self._fail(f"查询失败: {e}")
        finally:
            db.close()

    # ── Datasource Config ─────────────────────────────────

    def datasource_set(self, primary: str = None) -> dict:
        """Set primary datasource and persist to config."""
        if primary:
            self.fetcher.primary = primary

        ds = self.config.setdefault("datasources", {})
        if primary:
            ds["primary"] = primary

        self._save_config()
        return self._ok({
            "primary": self.fetcher.primary,
        }, f"数据源已更新: primary={self.fetcher.primary}")

    # ── Schedule Config ─────────────────────────────────

    def schedule_set(self,
                     morning_start: str = None, morning_end: str = None,
                     afternoon_start: str = None, afternoon_end: str = None,
                     interval_seconds: int = None) -> dict:
        """Update schedule parameters and persist to config."""
        ms = morning_start or self.scheduler.morning_start
        me = morning_end   or self.scheduler.morning_end
        aas = afternoon_start or self.scheduler.afternoon_start
        aae = afternoon_end   or self.scheduler.afternoon_end
        secs = interval_seconds if interval_seconds is not None else self.scheduler.interval_seconds

        self.scheduler = RealtimeScheduler(ms, me, aas, aae, secs)

        sc = self.config.setdefault("schedule", {})
        sc["morning_start"]    = ms
        sc["morning_end"]       = me
        sc["afternoon_start"]  = aas
        sc["afternoon_end"]    = aae
        sc["interval_seconds"] = secs

        self._save_config()
        return self._ok({
            "morning_start": ms, "morning_end": me,
            "afternoon_start": aas, "afternoon_end": aae,
            "interval_seconds": secs,
        }, "调度配置已更新")

    # ── Config ──────────────────────────────────────────────

    def config_show(self) -> dict:
        """Return current full configuration."""
        return self._ok({
            "datasource": {
                "primary": self.fetcher.primary,
            },
            "schedule": {
                "morning_start": self.scheduler.morning_start,
                "morning_end": self.scheduler.morning_end,
                "afternoon_start": self.scheduler.afternoon_start,
                "afternoon_end": self.scheduler.afternoon_end,
                "interval_seconds": self.scheduler.interval_seconds,
            },
            "feishu": {
                "enabled": self.pusher.enabled,
                "sign_enabled": self.pusher.sign_enabled,
                "webhook_configured": bool(self.pusher.webhook_url),
            },
            "signal": {
                "function_count": len(self.registry.get_all()),
                "enabled_count": len(self.registry.get_enabled()),
            },
        })

    def feishu_test(self) -> dict:
        """Send a test message to Feishu."""
        if not self.pusher.webhook_url:
            return self._fail("飞书 Webhook 未配置")
        result = self.pusher.test()
        return (
            self._ok({"push_result": result}, "测试推送成功")
            if result.get("success")
            else self._fail(f"测试推送失败: {result.get('message', '')}")
        )

    # ── Feishu Push ─────────────────────────────────────────

    def push_status(self) -> dict:
        """Push formatted status report to Feishu."""
        status_data = self.status()
        if not status_data["success"]:
            return status_data
        d = status_data["data"]
        running_icon = "✅" if d["running"] else "⏹"
        feishu_icon = "✅" if d["feishu"]["enabled"] else "❌"
        signals = d["today_signals"]
        signals_detail = ""
        for s in signals["latest"]:
            signals_detail += f"\n  {s['symbol']} {s.get('name','')} {'买入' if s['signal']=='buy' else '卖出'} {s['time']}"

        msg = (
            f"[F5.1 远程控制] 状态报告  {d['timestamp'][11:16]}\n"
            f"─────────────────\n"
            f"监控: {running_icon} {'运行中' if d['running'] else '已停止'}\n"
            f"自选股: {d['watchlist']['count']} 只\n"
            f"数据源: {d['datasource']['primary']}\n"
            f"信号函数: {d['signal']['enabled_count']}个启用, {d['signal']['function_count']}个共计\n"
            f"今日信号: {signals['count']} 个{signals_detail}\n"
            f"调度: {d['schedule']['morning']} / {d['schedule']['afternoon']}  每{d['schedule']['interval_seconds']}s\n"
            f"下次运行: {d['schedule']['next_run'] or 'N/A'}\n"
            f"─────────────────\n"
            f"飞书推送: {feishu_icon} {'已启用' if d['feishu']['enabled'] else '未启用'}"
        )
        result = self.pusher.push(msg)
        return (
            self._ok({"push_result": result}, "状态已推送")
            if result.get("success")
            else self._fail(f"推送失败: {result.get('message', '')}")
        )

    def push_pool(self) -> dict:
        """Push watchlist to Feishu."""
        pool_data = self.pool_list()
        if not pool_data["success"]:
            return pool_data
        stocks = pool_data["data"]["stocks"]
        lines = ["[F5.1 远程控制] 自选股列表"]
        lines.append(f"共 {len(stocks)} 只\n")
        for s in stocks:
            lines.append(f"{s['symbol']} {s['name']} ({s['type']})")
        msg = "\n".join(lines)
        result = self.pusher.push(msg)
        return (
            self._ok({"push_result": result}, "自选股列表已推送")
            if result.get("success")
            else self._fail(f"推送失败: {result.get('message', '')}")
        )

    def push_menu(self) -> dict:
        """Push full menu card to Feishu."""
        msg = (
            "[F5.1 远程控制] 操作菜单\n"
            "─────────────────\n"
            "📊 监控管理\n"
            "  1.1 查看状态    1.2 启动\n"
            "  1.3 停止        1.4 数据补全\n"
            "  1.5 今日信号\n\n"
            "📈 数据查询\n"
            "  2.1 数据概览    2.2 数据明细\n"
            "  2.3 除权除息    2.4 历史回填\n\n"
            "📋 自选股\n"
            "  6.1 添加        6.2 删除\n"
            "  6.3 查看列表\n\n"
            "⚙ 配置 & 工具\n"
            "  3.1 查看配置    5.1 测试飞书\n"
            "─────────────────\n"
            "💡 直接说:\n"
            '  "查看状态" / "启动监控"\n'
            '  "加自选 000001"\n'
            '  "今日信号"'
        )
        result = self.pusher.push(msg)
        return (
            self._ok({"push_result": result}, "菜单已推送")
            if result.get("success")
            else self._fail(f"推送失败: {result.get('message', '')}")
        )

    # ── Signal Management (new API endpoints) ─────────────

    def handle_list_functions(self) -> dict:
        """List all registered functions."""
        funcs = self.registry.get_all()
        return self._ok({
            "count": len(funcs),
            "functions": [
                {
                    "id": f.id,
                    "name": f.name,
                    "display_name": f.display_name,
                    "period": f.period,
                    "enabled": f.enabled,
                }
                for f in funcs
            ],
        })

    def handle_today_signals(self) -> dict:
        """Get today's signals from store."""
        rows = self.store.get_today()
        result = []
        for r in rows:
            result.append({
                "id": r.get("id"),
                "symbol": r.get("symbol"),
                "func_name": r.get("func_name"),
                "display_name": r.get("display_name"),
                "signal": r.get("direction", ""),
                "signal_time": str(r.get("signal_time", "")),
                "signal_type": r.get("direction", ""),
            })
        return self._ok({
            "count": len(result),
            "signals": result,
        })

    def handle_backtest(self, func_name: str, symbol: str) -> dict:
        """Backtest a function for a symbol (no archive/push)."""
        try:
            sym = self._validate_symbol(symbol)
        except ValueError as e:
            return self._fail(str(e))

        func_info = self.registry.get_by_name(func_name)
        if not func_info:
            return self._fail(f"函数 '{func_name}' 未注册")

        try:
            signals = self.engine.backtest(func_name, sym)
            return self._ok({
                "func_name": func_name,
                "symbol": sym,
                "count": len(signals),
                "signals": signals,
            })
        except Exception as e:
            return self._fail(f"回测失败: {e}")

    def handle_validate_func(self, **kwargs) -> dict:
        """Validate a function module/name pair."""
        module_path = kwargs.get("module_path")
        func_name = kwargs.get("func_name")

        if not module_path or not func_name:
            return self._fail("参数缺失: module_path, func_name")

        result = self.registry.validate(module_path, func_name)
        if result.get("valid"):
            return self._ok(result, "验证通过")
        return self._fail(result.get("error", "验证失败"))

    def handle_register_func(self, **kwargs) -> dict:
        """Register a new function in the registry."""
        name = kwargs.get("name")
        display_name = kwargs.get("display_name")
        module_path = kwargs.get("module_path")
        func_name = kwargs.get("func_name")
        period = kwargs.get("period", "1d")
        param_set_id = int(kwargs.get("param_set_id", 0))
        enabled = kwargs.get("enabled", True)

        if not all([name, module_path, func_name]):
            return self._fail("参数缺失: name, module_path, func_name")

        try:
            new_id = self.registry.register(
                name, display_name or name, module_path, func_name,
                period, param_set_id, enabled,
            )
            return self._ok({"id": new_id}, f"函数 '{name}' 注册成功")
        except Exception as e:
            return self._fail(f"注册失败: {e}")

    def handle_remove_func(self, name: str) -> dict:
        """Remove a function from the registry."""
        func_info = self.registry.get_by_name(name)
        if not func_info:
            return self._fail(f"函数 '{name}' 未注册")
        try:
            self.registry.remove(name)
            return self._ok({"name": name}, f"函数 '{name}' 已删除")
        except Exception as e:
            return self._fail(f"删除失败: {e}")

    def handle_toggle_func(self, name: str) -> dict:
        """Toggle function enabled/disabled state."""
        func_info = self.registry.get_by_name(name)
        if not func_info:
            return self._fail(f"函数 '{name}' 未注册")
        try:
            new_state = not func_info.enabled
            self.registry.set_enabled(name, new_state)
            return self._ok(
                {"name": name, "enabled": new_state},
                f"函数 '{name}' 已{'启用' if new_state else '禁用'}",
            )
        except Exception as e:
            return self._fail(f"切换失败: {e}")
