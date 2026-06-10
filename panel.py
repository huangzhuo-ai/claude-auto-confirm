"""
状态面板（CustomTkinter）：左侧边栏导航 4 个页面——监控/日志/设置/关于。
通过 open_panel() 单例开窗，关掉面板不影响后台监控。
主题跟随系统，设置页可即时切换明暗与主题色。
"""
import time
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk

import monitor
import config
import updater
from version import __version__

_STATE_ICONS = {
    'running': '🔵 运行中', 'idle': '🟡 空闲', 'idle_notified': '🟠 空闲已通知',
    'confirmed': '✅ 已自动确认', 'prompt': '🔴 需处理', 'error': '❌ 错误',
    'unknown': '⚠️ 未知确认框', 'ignored': '⚫ 已忽略',
}
_ACTION_LABELS = {
    'auto_yes': '✅ 自动确认', 'notify': '🔔 已通知', 'error': '❌ 错误通知',
    'unknown': '⚠️ 未知框(已记录)', 'idle': '🟠 空闲通知',
}
_THEME_MAP = {'system': 'system', 'dark': 'dark', 'light': 'light'}
_COLOR_MAP  = {'blue': 'blue', 'green': 'green', 'dark-blue': 'dark-blue'}

_panel_thread: threading.Thread | None = None
_panel_lock = threading.Lock()
_tree = None
_log_box = None
_log_snapshot = [None]
_about_status = None


def open_panel():
    """从托盘菜单调用：若面板已开则忽略，否则新建。"""
    global _panel_thread
    with _panel_lock:
        if _panel_thread is not None and _panel_thread.is_alive():
            return
        _panel_thread = threading.Thread(target=_run_panel, daemon=True, name='panel')
        _panel_thread.start()


# ── 各页构建 ──────────────────────────────────────────────────────────────────

def _build_monitor_page(frame):
    global _tree
    bar = ctk.CTkFrame(frame, fg_color='transparent')
    bar.pack(fill='x', pady=(0, 8))
    ctk.CTkLabel(bar, text='选中行后设策略：').pack(side='left', padx=(0, 6))
    for label, policy in [('自动确认', 'auto'), ('仅通知', 'notify'), ('忽略', 'ignore')]:
        ctk.CTkButton(bar, text=label, width=72,
                      command=lambda p=policy: _set_selected_policy(p)
                      ).pack(side='left', padx=3)

    cols = ('kind', 'title', 'policy', 'state', 'detail', 'ts')
    _tree = ttk.Treeview(frame, columns=cols, show='headings',
                         selectmode='browse', height=12)
    for col, head, w in [('kind', '类型', 90), ('title', '标题', 240),
                         ('policy', '策略', 70), ('state', '状态', 130),
                         ('detail', '详情', 180), ('ts', '时间', 80)]:
        _tree.heading(col, text=head)
        _tree.column(col, width=w, anchor='w')
    _tree.pack(fill='both', expand=True)

    def _on_dbl(_e):
        item = _tree.focus()
        if item:
            try:
                monitor._bring_to_front(int(item))
            except Exception:
                pass
    _tree.bind('<Double-1>', _on_dbl)


def _get_policy_label(hwnd):
    return {'auto': '自动', 'notify': '仅通知', 'ignore': '忽略'}.get(
        monitor.get_policy(hwnd), '自动')


def _set_selected_policy(policy):
    if _tree is None:
        return
    item = _tree.focus()
    if not item:
        return
    try:
        monitor.set_policy(int(item), policy)
    except Exception:
        pass


def _refresh_monitor():
    if _tree is None:
        return
    snap = dict(monitor._win_state)
    existing = set(_tree.get_children())
    seen = set()
    for hwnd, row in snap.items():
        iid = str(hwnd)
        seen.add(iid)
        vals = (row.get('kind', ''), row.get('title', '')[:50],
                _get_policy_label(hwnd),
                _STATE_ICONS.get(row.get('state', ''), row.get('state', '')),
                row.get('detail', '')[:60],
                time.strftime('%H:%M:%S', time.localtime(row.get('ts', 0))))
        if iid in existing:
            _tree.item(iid, values=vals)
        else:
            _tree.insert('', 'end', iid=iid, values=vals)
    for iid in existing - seen:
        _tree.delete(iid)


