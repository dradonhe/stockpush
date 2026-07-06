"""F5.1 函数注册表测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from stockpush.services.function_registry import FunctionRegistry


def test_get_all_functions():
    """TC-4.1: 获取已注册函数"""
    registry = FunctionRegistry()
    funcs = registry.get_all()
    assert len(funcs) > 0
    for f in funcs:
        assert f.name
        assert f.module_path


def test_get_enabled_functions():
    """TC-4.2: 获取启用函数"""
    registry = FunctionRegistry()
    funcs = registry.get_enabled()
    for f in funcs:
        assert f.enabled


def test_get_by_name():
    """TC-4.3: 按名称查询"""
    registry = FunctionRegistry()
    all_funcs = registry.get_all()
    if all_funcs:
        f = registry.get_by_name(all_funcs[0].name)
        assert f is not None
        assert f.name == all_funcs[0].name


def test_get_params():
    """TC-4.5: 获取函数参数"""
    registry = FunctionRegistry()
    funcs = registry.get_enabled()
    for f in funcs:
        params = registry.get_params(f.name, f.param_set_id)
        assert isinstance(params, dict)


def test_validate():
    """TC-4.9: 函数验证"""
    registry = FunctionRegistry()
    funcs = registry.get_all()
    for f in funcs:
        result = registry.validate(f.module_path, f.func_name)
        assert 'valid' in result


if __name__ == '__main__':
    test_get_all_functions()
    print("TC-4.1 PASS")
    test_get_enabled_functions()
    print("TC-4.2 PASS")
    test_get_by_name()
    print("TC-4.3 PASS")
    test_get_params()
    print("TC-4.5 PASS")
    test_validate()
    print("TC-4.9 PASS")
