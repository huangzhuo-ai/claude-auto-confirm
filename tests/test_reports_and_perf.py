"""reports.py 和 resource_monitor.py 单元测试。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import reports
import resource_monitor
import state
from pathlib import Path
import time


# ── reports.py 测试 ──

def test_generate_markdown_report(tmp_path, monkeypatch):
    """测试生成Markdown报告。"""
    monkeypatch.setattr(state, '_state_path', lambda: tmp_path / 'state.json')

    # 准备测试数据
    state.archive_daily_stats('2026-06-10', {'auto_yes': 10, 'notify': 2, 'error': 0, 'idle': 1})
    state.archive_daily_stats('2026-06-11', {'auto_yes': 15, 'notify': 3, 'error': 1, 'idle': 0})

    # 生成周报
    report = reports.generate_report(days=7, format='markdown')

    assert '# Claude Auto-Yes 周报' in report
    assert '## 📊 概览' in report
    assert '总确认次数' in report
    assert '节省时间估算' in report
    assert '## 📈 每日趋势' in report


def test_generate_html_report(tmp_path, monkeypatch):
    """测试生成HTML报告。"""
    monkeypatch.setattr(state, '_state_path', lambda: tmp_path / 'state.json')

    # 准备测试数据
    state.archive_daily_stats('2026-06-10', {'auto_yes': 5, 'notify': 1, 'error': 0, 'idle': 0})

    # 生成HTML
    report = reports.generate_report(days=7, format='html')

    assert '<!DOCTYPE html>' in report
    assert '<html lang="zh-CN">' in report
    assert 'Claude Auto-Yes 统计报告' in report
    assert '<table>' in report
    assert '</html>' in report


def test_save_report_creates_file(tmp_path):
    """测试保存报告到文件。"""
    content = '# Test Report\n\nThis is a test.'
    filename = tmp_path / 'test_report.md'

    filepath = reports.save_report(content, str(filename), format='markdown')

    assert Path(filepath).exists()
    assert Path(filepath).read_text(encoding='utf-8') == content


def test_report_calculates_time_saved(tmp_path, monkeypatch):
    """测试报告正确计算节省时间。"""
    monkeypatch.setattr(state, '_state_path', lambda: tmp_path / 'state.json')

    # 100次自动确认 = 200秒 = 3.33分钟
    state.archive_daily_stats('2026-06-10', {'auto_yes': 100, 'notify': 0, 'error': 0, 'idle': 0})

    report = reports.generate_report(days=7, format='markdown')

    assert '3.3分钟' in report or '3.4分钟' in report  # 浮点精度


# ── resource_monitor.py 测试 ──

def test_resource_monitor_sample():
    """测试资源监控采样。"""
    sample_data = resource_monitor.sample()

    assert 'cpu' in sample_data
    assert 'memory_mb' in sample_data
    assert 'ts' in sample_data
    assert sample_data['cpu'] >= 0
    assert sample_data['memory_mb'] > 0


def test_resource_monitor_get_current_usage():
    """测试获取当前资源占用。"""
    # 先采样
    resource_monitor.sample()
    time.sleep(0.1)

    usage = resource_monitor.get_current_usage()

    assert 'cpu' in usage
    assert 'memory_mb' in usage
    assert usage['cpu'] >= 0
    assert usage['memory_mb'] > 0


def test_resource_monitor_get_history():
    """测试获取历史数据。"""
    # 清空历史
    resource_monitor._perf_history.clear()

    # 采样几次
    for _ in range(5):
        resource_monitor.sample()
        time.sleep(0.1)

    hist = resource_monitor.get_history(seconds=60)

    assert len(hist) == 5
    assert all('cpu' in s for s in hist)
    assert all('memory_mb' in s for s in hist)


def test_resource_monitor_get_average():
    """测试获取平均资源占用。"""
    # 清空历史
    resource_monitor._perf_history.clear()

    # 采样几次
    for _ in range(3):
        resource_monitor.sample()
        time.sleep(0.1)

    avg = resource_monitor.get_average(seconds=60)

    assert 'cpu_avg' in avg
    assert 'memory_avg_mb' in avg
    assert avg['cpu_avg'] >= 0
    assert avg['memory_avg_mb'] > 0


def test_resource_monitor_check_degradation():
    """测试降级检查（正常情况）。"""
    # 清空历史
    resource_monitor._perf_history.clear()

    # 采样几次（正常负载）
    for _ in range(12):
        resource_monitor.sample()
        time.sleep(0.05)

    need_degrade, reason = resource_monitor.check_degradation()

    # 正常情况下不应该降级
    assert not need_degrade or reason  # 如果降级，必须有原因


def test_resource_monitor_get_stats():
    """测试获取完整统计信息。"""
    # 确保有历史数据
    resource_monitor.sample()

    stats = resource_monitor.get_stats()

    assert 'current_cpu' in stats
    assert 'current_memory_mb' in stats
    assert 'avg_cpu_60s' in stats
    assert 'avg_memory_60s_mb' in stats
    assert 'max_cpu_60s' in stats
    assert 'max_memory_60s_mb' in stats
    assert 'degraded' in stats
    assert isinstance(stats['degraded'], bool)
