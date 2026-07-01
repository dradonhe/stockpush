"""
F5.1 系统初始化服务

仅初始化 F5.1 运行所需的核心表，不涉及本地测试模块的表。
部署到 VPS 后运行一次即可完成数据库准备。

使用方式:
    python -m stockpush.services.sys_init          # 直接执行
    python stockpush/services/sys_init.py          # 脚本执行
"""

import sys
import logging
from pathlib import Path
from typing import Dict, Any, List

# 项目根目录加入 sys.path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# F5.1 所需表结构（仅包含 F5.1 运行时用到的表）
# ---------------------------------------------------------------------------
F51_TABLE_SQLS: List[str] = [
    # 1. tb_sys_cfg — 系统配置（F5.1 config.yaml 之外的运行期配置）
    """
    CREATE TABLE IF NOT EXISTS tb_sys_cfg (
        id          SERIAL PRIMARY KEY,
        key         VARCHAR(100) NOT NULL UNIQUE,
        value       TEXT NOT NULL,
        description VARCHAR(200),
        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # 2. tb_stock_codes — 股票代码主表
    """
    CREATE TABLE IF NOT EXISTS tb_stock_codes (
        symbol     VARCHAR(10) PRIMARY KEY,
        name       VARCHAR(50),
        market     VARCHAR(10),
        list_date  DATE,
        status     VARCHAR(10) DEFAULT 'active',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # 3. tb_fund_codes — 基金代码主表
    """
    CREATE TABLE IF NOT EXISTS tb_fund_codes (
        symbol     VARCHAR(10) PRIMARY KEY,
        name       VARCHAR(100),
        type       VARCHAR(20),
        list_date  DATE,
        status     VARCHAR(10) DEFAULT 'active',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # 4. tb_stock_pool — 自选股池
    """
    CREATE TABLE IF NOT EXISTS tb_stock_pool (
        id         SERIAL PRIMARY KEY,
        symbol     VARCHAR(10) NOT NULL,
        name       VARCHAR(50),
        type       VARCHAR(10),
        market     VARCHAR(10),
        group_name VARCHAR(50),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, group_name)
    )
    """,

    # 5. tb_calendar — 交易日历
    """
    CREATE TABLE IF NOT EXISTS tb_calendar (
        date         DATE PRIMARY KEY,
        is_trading_day BOOLEAN NOT NULL,
        year         INTEGER,
        month        INTEGER,
        weekday      INTEGER
    )
    """,

    # 6~9. K 线表（1m / 5m / 30m / 1d）
    """
    CREATE TABLE IF NOT EXISTS tb_raw_1m (
        ts      TIMESTAMP NOT NULL,
        symbol  VARCHAR(10) NOT NULL,
        open    DECIMAL(10,3) NOT NULL,
        high    DECIMAL(10,3) NOT NULL,
        low     DECIMAL(10,3) NOT NULL,
        close   DECIMAL(10,3) NOT NULL,
        vol     BIGINT NOT NULL,
        amount  DECIMAL(20,2) NOT NULL,
        PRIMARY KEY (ts, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tb_raw_5m (
        ts      TIMESTAMP NOT NULL,
        symbol  VARCHAR(10) NOT NULL,
        open    DECIMAL(10,3) NOT NULL,
        high    DECIMAL(10,3) NOT NULL,
        low     DECIMAL(10,3) NOT NULL,
        close   DECIMAL(10,3) NOT NULL,
        vol     BIGINT NOT NULL,
        amount  DECIMAL(20,2) NOT NULL,
        PRIMARY KEY (ts, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tb_raw_30m (
        ts      TIMESTAMP NOT NULL,
        symbol  VARCHAR(10) NOT NULL,
        open    DECIMAL(10,3) NOT NULL,
        high    DECIMAL(10,3) NOT NULL,
        low     DECIMAL(10,3) NOT NULL,
        close   DECIMAL(10,3) NOT NULL,
        vol     BIGINT NOT NULL,
        amount  DECIMAL(20,2) NOT NULL,
        PRIMARY KEY (ts, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tb_raw_1d (
        ts      TIMESTAMP NOT NULL,
        symbol  VARCHAR(10) NOT NULL,
        open    DECIMAL(10,3) NOT NULL,
        high    DECIMAL(10,3) NOT NULL,
        low     DECIMAL(10,3) NOT NULL,
        close   DECIMAL(10,3) NOT NULL,
        vol     BIGINT NOT NULL,
        amount  DECIMAL(20,2) NOT NULL,
        PRIMARY KEY (ts, symbol)
    )
    """,

    # 10. tb_signal_functions — 自定义函数注册表
    """
    CREATE TABLE IF NOT EXISTS tb_signal_functions (
        id            SERIAL PRIMARY KEY,
        name          VARCHAR(100) NOT NULL UNIQUE,
        display_name  VARCHAR(200),
        module_path   VARCHAR(500) NOT NULL,
        func_name     VARCHAR(100) NOT NULL,
        period        VARCHAR(10),
        param_set_id  INTEGER DEFAULT 0,
        enabled       BOOLEAN DEFAULT TRUE,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # 11. tb_signal_function_params — 函数参数集
    """
    CREATE TABLE IF NOT EXISTS tb_signal_function_params (
        func_id     INTEGER NOT NULL REFERENCES tb_signal_functions(id) ON DELETE CASCADE,
        set_id      INTEGER DEFAULT 0,
        param_key   VARCHAR(100) NOT NULL,
        param_value TEXT,
        PRIMARY KEY (func_id, set_id, param_key)
    )
    """,

    # 12. tb_signal_log — 信号存档
    """
    CREATE TABLE IF NOT EXISTS tb_signal_log (
        id           SERIAL PRIMARY KEY,
        func_id      INTEGER NOT NULL REFERENCES tb_signal_functions(id),
        direction    VARCHAR(10) NOT NULL,
        symbol       VARCHAR(10) NOT NULL,
        signal_time  TIMESTAMP NOT NULL,
        price        DOUBLE PRECISION,
        indicator    VARCHAR(100),
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_signal_log_symbol ON tb_signal_log(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_signal_log_time ON tb_signal_log(signal_time)",

    # 13. tb_download_request_log — 下载请求审计日志（由 download_logger.py 按需创建，此处也预建）
    """
    CREATE SEQUENCE IF NOT EXISTS seq_tb_download_request_log_id START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS tb_download_request_log (
        id           BIGINT PRIMARY KEY DEFAULT nextval('seq_tb_download_request_log_id'),
        request_time TEXT    NOT NULL,
        symbol       TEXT    NOT NULL,
        period       TEXT    NOT NULL,
        open         DOUBLE PRECISION,
        high         DOUBLE PRECISION,
        low          DOUBLE PRECISION,
        close        DOUBLE PRECISION,
        volume       DOUBLE PRECISION,
        amount       DOUBLE PRECISION,
        preclose     DOUBLE PRECISION,
        api_bar_time TEXT,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

# F5.1 完全无关、可在 VPS 上安全删除的表（仅供参考，不自动执行）
UNRELATED_TABLES = [
    "tb_alert_log",          # 报警日志（Web UI 功能）
    "tb_bt_results",         # F5.6 回测结果
    "tb_compare_history",    # F6.1 数据比对历史
    "tb_compare_log",        # F6.1 数据比对日志
    "tb_custom_func_def",    # F4.0 自定义函数定义
    "tb_datasource_registry",# F2.1 数据源注册表
    "tb_download_history",   # F3.1 下载历史
    "tb_f61_operation_log",  # F6.1 操作日志
    "tb_func_map",           # F4.2 函数映射
    "tb_logic_cfg",          # F4.6 逻辑配置（矩阵规则）
    "tb_logic_var_cfg",      # F4.6 逻辑变量配置
    "tb_manual_pts",         # F4.6 手动标注点
    "tb_matrix_pts",         # F4.1 矩阵标注点
    "tb_mc_scan_job",        # F6.2 MC 策略扫描任务
    "tb_rt_test_run",        # F3.2 实时测试运行记录
    "tb_src_status",         # F2.1 数据源状态
    "tb_zigzag_pts",         # F3.6 高低点标注
]


# ---------------------------------------------------------------------------
# F51SysInit
# ---------------------------------------------------------------------------
class F51SysInit:
    """F5.1 专用数据库初始化器

    只创建 F5.1 运行所需的 13 张核心表，不涉及其他模块。
    """

    def __init__(self):
        self._db = None

    def _get_db(self):
        if self._db is None:
            from stockpush.pg_connector import PGConnector
            self._db = PGConnector()
        return self._db

    def check_connection(self) -> bool:
        """验证 PostgreSQL 连接"""
        try:
            db = self._get_db()
            db.execute_query("SELECT 1")
            logger.info("[F51-SysInit] PostgreSQL 连接成功")
            return True
        except Exception as e:
            logger.error("[F51-SysInit] PostgreSQL 连接失败: %s", e)
            return False

    def init_tables(self) -> Dict[str, Any]:
        """创建 F5.1 所需全部表，返回执行结果"""
        db = self._get_db()
        results: Dict[str, Any] = {"ok": [], "failed": []}

        for sql in F51_TABLE_SQLS:
            sql_short = sql.strip().split("\n")[0][:60]
            try:
                db.execute_update(sql)
                results["ok"].append(sql_short)
            except Exception as e:
                logger.error("[F51-SysInit] 执行失败: %s\n  SQL: %s", e, sql_short)
                results["failed"].append({"sql": sql_short, "error": str(e)})

        ok_cnt = len(results["ok"])
        fail_cnt = len(results["failed"])
        logger.info("[F51-SysInit] 表初始化完成: %d 成功, %d 失败", ok_cnt, fail_cnt)
        return results

    def list_unrelated_tables(self) -> List[str]:
        """列出与 F5.1 无关、可安全删除的表（仅参考）"""
        return list(UNRELATED_TABLES)

    def drop_unrelated_tables(self, confirm: bool = False) -> List[str]:
        """删除与 F5.1 无关的表（需显式 confirm=True）"""
        if not confirm:
            logger.warning("[F51-SysInit] drop_unrelated_tables 需要 confirm=True，已跳过")
            return []

        db = self._get_db()
        dropped = []
        for table in UNRELATED_TABLES:
            try:
                db.execute_update(f"DROP TABLE IF EXISTS {table} CASCADE")
                dropped.append(table)
                logger.info("[F51-SysInit] 已删除: %s", table)
            except Exception as e:
                logger.warning("[F51-SysInit] 删除失败 %s: %s", table, e)
        return dropped

    def close(self):
        if self._db:
            self._db.close()
            self._db = None


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    init = F51SysInit()

    print("=" * 50)
    print("  F5.1 数据库初始化")
    print("=" * 50)

    if not init.check_connection():
        print("PostgreSQL 连接失败，请检查配置")
        sys.exit(1)

    result = init.init_tables()
    print(f"\n完成: {len(result['ok'])} 条 SQL 成功, {len(result['failed'])} 条失败")

    if result["failed"]:
        print("\n失败详情:")
        for f in result["failed"]:
            print(f"  - {f['sql']}: {f['error']}")

    print("\n与 F5.1 无关的表（可在 VPS 上手动清理）:")
    for t in init.list_unrelated_tables():
        print(f"  DROP TABLE IF EXISTS {t} CASCADE;")

    init.close()


if __name__ == "__main__":
    main()

