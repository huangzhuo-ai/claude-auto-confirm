"""
开机自启动：在当前用户的「启动」文件夹放一个 .lnk 快捷方式实现。

为何改用启动文件夹而非 HKCU\\...\\Run 注册表项：
  * 部分安全软件（火绒、360、Defender ASR、企业 EDR）会延迟清除 Run 键里的
    陌生值（写入当场成功、约数秒后被抹），导致「勾了没生效」。
  * 启动文件夹快捷方式不受上述管控影响（实测 11 秒仍存活）。
  * 同样不需要管理员权限（shell:startup 是当前用户目录）。
  * 卸载即删 .lnk，干净。

命令目标兼容两种运行形态：
  * frozen（PyInstaller exe）：快捷方式指向 exe；
  * dev（脚本）：指向 pythonw.exe，Arguments 传 monitor.py 路径。
"""
import os
import sys
import pathlib
import subprocess

from applog import log

_LNK_NAME = 'ClaudeAutoConfirm.lnk'


def _startup_dir() -> pathlib.Path:
    return pathlib.Path(os.environ['APPDATA']) / \
        'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'


def _lnk_path() -> pathlib.Path:
    return _startup_dir() / _LNK_NAME


def _exe_target() -> tuple[str, str]:
    """返回 (target, arguments)。frozen → (exe, ''); dev → (pythonw, script)。"""
    if getattr(sys, 'frozen', False):
        return sys.executable, ''
    pyw = pathlib.Path(sys.executable).with_name('pythonw.exe')
    runner = str(pyw) if pyw.exists() else sys.executable
    script = str(pathlib.Path(__file__).with_name('monitor.py'))
    return runner, script


# ── 三个原子操作（测试中被 monkeypatch 替换为内存桩）──────────────
def _read_value():
    """快捷方式存在则返回目标路径字符串，否则返回 None。"""
    p = _lnk_path()
    return str(p) if p.exists() else None


def _write_value(_cmd: str):
    """用 PowerShell 的 WScript.Shell 创建真实 .lnk。_cmd 参数保持接口兼容但不使用。"""
    target, args = _exe_target()
    lnk = str(_lnk_path())
    ps = (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$s = $ws.CreateShortcut("{lnk}"); '
        f'$s.TargetPath = "{target}"; '
        f'$s.Arguments = "{args}"; '
        f'$s.WindowStyle = 7; '   # 7 = minimized, 避免开机弹窗
        f'$s.Save()'
    )
    subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
        check=True, capture_output=True,
    )


def _delete_value():
    try:
        _lnk_path().unlink(missing_ok=True)
    except OSError:
        pass


# ── 对外 API（接口与之前完全相同）────────────────────────────────
def is_enabled() -> bool:
    return _read_value() is not None


def enable() -> bool:
    """写入开机自启快捷方式。成功返回 True。"""
    try:
        _write_value('')
    except Exception as e:
        log(f'[autostart] 启用失败: {e}')
        return False
    if not is_enabled():
        log('[autostart] 启用失败：快捷方式未能创建')
        return False
    log('[autostart] 已启用开机自启')
    return True


def disable() -> bool:
    """移除开机自启快捷方式。成功返回 True。"""
    try:
        _delete_value()
        log('[autostart] 已关闭开机自启')
        return True
    except Exception as e:
        log(f'[autostart] 关闭失败: {e}')
        return False


def toggle() -> bool:
    """切换状态，返回切换后的启用状态。"""
    if is_enabled():
        disable()
    else:
        enable()
    return is_enabled()
