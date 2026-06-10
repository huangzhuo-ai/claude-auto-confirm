"""
monitor.process() 状态/事件/策略的单元测试。
不需要真实终端窗口：monkeypatch terminal.read_window_text 注入屏幕文本，
打桩 send_enter / _notify_async，驱动 process() 后断言 _win_state / EVENTS / 去重。
"""
import sys, os, types

# 让 import monitor 能找到上级目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# win11toast 在无 GUI/CI 环境可能无法 import；toast 仅在 _notify_async 用，提前打桩。
sys.modules.setdefault('win11toast', types.SimpleNamespace(toast=lambda *a, **k: None))

import pytest
import monitor
import terminal


# ── 各类屏幕文本样本（贴近真实渲染，底部带 footer）─────────────────
YES_SCREEN = """\
● Bash(ls -la)
  Do you want to proceed?
❯ 1. Yes
  2. No
 Esc to cancel · Enter to select
"""

CHOICE_SCREEN = """\
Which approach would you like?
❯ 1. Use Redis
  2. Use Postgres
  3. Tell Claude what to do differently
 Esc to cancel · Enter to select
"""

ERROR_SCREEN = """\
✗ API Error: Credit balance is too low
Please run /login
 esc to interrupt
"""

IDLE_SCREEN = """\
● Done. Updated 3 files.

>
 ? for shortcuts
"""

RUNNING_SCREEN = """\
● Running tests...
  esc to interrupt
"""

# 有确认框 footer（Esc to cancel），但无 1.Yes / 无 Do you want to / 无编号选项
# → 模拟 Claude 改版后出现的、现有规则识别不了的新式确认框。
UNKNOWN_SCREEN = """\
● Some brand-new confirmation Claude just shipped
  This wording does not match any known pattern
 Esc to cancel · Tab to amend
"""

# 普通屏：完全没有确认框 footer → 应判 None（不误报为 unknown）
NO_FOOTER_SCREEN = """\
● Working on the task
  some output here
  more output
"""


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    """每个测试前清空 monitor 的全局可变状态，并打桩 IO。
    样本目录重定向到 tmp_path，绝不污染真实 misfires/。"""
    monitor._last.clear()
    monitor._idle_since.clear()
    monitor._win_state.clear()
    monitor._policy.clear()
    monitor.EVENTS.clear()
    monitor._misfire_sigs.clear()
    monitor.DRY_RUN = False
    monitor.PAUSED.clear()
    # 默认：发回车总是成功
    monkeypatch.setattr(monitor, 'send_enter', lambda hwnd: 'ok')
    # 通知不真正弹窗
    monkeypatch.setattr(monitor, '_notify_async', lambda *a, **k: None)
    # 样本目录隔离到临时目录
    monkeypatch.setattr(monitor, '_misfires_dir', lambda: tmp_path / 'misfires')
    yield


def _win(hwnd=1, kind='wt', title='test'):
    return {'hwnd': hwnd, 'kind': kind, 'title': title}


def _feed(monkeypatch, text):
    monkeypatch.setattr(terminal, 'read_window_text', lambda hwnd, rows=40: text)


# ── 自动确认 ──────────────────────────────────────────────────
def test_yes_auto_confirms_and_logs(monkeypatch):
    _feed(monkeypatch, YES_SCREEN)
    monitor.process(_win())
    assert monitor._win_state[1]['state'] == 'confirmed'
    assert any(e['action'] == 'auto_yes' for e in monitor.EVENTS)


def test_yes_deduped_second_round(monkeypatch):
    _feed(monkeypatch, YES_SCREEN)
    calls = []
    monkeypatch.setattr(monitor, 'send_enter', lambda hwnd: calls.append(hwnd) or 'ok')
    monitor.process(_win())
    monitor.process(_win())  # 同一确认框，不应再次发键
    assert len(calls) == 1


def test_yes_failed_send_no_dedup(monkeypatch):
    _feed(monkeypatch, YES_SCREEN)
    monkeypatch.setattr(monitor, 'send_enter', lambda hwnd: 'still')
    monitor.process(_win())
    assert monitor._win_state[1]['state'] == 'prompt'
    # 失败不记忆去重 → 下轮还会重试（_last 未记 yes）
    assert monitor._last.get(1) != ('yes', monitor._prompt_signature(YES_SCREEN))


# ── 多选 / 错误 → 通知，不发键 ─────────────────────────────────
def test_choice_notifies_not_confirms(monkeypatch):
    _feed(monkeypatch, CHOICE_SCREEN)
    sent = []
    monkeypatch.setattr(monitor, 'send_enter', lambda hwnd: sent.append(hwnd) or 'ok')
    monitor.process(_win())
    assert not sent
    assert monitor._win_state[1]['state'] == 'prompt'
    assert any(e['action'] == 'notify' for e in monitor.EVENTS)


def test_error_state_and_event(monkeypatch):
    _feed(monkeypatch, ERROR_SCREEN)
    monitor.process(_win())
    assert monitor._win_state[1]['state'] == 'error'
    assert any(e['action'] == 'error' for e in monitor.EVENTS)


