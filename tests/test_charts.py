"""charts.py 单元测试：图表生成逻辑验证。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import charts
import state


def test_charts_module_importable():
    """测试charts模块可以导入。"""
    assert hasattr(charts, 'create_trend_chart')
    assert hasattr(charts, 'create_distribution_pie')
    assert hasattr(charts, 'create_window_bar_chart')
    assert hasattr(charts, 'create_hourly_heatmap')


def test_trend_chart_data_preparation(tmp_path, monkeypatch):
    """测试趋势图数据准备逻辑（不真正绘图）。"""
    monkeypatch.setattr(state, '_state_path', lambda: tmp_path / 'state.json')

    # 归档一些测试数据
    state.archive_daily_stats('2026-06-01', {'auto_yes': 10, 'notify': 2, 'error': 0, 'idle': 1})
    state.archive_daily_stats('2026-06-02', {'auto_yes': 15, 'notify': 3, 'error': 1, 'idle': 0})

    # 获取历史数据
    hist = state.get_daily_history(days=7)
    assert len(hist) <= 7
    assert all('auto_yes' in d for d in hist)


def test_distribution_data_preparation(tmp_path, monkeypatch):
    """测试饼图数据准备逻辑。"""
    monkeypatch.setattr(state, '_state_path', lambda: tmp_path / 'state.json')

    # 设置累计统计
    data = {
        'counters': {
            'total': {'auto_yes': 100, 'notify': 20, 'error': 5, 'idle': 10}
        }
    }
    state.save(data)

    # 读取验证
    loaded = state.load()
    total = loaded['counters']['total']
    assert total['auto_yes'] == 100
    assert total['notify'] == 20


def test_window_stats_data_preparation(tmp_path, monkeypatch):
    """测试按窗口统计数据准备。"""
    monkeypatch.setattr(state, '_state_path', lambda: tmp_path / 'state.json')

    # 更新窗口统计
    state.update_window_stats('WT:PowerShell', 'auto_yes')
    state.update_window_stats('WT:PowerShell', 'auto_yes')
    state.update_window_stats('VSCode:terminal', 'notify')

    # 获取统计
    stats = state.get_window_stats()
    assert stats['WT:PowerShell']['auto_yes'] == 2
    assert stats['VSCode:terminal']['notify'] == 1


def test_hourly_stats_data_preparation(tmp_path, monkeypatch):
    """测试按小时统计数据准备。"""
    monkeypatch.setattr(state, '_state_path', lambda: tmp_path / 'state.json')

    # 更新小时统计
    state.update_hourly_stats(9, 'auto_yes')
    state.update_hourly_stats(9, 'auto_yes')
    state.update_hourly_stats(14, 'notify')

    # 获取统计
    stats = state.get_hourly_stats()
    assert stats['09']['auto_yes'] == 2
    assert stats['14']['notify'] == 1
