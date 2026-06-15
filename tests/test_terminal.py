# -*- coding: utf-8 -*-
"""terminal.read_window_text 的 COM 容错测试：GetChildren() 抛异常时不崩、返回安全值。"""
import sys, os, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import terminal


class _FakePattern:
    def __init__(self, text):
        self._text = text
        self.DocumentRange = self
    def GetText(self, _n):
        return self._text


class _GoodControl:
    """有文本、有正常子节点的控件。"""
    def __init__(self, text='', children=None):
        self._text = text
        self._children = children or []
    def GetPattern(self, _pid):
        return _FakePattern(self._text) if self._text else None
    def GetChildren(self):
        return self._children


class _BadControl:
    """GetChildren 抛 COM 错误的控件（模拟正在关闭的窗口）。"""
    def GetPattern(self, _pid):
        return None
    def GetChildren(self):
        raise OSError(-2147467259, '未指定的错误')


def _patch_uia(monkeypatch, root_control):
    fake_auto = types.SimpleNamespace(
        PatternId=types.SimpleNamespace(TextPattern=1),
        ControlFromHandle=lambda hwnd: root_control,
    )
    monkeypatch.setattr(terminal, '_uia', lambda: fake_auto)


def test_getchildren_com_error_does_not_crash(monkeypatch):
    """根节点 GetChildren 抛 COM 错误 → 返回 ''，不抛异常。"""
    _patch_uia(monkeypatch, _BadControl())
    assert terminal.read_window_text(123) == ''


def test_bad_child_does_not_block_good_text(monkeypatch):
    """部分子节点 GetChildren 抛错，不应影响已读到的文本。"""
    good = _GoodControl(text='line1\nline2\n')
    bad = _BadControl()
    root = _GoodControl(text='', children=[good, bad])
    _patch_uia(monkeypatch, root)
    out = terminal.read_window_text(123)
    assert 'line1' in out and 'line2' in out


def test_normal_read_still_works(monkeypatch):
    """回归：正常窗口文本照常读取。"""
    root = _GoodControl(text='hello\nworld\n')
    _patch_uia(monkeypatch, root)
    out = terminal.read_window_text(123)
    assert 'hello' in out and 'world' in out
