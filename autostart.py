"""
开机自启动：通过 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 注册表项实现。

为什么用 HKCU 而非启动文件夹 / 计划任务：
  * HKCU Run 不需要管理员权限（当前用户即可写），符合「双击即用」的轻量定位；
  * 退出登录前由系统自动拉起，无需额外快捷方式文件维护；
  * 卸载即删值，干净。

命令构造兼容两种运行形态：
  * frozen（PyInstaller exe）：直接写 exe 路径；
  * dev（脚本）：写 pythonw.exe + monitor.py，pythonw 避免开机弹黑框。
"""
import sys
import pathlib
import winreg

from applog import log

_RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
_VALUE_NAME = 'ClaudeAutoConfirm'


def _run_command() -> str:
    """构造写入 Run 键的启动命令（路径均加引号，容忍空格目录）。"""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    # dev 模式：用同目录的 pythonw.exe（无控制台）跑 monitor.py
    pyw = pathlib.Path(sys.executable).with_name('pythonw.exe')
    runner = pyw if pyw.exists() else pathlib.Path(sys.executable)
    script = pathlib.Path(__file__).with_name('monitor.py')
    return f'"{runner}" "{script}"'


# ── 注册表三个原子操作（测试中被打桩为内存 dict）─────────────────
def _read_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, _VALUE_NAME)
            return val
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _write_value(cmd: str):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
        winreg.SetValueEx(k, _VALUE_NAME, 0, winreg.REG_SZ, cmd)


def _delete_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, _VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        pass


# ── 对外 API ─────────────────────────────────────────────────
def is_enabled() -> bool:
    return _read_value() is not None


def enable() -> bool:
    """写入开机自启项。成功返回 True。"""
    try:
        _write_value(_run_command())
        log('[autostart] 已启用开机自启')
        return True
    except Exception as e:
        log(f'[autostart] 启用失败: {e}')
        return False


def disable() -> bool:
    """移除开机自启项。成功返回 True。"""
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
