"""
系统托盘界面：主线程跑 pystray 托盘，monitor.scan_loop() 在子线程运行。
右键菜单：状态行 / 打开面板 / 暂停·恢复 / 配置方案 / 退出。
"""
import threading
import pystray
from PIL import Image
import monitor
import hotkeys
from applog import log


_stop = threading.Event()


def _make_icon(paused: bool = False) -> Image.Image:
    """托盘图标：读取 AI 生成的 icon.png（紫色 >_✓），暂停时叠加灰色滤镜。
    统一品牌视觉：托盘、GUI、通知、exe 全用同一 AI 图标。"""
    import os, sys
    # 解析 icon.png 路径（打包后在 sys._MEIPASS，开发时在项目根）
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base, 'icon.png')

    img = Image.open(icon_path).convert('RGBA')
    # 托盘用 64px（Windows 标准）
    if img.size != (64, 64):
        img = img.resize((64, 64), Image.LANCZOS)

    if paused:
        # 暂停态：灰色滤镜（降饱和度，保留轮廓）
        from PIL import ImageEnhance
        img = ImageEnhance.Color(img).enhance(0.2)  # 几乎完全去色
        img = ImageEnhance.Brightness(img).enhance(0.85)  # 稍微变暗

    return img


def _status_text(_item) -> str:
    if monitor.PAUSED.is_set():
        return '⏸ 已暂停'
    s = monitor.STATS
    today = monitor.COUNTERS['today']
    return (f'监控中 · {s["windows"]} 个终端 · '
            f'今日已确认 {today["auto_yes"]} 次')


def _toggle_pause(icon, _item):
    if monitor.PAUSED.is_set():
        monitor.cancel_pause_timer()   # 手动恢复时取消待定的自动恢复 timer
        monitor.PAUSED.clear()
    else:
        monitor.PAUSED.set()
    icon.icon = _make_icon(monitor.PAUSED.is_set())
    icon.update_menu()


def _pause_for(icon, minutes: int):
    """定时暂停 minutes 分钟后自动恢复。"""
    monitor.pause_for(minutes * 60)
    icon.icon = _make_icon(True)
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
    monitor.cancel_pause_timer()
    hotkeys.stop()  # 停止热键监听
    _stop.set()
    icon.stop()


def _switch_profile(icon, item, profile_name):
    """切配置方案。重新加载配置后，需要重新加载过滤规则。"""
    import profiles
    import config
    import filters
    if profiles.switch_profile(profile_name):
        # 重新加载配置和过滤规则
        cfg = config.load()
        filters.load_from_config(cfg)
        log(f'[tray] 已切换到方案: {profile_name}')
        icon.update_menu()  # 刷新菜单（更新选中状态）


def _current_profile(_item) -> str:
    """返回当前方案名（用于菜单显示）。"""
    import profiles
    return profiles.get_current_profile()


def run(dry_run: bool = False):
    """启动托盘（阻塞主线程），扫描循环在子线程跑。"""
    t = threading.Thread(
        target=monitor.scan_loop, args=(_stop,), daemon=True)
    t.start()

    # 启动全局快捷键监听
    hotkeys.start()

    # 注册快捷键回调
    def _hotkey_pause_resume():
        if monitor.PAUSED.is_set():
            monitor.cancel_pause_timer()
            monitor.PAUSED.clear()
            log('[hotkey] 已恢复监控')
        else:
            monitor.PAUSED.set()
            log('[hotkey] 已暂停监控')

    def _hotkey_open_panel():
        import panel
        panel.open_panel()
        log('[hotkey] 打开面板')

    def _hotkey_mute():
        hotkeys.toggle_mute()

    hotkeys.register('pause_resume', _hotkey_pause_resume)
    hotkeys.register('open_panel', _hotkey_open_panel)
    hotkeys.register('mute_hotkeys', _hotkey_mute)

    # 预热面板窗口（隐藏构建），让首次双击托盘瞬间打开
    try:
        import panel
        panel.prewarm_panel()
    except Exception:
        pass

    # 构建配置方案子菜单
    import profiles
    profile_items = []
    current = profiles.get_current_profile()
    for pname in profiles.list_profiles():
        # 为每个方案创建独立的 action 和 checked 函数（避免闭包陷阱）
        def make_action(profile_name):
            def _action(icon, item):
                _switch_profile(icon, item, profile_name)
            return _action

        def make_checked(profile_name):
            def _checked(item):
                return profiles.get_current_profile() == profile_name
            return _checked

        profile_items.append(
            pystray.MenuItem(
                pname,
                make_action(pname),
                checked=make_checked(pname),
                radio=True,
            )
        )

    menu = pystray.Menu(
        pystray.MenuItem(_status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        # default=True：设为默认项，Windows 下双击托盘图标即触发「打开面板」
        pystray.MenuItem('打开面板', _open_panel, default=True),
        pystray.MenuItem('暂停', _toggle_pause, checked=_is_paused),
        pystray.MenuItem('定时暂停', pystray.Menu(
            pystray.MenuItem('暂停 30 分钟', lambda icon, item: _pause_for(icon, 30)),
            pystray.MenuItem('暂停 1 小时', lambda icon, item: _pause_for(icon, 60)),
            pystray.MenuItem('暂停 2 小时', lambda icon, item: _pause_for(icon, 120)),
        )),
        pystray.MenuItem('配置方案', pystray.Menu(*profile_items)) if profile_items else None,
        pystray.MenuItem('开机自启', _toggle_autostart, checked=_is_autostart),
        pystray.MenuItem('退出', _quit),
    )
    def _setup(icon):
        # 托盘图标就绪后调用（在 icon 线程内）：首次运行弹引导提示，之后不再弹
        icon.visible = True
        try:
            import state
            if state.is_first_run():
                from win11toast import toast as _toast
                _toast('Claude Auto-Yes 已在后台运行',
                       '双击托盘图标即可打开面板。需要你处理时会桌面通知。',
                       icon=monitor._asset_path('icon.png'),
                       app_id='Claude Auto-Yes')
                state.mark_launched()
        except Exception as e:
            log(f'  [WARN] 首次引导提示失败: {e}')

    icon = pystray.Icon(
        'claude-auto-confirm', _make_icon(), 'Claude Auto-Yes', menu)
    icon.run(setup=_setup)


if __name__ == '__main__':
    run()
