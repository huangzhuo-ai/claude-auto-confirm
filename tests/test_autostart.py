"""
autostart 的单元测试。
不碰真实注册表：monkeypatch 三个 registry 读写桩为内存 dict 替身，
驱动 enable/disable/is_enabled 并断言写入的命令；另测 frozen/dev 命令构造。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autostart


def _fake_store(monkeypatch):
    """用内存 dict 替换三个注册表桩，返回该 dict 供断言。"""
    store = {}
    monkeypatch.setattr(autostart, '_read_value',
                        lambda: store.get('v'))
    monkeypatch.setattr(autostart, '_write_value',
                        lambda cmd: store.__setitem__('v', cmd))
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
    assert store['v']  # 写入了非空命令


def test_disable_removes(monkeypatch):
    _fake_store(monkeypatch)
    autostart.enable()
    autostart.disable()
    assert autostart.is_enabled() is False


def test_enable_writes_run_command(monkeypatch):
    store = _fake_store(monkeypatch)
    monkeypatch.setattr(autostart, '_run_command', lambda: '"X:\\app.exe"')
    autostart.enable()
    assert store['v'] == '"X:\\app.exe"'


def test_run_command_frozen(monkeypatch):
    """frozen 时命令即 exe 路径（带引号）。"""
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\foo\claude-auto-confirm.exe')
    cmd = autostart._run_command()
    assert cmd == r'"C:\foo\claude-auto-confirm.exe"'


def test_run_command_dev(monkeypatch):
    """dev 模式命令含 pythonw 与脚本入口，且都加引号。"""
    import pathlib
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\py\python.exe')
    # 真机上 pythonw.exe 必与 python.exe 同目录；测试里打桩为存在
    monkeypatch.setattr(pathlib.Path, 'exists', lambda self: True)
    cmd = autostart._run_command()
    assert 'pythonw' in cmd.lower()
    assert 'monitor.py' in cmd
    assert cmd.count('"') == 4  # 两段路径各一对引号