def _build_log_page(frame):
    global _log_box
    ctk.CTkLabel(frame, text='事件日志',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(0, 6))
    _log_box = ctk.CTkTextbox(frame, font=ctk.CTkFont(family='Consolas', size=12))
    _log_box.pack(fill='both', expand=True)
    _log_box.configure(state='disabled')


def _refresh_log():
    if _log_box is None:
        return
    events = list(monitor.EVENTS)
    if events == _log_snapshot[0]:
        return
    _log_snapshot[0] = events
    _log_box.configure(state='normal')
    _log_box.delete('1.0', 'end')
    for ev in reversed(events):
        ts = time.strftime('%H:%M:%S', time.localtime(ev['ts']))
        action = _ACTION_LABELS.get(ev['action'], ev['action'])
        _log_box.insert('end',
            f"{ts}  {action:<12}  [{ev['kind']}] {ev['title'][:35]}  {ev['detail'][:60]}\n")
    _log_box.configure(state='disabled')


def _build_settings_page(frame):
    cfg = config.load()

    ctk.CTkLabel(frame, text='监控开关',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w')

    pause_sw = ctk.CTkSwitch(frame, text='暂停监控')
    pause_sw.pack(anchor='w', pady=4)
    if monitor.PAUSED.is_set():
        pause_sw.select()

    def _toggle_pause():
        if pause_sw.get():
            monitor.PAUSED.set()
        else:
            monitor.PAUSED.clear()
    pause_sw.configure(command=_toggle_pause)

    dry_sw = ctk.CTkSwitch(frame, text='干跑（只检测不发键）')
    dry_sw.pack(anchor='w', pady=4)
    if monitor.DRY_RUN:
        dry_sw.select()
    dry_sw.configure(command=lambda: setattr(monitor, 'DRY_RUN', bool(dry_sw.get())))

    import autostart
    auto_sw = ctk.CTkSwitch(frame, text='开机自启')
    auto_sw.pack(anchor='w', pady=4)
    if autostart.is_enabled():
        auto_sw.select()

    def _toggle_auto():
        want_on = bool(auto_sw.get())
        autostart.toggle()
        ok = autostart.is_enabled()
        if ok != want_on:
            auto_sw.deselect() if not ok else auto_sw.select()
        if want_on and not ok:
            messagebox.showwarning('开机自启被拦截',
                '写入失败，疑被安全软件/系统管控拦截。请加白名单后重试。')
    auto_sw.configure(command=_toggle_auto)

    # ── 外观 ──
    ctk.CTkLabel(frame, text='外观',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 0))

    _THEME_LABELS = {'跟随系统': 'system', '深色': 'dark', '浅色': 'light'}
    _THEME_REV    = {v: k for k, v in _THEME_LABELS.items()}
    _COLOR_LABELS = {'蓝': 'blue', '绿': 'green', '深蓝': 'dark-blue'}
    _COLOR_REV    = {v: k for k, v in _COLOR_LABELS.items()}

    row1 = ctk.CTkFrame(frame, fg_color='transparent')
    row1.pack(anchor='w', pady=6, fill='x')
    ctk.CTkLabel(row1, text='明暗：', width=60, anchor='w').pack(side='left')

    def _on_theme(choice):
        mode = _THEME_LABELS[choice]
        ctk.set_appearance_mode(mode)
        cfg['theme'] = mode
        config.save(cfg)

    theme_menu = ctk.CTkOptionMenu(row1, values=list(_THEME_LABELS.keys()),
                                   command=_on_theme)
    theme_menu.set(_THEME_REV.get(cfg.get('theme', 'system'), '跟随系统'))
    theme_menu.pack(side='left')

    row2 = ctk.CTkFrame(frame, fg_color='transparent')
    row2.pack(anchor='w', pady=6, fill='x')
    ctk.CTkLabel(row2, text='主题色：', width=60, anchor='w').pack(side='left')

    def _on_color(choice):
        cfg['color'] = _COLOR_LABELS[choice]
        config.save(cfg)
        messagebox.showinfo('主题色', '主题色将在下次打开面板时完整生效。')

    color_menu = ctk.CTkOptionMenu(row2, values=list(_COLOR_LABELS.keys()),
                                   command=_on_color)
    color_menu.set(_COLOR_REV.get(cfg.get('color', 'blue'), '蓝'))
    color_menu.pack(side='left')


