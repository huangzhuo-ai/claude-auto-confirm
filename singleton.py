"""
单实例锁：用 Windows 命名 mutex 保证同一时刻只有一个监控进程在跑。

为什么需要它：v0.5.0 加了开机自启后，用户可能开机自动拉起一个实例、之后又
手动双击拉起第二个。两个进程会抢着对同一个确认框发回车（重复发键、竞态）。
命名 mutex 是 Windows 上最轻的进程级互斥：第一个进程 CreateMutex 成功，
后续进程 CreateMutex 仍返回句柄但 GetLastError == ERROR_ALREADY_EXISTS，
据此判断「已有实例」并退出。

mutex 句柄由本模块在进程存活期间持有（_handle），进程退出时由 OS 自动释放，
无需手动清理；崩溃残留也会被 OS 回收，不像文件锁会留下陈旧锁文件。

win32 调用被隔离成 _create_mutex / _already_exists 两个薄函数，便于单测打桩。
"""
import win32event
import win32api
import winerror

# 固定锁名：用 Local\ 前缀按登录会话隔离即可（按用户隔离，无需跨会话独占）。
# 名字必须稳定，保证 exe 启动与 python 启动命中同一把锁。
DEFAULT_MUTEX_NAME = r'Local\claude-auto-confirm-singleton'

# 模块级持有句柄，防止被 GC 回收导致锁提前释放。
_handle = None


def _create_mutex(name: str):
    """创建命名 mutex，返回句柄。抽成独立函数便于测试打桩。"""
    return win32event.CreateMutex(None, False, name)


def _already_exists() -> bool:
    """上一次 Win32 调用是否返回 ERROR_ALREADY_EXISTS。"""
    return win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS


def acquire(name: str = DEFAULT_MUTEX_NAME) -> bool:
    """
    尝试获取单实例锁。

    返回 True  —— 当前进程是唯一实例（拿锁成功），可继续启动。
    返回 False —— 已有实例在运行，调用方应退出。

    若锁机制本身故障（CreateMutex 抛异常），按「无法确认独占」放行（返回 True）：
    宁可极端情况下多开，也不要因锁故障把用户挡在门外。
    """
    global _handle
    try:
        handle = _create_mutex(name)
        if _already_exists():
            return False
        _handle = handle  # 持有句柄，进程存活期间不释放
        return True
    except Exception:
        return True
