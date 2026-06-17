"""
全局快捷键管理：用 pynput 监听系统级热键，无需管理员权限。
独立线程运行，触发回调时调用 monitor/panel/tray 的相应函数。
"""
import threading
from pynput import keyboard
from applog import log
import config


class HotkeyManager:
    """全局热键管理器。在独立守护线程监听键盘，支持运行时启用/禁用。"""

    def __init__(self):
        self._listener = None
        self._thread = None
        self._enabled = False
        self._muted = False  # 临时静音（Ctrl+Alt+M 切换）
        self._callbacks = {}  # hotkey_name -> callback
        self._lock = threading.Lock()

    def register(self, name: str, callback):
        """注册一个热键回调。name 如 'pause_resume'，callback 无参函数。"""
        with self._lock:
            self._callbacks[name] = callback

    def start(self):
        """启动热键监听（独立守护线程）。配置禁用时不启动。"""
        cfg = config.load()
        hotkeys_cfg = cfg.get('hotkeys', {})
        if not hotkeys_cfg.get('enabled', True):
            log('[hotkeys] 配置已禁用，跳过启动')
            return

        with self._lock:
            if self._enabled:
                return
            self._enabled = True

        def _run():
            try:
                # pynput 的 GlobalHotKeys：传入 {组合键字符串: 回调} 字典
                # 读取配置的快捷键（格式如 'ctrl+alt+p'，pynput 接受 '<ctrl>+<alt>+p'）
                cfg = config.load()
                hotkeys_cfg = cfg.get('hotkeys', {})

                # 默认快捷键
                defaults = {
                    'pause_resume': '<ctrl>+<alt>+p',
                    'open_panel': '<ctrl>+<alt>+c',
                    'mute_hotkeys': '<ctrl>+<alt>+m',
                }

                # 从配置读取（用户可自定义），转换为 pynput 格式
                hotkey_map = {}
                for name, default in defaults.items():
                    user_key = hotkeys_cfg.get(name, default)
                    # 转换格式：'ctrl+alt+p' -> '<ctrl>+<alt>+p'
                    pynput_key = self._to_pynput_format(user_key)
                    hotkey_map[pynput_key] = lambda n=name: self._on_hotkey(n)

                self._listener = keyboard.GlobalHotKeys(hotkey_map)
                self._listener.start()
                log(f'[hotkeys] 已启动，监听 {len(hotkey_map)} 个快捷键')
            except Exception as e:
                log(f'[hotkeys] 启动失败: {e}')
                with self._lock:
                    self._enabled = False

        self._thread = threading.Thread(target=_run, daemon=True, name='hotkeys')
        self._thread.start()

    def stop(self):
        """停止热键监听。"""
        with self._lock:
            if not self._enabled:
                return
            self._enabled = False

        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
        log('[hotkeys] 已停止')

    def is_enabled(self) -> bool:
        """是否已启动。"""
        with self._lock:
            return self._enabled

    def toggle_mute(self):
        """切换静音状态（临时禁用所有快捷键响应，但监听线程仍在跑）。"""
        with self._lock:
            self._muted = not self._muted
        state = '已静音' if self._muted else '已恢复'
        log(f'[hotkeys] {state}')

    def _on_hotkey(self, name: str):
        """快捷键触发时的内部回调。检查静音状态，调用用户注册的回调。"""
        with self._lock:
            if self._muted:
                return
            cb = self._callbacks.get(name)
        if cb:
            try:
                cb()
            except Exception as e:
                log(f'[hotkeys] 回调 {name} 执行失败: {e}')

    @staticmethod
    def _to_pynput_format(key: str) -> str:
        """转换用户配置格式到 pynput 格式。
        'ctrl+alt+p' -> '<ctrl>+<alt>+p'
        'shift+f1' -> '<shift>+<f1>'
        """
        parts = key.lower().split('+')
        result = []
        for p in parts:
            p = p.strip()
            # 修饰键加尖括号
            if p in ('ctrl', 'alt', 'shift', 'cmd', 'ctrl_l', 'ctrl_r', 'alt_l', 'alt_r'):
                result.append(f'<{p}>')
            else:
                result.append(p)
        return '+'.join(result)


# 全局单例
_manager = HotkeyManager()


def start():
    """启动全局热键监听。"""
    _manager.start()


def stop():
    """停止全局热键监听。"""
    _manager.stop()


def register(name: str, callback):
    """注册热键回调。name ∈ pause_resume | open_panel | mute_hotkeys。"""
    _manager.register(name, callback)


def toggle_mute():
    """切换静音（临时禁用快捷键）。"""
    _manager.toggle_mute()


def is_enabled() -> bool:
    """热键监听是否已启动。"""
    return _manager.is_enabled()
