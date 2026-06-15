"""state.py 持久化模块测试：load/save 往返、缺失/损坏文件的容错。"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import state


def test_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / 'state.json'
    monkeypatch.setattr(state, '_state_path', lambda: p)
    data = {'counters': {'total': {'auto_yes': 3}}, 'policies': {'foo': 'notify'}}
    assert state.save(data) is True
    assert state.load() == data


def test_load_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(state, '_state_path', lambda: tmp_path / 'nope.json')
    assert state.load() == {}


def test_load_corrupt_returns_empty(tmp_path, monkeypatch):
    p = tmp_path / 'state.json'
    p.write_text('{not valid json', encoding='utf-8')
    monkeypatch.setattr(state, '_state_path', lambda: p)
    assert state.load() == {}


def test_save_unwritable_is_safe(tmp_path, monkeypatch):
    # 指向一个不可写路径（父目录不存在）→ 应安全返回 False，不抛异常
    monkeypatch.setattr(state, '_state_path',
                        lambda: tmp_path / 'no' / 'such' / 'dir' / 'state.json')
    assert state.save({'a': 1}) is False


# ── 统计计数器持久化（monitor 侧）────────────────────────────────
def test_counters_persist_and_restore(tmp_path, monkeypatch):
    import time
    import types
    sys.modules.setdefault('win11toast', types.SimpleNamespace(toast=lambda *a, **k: None))
    import monitor

    p = tmp_path / 'state.json'
    monkeypatch.setattr(state, '_state_path', lambda: p)
    today = time.strftime('%Y-%m-%d')

    # 写入计数并存盘
    monitor.COUNTERS['total'] = {'auto_yes': 7, 'notify': 2, 'error': 1, 'idle': 0}
    monitor.COUNTERS['today'] = {'auto_yes': 4, 'notify': 1, 'error': 0,
                                 'idle': 0, 'date': today}
    monitor.save_counters()

    # 清零后从盘恢复
    monitor.COUNTERS['total'] = {'auto_yes': 0, 'notify': 0, 'error': 0, 'idle': 0}
    monitor.COUNTERS['today'] = {'auto_yes': 0, 'notify': 0, 'error': 0,
                                 'idle': 0, 'date': today}
    monitor.load_counters()
    assert monitor.COUNTERS['total']['auto_yes'] == 7
    assert monitor.COUNTERS['today']['auto_yes'] == 4


def test_restore_resets_today_if_stale(tmp_path, monkeypatch):
    """恢复时若存档的 today 不是今天，今日清零但累计保留。"""
    import types
    sys.modules.setdefault('win11toast', types.SimpleNamespace(toast=lambda *a, **k: None))
    import monitor

    p = tmp_path / 'state.json'
    monkeypatch.setattr(state, '_state_path', lambda: p)
    # 存一份「昨天」的数据
    state.save({'counters': {
        'total': {'auto_yes': 10, 'notify': 5, 'error': 2, 'idle': 1},
        'today': {'auto_yes': 6, 'notify': 3, 'error': 1, 'idle': 0,
                  'date': '2000-01-01'},
    }})
    monitor.load_counters()
    # 累计保留
    assert monitor.COUNTERS['total']['auto_yes'] == 10
    # 今日因日期过期被清零
    assert monitor.COUNTERS['today']['auto_yes'] == 0
    assert monitor.COUNTERS['today']['date'] != '2000-01-01'


# ── 单窗口策略持久化（按标题）─────────────────────────────────────
def test_policy_persists_by_title(tmp_path, monkeypatch):
    import types
    sys.modules.setdefault('win11toast', types.SimpleNamespace(toast=lambda *a, **k: None))
    import monitor

    p = tmp_path / 'state.json'
    monkeypatch.setattr(state, '_state_path', lambda: p)
    monitor._policy.clear()
    monitor._persisted_policies.clear()

    # 给某标题的窗口设 ignore（显式传 title）
    monitor.set_policy(123, 'ignore', title='claude — proj')
    # 存盘后清空内存，再加载
    monitor._persisted_policies.clear()
    monitor.load_policies()
    assert monitor._persisted_policies.get('claude — proj') == 'ignore'


def test_policy_auto_removes_persisted(tmp_path, monkeypatch):
    import types
    sys.modules.setdefault('win11toast', types.SimpleNamespace(toast=lambda *a, **k: None))
    import monitor

    p = tmp_path / 'state.json'
    monkeypatch.setattr(state, '_state_path', lambda: p)
    monitor._policy.clear()
    monitor._persisted_policies.clear()

    monitor.set_policy(1, 'notify', title='win-A')
    assert monitor._persisted_policies.get('win-A') == 'notify'
    # 改回 auto 应从持久化里移除
    monitor.set_policy(1, 'auto', title='win-A')
    assert 'win-A' not in monitor._persisted_policies
    monitor._persisted_policies.clear()
    monitor.load_policies()
    assert 'win-A' not in monitor._persisted_policies


# ── 持久化开关（persist_policies）─────────────────────────────────
def test_set_policy_no_persist_when_disabled(tmp_path, monkeypatch):
    """开关关闭时：set_policy 仍设会话内策略，但不写盘。"""
    import types
    import config
    sys.modules.setdefault('win11toast', types.SimpleNamespace(toast=lambda *a, **k: None))
    import monitor

    p = tmp_path / 'state.json'
    monkeypatch.setattr(state, '_state_path', lambda: p)
    monkeypatch.setattr(config, 'load',
                        lambda: {**config.DEFAULTS, 'persist_policies': False})
    monitor._policy.clear()
    monitor._persisted_policies.clear()

    monitor.set_policy(5, 'ignore', title='win-B')
    # 会话内仍生效
    assert monitor.resolve_policy(5, 'win-B') == 'ignore'
    # 但不写持久化
    assert 'win-B' not in monitor._persisted_policies
    assert not p.exists() or 'policies' not in state.load()


def test_load_policies_skipped_when_disabled(tmp_path, monkeypatch):
    """开关关闭时：load_policies 不读盘，已存档的策略不恢复。"""
    import types
    import config
    sys.modules.setdefault('win11toast', types.SimpleNamespace(toast=lambda *a, **k: None))
    import monitor

    p = tmp_path / 'state.json'
    monkeypatch.setattr(state, '_state_path', lambda: p)
    # 盘上有存档
    state.save({'policies': {'win-C': 'ignore'}})
    monkeypatch.setattr(config, 'load',
                        lambda: {**config.DEFAULTS, 'persist_policies': False})
    monitor._persisted_policies.clear()

    monitor.load_policies()
    assert 'win-C' not in monitor._persisted_policies


# ── 声音提示开关（sound_enabled）─────────────────────────────────
def test_sound_played_when_enabled(monkeypatch):
    import types
    import config
    sys.modules.setdefault('win11toast', types.SimpleNamespace(toast=lambda *a, **k: None))
    import monitor

    monkeypatch.setattr(config, 'load',
                        lambda: {**config.DEFAULTS, 'sound_enabled': True})
    calls = []
    monkeypatch.setattr(monitor, '_winsound_beep', lambda: calls.append(1))
    monitor._play_sound()
    assert calls == [1]


def test_sound_silent_when_disabled(monkeypatch):
    import types
    import config
    sys.modules.setdefault('win11toast', types.SimpleNamespace(toast=lambda *a, **k: None))
    import monitor

    monkeypatch.setattr(config, 'load',
                        lambda: {**config.DEFAULTS, 'sound_enabled': False})
    calls = []
    monkeypatch.setattr(monitor, '_winsound_beep', lambda: calls.append(1))
    monitor._play_sound()
    assert calls == []




