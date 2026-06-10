"""
autostart 的单元测试。
不碰真实文件系统：monkeypatch 三个原子操作桩为内存 dict 替身，
驱动 enable/disable/is_enabled 并断言行为；另测 frozen/dev 目标构造。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autostart


def _fake_store(monkeypatch):
    """用内存 dict 替换三个原子操作桩，返回该 dict 供断言。"""
    store = {}
    monkeypatch.setattr(autostart, '_read_value',
                        lambda: store.get('v'))
    monkeypatch.setattr(autostart, '_write_value',
                        lambda cmd: store.__setitem__('v', cmd or 'lnk'))
    monkeypatch.setattr(autostart, '_delete_value',
                        lambda: store.pop('v', None))
    return store


def test_disabled_by_default(monkeypatch):
    _fake_store(monkeypatch)
    assert autostart.is_enabled() is False


def test_enable_then_is_enabled(monkeypatch):
    store = _fake_store(monkeypatch)
    autostart.enable()
    assert autostart.is_enabled() is True
    assert store['v']


def test_disable_removes(monkeypatch):
    _fake_store(monkeypatch)
    autostart.enable()
    autostart.disable()
    assert autostart.is_enabled() is False


def test_enable_returns_false_when_value_not_persisted(monkeypatch):
    """_write_value 不留值时（模拟创建 .lnk 失败），enable() 返回 False。"""
    store = {}
    monkeypatch.setattr(autostart, '_read_value', lambda: store.get('v'))
    monkeypatch.setattr(autostart, '_write_value', lambda cmd: None)
    monkeypatch.setattr(autostart, '_delete_value', lambda: store.pop('v', None))
    assert autostart.enable() is False
    assert autostart.is_enabled() is False


def test_exe_target_frozen(monkeypatch):
    """frozen 时目标即 exe，arguments 为空。"""
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\foo\claude-auto-confirm.exe')
    target, args = autostart._exe_target()
    assert target == r'C:\foo\claude-auto-confirm.exe'
    assert args == ''


def test_exe_target_dev(monkeypatch):
    """dev 模式目标为 pythonw，arguments 含 monitor.py。"""
    import pathlib
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\py\python.exe')
    monkeypatch.setattr(pathlib.Path, 'exists', lambda self: True)
    target, args = autostart._exe_target()
    assert 'pythonw' in target.lower()
    assert 'monitor.py' in args
