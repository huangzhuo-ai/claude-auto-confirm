"""静默时段判断逻辑测试。"""
from datetime import datetime
from unittest.mock import patch

import config
import monitor


def _t(hhmm):
    h, m = map(int, hhmm.split(':'))
    return datetime(2026, 6, 15, h, m).time()


def _cfg(enabled=True, start='22:00', end='08:00'):
    return {**config.DEFAULTS, 'quiet_hours_enabled': enabled,
            'quiet_hours_start': start, 'quiet_hours_end': end}


def test_overnight_window():
    """22:00-08:00 跨日静默时段。"""
    with patch.object(config, 'load', _cfg):
        assert monitor.is_quiet_hours(_t('23:30')) is True
        assert monitor.is_quiet_hours(_t('02:00')) is True
        assert monitor.is_quiet_hours(_t('07:59')) is True
        assert monitor.is_quiet_hours(_t('22:00')) is True   # 开始边界含
        assert monitor.is_quiet_hours(_t('08:00')) is False  # 结束边界不含
        assert monitor.is_quiet_hours(_t('12:00')) is False
        assert monitor.is_quiet_hours(_t('21:59')) is False


def test_same_day_window():
    """12:00-14:00 同日静默时段。"""
    with patch.object(config, 'load', lambda: _cfg(start='12:00', end='14:00')):
        assert monitor.is_quiet_hours(_t('13:00')) is True
        assert monitor.is_quiet_hours(_t('12:00')) is True
        assert monitor.is_quiet_hours(_t('14:00')) is False
        assert monitor.is_quiet_hours(_t('11:59')) is False
        assert monitor.is_quiet_hours(_t('23:00')) is False


def test_disabled_always_false():
    with patch.object(config, 'load', lambda: _cfg(enabled=False)):
        assert monitor.is_quiet_hours(_t('02:00')) is False


def test_bad_time_format_is_safe():
    """格式错误时应安全返回 False，不抛异常。"""
    with patch.object(config, 'load', lambda: _cfg(start='oops', end='08:00')):
        assert monitor.is_quiet_hours(_t('02:00')) is False
