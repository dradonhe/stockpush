"""F5.1 系统初始化与数据库连接测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from stockpush.pg_connector import PGConnector


def test_db_connection():
    """TC-1.1: PGConnector 可连接"""
    db = PGConnector()
    rows = db.execute_query("SELECT 1 AS ok")
    assert rows[0]['ok'] == 1
    db.close()


def test_core_tables_exist():
    """TC-1.2: 核心表存在"""
    db = PGConnector()
    tables = [
        'tb_stock_pool', 'tb_signal_functions', 'tb_signal_log',
        'tb_raw_30m', 'tb_raw_1d', 'tb_datasource_registry',
        'tb_signal_function_params',
    ]
    for t in tables:
        rows = db.execute_query(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = %s)", (t,)
        )
        assert rows[0]['exists'], f"Table {t} not found"
    db.close()


def test_datasource_registry_has_data():
    """TC-1.3: 数据源注册表有种子数据"""
    db = PGConnector()
    rows = db.execute_query("SELECT COUNT(*) AS cnt FROM tb_datasource_registry")
    assert rows[0]['cnt'] > 0
    db.close()


if __name__ == '__main__':
    test_db_connection()
    print("TC-1.1 PASS")
    test_core_tables_exist()
    print("TC-1.2 PASS")
    test_datasource_registry_has_data()
    print("TC-1.3 PASS")
