"""
状态面板（CustomTkinter）：左侧边栏导航 4 个页面——监控/日志/设置/关于。
通过 open_panel() 单例开窗，关掉面板不影响后台监控。
主题跟随系统，设置页可即时切换明暗与主题色。
"""
import time
import threading
import webbrowser
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
import customtkinter as ctk

import monitor
import config
import updater
import applog
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
_stats_labels = {}  # 统计标签缓存


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
    global _tree, _stats_labels

    # 统计卡片
    stats_frame = ctk.CTkFrame(frame)
    stats_frame.pack(fill='x', pady=(0, 12))

    ctk.CTkLabel(stats_frame, text='📊 统计',
                 font=ctk.CTkFont(size=13, weight='bold')).pack(anchor='w', padx=10, pady=(8, 4))

    cards = ctk.CTkFrame(stats_frame, fg_color='transparent')
    cards.pack(fill='x', padx=10, pady=(0, 8))

    # 今日统计卡
    today_card = ctk.CTkFrame(cards)
    today_card.pack(side='left', fill='x', expand=True, padx=(0, 6))
    ctk.CTkLabel(today_card, text='今日', font=ctk.CTkFont(size=11, weight='bold')).pack(pady=(6, 2))
    _stats_labels['today_auto'] = ctk.CTkLabel(today_card, text='✅ 自动确认: 0')
    _stats_labels['today_auto'].pack(anchor='w', padx=8, pady=1)
    _stats_labels['today_notify'] = ctk.CTkLabel(today_card, text='🔔 通知: 0')
    _stats_labels['today_notify'].pack(anchor='w', padx=8, pady=1)
    _stats_labels['today_error'] = ctk.CTkLabel(today_card, text='❌ 错误: 0')
    _stats_labels['today_error'].pack(anchor='w', padx=8, pady=1)
    _stats_labels['today_idle'] = ctk.CTkLabel(today_card, text='🟠 空闲: 0')
    _stats_labels['today_idle'].pack(anchor='w', padx=8, pady=(1, 6))

    # 累计统计卡
    total_card = ctk.CTkFrame(cards)
    total_card.pack(side='left', fill='x', expand=True, padx=(6, 0))
    ctk.CTkLabel(total_card, text='累计', font=ctk.CTkFont(size=11, weight='bold')).pack(pady=(6, 2))
    _stats_labels['total_auto'] = ctk.CTkLabel(total_card, text='✅ 自动确认: 0')
    _stats_labels['total_auto'].pack(anchor='w', padx=8, pady=1)
    _stats_labels['total_notify'] = ctk.CTkLabel(total_card, text='🔔 通知: 0')
    _stats_labels['total_notify'].pack(anchor='w', padx=8, pady=1)
    _stats_labels['total_error'] = ctk.CTkLabel(total_card, text='❌ 错误: 0')
    _stats_labels['total_error'].pack(anchor='w', padx=8, pady=1)
    _stats_labels['total_idle'] = ctk.CTkLabel(total_card, text='🟠 空闲: 0')
    _stats_labels['total_idle'].pack(anchor='w', padx=8, pady=(1, 6))

    # 策略按钮栏
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


def _get_policy_label(hwnd, title=''):
    return {'auto': '自动', 'notify': '仅通知', 'ignore': '忽略'}.get(
        monitor.resolve_policy(hwnd, title), '自动')


def _set_selected_policy(policy):
    if _tree is None:
        return
    item = _tree.focus()
    if not item:
        return
    try:
        hwnd = int(item)
        # 取该窗口的完整标题用于持久化（表格里是截断的，从 _win_state 拿原始值）
        title = monitor._win_state.get(hwnd, {}).get('title', '')
        monitor.set_policy(hwnd, policy, title=title)
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
                _get_policy_label(hwnd, row.get('title', '')),
                _STATE_ICONS.get(row.get('state', ''), row.get('state', '')),
                row.get('detail', '')[:60],
                time.strftime('%H:%M:%S', time.localtime(row.get('ts', 0))))
        if iid in existing:
            _tree.item(iid, values=vals)
        else:
            _tree.insert('', 'end', iid=iid, values=vals)
    for iid in existing - seen:
        _tree.delete(iid)

    # 更新统计数据
    if _stats_labels:
        today = monitor.COUNTERS['today']
        total = monitor.COUNTERS['total']
        _stats_labels['today_auto'].configure(text=f'✅ 自动确认: {today["auto_yes"]}')
        _stats_labels['today_notify'].configure(text=f'🔔 通知: {today["notify"]}')
        _stats_labels['today_error'].configure(text=f'❌ 错误: {today["error"]}')
        _stats_labels['today_idle'].configure(text=f'🟠 空闲: {today["idle"]}')
        _stats_labels['total_auto'].configure(text=f'✅ 自动确认: {total["auto_yes"]}')
        _stats_labels['total_notify'].configure(text=f'🔔 通知: {total["notify"]}')
        _stats_labels['total_error'].configure(text=f'❌ 错误: {total["error"]}')
        _stats_labels['total_idle'].configure(text=f'🟠 空闲: {total["idle"]}')


def _open_log_folder():
    """在资源管理器中定位到 app.log。"""
    try:
        log_path = applog._log_path()
        if log_path.exists():
            subprocess.run(['explorer', '/select,', str(log_path)], check=False)
        else:
            subprocess.run(['explorer', str(log_path.parent)], check=False)
    except Exception as e:
        messagebox.showerror('打开失败', f'无法打开日志目录：{e}')


