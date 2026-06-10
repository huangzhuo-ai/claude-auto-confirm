"""
singleton.acquire() 的单元测试。
不依赖真实 Windows mutex：monkeypatch _create_mutex / _last_error_already_exists
注入两种结果，验证「首个实例拿锁成功 / 后续实例被拒」两条分支，
并确认句柄被模块级持有（防 GC 释放锁）。
"""
import sys
import os
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh():
    """每个用例拿一份干净的 singleton 模块，避免模块级句柄跨用例污染。"""
    import singleton
    importlib.reload(singleton)
    return singleton


def test_first_instance_acquires(monkeypatch):
    s = _fresh()
    # 首个实例：CreateMutex 成功，GetLastError 不是 ALREADY_EXISTS
    monkeypatch.setattr(s, '_create_mutex', lambda name: 'HANDLE-1')
    monkeypatch.setattr(s, '_already_exists', lambda: False)
    assert s.acquire('test-mutex') is True
    # 句柄被持有，便于进程存活期间锁不被释放
    assert s._handle == 'HANDLE-1'


def test_second_instance_rejected(monkeypatch):
    s = _fresh()
    # 第二个实例：CreateMutex 仍返回句柄，但 GetLastError == ALREADY_EXISTS
    monkeypatch.setattr(s, '_create_mutex', lambda name: 'HANDLE-2')
    monkeypatch.setattr(s, '_already_exists', lambda: True)
    assert s.acquire('test-mutex') is False


def test_create_failure_treated_as_not_singleton(monkeypatch):
    """CreateMutex 抛异常（极端情况）：不应崩溃，按「无法确认独占」放行，
    宁可多开也不要因为锁机制本身故障而阻止用户启动。"""
    s = _fresh()
    def _boom(name):
        raise OSError('mutex create failed')
    monkeypatch.setattr(s, '_create_mutex', _boom)
    assert s.acquire('test-mutex') is True


def test_default_name_is_stable():
    s = _fresh()
    # 默认锁名应是固定常量，保证不同启动方式（exe/python）命中同一把锁
    assert isinstance(s.DEFAULT_MUTEX_NAME, str)
    assert s.DEFAULT_MUTEX_NAME  # 非空
