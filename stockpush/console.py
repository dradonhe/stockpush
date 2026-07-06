"""
F5.1 控制台管理面板
终端交互式菜单，类似 3X-ui 风格
"""
import os
import sys
import json
import logging
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from stockpush.services.hermes_api import HermesAPI


class Console:
    def __init__(self, config: dict, project_root: Path, f51_root: Path):
        self.config = config
        self.project_root = project_root
        self.f51_root = f51_root
        self._log_messages = []
        self._log_lock = threading.Lock()
        self._log_silent = False  # suppress print during interactive input
        self.api = HermesAPI(config, project_root, f51_root)

    # ── service running check (systemd managed) ──
    @staticmethod
    def _is_running() -> bool:
        """Check if F5.1 monitor service is active via systemctl."""
        r = subprocess.run(
            ["systemctl", "is-active", "f51-start.service"],
            capture_output=True, text=True
        )
        return r.stdout.strip() == "active"

    @property
    def pusher(self): return self.api.pusher
    @property
    def fetcher(self): return self.api.fetcher
    @property
    def calendar(self): return self.api.calendar
    @property
    def watcher(self): return self.api.watcher
    @property
    def scheduler(self): return self.api.scheduler


    @contextmanager
    def _silent(self):
        """Suppress _log print output during interactive input."""
        prev = self._log_silent
        self._log_silent = True
        try:
            yield
        finally:
            self._log_silent = prev

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        with self._log_lock:
            self._log_messages.append(entry)
            if len(self._log_messages) > 200:
                self._log_messages = self._log_messages[-200:]
        if not self._log_silent:
            print(entry)

    def _save_config(self):
        raw_secret = self.api.pusher.sign_secret if self.api.pusher else ""
        enc_secret = ""
        if raw_secret:
            try:
                from stockpush.credential_store import encrypt_value
                enc_secret = encrypt_value(raw_secret)
            except Exception:
                enc_secret = raw_secret
        raw_webhook = self.api.pusher.webhook_url if self.api.pusher else ""
        enc_webhook = ""
        if raw_webhook:
            try:
                from stockpush.credential_store import encrypt_value
                enc_webhook = encrypt_value(raw_webhook)
            except Exception:
                enc_webhook = raw_webhook
        cfg = dict(self.config)  # preserve all existing keys
        cfg.update({
            "feishu": {"webhook": enc_webhook, "enabled": self.api.pusher.enabled,
                        "sign_secret": enc_secret, "sign_enabled": self.api.pusher.sign_enabled} if self.api.pusher else {},
            "datasources": {"primary": self.api.fetcher.primary} if self.api.fetcher else {},
            "schedule": {
                "morning_start": self.api.scheduler.morning_start,
                "morning_end": self.api.scheduler.morning_end,
                "afternoon_start": self.api.scheduler.afternoon_start,
                "afternoon_end": self.api.scheduler.afternoon_end,
                "interval_seconds": self.api.scheduler.interval_seconds,
            } if self.api.scheduler else {},
        })
        path = self.f51_root / "config.local.yaml"
        if not path.exists():
            path = self.f51_root / "config.yaml"
        import yaml
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

    def _cls(self):
        os.system("cls" if sys.platform == "win32" else "clear")

    def _press_enter(self):
        input("\n按回车返回...")

    def _print_header(self, title: str):
        self._cls()
        print("=" * 50)
        print(f"  F5.1 实时监控控制台 - {title}")
        print("=" * 50)
        print()

    def _input(self, prompt: str, default: str = "") -> str:
        val = input(prompt).strip()
        return val if val else default

    def _input_int(self, prompt: str, default: int = 0) -> int:
        try:
            return int(self._input(prompt, str(default)))
        except ValueError:
            return default

    def _input_date(self, prompt_label: str, default: str = "",
                      allow_empty: bool = False) -> str:
        """Validate YYYY-MM-DD date input, loop until valid."""
        import re
        pat = r"^\d{4}-\d{2}-\d{2}$"
        while True:
            val = self._input(f"{prompt_label} (YYYY-MM-DD) [{default}]: ", default)
            cleaned = "".join(c for c in val if c.isprintable() or c == "-")
            if allow_empty and not cleaned:
                return ""
            if re.match(pat, cleaned):
                return cleaned
            print(f"  ! 日期格式错误，需要 YYYY-MM-DD (如 {default})")

    def _input_time(self, prompt_label: str, default: str = "", fmt: str = "HH:MM") -> str:
        """Validate time format input, loop until valid.
        Accepts HH:MM, HH:MM:SS, HHMM, or HHMMSS; normalizes to fmt.
        Shows the normalized default in the prompt.
        """
        import re
        has_sec = fmt == "HH:MM:SS"

        def _normalize(raw: str) -> str:
            s = "".join(c for c in raw if c.isprintable() or c in ":")
            s = s.replace(".", ":").replace("。", ":")
            if re.match(r"^\d{4}$", s):
                s = s[:2] + ":" + s[2:]
            elif re.match(r"^\d{6}$", s):
                s = s[:2] + ":" + s[2:4] + ":" + s[4:]
            return s

        norm_default = _normalize(default)
        while True:
            prompt = f"{prompt_label} [{norm_default}]: "
            val = input(prompt).strip()
            if not val:
                return norm_default
            cleaned = _normalize(val)
            pat = r"^\d{2}:\d{2}$" if not has_sec else r"^\d{2}:\d{2}:\d{2}$"
            if re.match(pat, cleaned):
                return cleaned
            print(f"  ! 格式错误，请输入 {fmt} 或 {'HHMM' if not has_sec else 'HHMMSS'} (如 {norm_default})")

    # ===== menus =====

    def run(self):
        while True:
            self._print_header("主菜单")
            print("  1. 监控管理")
            print("  2. 数据查询")
            print("  3. 信号监控管理")
            print("  4. 自定义函数")
            print("  5. 工具")
            print("  6. 自选股管理")
            if self._is_running():
                print()
                print("  \033[32m● 监控正在后台运行中\033[0m")
            print("  0. 退出")
            print()
            with self._silent():
                c = self._input("请输入选项: ")
            if c == "0":
                if self._is_running():
                    print("\n控制台已退出，监控仍在后台运行。")
                break
            {"1": self._menu_monitor, "2": self._menu_data, "3": self._signal_mgr_menu,
             "4": self._menu_functions, "5": self._menu_tools, "6": self._menu_pool}.get(c, lambda: None)()
        print("\n再见!")

    def _menu_monitor(self):
        while True:
            self._print_header("监控管理")
            print("  1.1 查看状态")
            print("  1.2 启动监控")
            print("  1.3 停止监控")
            print("  1.4 当日数据补全")
            print("  1.5 查看当天信号触发")
            print("  0. 返回上级")
            with self._silent():
                c = self._input("\n请输入选项: ")
            if c == "0": break
            {"1.1": self._status, "1.2": self._start, "1.3": self._stop,
             "1.4": self._fill_today, "1.5": self._today_signals}.get(c, lambda: None)()

    def _menu_data(self):
        while True:
            self._print_header("数据查询")
            print("  2.1 查看数据下载")
            print("  2.2 查看详细数据")
            print("  2.3 查看自选股除权除息")
            print("  2.4 历史数据回填")
            print("  2.5 查看临时下载数据")
            print("  0. 返回上级")
            with self._silent():
                c = self._input("\n请输入选项: ")
            if c == "0": break
            {"2.1": self._data_summary, "2.2": self._data_detail,
             "2.3": self._dividend_view, "2.4": self._fill_history,
             "2.5": self._view_download_log}.get(c, lambda: None)()

    def _signal_mgr_menu(self):
        while True:
            self._print_header("信号监控管理")
            print("  3.1 实时信号展示")
            print("  3.2 函数注册管理")
            print("  3.3 参数管理")
            print("  3.4 验证函数")
            print("  3.5 回调查询")
            print("  3.6 推送管理")
            print("  0. 返回上级")
            with self._silent():
                c = self._input("\n请输入选项: ")
            if c == "0": break
            {"3.1": self._today_signals, "3.2": self._func_list_mgr,
             "3.3": self._func_params_mgr, "3.4": self._func_validate,
             "3.5": self._backtest_query, "3.6": self._push_mgr}.get(c, lambda: None)()

    def _menu_functions(self):
        while True:
            self._print_header("自定义函数")
            func_dir = self.config.get("custom_functions", {}).get("dir", str(self.project_root / "userfunc"))
            print(f"  函数目录: {func_dir}")
            print("  4.1 设置函数目录")
            print("  4.2 注册自定义函数")
            print("  4.3 查看已注册函数")
            print("  4.4 测试函数")
            print("  4.5 函数要求说明")
            print("  0. 返回上级")
            with self._silent():
                c = self._input("\n请输入选项: ")
            if c == "0": break
            {"4.1": self._func_set_dir, "4.2": self._func_register,
             "4.3": self._func_list, "4.4": self._func_test,
             "4.5": self._func_requirements}.get(c, lambda: None)()

    def _menu_tools(self):
        while True:
            self._print_header("工具")
            print("  5.1 测试飞书推送")
            print("  5.2 实时日志")
            print("  0. 返回上级")
            with self._silent():
                c = self._input("\n请输入选项: ")
            if c == "0": break
            {"5.1": self._feishu_test, "5.2": self._live_logs}.get(c, lambda: None)()

    # ===== 6.x 自选股管理 =====

    def _menu_pool(self):
        while True:
            self._print_header("自选股管理")
            wl = self.api.watcher.load_watchlist()
            print(f"  当前自选股: {len(wl)} 只")
            print()
            print("  6.1 添加自选股")
            print("  6.2 删除自选股")
            print("  6.3 查看自选股列表")
            print("  6.4 更新代码库")
            print("  0. 返回上级")
            with self._silent():
                c = self._input("\n请输入选项: ")
            if c == "0": break
            {"6.1": self._pool_add, "6.2": self._pool_remove,
             "6.3": self._pool_list,
             "6.4": self._pool_import_codes}.get(c, lambda: None)()

    def _pool_add(self):
        self._print_header("添加自选股")
        with self._silent():
            symbol = self._input("请输入代码: ").strip()
        if not symbol:
            print("代码不能为空。")
            self._press_enter()
            return
        result = self.api.pool_add(symbol)
        if result.get("success"):
            d = result["data"]
            print(f"\n已添加: {d['symbol']} {d['name']} ({d['type']})")
            self._log(f"添加自选股: {d['symbol']} {d['name']} ({d['type']})")
        else:
            print(result.get("message", "添加失败"))
        self._press_enter()

    def _pool_remove(self):
        self._print_header("删除自选股")
        wl = self.api.watcher.load_watchlist()
        if not wl:
            print("自选股池为空。")
            self._press_enter()
            return
        seen = set()
        unique = []
        for item in wl:
            s = item['symbol']
            if s not in seen:
                seen.add(s)
                unique.append(item)
        print(f"当前共 {len(unique)} 只:")
        print(f"{'序号':>4} {'代码':<10} {'名称':<12} {'类型':<8}")
        print("-" * 40)
        for i, item in enumerate(unique, 1):
            print(f"  {i:>2}. {item['symbol']:<10} {item.get('name',''):<12} {item.get('type','')}")
        print()
        with self._silent():
            idx = self._input_int("请选择要删除的序号 (0=取消): ")
        if idx < 1 or idx > len(unique):
            print("已取消。")
            self._press_enter()
            return
        symbol = unique[idx - 1]['symbol']
        name = unique[idx - 1].get('name', '')
        with self._silent():
            c = self._input(f"确认删除 {symbol} {name}? (y/n): ").lower()
        if c != 'y':
            print("已取消。")
            self._press_enter()
            return
        result = self.api.pool_remove(symbol)
        if result.get("success"):
            print(f"已删除: {symbol} {name}")
            self._log(f"删除自选股: {symbol} {name}")
        else:
            print(result.get("message", f"删除失败: {symbol}"))
        self._press_enter()

    def _pool_list(self):
        self._print_header("自选股列表")
        result = self.api.pool_list()
        if not result.get("success"):
            print(result.get("message", ""))
            self._press_enter()
            return
        stocks = result["data"]["stocks"]
        if not stocks:
            print("自选股池为空。")
            self._press_enter()
            return
        print(f"共 {len(stocks)} 只:\n")
        print(f"{'代码':<10} | {'名称':<14} | {'类型':<8} | {'分组':<12}")
        print("-" * 52)
        for item in stocks:
            name = item.get('name', '') or ''
            print(f"  {item['symbol']:<10} | {name:<14} | {item.get('type',''):<8} | {item.get('group_name',''):<12}")
        self._press_enter()

    def _pool_import_codes(self):
        self._print_header("更新代码库")
        print("正在从数据源获取最新股票代码列表...")
        result = self.api.pool_import_codes()
        if result.get("success"):
            d = result["data"]
            print(f"\n✅ 导入完成: {d['count']} 条 (数据源: {d['provider']})")
            self._log(f"更新代码库: 导入{d['count']}条 (来源: {d['provider']})")
        else:
            print(f"\n❌ {result.get('message', '导入失败')}")
        self._press_enter()

    # ===== helpers =====

    def _pick_symbol(self):
        with self._silent():
            wl = self.api.watcher.load_watchlist()
        if not wl:
            return None, None
        seen = set()
        unique = []
        for item in wl:
            s = item['symbol']
            if s not in seen:
                seen.add(s)
                unique.append(item)
        print(f"{'序号':>4} {'代码':<10} {'名称':<12} {'类型':<8}")
        print("-" * 40)
        for i, item in enumerate(unique, 1):
            print(f"  {i:>2}. {item['symbol']:<10} {item.get('name',''):<12} {item.get('type','')}")
        print(f"  0. 全部 ({len(unique)} 只)")
        print(f"  回车 = 返回上级")
        val = self._input("请选择序号: ")
        if val == "":
            return None, None
        try:
            idx = int(val)
        except ValueError:
            return None, None
        if idx == 0:
            return [s['symbol'] for s in unique], unique
        if 1 <= idx <= len(unique):
            return [unique[idx - 1]['symbol']], unique
        return None, None

    def _pick_period(self):
        periods = [("1m", "1分钟"), ("5m", "5分钟"),
                    ("30m", "30分钟"), ("1d", "日线")]
        for i, (p, desc) in enumerate(periods, 1):
            print(f"  {i}. {p} ({desc})")
        print("  0. 全部")
        print("  回车 = 返回上级")
        val = self._input("请选择周期: ")
        if val == "":
            return None
        try:
            idx = int(val)
        except ValueError:
            return None
        if idx == 0:
            return [p for p, _ in periods]
        if 1 <= idx <= len(periods):
            return [periods[idx - 1][0]]
        return None

    # ===== 1.x 监控管理 =====

    def _status(self):
        self._print_header("运行状态")
        r = self.api.status()
        if not r["success"]:
            print(r["message"])
            self._press_enter()
            return
        d = r["data"]
        running = d["running"]
        print(f"  监控状态:   {'运行中' if running else '已停止'}")
        print(f"  飞书推送:   {'已启用' if d['feishu']['enabled'] else '未启用'} (签名: {'开' if d['feishu']['sign_enabled'] else '关'})")
        print(f"  主数据源:   {d['datasource']['primary']}")
        print(f"  调度时间:   {d['schedule']['morning']} / {d['schedule']['afternoon']}  每 {d['schedule']['interval_seconds']} 秒")
        s = d['signal']
        print(f"  信号函数:   {s['enabled_count']}/{s['function_count']} 个启用")
        if running and d['schedule']['next_run']:
            print(f"  下次运行:   {d['schedule']['next_run']}")
        print(f"  日志文件:   log/f51-headless.log")
        self._press_enter()

    def _start(self):
        self._print_header("启动监控")
        if self._is_running():
            print("监控已在运行中。")
            self._press_enter()
            return

        # Late-start data integrity check
        now = datetime.now()
        nine_thirty = now.replace(hour=9, minute=30, second=0, microsecond=0)
        if now > nine_thirty:
            self._log("超过 9:30，检查当日数据完整性...")
            print("超过 9:30，检查当日数据完整性...")
            symbols = self.api.watcher.get_symbols()
            for symbol in symbols:
                for period in ['1m', '5m', '30m', '1d']:
                    try:
                        complete = self.api.fetcher.check_today_data_complete(symbol, period)
                    except Exception:
                        complete = False
                    if not complete:
                        try:
                            ok, saved, src = self.api.fetcher.fetch_and_save(symbol, period)
                            status = f"{saved} 条 ({src})" if ok else "补全失败"
                        except Exception as e:
                            status = f"出错: {e}"
                        self._log(f"{symbol} {period}: 缺失, 已补全 ({status})")
                        print(f"  {symbol} {period}: 缺失, 已补全 ({status})")
                    else:
                        self._log(f"{symbol} {period}: 数据完整")

        print("启动监控服务...")
        sc = self.config.get("schedule", {})
        subprocess.run(["systemctl", "start", "f51-start.service"])
        self._log("监控已启动")
        print(f"监控已启动")
        print(f"调度: {sc.get('morning_start','09:25')}-{sc.get('morning_end','11:35')} / "
              f"{sc.get('afternoon_start','13:00:05')}-{sc.get('afternoon_end','15:05')}，"
              f"每 {sc.get('interval_seconds', 65)} 秒")
        print(f"日志: log/f51-headless.log")
        self._press_enter()

    def _stop(self):
        self._print_header("停止监控")
        if not self._is_running():
            print("监控未运行。")
            self._press_enter()
            return
        subprocess.run(["systemctl", "stop", "f51-start.service"])
        self._log_silent = False
        logging.getLogger().setLevel(logging.INFO)
        self._log("监控已停止")
        print("监控已停止。")
        self._press_enter()

    def _fill_today(self):
        self._print_header("当日数据补全")
        with self._silent():
            symbols, _ = self._pick_symbol()
            if symbols is None:
                return
            if not symbols:
                self._press_enter()
                return
            periods = self._pick_period()
        if periods is None:
            return
        if not periods:
            periods = ["1m", "5m", "30m"]
        for symbol in symbols:
            print(f"\n{symbol}:")
            for period in periods:
                ok, saved, src = self.api.fetcher.fetch_and_save(symbol, period)
                status = f"{saved} 条 ({src})" if ok else "无数据"
                print(f"  {period}: {status}")
            self._log(f"补全 {symbol}: done")
        # 信号补全
        print("\n计算信号...")
        signal_results = self.api._run_signals_for_symbols(symbols)
        for sr in signal_results:
            if sr["signals"]:
                print(f"  {sr['symbol']} {sr['function']}: {sr['signals']} 个信号")
        self._press_enter()

    def _today_signals(self):
        """1.5 / 3.1 当天信号展示"""
        self._print_header("当天信号触发")
        signals = self.api.store.get_today()
        if not signals:
            print("\n暂无当天信号")
            self._press_enter()
            return
        groups = {}
        for s in signals:
            fn = s.get('display_name', s.get('func_name', '未知'))
            groups.setdefault(fn, []).append(s)
        for func_name, sigs in groups.items():
            print(f"\n  {func_name}:")
            print(f"    {'代码':<10} {'方向':<6} {'时间':<22} {'说明':<20}")
            print(f"    {'----':<10} {'----':<6} {'----':<22} {'----':<20}")
            for s in sigs[:10]:
                print(f"    {s['symbol']}  {'BUY' if s.get('direction')=='buy' else 'SELL'}  "
                      f"{str(s.get('signal_time',''))}  {s.get('indicator','')}")
        total = sum(len(v) for v in groups.values())
        print(f"\n共 {total} 个信号")
        self._press_enter()

    # ===== 2.x 数据查询 =====

    def _get_stock_name(self, symbol: str) -> str:
        pool = {s['symbol']: s.get('name', '') for s in
                ({'symbol': r.get('symbol'), 'name': r.get('name')}
                 for r in self.api.watcher.load_watchlist())}
        return pool.get(symbol, symbol)

    def _data_summary(self):
        self._print_header("数据下载")
        symbols, _ = self._pick_symbol()
        if symbols is None:
            return
        if not symbols:
            self._press_enter()
            return
        code = None if len(symbols) > 1 else symbols[0]
        with self._silent():
            start = self._input_date("开始日期", datetime.now().strftime("%Y-%m-%d"))
            end = self._input_date("结束日期", start)
            periods = self._pick_period()
        if periods is None:
            return
        if not periods:
            periods = ["1d", "1m", "5m", "30m"]

        print(f"\n{'代码':<10} | {'周期':<6} | 时间戳列表")
        print("-" * 65)
        for p in periods:
            result = self.api.data_summary(symbol=code, start=start, end=end, period=p)
            if result.get("success"):
                for r in result["data"]["results"]:
                    tss = r.get("timestamps", [])
                    if tss:
                        if p == '1d':
                            items = [t[:10] for t in tss]
                        else:
                            items = [t[11:16] for t in tss]
                        print(f"  {r['symbol']:<10} | {p:<6} | {' '.join(items)}")
                    else:
                        print(f"  {r['symbol']:<10} | {p:<6} | (无数据)")
        self._press_enter()

    def _data_detail(self):
        self._print_header("详细数据")
        symbols, _ = self._pick_symbol()
        if symbols is None:
            return
        if not symbols:
            self._press_enter()
            return
        code = symbols[0]
        periods = self._pick_period()
        if periods is None:
            return
        if not periods:
            periods = ["5m"]
        today = datetime.now().strftime("%Y-%m-%d")
        start = self._input_date("开始日期", today)
        end = self._input_date("结束日期", start)
        limit = self._input_int("显示条数: ", 20)

        for period in periods:
            result = self.api.data_detail(code, period, start, end, limit)
            if not result.get("success"):
                print(f"\n{period}: {result.get('message', '查询失败')}")
                continue
            d = result["data"]
            print(f"\n{d['symbol']} {d['name']} | {d['period']} | {d['start']} ~ {d['end']}")
            print(f"\n{'时间':<22} | {'开盘':>8} | {'最高':>8} | {'最低':>8} | {'收盘':>8} | {'成交量':>12}")
            print("-" * 85)
            for r in d["candles"]:
                print(f"  {r['time']:<22} | {r['open']:>8.3f} | {r['high']:>8.3f} | {r['low']:>8.3f} | {r['close']:>8.3f} | {r['vol']:>12.0f}")
            print(f"\n共 {d['count']} 条")
        self._press_enter()

    def _dividend_view(self):
        self._print_header("自选股除权除息")
        result = self.api.dividend_view()
        if not result.get("success"):
            print(result.get("message", ""))
            self._press_enter()
            return
        stocks = result["data"]["results"]
        if not stocks:
            print("自选股池为空。")
            self._press_enter()
            return
        print("查询中...")
        print(f"{'代码':<10} | {'名称':<10} | {'除权除息日':<14}")
        print("-" * 42)
        for item in stocks:
            print(f"  {item['symbol']:<10} | {item.get('name',''):<10} | {item.get('dividend_date', '--')}")
        self._press_enter()

    # ===== 2.5 临时下载数据 =====

    def _view_download_log(self):
        self._print_header("临时下载数据")
        symbols, _ = self._pick_symbol()
        if symbols is None:
            return
        if not symbols:
            self._press_enter()
            return
        code = symbols[0]

        periods = self._pick_period()
        if periods is None:
            return
        query_period = periods[0] if periods and periods != ["1m", "5m", "30m", "1d"] else None

        today = datetime.now().strftime("%Y-%m-%d")
        start = self._input_date("开始日期", today)
        end = self._input_date("结束日期", start)

        direction = self._input("查看方向（1=从头看, 2=从尾看）: ", "2").strip()
        from_end = (direction == "2")

        limit = self._input_int("显示条数: ", 100)

        result = self.api.data_download_log(code, start, end, query_period, limit, desc=from_end)
        if not result.get("success"):
            print(result.get("message", "查询失败"))
            self._press_enter()
            return
        d = result["data"]
        records = d["records"]
        if not records:
            print("暂无临时下载数据。")
            self._press_enter()
            return
        period_label = query_period or "全部"
        print(f"\n{symbols[0]} | {d['start']} ~ {d['end']} | {period_label} | 共 {d['count']} 条")
        print(f"\n{'请求时间':<10} {'数据时间':<10} {'周期':<4} {'开盘':>7} {'最高':>7} {'最低':>7} {'收盘':>7} {'成交量':>8}")
        print("-" * 82)
        for r in records:
            rt = r.get("time", "")[-8:] if r.get("time") else ""
            bt = r.get("api_bar_time", "")[-8:] if r.get("api_bar_time") else ""
            open_ = r["open"] if r["open"] is not None else 0
            high_ = r["high"] if r["high"] is not None else 0
            low_ = r["low"] if r["low"] is not None else 0
            close_ = r["close"] if r["close"] is not None else 0
            vol_ = r["volume"] if r["volume"] is not None else 0
            print(f"  {rt:<10} {bt:<10} {r['period']:<4} {open_:>7.3f} {high_:>7.3f} {low_:>7.3f} {close_:>7.3f} {vol_:>8.0f}")
        self._press_enter()

    # ===== 2.4 历史回填 =====

    def _fill_history(self):
        self._print_header("历史数据回填")
        symbols, _ = self._pick_symbol()
        if symbols is None:
            return
        if not symbols:
            self._press_enter()
            return
        periods = self._pick_period()
        if periods is None:
            return
        if not periods:
            periods = ["1m", "5m", "30m", "1d"]
        from datetime import timedelta
        default_start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        default_end = datetime.now().strftime("%Y-%m-%d")
        s = self._input_date("开始日期", default_start, allow_empty=True)
        e = self._input_date("结束日期", default_end, allow_empty=True)
        total = 0
        total_jobs = len(symbols) * len(periods)
        time_range = f"{s or 'auto'} ~ {e or 'auto'}"
        print(f"  任务数: {total_jobs}, 时间范围: {time_range}")
        print(f"  {'#' * 60}")
        try:
            for i, symbol in enumerate(symbols, 1):
                for j, period in enumerate(periods, 1):
                    idx = (i - 1) * len(periods) + j
                    line = f"  [{idx}/{total_jobs}] {symbol:<6} {period:<4} {time_range}"
                    print(line, end=" -> ", flush=True)
                    result = self.api.fill_history(symbol, period, s or None, e or None)
                    if result.get("success"):
                        r = result["data"]["results"][0]
                        if r["success"]:
                            print(f"{r['saved']} 条 ({r['source']})")
                            total += r["saved"]
                        else:
                            print("无数据")
                    else:
                        print(result.get("message", "出错"))
        except KeyboardInterrupt:
            print(f"\n  ! 中断: 已处理 {idx}/{total_jobs} 个任务")
            confirmed = self._input("  确认退出? (y/n): ", "n").lower() == "y"
            if confirmed:
                self._log(f"历史回填中断，共写入 {total} 条")
                print(f"\n写入数据库: {total} 条")
                self._press_enter()
                return
            print("  继续执行...")
        self._log(f"历史回填完成，共写入 {total} 条")
        print(f"\n写入数据库: {total} 条")
        self._press_enter()

    # ===== 3.x 配置管理 =====

    def _cfg_datasource(self):
        self._print_header("配置数据源")
        print(f"  当前主数据源: {self.api.fetcher.primary}")
        try:
            from stockpush.services.data_source_registry import get_registry
            reg = get_registry()
            providers = reg.list_providers()
        except Exception:
            providers = []
        if providers:
            print("\n  可用数据源:")
            for i, p in enumerate(providers):
                print(f"    {i+1}. {p['provider_name']} ({p['display_name']})")
            idx = self._input_int("\n选择主数据源 (序号): ", 1)
            if 1 <= idx <= len(providers):
                self.api.fetcher.primary = providers[idx-1]["provider_name"]
        else:
            self.api.fetcher.primary = self._input("主数据源: ", self.api.fetcher.primary)
        self._save_config()
        print("\n已保存。")
        self._press_enter()

    def _cfg_schedule(self):
        self._print_header("配置调度时间")
        print("  早盘时段:")
        ms = self._input_time("  开始 (HH:MM)", self.api.scheduler.morning_start, "HH:MM")
        me = self._input_time("  结束 (HH:MM)", self.api.scheduler.morning_end, "HH:MM")
        print("  午盘时段:")
        aas = self._input_time("  开始 (HH:MM:SS)", self.api.scheduler.afternoon_start, "HH:MM:SS")
        aae = self._input_time("  结束 (HH:MM)", self.api.scheduler.afternoon_end, "HH:MM")
        cur = self.api.scheduler.interval_seconds
        mins = self._input_int(f"间隔-分 [{cur // 60}]: ", cur // 60)
        secs = self._input_int(f"间隔-秒 [{cur % 60}]: ", cur % 60)
        self.api.schedule_set(morning_start=ms, morning_end=me, afternoon_start=aas, afternoon_end=aae, interval_seconds=mins * 60 + secs)
        self.config["schedule"] = {
            "morning_start": ms, "morning_end": me,
            "afternoon_start": aas, "afternoon_end": aae,
            "interval_seconds": mins * 60 + secs,
        }
        self._save_config()
        print("\n已保存。")
        self._press_enter()

    def _func_list_mgr(self):
        """3.2 函数注册管理"""
        while True:
            self._print_header("函数注册管理")
            funcs = self.api.registry.get_all()
            if funcs:
                print(f"当前注册函数 ({len(funcs)} 个):")
                print(f"  {'ID':>4} {'名称':<16} {'显示名':<16} {'周期':<5} {'启用':<4}")
                print("  " + "-" * 52)
                for f in funcs:
                    en = "是" if f.enabled else "否"
                    print(f"  {f.id:>4} {f.name:<16} {f.display_name:<16} {f.period:<5} {en:<4}")
            else:
                print("暂无注册函数。")
            print()
            print("  1. 注册新函数")
            print("  2. 删除函数")
            print("  3. 启用/禁用函数")
            print("  0. 返回上级")
            with self._silent():
                c = self._input("\n请选择操作: ")
            if c == "0":
                break
            elif c == "1":
                self._func_register_new()
            elif c == "2":
                self._func_delete()
            elif c == "3":
                self._func_toggle()

    def _func_register_new(self):
        """注册新函数"""
        self._print_header("注册新函数")
        name = self._input("函数名称: ")
        if not name:
            self._press_enter()
            return
        display_name = self._input("显示名称: ", name)
        module_path = self._input("模块路径 (如 strategies.signal_zg): ")
        func_name = self._input("函数名: ")
        period = self._input("周期 (5m/30m/1d): ", "5m")
        try:
            new_id = self.api.registry.register(name, display_name, module_path, func_name, period)
            print(f"注册成功! ID: {new_id}")
            self._log(f"注册函数: {name} ({display_name})")
        except Exception as e:
            print(f"注册失败: {e}")
        self._press_enter()

    def _func_delete(self):
        """删除函数"""
        self._print_header("删除函数")
        name = self._input("要删除的函数名称: ")
        if not name:
            self._press_enter()
            return
        c = self._input(f"确认删除函数 '{name}'? (y/n): ").lower()
        if c != 'y':
            print("已取消。")
            self._press_enter()
            return
        try:
            self.api.registry.remove(name)
            print(f"已删除: {name}")
            self._log(f"删除函数: {name}")
        except Exception as e:
            print(f"删除失败: {e}")
        self._press_enter()

    def _func_toggle(self):
        """启用/禁用函数"""
        self._print_header("启用/禁用函数")
        funcs = self.api.registry.get_all()
        if not funcs:
            print("暂无注册函数。")
            self._press_enter()
            return
        print(f"{'序号':>4} {'名称':<16} {'显示名':<16} {'状态':<8}")
        print("-" * 48)
        for i, f in enumerate(funcs, 1):
            en = "启用" if f.enabled else "禁用"
            print(f"  {i:>2}. {f.name:<16} {f.display_name:<16} [{en}]")
        idx = self._input_int("选择序号: ")
        if idx < 1 or idx > len(funcs):
            self._press_enter()
            return
        selected = funcs[idx - 1]
        new_state = not selected.enabled
        try:
            self.api.registry.set_enabled(selected.name, new_state)
            print(f"{selected.name}: {'已启用' if new_state else '已禁用'}")
            self._log(f"{'启用' if new_state else '禁用'}函数: {selected.name}")
        except Exception as e:
            print(f"操作失败: {e}")
        self._press_enter()

    def _func_params_mgr(self):
        """3.3 参数管理"""
        self._print_header("参数管理")
        funcs = self.api.registry.get_all()
        if not funcs:
            print("暂无注册函数。")
            self._press_enter()
            return
        print("选择函数:")
        print(f"{'序号':>4} {'名称':<16} {'显示名':<16}")
        print("-" * 40)
        for i, f in enumerate(funcs, 1):
            print(f"  {i:>2}. {f.name:<16} {f.display_name:<16}")
        idx = self._input_int("序号: ")
        if idx < 1 or idx > len(funcs):
            self._press_enter()
            return
        selected = funcs[idx - 1]
        params = self.api.registry.get_params(selected.name, selected.param_set_id)
        print(f"\n当前参数 ({selected.name}):")
        if params:
            for k, v in params.items():
                print(f"  {k} = {v}")
        else:
            print("  (无参数)")
        c = self._input("\n是否修改参数? (y/n): ").lower()
        if c != 'y':
            self._press_enter()
            return
        new_params = {}
        for k, v in params.items():
            val = self._input(f"  {k} [{v}]: ", str(v))
            new_params[k] = val
        added = self._input("新增参数 (key=value, 回车跳过): ")
        if added:
            parts = added.split("=", 1)
            if len(parts) == 2:
                new_params[parts[0].strip()] = parts[1].strip()
        try:
            self.api.registry.set_params(selected.name, selected.param_set_id, new_params)
            print("参数已保存。")
            self._log(f"更新参数: {selected.name}")
        except Exception as e:
            print(f"保存失败: {e}")
        self._press_enter()

    def _func_validate(self):
        """3.4 验证函数"""
        self._print_header("验证函数")
        module_path = self._input("模块路径: ")
        func_name = self._input("函数名: ")
        if not module_path or not func_name:
            print("模块路径和函数名不能为空。")
            self._press_enter()
            return
        result = self.api.registry.validate(module_path, func_name)
        if result.get('valid'):
            print(f"\n验证成功!")
            print(f"  签名: {result.get('signature', '')}")
        else:
            print(f"\n验证失败:")
            print(f"  错误: {result.get('error', '未知错误')}")
        self._press_enter()

    def _backtest_query(self):
        """3.5 回调查询"""
        self._print_header("回调查询")
        funcs = self.api.registry.get_all()
        if not funcs:
            print("暂无注册函数。")
            self._press_enter()
            return
        print("选择函数:")
        print(f"{'序号':>4} {'名称':<16} {'显示名':<16} {'状态':<8}")
        print("-" * 48)
        for i, f in enumerate(funcs, 1):
            en = "启用" if f.enabled else "禁用"
            print(f"  {i:>2}. {f.name:<16} {f.display_name:<16} [{en}]")
        idx = self._input_int("序号: ")
        if idx < 1 or idx > len(funcs):
            self._press_enter()
            return
        selected = funcs[idx - 1]
        symbols, _ = self._pick_symbol()
        if not symbols:
            self._press_enter()
            return
        symbol = symbols[0]
        start = self._input_date("开始日期")
        end = self._input_date("结束日期", start)
        print(f"\n回测: {selected.name} | {symbol} | {start} ~ {end}")
        try:
            signals = self.api.engine.backtest(selected.name, selected.period, symbol, start, end)
            if signals:
                print(f"  {'时间':<22} {'代码':<10} {'方向':<6} {'说明':<20}")
                print(f"  {'----':<22} {'----':<10} {'----':<6} {'----':<20}")
                print(f"共 {len(signals)} 个信号:")
                for s in signals:
                    print(f"  {s.get('time','')}  {s.get('symbol','')}  "
                          f"{s.get('direction','')}  {s.get('indicator','')}")
            else:
                print("无信号。")
        except Exception as e:
            print(f"回测失败: {e}")
        self._press_enter()

    def _push_mgr(self):
        """3.6 推送管理"""
        while True:
            self._print_header("推送管理")
            p = self.api.pusher
            print(f"  推送状态: {'已启用' if p.enabled else '未启用'}")
            print(f"  Webhook:  {'已配置' if p.webhook_url else '未配置'}")
            print(f"  签名校验: {'开' if p.sign_enabled else '关'}")
            print()
            print("  1. 启用/禁用推送")
            print("  2. 测试推送")
            print("  0. 返回上级")
            with self._silent():
                c = self._input("\n请输入选项: ")
            if c == "0":
                break
            elif c == "1":
                p.enabled = not p.enabled
                print(f"推送已{'启用' if p.enabled else '禁用'}")
                self._save_config()
                self._press_enter()
            elif c == "2":
                self._feishu_test()

    def _cfg_feishu(self):
        self._print_header("配置飞书推送")
        print(f"  Webhook: {'已配置' if self.api.pusher.webhook_url else '未配置'}")
        print(f"  启用: {'是' if self.api.pusher.enabled else '否'}")
        print(f"  签名校验: {'开' if self.api.pusher.sign_enabled else '关'}")
        print()
        url = self._input(f"Webhook URL (回车=不变): ", self.api.pusher.webhook_url or "")
        enabled = self._input("启用推送 (y/n): ", "y" if self.api.pusher.enabled else "n").lower() == "y"
        sign_on = self._input("签名校验 (y/n): ", "y" if self.api.pusher.sign_enabled else "n").lower() == "y"
        secret = ""
        if sign_on:
            secret = self._input("签名秘钥: ", "")
        self.api.pusher.set_config(url, enabled, secret if secret else self.api.pusher.sign_secret, sign_on)
        self._save_config()
        print("\n已保存。")
        if enabled and url:
            try:
                result = self.api.pusher.test()
                print(f"测试推送: {'成功' if result['success'] else '失败'} - {result['message']}")
            except Exception as e:
                print(f"测试推送失败: {e}")
        self._press_enter()

    # ===== 4.x 自定义函数 =====

    def _func_set_dir(self):
        self._print_header("设置函数目录")
        default = self.config.get("custom_functions", {}).get("dir", str(self.project_root / "userfunc"))
        new_dir = self._input(f"函数目录 [{default}]: ", default)
        self.config.setdefault("custom_functions", {})["dir"] = new_dir
        self._save_config()
        p = Path(new_dir)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            (p / "__init__.py").touch()
            print(f"已创建目录: {p}")
        print("已保存。")
        self._press_enter()

    def _func_register(self):
        self._print_header("注册自定义函数")
        func_dir = Path(self.config.get("custom_functions", {}).get("dir", str(self.project_root / "userfunc")))
        if not func_dir.exists():
            print(f"目录不存在: {func_dir}")
            self._press_enter()
            return
        py_files = list(func_dir.glob("*.py"))
        if not py_files:
            print(f"目录下无 .py 文件: {func_dir}")
            self._press_enter()
            return
        print("找到以下函数文件:")
        for i, f in enumerate(py_files):
            print(f"  {i+1}. {f.name}")
        idx = self._input_int("选择文件: ", 1)
        if idx < 1 or idx > len(py_files):
            self._press_enter()
            return
        filename = py_files[idx-1].name
        func_name = self._input("调用的函数名: ", "execute")
        desc = self._input("描述: ", filename)

        funcs = self.config.setdefault("custom_functions", {}).setdefault("functions", [])
        funcs.append({"name": filename.replace(".py", ""), "file": filename,
                       "func": func_name, "dir": str(func_dir), "desc": desc})
        self._save_config()
        print(f"\n已注册: {filename} -> {func_name}()")
        print("函数需返回: buy_point(bool), buy_status(str), sell_point(bool), sell_status(str)")
        self._press_enter()

    def _func_list(self):
        self._print_header("已注册自定义函数")
        funcs = self.config.get("custom_functions", {}).get("functions", [])
        if not funcs:
            print("暂无注册的自定义函数。")
        else:
            print(f"{'序号':>4} {'名称':<16} {'文件':<20} {'函数':<20} {'说明':<20}")
            print("-" * 85)
            for i, f in enumerate(funcs):
                print(f"  {i+1}. {f.get('name')} ({f.get('file')}) -> {f.get('func')}()  [{f.get('desc','')}]")
        self._press_enter()

    def _func_test(self):
        self._print_header("测试自定义函数")
        funcs = self.config.get("custom_functions", {}).get("functions", [])
        if not funcs:
            print("暂无注册的自定义函数。")
            self._press_enter()
            return
        print(f"{'序号':>4} {'名称':<16} {'文件':<20} {'函数':<20}")
        print("-" * 64)
        for i, f in enumerate(funcs):
            print(f"  {i+1}. {f.get('name')} ({f.get('file')}) -> {f.get('func')}()")
        idx = self._input_int("选择要测试的函数: ", 1)
        if idx < 1 or idx > len(funcs):
            self._press_enter()
            return
        fcfg = funcs[idx-1]
        import importlib.util
        spec = importlib.util.spec_from_file_location(fcfg["name"], Path(fcfg["dir"]) / fcfg["file"])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, fcfg["func"], None)
        if not fn:
            print(f"函数 {fcfg['func']} 未找到。")
            self._press_enter()
            return
        import pandas as pd
        import numpy as np
        dates = pd.date_range(end=pd.Timestamp.today(), periods=200, freq="D")
        df = pd.DataFrame({"open": np.random.randn(200).cumsum()+100, "high": np.random.randn(200).cumsum()+102,
                           "low": np.random.randn(200).cumsum()+98, "close": np.random.randn(200).cumsum()+100,
                           "volume": np.abs(np.random.randn(200)*1000000), "amount": np.abs(np.random.randn(200)*10000000)}, index=dates)
        try:
            result = fn(df)
            if isinstance(result, dict):
                print(f"  buy_point:     {result.get('buy_point', 'N/A')}")
                print(f"  buy_status:    {result.get('buy_status', 'N/A')}")
                print(f"  sell_point:    {result.get('sell_point', 'N/A')}")
                print(f"  sell_status:   {result.get('sell_status', 'N/A')}")
            else:
                print(f"  返回: {result}")
        except Exception as e:
            print(f"测试失败: {e}")
        self._press_enter()
    def _func_requirements(self):
        self._print_header("自定义函数要求说明")
        print("=" * 50)
        print("  【文件型自定义函数】（通过本菜单 4.2 注册）")
        print("=" * 50)
        print()
        print("  1. 目录结构")
        print("     - 函数文件存放于函数目录（默认 userfunc/）")
        print("     - 可通过 4.1 设置函数目录更改路径")
        print("     - 目录将在修改时自动创建（含 __init__.py）")
        print()
        print("  2. 文件要求")
        print("     - 必须是 .py 文件")
        print("     - 文件内需定义一个可调用的函数")
        print()
        print("  3. 注册信息")
        print("     - 文件名：选择要注册的 .py 文件")
        print("     - 函数名：文件中实际定义的函数名（默认 execute）")
        print("     - 描述：简要说明（默认文件名）")
        print()
        print("  4. 函数签名")
        print("     def execute(df: pd.DataFrame) -> dict:")
        print("         ...")
        print("         return {")
        print("             'buy_point':  True/False,    # bool 买点信号")
        print("             'buy_status': '说明文字',     # str  买点状态")
        print("             'sell_point': True/False,    # bool 卖点信号")
        print("             'sell_status':'说明文字',     # str  卖点状态")
        print("         }")
        print()
        print("  5. 测试方式")
        print("     - 4.4 测试函数：加载已注册函数，传入 200 日随机行情")
        print("     - 打印返回的四个字段值")
        print()
        print("  6. 执行周期")
        print("     - 系统自动按调度时间遍历所有自选股执行")
        print("     - 有信号时自动归档至 tb_signals 并推送飞书")
        print()
        print("=" * 50)
        print("  【系统注册函数】（通过 3.2 函数注册管理->注册新函数）")
        print("=" * 50)
        print()
        print("  1. 注册字段")
        print("     - 函数名称(name)：唯一标识")
        print("     - 显示名称(display_name)：推送时显示的名称")
        print("     - 模块路径(module_path)：如 strategies.signal_zg")
        print("     - 函数名(func_name)：模块中的实际函数名")
        print("     - 周期(period)：5m / 30m / 1d")
        print()
        print("  2. 函数签名要求（validate 验证）")
        print("     def my_func(symbol: str, period: str,")
        print("                 start: str, end: str,")
        print("                 param_set_id: int) -> dict:")
        print("         ...")
        print("         return {'signals': [")
        print("             {'time': ..., 'direction': 'buy/sell',")
        print("              'indicator': '说明', ...}")
        print("         ]}")
        print()
        print("  3. 执行流程")
        print("     - 函数必须已启用(enabled=true)")
        print("     - 按周期筛选，只跑匹配周期的函数")
        print("     - 对每个自选股逐只调用 execute()")
        print("     - 返回的 signals 数组非空时归档+推送")
        print()
        self._press_enter()

    # ===== 5.x 工具 =====

    def _feishu_test(self):
        self._print_header("测试飞书推送")
        if not self.api.pusher.webhook_url:
            print("飞书 Webhook 未配置。")
            self._press_enter()
            return
        print("发送测试消息...")
        result = self.api.pusher.test()
        print(f"结果: {'成功' if result['success'] else '失败'} - {result['message']}")
        self._press_enter()

    def _cfg_register_systemd(self):
        self._print_header("注册系统自启")
        print(f"  项目路径: {self.project_root}")
        print(f"  Python:    {self.project_root / '.venv/bin/python3'}")
        print(f"  Worker:    {self.f51_root / 'worker.py'}")
        print()
        print("  将创建以下 systemd 单元:")
        print("    - /etc/systemd/system/f51-start.service")
        print("    - /etc/systemd/system/f51-stop.service")
        print("    - /etc/systemd/system/f51-start.timer")
        print("    - /etc/systemd/system/f51-stop.timer")
        print()
        c = self._input("确认注册? (y/n): ").lower()
        if c != 'y':
            print("已取消。")
            self._press_enter()
            return

        venv_python = self.project_root / '.venv' / 'bin' / 'python3'
        worker_py = self.f51_root / 'worker.py'
        unit_dir = '/etc/systemd/system'

        service = f"""[Unit]
Description=F5.1 Realtime Monitor
After=network.target

[Service]
Type=exec
ExecStart={venv_python} {worker_py} --headless
WorkingDirectory={self.project_root}
Restart=no
KillSignal=SIGTERM
TimeoutStopSec=30
"""
        start_timer = f"""[Unit]
Description=F5.1 Monitor Start

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=false

[Install]
WantedBy=timers.target
"""
        stop_timer = f"""[Unit]
Description=F5.1 Monitor Stop

[Timer]
OnCalendar=*-*-* 15:30:00
Persistent=false

[Install]
WantedBy=timers.target
"""

        try:
            import subprocess
            for name, content in [("f51-start.service", service),
                                   ("f51-start.timer", start_timer),
                                   ("f51-stop.timer", stop_timer)]:
                path = f"{unit_dir}/{name}"
                proc = subprocess.run(
                    ["sudo", "tee", path], input=content,
                    capture_output=True, text=True, check=True
                )
                print(f"  已写入: {path}")

            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            subprocess.run(["sudo", "systemctl", "enable", "f51-start.timer"], check=True)
            subprocess.run(["sudo", "systemctl", "enable", "f51-stop.timer"], check=True)
            print("\n已注册系统自启。f51-start.timer 和 f51-stop.timer 已启用。")
            self._log("注册系统自启完成")
        except subprocess.CalledProcessError as e:
            print(f"\n注册失败: {e}")
            self._log(f"注册系统自启失败: {e}")
        self._press_enter()

    def _cfg_unregister_systemd(self):
        self._print_header("取消系统自启")
        c = self._input("确认取消系统自启? (y/n): ").lower()
        if c != 'y':
            print("已取消。")
            self._press_enter()
            return

        try:
            import subprocess
            subprocess.run(["sudo", "systemctl", "disable", "f51-start.timer"], check=False)
            subprocess.run(["sudo", "systemctl", "disable", "f51-stop.timer"], check=False)

            for name in ["f51-start.service", "f51-stop.service", "f51-start.timer", "f51-stop.timer"]:
                path = f"/etc/systemd/system/{name}"
                if os.path.exists(path):
                    subprocess.run(["sudo", "rm", path], check=True)
                    print(f"  已删除: {path}")

            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            print("\n已取消系统自启。")
            self._log("取消系统自启完成")
        except subprocess.CalledProcessError as e:
            print(f"\n操作失败: {e}")
        except Exception as e:
            print(f"\n错误: {e}")
        self._press_enter()

    def _live_logs(self):
        self._print_header("实时日志 (按 q+回车 返回)")
        print("  (按 q 然后回车返回上级菜单)")
        import select
        last_idx = len(self._log_messages)
        try:
            while True:
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    line = sys.stdin.readline()
                    if line.strip().lower() == 'q':
                        break
                with self._log_lock:
                    new = self._log_messages[last_idx:]
                for entry in new:
                    print(entry)
                last_idx += len(new)
        except (KeyboardInterrupt, EOFError):
            pass