def _export_events():
    """把当前事件流导出为 CSV 文件。"""
    events = list(monitor.EVENTS)
    if not events:
        messagebox.showinfo('导出事件', '当前没有事件可导出。')
        return

    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    default_name = f'events_{now}.csv'
    path = filedialog.asksaveasfilename(
        title='导出事件日志',
        defaultextension='.csv',
        filetypes=[('CSV 文件', '*.csv'), ('文本文件', '*.txt'), ('所有文件', '*.*')],
        initialfile=default_name
    )
    if not path:
        return

    try:
        import csv
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['时间', '动作', '类型', '标题', '详情'])
            for ev in reversed(events):
                ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ev['ts']))
                action = _ACTION_LABELS.get(ev['action'], ev['action'])
                writer.writerow([ts, action, ev['kind'], ev['title'], ev['detail']])
        messagebox.showinfo('导出成功', f'已导出 {len(events)} 条事件到:\n{path}')
    except Exception as e:
        messagebox.showerror('导出失败', f'保存文件时出错：{e}')


def _build_log_page(frame):
    global _log_box
    header = ctk.CTkFrame(frame, fg_color='transparent')
    header.pack(fill='x', pady=(0, 8))
    ctk.CTkLabel(header, text='事件日志',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(side='left')

    btn_bar = ctk.CTkFrame(header, fg_color='transparent')
    btn_bar.pack(side='right')
    ctk.CTkButton(btn_bar, text='📁 打开日志目录', width=120,
                  command=_open_log_folder).pack(side='left', padx=3)
    ctk.CTkButton(btn_bar, text='💾 导出事件', width=100,
                  command=_export_events).pack(side='left', padx=3)

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

    # ── 忽略列表 ──
    ctk.CTkLabel(frame, text='忽略列表',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 0))
    ctk.CTkLabel(frame, text='含以下字串的窗口标题将被跳过（不监控）',
                 font=ctk.CTkFont(size=11), text_color='gray').pack(anchor='w', pady=(2, 4))

    ignore_frame = ctk.CTkFrame(frame)
    ignore_frame.pack(fill='x', pady=4)

    ignore_listbox = tk.Listbox(ignore_frame, height=4, font=('Consolas', 10))
    ignore_listbox.pack(side='left', fill='both', expand=True, padx=(8, 4), pady=8)
    for item in cfg.get('ignored_titles', []):
        ignore_listbox.insert('end', item)

    btn_col = ctk.CTkFrame(ignore_frame, fg_color='transparent')
    btn_col.pack(side='right', padx=(0, 8), pady=8)

    def _add_ignore():
        from tkinter import simpledialog
        title = simpledialog.askstring('添加忽略规则', '输入要忽略的窗口标题关键词：')
        if title and title.strip():
            ignore_listbox.insert('end', title.strip())
            cfg['ignored_titles'] = list(ignore_listbox.get(0, 'end'))
            config.save(cfg)

    def _remove_ignore():
        sel = ignore_listbox.curselection()
        if sel:
            ignore_listbox.delete(sel[0])
            cfg['ignored_titles'] = list(ignore_listbox.get(0, 'end'))
            config.save(cfg)

    ctk.CTkButton(btn_col, text='➕ 添加', width=60, command=_add_ignore).pack(pady=2)
    ctk.CTkButton(btn_col, text='➖ 删除', width=60, command=_remove_ignore).pack(pady=2)

    # ── 静默时段 ──
    ctk.CTkLabel(frame, text='静默时段',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 0))
    ctk.CTkLabel(frame, text='静默时段内只记录日志，不发送桌面通知',
                 font=ctk.CTkFont(size=11), text_color='gray').pack(anchor='w', pady=(2, 4))

    quiet_sw = ctk.CTkSwitch(frame, text='启用静默时段')
    quiet_sw.pack(anchor='w', pady=4)
    if cfg.get('quiet_hours_enabled', False):
        quiet_sw.select()

    quiet_row = ctk.CTkFrame(frame, fg_color='transparent')
    quiet_row.pack(anchor='w', pady=4, fill='x')
    ctk.CTkLabel(quiet_row, text='从', width=30, anchor='w').pack(side='left', padx=(0, 4))

    start_entry = ctk.CTkEntry(quiet_row, width=70, placeholder_text='HH:MM')
    start_entry.insert(0, cfg.get('quiet_hours_start', '22:00'))
    start_entry.pack(side='left', padx=2)

    ctk.CTkLabel(quiet_row, text='到', width=30, anchor='center').pack(side='left', padx=4)

    end_entry = ctk.CTkEntry(quiet_row, width=70, placeholder_text='HH:MM')
    end_entry.insert(0, cfg.get('quiet_hours_end', '08:00'))
    end_entry.pack(side='left', padx=2)

    def _save_quiet():
        cfg['quiet_hours_enabled'] = bool(quiet_sw.get())
        start = start_entry.get().strip()
        end = end_entry.get().strip()
        # 简单验证格式
        import re
        if re.match(r'^\d{1,2}:\d{2}$', start) and re.match(r'^\d{1,2}:\d{2}$', end):
            cfg['quiet_hours_start'] = start
            cfg['quiet_hours_end'] = end
            config.save(cfg)
            messagebox.showinfo('保存成功', '静默时段设置已保存')
        else:
            messagebox.showerror('格式错误', '时间格式应为 HH:MM（如 22:00）')

    ctk.CTkButton(quiet_row, text='保存', width=60, command=_save_quiet).pack(side='left', padx=(8, 0))

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