def _build_about_page(frame):
    global _about_status
    ctk.CTkLabel(frame, text='Claude Auto-Yes',
                 font=ctk.CTkFont(size=20, weight='bold')).pack(anchor='w', pady=(0, 4))
    ctk.CTkLabel(frame, text=f'版本 v{__version__}').pack(anchor='w')
    ctk.CTkLabel(frame, text='作者：huangzhuo').pack(anchor='w', pady=(8, 0))

    link = ctk.CTkLabel(frame, text='GitHub 项目主页',
                        text_color=('blue', '#6db3f2'), cursor='hand2')
    link.pack(anchor='w', pady=(8, 0))
    link.bind('<Button-1>',
              lambda _e: webbrowser.open('https://github.com/huangzhuo-ai/claude-auto-confirm'))

    _about_status = ctk.CTkLabel(frame, text='')
    _about_status.pack(anchor='w', pady=(16, 0))

    def _manual_check():
        _about_status.configure(text='检查中…', text_color=('gray', 'gray'))
        def _run():
            has, latest = updater.check(__version__)
            if has and latest:
                _about_status.configure(
                    text=f'发现新版 {latest}，点此前往下载',
                    text_color=('blue', '#6db3f2'), cursor='hand2')
                _about_status.bind('<Button-1>',
                    lambda _e: webbrowser.open(updater.RELEASES_PAGE))
            elif latest:
                _about_status.configure(text='已是最新版 ✓',
                                        text_color=('gray', 'gray'), cursor='')
            else:
                _about_status.configure(text='检查失败（网络问题）',
                                        text_color=('gray', 'gray'), cursor='')
        threading.Thread(target=_run, daemon=True).start()

    ctk.CTkButton(frame, text='检查更新', command=_manual_check).pack(anchor='w', pady=(8, 0))


def _on_update_found(latest):
    if _about_status is not None:
        try:
            _about_status.configure(
                text=f'发现新版 {latest}，去「关于」页查看',
                text_color=('blue', '#6db3f2'))
        except Exception:
            pass


# ── 主面板入口 ────────────────────────────────────────────────────────────────

def _run_panel():
    cfg = config.load()
    ctk.set_appearance_mode(_THEME_MAP.get(cfg.get('theme', 'system'), 'system'))
    ctk.set_default_color_theme(_COLOR_MAP.get(cfg.get('color', 'blue'), 'blue'))

    root = ctk.CTk()
    root.title('Claude Auto-Yes · 状态面板')
    root.geometry('900x560')

    sidebar = ctk.CTkFrame(root, width=160, corner_radius=0)
    sidebar.pack(side='left', fill='y')
    sidebar.pack_propagate(False)
    ctk.CTkLabel(sidebar, text='⚡ Auto-Yes',
                 font=ctk.CTkFont(size=16, weight='bold')).pack(pady=(18, 16))

    content = ctk.CTkFrame(root, corner_radius=0, fg_color='transparent')
    content.pack(side='left', fill='both', expand=True)

    pages = {name: ctk.CTkFrame(content, fg_color='transparent')
             for name in ('监控', '日志', '设置', '关于')}

    def show(name):
        for p in pages.values():
            p.pack_forget()
        pages[name].pack(fill='both', expand=True, padx=16, pady=16)

    for name in ('监控', '日志', '设置', '关于'):
        ctk.CTkButton(sidebar, text=name, anchor='w',
                      command=lambda n=name: show(n)).pack(fill='x', padx=10, pady=3)

    status_lbl = ctk.CTkLabel(sidebar, text='', font=ctk.CTkFont(size=11))
    status_lbl.pack(side='bottom', pady=12)

    _build_monitor_page(pages['监控'])
    _build_log_page(pages['日志'])
    _build_settings_page(pages['设置'])
    _build_about_page(pages['关于'])

    show('监控')
    updater.check_in_background(__version__, _on_update_found)

    def _refresh():
        status_lbl.configure(
            text='⏸ 已暂停' if monitor.PAUSED.is_set()
            else f'监控中 · {monitor.STATS["windows"]} 个终端')
        _refresh_monitor()
        _refresh_log()
        root.after(1000, _refresh)

    root.after(0, _refresh)
    root.mainloop()
