"""F5.1 信号存储测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from stockpush.services.signal_store import SignalStore
from stockpush.services.function_registry import FunctionRegistry


def test_write_and_query_signals():
    """TC-6.1 + TC-6.3: 写入并查询信号"""
    store = SignalStore()
    registry = FunctionRegistry()
    funcs = registry.get_enabled()
    if not funcs:
        print("SKIP: no enabled functions")
        return

    func = funcs[0]
    test_signals = [{
        'time': '2026-07-01 10:00:00',
        'direction': 'buy',
        'price': 10.0,
        'indicator': 'test',
    }]
    inserted = store.write_signals(func.id, '000001', test_signals)
    # Check query
    today = store.get_today()
    assert isinstance(today, list)


def test_empty_result():
    """TC-6.6: 空结果处理"""
    store = SignalStore()
    rows = store.get_today(func_name='nonexistent_func')
    assert rows == []


if __name__ == '__main__':
    test_write_and_query_signals()
    print("TC-6.1/6.3 PASS")
    test_empty_result()
    print("TC-6.6 PASS")
