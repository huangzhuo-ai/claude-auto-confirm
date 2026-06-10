"""
系统托盘界面：主线程跑 pystray 托盘，monitor.scan_loop() 在子线程运行。
右键菜单：状态行 / 暂停·恢复 / 退出。
"""
import threading
import pystray
from PIL import Image, ImageDraw
import monitor


_stop = threading.Event()
_paused = threading.Event()


def _make_icon(paused: bool = False) -> Image.Image:
    """动态生成 64x64 托盘图标：紫色圆底 + 中心字符。暂停时显示灰色。"""
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (120, 120, 120, 255) if paused else (138, 92, 246, 255)  # 灰 / 紫
    d.ellipse([4, 4, 60, 60], fill=color)
    # 中心画一个对勾（确认的意象）
    d.line([(20, 34), (29, 44), (46, 22)], fill=(255, 255, 255, 255), width=6)
    return img


def _status_text(_item) -> str:
    if _paused.is_set():
        return '⏸ 已暂停'
    s = monitor.STATS
    return f'监控中 · {s["windows"]} 个终端'


def _toggle_pause(icon, _item):
    if _paused.is_set():
        _paused.clear()
    else:
        _paused.set()
    icon.icon = _make_icon(_paused.is_set())
    icon.update_menu()


def _is_paused(_item) -> bool:
    return _paused.is_set()


def _quit(icon, _item):
    _stop.set()
    icon.stop()


def run(dry_run: bool = False):
    """启动托盘（阻塞主线程），扫描循环在子线程跑。"""
    t = threading.Thread(
        target=monitor.scan_loop, args=(_stop, _paused), daemon=True)
    t.start()

    menu = pystray.Menu(
        pystray.MenuItem(_status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('暂停', _toggle_pause, checked=_is_paused),
        pystray.MenuItem('退出', _quit),
    )
    icon = pystray.Icon(
        'claude-auto-confirm', _make_icon(), 'Claude Auto-Yes', menu)
    icon.run()


if __name__ == '__main__':
    run()
