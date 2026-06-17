"""资源占用监控模块：监控自身CPU/内存占用，异常时降级运行。

功能：
- 监控自身进程的CPU和内存占用
- 记录最近60个采样点（1分钟历史，采样间隔1秒）
- CPU持续高于阈值时自动增加扫描间隔
- 内存超过阈值时清理事件缓冲
- 提供性能统计数据供UI显示
"""
import psutil
import os
from collections import deque
import time
import threading


# 性能数据：存储最近60秒的采样（CPU%, Memory MB）
_perf_history = deque(maxlen=60)
_perf_lock = threading.Lock()

# 当前进程
_process = psutil.Process(os.getpid())

# 阈值配置
CPU_THRESHOLD = 10.0  # CPU使用率阈值（%）
MEMORY_THRESHOLD_MB = 200  # 内存阈值（MB）

# 降级状态
_degraded = False
_degraded_reason = ''


def sample():
    """采样当前资源占用，存入历史记录。

    应该由主循环定期调用（建议1秒间隔）。

    Returns:
        dict: 当前采样数据 {'cpu': float, 'memory_mb': float, 'ts': float}
    """
    try:
        # CPU使用率（%）- interval=0.1表示采样0.1秒计算平均值
        cpu_percent = _process.cpu_percent(interval=0.1)

        # 内存占用（MB）
        mem_info = _process.memory_info()
        memory_mb = mem_info.rss / 1024 / 1024

        sample_data = {
            'cpu': cpu_percent,
            'memory_mb': memory_mb,
            'ts': time.time(),
        }

        with _perf_lock:
            _perf_history.append(sample_data)

        return sample_data

    except Exception:
        return {'cpu': 0.0, 'memory_mb': 0.0, 'ts': time.time()}


def get_current_usage():
    """获取当前资源占用。

    Returns:
        dict: {'cpu': float, 'memory_mb': float}
    """
    with _perf_lock:
        if not _perf_history:
            return {'cpu': 0.0, 'memory_mb': 0.0}
        return {
            'cpu': _perf_history[-1]['cpu'],
            'memory_mb': _perf_history[-1]['memory_mb'],
        }


def get_history(seconds=60):
    """获取历史采样数据。

    Args:
        seconds: 获取最近N秒的数据（最多60秒）

    Returns:
        list[dict]: 采样数据列表
    """
    with _perf_lock:
        if seconds >= 60:
            return list(_perf_history)
        else:
            cutoff_ts = time.time() - seconds
            return [s for s in _perf_history if s['ts'] >= cutoff_ts]


def get_average(seconds=60):
    """获取平均资源占用。

    Args:
        seconds: 统计最近N秒（最多60秒）

    Returns:
        dict: {'cpu_avg': float, 'memory_avg_mb': float}
    """
    hist = get_history(seconds)

    if not hist:
        return {'cpu_avg': 0.0, 'memory_avg_mb': 0.0}

    cpu_avg = sum(s['cpu'] for s in hist) / len(hist)
    mem_avg = sum(s['memory_mb'] for s in hist) / len(hist)

    return {'cpu_avg': cpu_avg, 'memory_avg_mb': mem_avg}


def check_degradation():
    """检查是否需要降级运行。

    检查逻辑：
    - CPU持续10秒高于阈值 → 降级
    - 内存超过阈值 → 降级

    Returns:
        tuple: (need_degrade: bool, reason: str)
    """
    global _degraded, _degraded_reason

    current = get_current_usage()

    # 检查内存
    if current['memory_mb'] > MEMORY_THRESHOLD_MB:
        _degraded = True
        _degraded_reason = f'内存占用过高({current["memory_mb"]:.1f}MB > {MEMORY_THRESHOLD_MB}MB)'
        return True, _degraded_reason

    # 检查CPU（需要持续高负载）
    recent = get_history(seconds=10)
    if len(recent) >= 10:
        cpu_high_count = sum(1 for s in recent if s['cpu'] > CPU_THRESHOLD)
        if cpu_high_count >= 8:  # 10秒内有8秒超过阈值
            _degraded = True
            _degraded_reason = f'CPU持续高负载(>{CPU_THRESHOLD}%)'
            return True, _degraded_reason

    # 正常状态
    if _degraded:
        _degraded = False
        _degraded_reason = ''

    return False, ''


def is_degraded():
    """是否处于降级状态。

    Returns:
        tuple: (degraded: bool, reason: str)
    """
    return _degraded, _degraded_reason


def get_stats():
    """获取完整的性能统计数据（供UI显示）。

    Returns:
        dict: 包含当前、平均、最大值等统计信息
    """
    current = get_current_usage()
    avg = get_average(seconds=60)
    hist = get_history(seconds=60)

    max_cpu = max((s['cpu'] for s in hist), default=0.0)
    max_mem = max((s['memory_mb'] for s in hist), default=0.0)

    return {
        'current_cpu': current['cpu'],
        'current_memory_mb': current['memory_mb'],
        'avg_cpu_60s': avg['cpu_avg'],
        'avg_memory_60s_mb': avg['memory_avg_mb'],
        'max_cpu_60s': max_cpu,
        'max_memory_60s_mb': max_mem,
        'history_count': len(hist),
        'degraded': _degraded,
        'degraded_reason': _degraded_reason,
    }


def apply_mitigation():
    """应用缓解措施（由monitor.py在检测到降级时调用）。

    缓解措施：
    - 清理事件缓冲（只保留最近1000条）
    - 返回建议的扫描间隔增量
    """
    # 清理事件缓冲
    import monitor
    if len(monitor.EVENTS) > 1000:
        # 只保留最近1000条
        monitor.EVENTS = monitor.EVENTS[-1000:]

    # 建议增加扫描间隔0.5秒
    return 0.5