# ── 策略 ─────────────────────────────────────────────────────
def test_policy_ignore_skips(monkeypatch):
    _feed(monkeypatch, YES_SCREEN)
    sent = []
    monkeypatch.setattr(monitor, 'send_enter', lambda hwnd: sent.append(hwnd) or 'ok')
    monitor.set_policy(1, 'ignore')
    monitor.process(_win())
    assert not sent
    assert monitor._win_state[1]['state'] == 'ignored'


def test_policy_notify_does_not_confirm(monkeypatch):
    _feed(monkeypatch, YES_SCREEN)
    sent = []
    monkeypatch.setattr(monitor, 'send_enter', lambda hwnd: sent.append(hwnd) or 'ok')
    monitor.set_policy(1, 'notify')
    monitor.process(_win())
    assert not sent  # notify 策略：yes 框不自动回车
    assert monitor._win_state[1]['state'] == 'prompt'


def test_set_policy_auto_clears(monkeypatch):
    monitor.set_policy(1, 'ignore')
    assert monitor.get_policy(1) == 'ignore'
    monitor.set_policy(1, 'auto')
    assert monitor.get_policy(1) == 'auto'
    assert 1 not in monitor._policy


# ── 运行中 / 空闲 ─────────────────────────────────────────────
def test_running_state(monkeypatch):
    _feed(monkeypatch, RUNNING_SCREEN)
    monitor.process(_win())
    assert monitor._win_state[1]['state'] == 'running'


def test_idle_first_seen_no_notify(monkeypatch):
    _feed(monkeypatch, IDLE_SCREEN)
    monitor.process(_win())
    # 首次看到空闲只计时，状态 idle，不通知
    assert monitor._win_state[1]['state'] == 'idle'
    assert not any(e['action'] == 'idle' for e in monitor.EVENTS)


def test_idle_notifies_after_threshold(monkeypatch):
    _feed(monkeypatch, IDLE_SCREEN)
    monitor.process(_win())
    # 把进入空闲的时间往前拨，超过阈值
    monitor._idle_since[1] -= (monitor.WAITING_NOTIFY_SECONDS + 1)
    monitor.process(_win())
    assert monitor._win_state[1]['state'] == 'idle_notified'
    assert any(e['action'] == 'idle' for e in monitor.EVENTS)


# ── 非 Claude 窗口被清理 ───────────────────────────────────────
def test_non_claude_window_removed(monkeypatch):
    monitor._win_state[1] = {'state': 'running'}
    _feed(monkeypatch, "just a normal shell\nC:\\> dir\n")
    monitor.process(_win())
    assert 1 not in monitor._win_state


# ── 未知确认框（v3 检测健壮性核心）────────────────────────────
def test_unknown_detected_when_footer_but_unclassifiable():
    # 有 footer 但无法分类 → unknown，而非静默 None
    assert monitor.detect_prompt(UNKNOWN_SCREEN) == 'unknown'


def test_no_footer_is_none_not_unknown():
    # 没有确认框 footer → None（不能误报成 unknown）
    assert monitor.detect_prompt(NO_FOOTER_SCREEN) is None


def test_known_screens_still_classified():
    # 回归保护：已知屏分类不被 unknown 改动波及
    assert monitor.detect_prompt(YES_SCREEN) == 'yes'
    assert monitor.detect_prompt(CHOICE_SCREEN) == 'choice'
    assert monitor.detect_prompt(ERROR_SCREEN) == 'error'


def test_unknown_notifies_not_confirms_and_saves(monkeypatch):
    _feed(monkeypatch, UNKNOWN_SCREEN)
    sent = []
    monkeypatch.setattr(monitor, 'send_enter', lambda hwnd: sent.append(hwnd) or 'ok')
    monitor.process(_win())
    assert not sent  # 未知框绝不自动回车
    assert monitor._win_state[1]['state'] == 'unknown'
    assert any(e['action'] == 'unknown' for e in monitor.EVENTS)
    # 落盘了一个样本文件
    files = list(monitor._misfires_dir().glob('*.txt'))
    assert len(files) == 1


def test_unknown_sample_deduped(monkeypatch):
    _feed(monkeypatch, UNKNOWN_SCREEN)
    monitor.process(_win())
    monitor.process(_win())  # 同一未知框第二轮
    files = list(monitor._misfires_dir().glob('*.txt'))
    assert len(files) == 1   # 去重：仍只有一个文件


def test_unknown_sample_content(monkeypatch):
    _feed(monkeypatch, UNKNOWN_SCREEN)
    monitor.process(_win(title='my window'))
    files = list(monitor._misfires_dir().glob('*.txt'))
    content = files[0].read_text(encoding='utf-8')
    assert '# kind: wt' in content
    assert '# title: my window' in content
    assert 'brand-new confirmation' in content  # 含原始屏幕文本


def test_unknown_ignored_by_policy(monkeypatch):
    _feed(monkeypatch, UNKNOWN_SCREEN)
    monitor.set_policy(1, 'ignore')
    monitor.process(_win())
    # ignore 策略下完全跳过，不落盘
    assert monitor._win_state[1]['state'] == 'ignored'
    d = monitor._misfires_dir()
    assert not d.exists() or not list(d.glob('*.txt'))

