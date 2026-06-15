"""
系统托盘界面：主线程跑 pystray 托盘，monitor.scan_loop() 在子线程运行。
右键菜单：状态行 / 打开面板 / 暂停·恢复 / 退出。
"""
import threading
import pystray
from PIL import Image, ImageDraw
import monitor


_stop = threading.Event()


def _make_icon(paused: bool = False) -> Image.Image:
    """动态生成 64x64 托盘图标：紫色圆底 + 中心字符。暂停时显示灰色。"""
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (120, 120, 120, 255) if paused else (138, 92, 246, 255)
    d.ellipse([4, 4, 60, 60], fill=color)
    d.line([(20, 34), (29, 44), (46, 22)], fill=(255, 255, 255, 255), width=6)
    return img


def _status_text(_item) -> str:
    if monitor.PAUSED.is_set():
        return '⏸ 已暂停'
    s = monitor.STATS
    return f'监控中 · {s["windows"]} 个终端'


def _toggle_pause(icon, _item):
    if monitor.PAUSED.is_set():
        monitor.PAUSED.clear()
    else:
        monitor.PAUSED.set()
    icon.icon = _make_icon(monitor.PAUSED.is_set())
    icon.update_menu()


def _is_paused(_item) -> bool:
    return monitor.PAUSED.is_set()


def _toggle_autostart(_icon, _item):
    import autostart
    want_on = not autostart.is_enabled()  # 这次点击想开启?
    autostart.toggle()
    # 想开启却没开成 = 被系统/安全软件拦截(enable 写后回读校验已判失败)
    if want_on and not autostart.is_enabled():
        try:
            from win11toast import toast
            toast('开机自启被拦截',
                  '写入失败，疑被安全软件/系统管控清除。'
                  '请把本程序加入白名单后重试。',
                  app_id='Claude Auto-Yes')
        except Exception:
            pass


def _is_autostart(_item) -> bool:
    import autostart
    return autostart.is_enabled()


def _open_panel(_icon, _item):
    import panel
    panel.open_panel()


def _quit(icon, _item):
    _stop.set()
    icon.stop()


def run(dry_run: bool = False):
    """启动托盘（阻塞主线程），扫描循环在子线程跑。"""
    t = threading.Thread(
        target=monitor.scan_loop, args=(_stop,), daemon=True)
    t.start()

    menu = pystray.Menu(
        pystray.MenuItem(_status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        # default=True：设为默认项，Windows 下双击托盘图标即触发「打开面板」
        pystray.MenuItem('打开面板', _open_panel, default=True),
        pystray.MenuItem('暂停', _toggle_pause, checked=_is_paused),
        pystray.MenuItem('开机自启', _toggle_autostart, checked=_is_autostart),
        pystray.MenuItem('退出', _quit),
    )
    icon = pystray.Icon(
        'claude-auto-confirm', _make_icon(), 'Claude Auto-Yes', menu)
    icon.run()


if __name__ == '__main__':
    run()
