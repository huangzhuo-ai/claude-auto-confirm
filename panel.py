"""
状态面板（CustomTkinter）：左侧边栏导航 5 个页面——监控/日志/通知历史/设置/关于。
通过 open_panel() 单例开窗，关掉面板不影响后台监控。
主题跟随系统，设置页可即时切换明暗与主题色。
"""
import sys
import os
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
import hotkeys
import profiles
import filters
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
_root = None                       # 单一根窗口，只创建一次；关闭=隐藏，再开=显示
_show_request = threading.Event()  # 托盘线程置位 → Tk 线程内轮询到后 deiconify
_tree = None
_log_box = None
_log_snapshot = [None]
_about_status = None
_stats_labels = {}  # 统计标签缓存
_notification_tree = None  # 通知历史表格
_notification_filter = None  # 通知过滤下拉框
_notification_search = None  # 通知搜索输入框


def open_panel():
    """从托盘菜单调用：请求显示面板。窗口已存在则 deiconify，否则首次构建后显示。
    根窗口只在子线程创建一次，避免 Tk 跨线程反复重建导致的静默崩溃。"""
    global _panel_thread
    with _panel_lock:
        _show_request.set()  # 始终请求显示，由 Tk 线程的 _poll_show 处理
        if _panel_thread is not None and _panel_thread.is_alive():
            return
        _panel_thread = threading.Thread(target=_run_panel, daemon=True, name='panel')
        _panel_thread.start()


def prewarm_panel():
    """启动时预构建窗口（隐藏），让用户首次双击托盘瞬间打开（省去现建 4 页的耗时）。"""
    global _panel_thread
    with _panel_lock:
        if _panel_thread is not None and _panel_thread.is_alive():
            return
        _show_request.clear()  # 预热不显示，等用户真正点开
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

    # 最近7天趋势（条形图）
    trend_frame = ctk.CTkFrame(stats_frame, fg_color='transparent')
    trend_frame.pack(fill='x', padx=10, pady=(4, 8))
    ctk.CTkLabel(trend_frame, text='最近7天自动确认趋势',
                 font=ctk.CTkFont(size=11)).pack(anchor='w', pady=(0, 4))

    _stats_labels['trend_bars'] = []  # 存每天的 (date_lbl, bar, count_lbl) 三元组
    import state
    hist = state.get_daily_history(days=7)
    # 如果历史不足7天，补空白（显示为0）
    while len(hist) < 7:
        hist.append({'date': '', 'auto_yes': 0, 'notify': 0, 'error': 0, 'idle': 0})

    # 倒序显示（最老在左，最新在右）
    hist_reversed = list(reversed(hist))
    max_count = max((d.get('auto_yes', 0) for d in hist_reversed), default=1)

    bars_row = ctk.CTkFrame(trend_frame, fg_color='transparent')
    bars_row.pack(fill='x')
    for day_data in hist_reversed:
        day_col = ctk.CTkFrame(bars_row, fg_color='transparent')
        day_col.pack(side='left', fill='both', expand=True, padx=2)

        count = day_data.get('auto_yes', 0)
        date_str = day_data.get('date', '')
        date_label = date_str[-5:] if date_str else '─'  # 只显示 MM-DD，空日显示 ─

        # 日期标签（顶部）
        date_lbl = ctk.CTkLabel(day_col, text=date_label, font=ctk.CTkFont(size=9),
                                text_color='gray')
        date_lbl.pack()

        # 条形（用进度条模拟，纵向不支持所以用横向+旋转感觉）
        # 实际上 customtkinter ProgressBar 只支持横向，用高度模拟纵向条形
        bar_container = ctk.CTkFrame(day_col, height=60, fg_color='transparent')
        bar_container.pack(fill='x', pady=2)
        bar_container.pack_propagate(False)

        # 进度条横向放，value=count/max_count
        bar = ctk.CTkProgressBar(bar_container, width=40, height=10, orientation='horizontal')
        bar.pack(anchor='s')
        bar.set(count / max_count if max_count > 0 else 0)

        # 计数标签（底部）
        count_lbl = ctk.CTkLabel(day_col, text=str(count), font=ctk.CTkFont(size=10))
        count_lbl.pack()

        _stats_labels['trend_bars'].append((date_lbl, bar, count_lbl))

    # 高级图表视图区域（新增）
    chart_section = ctk.CTkFrame(frame)
    chart_section.pack(fill='both', expand=True, pady=(0, 12))

    # 图表视图切换按钮
    chart_toolbar = ctk.CTkFrame(chart_section, fg_color='transparent')
    chart_toolbar.pack(fill='x', padx=10, pady=8)
    ctk.CTkLabel(chart_toolbar, text='📈 图表视图：',
                 font=ctk.CTkFont(size=11, weight='bold')).pack(side='left', padx=(0, 6))

    # 图表容器（用于切换不同图表）
    chart_container = ctk.CTkFrame(chart_section, height=350)
    chart_container.pack(fill='both', expand=True, padx=10, pady=(0, 8))
    chart_container.pack_propagate(False)

    # 存储当前图表画布，用于切换时销毁旧图表
    current_chart = [None]

    def _show_chart(chart_type):
        """切换显示不同的图表"""
        # 销毁旧图表
        if current_chart[0]:
            try:
                current_chart[0].get_tk_widget().destroy()
            except Exception:
                pass

        # 清空容器
        for widget in chart_container.winfo_children():
            widget.destroy()

        # 创建新图表
        try:
            import charts
            if chart_type == '30day_trend':
                canvas = charts.create_trend_chart(chart_container, days=30)
            elif chart_type == 'distribution':
                canvas = charts.create_distribution_pie(chart_container)
            elif chart_type == 'by_window':
                canvas = charts.create_window_bar_chart(chart_container, top_n=10)
            elif chart_type == 'hourly':
                canvas = charts.create_hourly_heatmap(chart_container)
            else:
                # 隐藏图表区域
                chart_container.pack_forget()
                return
            current_chart[0] = canvas
            chart_container.pack(fill='both', expand=True, padx=10, pady=(0, 8))
        except Exception as e:
            import applog
            applog.log(f'[panel] 图表加载失败: {e}')
            error_label = ctk.CTkLabel(chart_container,
                                      text=f'图表加载失败: {e}',
                                      text_color='red')
            error_label.pack(expand=True)

    # 图表切换按钮
    chart_buttons = [
        ('30天趋势', '30day_trend'),
        ('动作分布', 'distribution'),
        ('按窗口', 'by_window'),
        ('按小时', 'hourly'),
        ('隐藏图表', 'none'),
    ]

    for label, chart_type in chart_buttons:
        ctk.CTkButton(chart_toolbar, text=label, width=80,
                      command=lambda ct=chart_type: _show_chart(ct)
                      ).pack(side='left', padx=3)

    # 默认隐藏图表区域（节省空间）
    chart_container.pack_forget()

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

        # 更新最近7天趋势条形图
        if 'trend_bars' in _stats_labels:
            import state
            hist = state.get_daily_history(days=7)
            while len(hist) < 7:
                hist.append({'date': '', 'auto_yes': 0, 'notify': 0, 'error': 0, 'idle': 0})
            hist_reversed = list(reversed(hist))
            max_count = max((d.get('auto_yes', 0) for d in hist_reversed), default=1)

            for i, (date_lbl, bar, count_lbl) in enumerate(_stats_labels['trend_bars']):
                if i < len(hist_reversed):
                    day_data = hist_reversed[i]
                    count = day_data.get('auto_yes', 0)
                    date_str = day_data.get('date', '')
                    date_label = date_str[-5:] if date_str else '─'

                    date_lbl.configure(text=date_label)
                    bar.set(count / max_count if max_count > 0 else 0)
                    count_lbl.configure(text=str(count))


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


def _open_misfires_folder():
    """打开未知确认框样本目录（misfires/），方便把样本反馈给作者改进识别。"""
    try:
        d = monitor._misfires_dir()
        if not d.exists():
            messagebox.showinfo('样本目录',
                '目前没有未知确认框样本（一切正常）。\n'
                '遇到无法识别的确认框时，样本会自动存到这里。')
            return
        subprocess.run(['explorer', str(d)], check=False)
    except Exception as e:
        messagebox.showerror('打开失败', f'无法打开样本目录：{e}')


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

    # 实时模式开关（新增）
    realtime_switch = ctk.CTkSwitch(header, text='🔴 实时模式')
    realtime_switch.pack(side='left', padx=(16, 0))
    _stats_labels['log_realtime'] = realtime_switch  # 存储开关状态

    btn_bar = ctk.CTkFrame(header, fg_color='transparent')
    btn_bar.pack(side='right')
    ctk.CTkButton(btn_bar, text='📁 日志目录', width=92,
                  command=_open_log_folder).pack(side='left', padx=3)
    ctk.CTkButton(btn_bar, text='🔬 样本目录', width=92,
                  command=_open_misfires_folder).pack(side='left', padx=3)
    ctk.CTkButton(btn_bar, text='💾 导出事件', width=92,
                  command=_export_events).pack(side='left', padx=3)

    _log_box = ctk.CTkTextbox(frame, font=ctk.CTkFont(family='Consolas', size=12))
    _log_box.pack(fill='both', expand=True)
    _log_box.configure(state='disabled')


# 存储上次事件数量，用于高亮新事件
_log_last_count = [0]

def _refresh_log():
    if _log_box is None:
        return

    events = list(monitor.EVENTS)

    # 检查是否启用实时模式
    realtime_enabled = False
    if 'log_realtime' in _stats_labels:
        realtime_enabled = _stats_labels['log_realtime'].get()

    # 非实时模式且事件未变化，不刷新
    if not realtime_enabled and events == _log_snapshot[0]:
        return

    # 计算新增事件数量
    new_event_count = len(events) - _log_last_count[0]
    _log_last_count[0] = len(events)

    _log_snapshot[0] = events
    _log_box.configure(state='normal')
    _log_box.delete('1.0', 'end')

    # 事件类型图标和颜色映射
    action_styles = {
        'auto_yes': ('✅', '#4CAF50'),
        'notify': ('🔔', '#FFC107'),
        'error': ('❌', '#F44336'),
        'idle': ('🟠', '#FF9800'),
        'unknown': ('❓', '#9E9E9E'),
    }

    for idx, ev in enumerate(reversed(events)):
        ts = time.strftime('%H:%M:%S', time.localtime(ev['ts']))
        action = ev['action']
        icon, color = action_styles.get(action, ('•', 'gray'))
        action_label = _ACTION_LABELS.get(action, action)

        # 新事件高亮（最近的new_event_count条）
        is_new = realtime_enabled and idx < new_event_count

        line_text = f"{ts}  {icon} {action_label:<10}  [{ev['kind']}] {ev['title'][:35]}  {ev['detail'][:60]}\n"

        # 插入文本
        start_idx = _log_box.index('end-1c')
        _log_box.insert('end', line_text)
        end_idx = _log_box.index('end-1c')

        # 应用颜色标签
        tag_name = f'color_{action}'
        _log_box.tag_config(tag_name, foreground=color)
        _log_box.tag_add(tag_name, start_idx, end_idx)

        # 新事件高亮背景（0.5秒后会消失的效果由下次刷新实现）
        if is_new:
            highlight_tag = f'highlight_{idx}'
            _log_box.tag_config(highlight_tag, background='#3d3d3d')
            _log_box.tag_add(highlight_tag, start_idx, end_idx)

    _log_box.configure(state='disabled')

    # 实时模式：自动滚动到底部
    if realtime_enabled:
        _log_box.see('end')



def _build_settings_page(frame):
    cfg = config.load()

    # 设置页内容很多（7个区块），用滚动容器防止超出窗口被截断
    scroll_frame = ctk.CTkScrollableFrame(frame, fg_color='transparent')
    scroll_frame.pack(fill='both', expand=True)

    ctk.CTkLabel(scroll_frame, text='监控开关',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w')

    pause_sw = ctk.CTkSwitch(scroll_frame, text='暂停监控')
    pause_sw.pack(anchor='w', pady=4)
    if monitor.PAUSED.is_set():
        pause_sw.select()

    def _toggle_pause():
        if pause_sw.get():
            monitor.PAUSED.set()
        else:
            monitor.cancel_pause_timer()  # 手动恢复时取消待定的自动恢复 timer
            monitor.PAUSED.clear()
    pause_sw.configure(command=_toggle_pause)

    dry_sw = ctk.CTkSwitch(scroll_frame, text='干跑（只检测不发键）')
    dry_sw.pack(anchor='w', pady=4)
    if monitor.DRY_RUN:
        dry_sw.select()
    dry_sw.configure(command=lambda: setattr(monitor, 'DRY_RUN', bool(dry_sw.get())))

    import autostart
    auto_sw = ctk.CTkSwitch(scroll_frame, text='开机自启')
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
    ctk.CTkLabel(scroll_frame, text='忽略列表',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 0))
    ctk.CTkLabel(scroll_frame, text='含以下字串的窗口标题将被跳过（不监控）',
                 font=ctk.CTkFont(size=11), text_color='gray').pack(anchor='w', pady=(2, 4))

    ignore_frame = ctk.CTkFrame(scroll_frame)
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

    # ── 自定义错误关键词 ──
    ctk.CTkLabel(scroll_frame, text='自定义错误关键词',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 0))
    ctk.CTkLabel(scroll_frame, text='屏幕底部出现以下任一字串时，按「错误」通知你处理'
                 '（内置已覆盖登录失效/额度耗尽等，这里补充 Claude 改版后的新措辞）',
                 font=ctk.CTkFont(size=11), text_color='gray',
                 wraplength=560, justify='left').pack(anchor='w', pady=(2, 4))

    err_frame = ctk.CTkFrame(scroll_frame)
    err_frame.pack(fill='x', pady=4)

    err_listbox = tk.Listbox(err_frame, height=4, font=('Consolas', 10))
    err_listbox.pack(side='left', fill='both', expand=True, padx=(8, 4), pady=8)
    for item in cfg.get('extra_error_keywords', []):
        err_listbox.insert('end', item)

    err_btn_col = ctk.CTkFrame(err_frame, fg_color='transparent')
    err_btn_col.pack(side='right', padx=(0, 8), pady=8)

    def _add_err():
        from tkinter import simpledialog
        kw = simpledialog.askstring('添加错误关键词', '输入错误关键词（大小写不敏感）：')
        if kw and kw.strip():
            err_listbox.insert('end', kw.strip())
            cfg['extra_error_keywords'] = list(err_listbox.get(0, 'end'))
            config.save(cfg)

    def _remove_err():
        sel = err_listbox.curselection()
        if sel:
            err_listbox.delete(sel[0])
            cfg['extra_error_keywords'] = list(err_listbox.get(0, 'end'))
            config.save(cfg)

    ctk.CTkButton(err_btn_col, text='➕ 添加', width=60, command=_add_err).pack(pady=2)
    ctk.CTkButton(err_btn_col, text='➖ 删除', width=60, command=_remove_err).pack(pady=2)

    # ── 声音提示 ──
    ctk.CTkLabel(scroll_frame, text='声音提示',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 0))
    sound_sw = ctk.CTkSwitch(scroll_frame,
                             text='发通知时播放提示音（错误/多选/未知框；静默时段不响）')
    sound_sw.pack(anchor='w', pady=4)
    if cfg.get('sound_enabled', False):
        sound_sw.select()

    def _toggle_sound():
        cfg['sound_enabled'] = bool(sound_sw.get())
        config.save(cfg)
        if cfg['sound_enabled']:
            try:
                monitor._winsound_beep()  # 开启时响一声让用户确认音量
            except Exception:
                pass
    sound_sw.configure(command=_toggle_sound)

    # ── 静默时段 ──
    ctk.CTkLabel(scroll_frame, text='静默时段',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 0))
    ctk.CTkLabel(scroll_frame, text='静默时段内只记录日志，不发送桌面通知',
                 font=ctk.CTkFont(size=11), text_color='gray').pack(anchor='w', pady=(2, 4))

    quiet_sw = ctk.CTkSwitch(scroll_frame, text='启用静默时段')
    quiet_sw.pack(anchor='w', pady=4)
    if cfg.get('quiet_hours_enabled', False):
        quiet_sw.select()

    quiet_row = ctk.CTkFrame(scroll_frame, fg_color='transparent')
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

    # ── 单窗口策略 ──
    ctk.CTkLabel(scroll_frame, text='单窗口策略',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 0))
    ctk.CTkLabel(scroll_frame, text='记住每个窗口的策略（自动确认/仅通知/忽略），'
                 '按窗口标题持久化，重启后标题匹配的窗口自动套用',
                 font=ctk.CTkFont(size=11), text_color='gray',
                 wraplength=560, justify='left').pack(anchor='w', pady=(2, 4))

    persist_sw = ctk.CTkSwitch(scroll_frame, text='持久化单窗口策略（关闭则仅本次运行有效，重启即忘）')
    persist_sw.pack(anchor='w', pady=4)
    if cfg.get('persist_policies', True):
        persist_sw.select()

    def _toggle_persist():
        on = bool(persist_sw.get())
        cfg['persist_policies'] = on
        config.save(cfg)
        if on:
            monitor.load_policies()      # 重新从盘加载，立即套用
        else:
            monitor._persisted_policies.clear()  # 关闭：清掉持久态，仅留会话内策略
    persist_sw.configure(command=_toggle_persist)

    # ── 外观 ──
    ctk.CTkLabel(scroll_frame, text='外观',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(anchor='w', pady=(16, 0))

    _THEME_LABELS = {'跟随系统': 'system', '深色': 'dark', '浅色': 'light'}
    _THEME_REV    = {v: k for k, v in _THEME_LABELS.items()}
    _COLOR_LABELS = {'蓝': 'blue', '绿': 'green', '深蓝': 'dark-blue'}
    _COLOR_REV    = {v: k for k, v in _COLOR_LABELS.items()}

    row1 = ctk.CTkFrame(scroll_frame, fg_color='transparent')
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

    row2 = ctk.CTkFrame(scroll_frame, fg_color='transparent')
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


def _build_notification_history_page(frame):
    """构建通知历史页：显示所有通知类型的事件（notify/error/idle/unknown），
    支持按类型过滤和关键词搜索。"""
    global _notification_tree, _notification_filter, _notification_search

    header = ctk.CTkFrame(frame, fg_color='transparent')
    header.pack(fill='x', pady=(0, 8))
    ctk.CTkLabel(header, text='通知历史',
                 font=ctk.CTkFont(size=14, weight='bold')).pack(side='left')

    # 按钮栏
    btn_bar = ctk.CTkFrame(header, fg_color='transparent')
    btn_bar.pack(side='right')

    # 过滤下拉框
    filter_options = ['全部', '通知', '错误', '空闲', '未知']
    _notification_filter = ctk.CTkOptionMenu(btn_bar, values=filter_options, width=80)
    _notification_filter.set('全部')
    _notification_filter.pack(side='left', padx=3)

    # 搜索框
    _notification_search = ctk.CTkEntry(btn_bar, width=120, placeholder_text='搜索关键词')
    _notification_search.pack(side='left', padx=3)

    def _do_filter():
        _refresh_notification_history()

    ctk.CTkButton(btn_bar, text='🔍 筛选', width=60, command=_do_filter).pack(side='left', padx=3)

    def _clear_history():
        if messagebox.askyesno('清空历史', '确定要清空所有通知历史记录吗？'):
            monitor.EVENTS.clear()
            _refresh_notification_history()

    ctk.CTkButton(btn_bar, text='🗑️ 清空', width=60, command=_clear_history).pack(side='left', padx=3)

    # 表格
    cols = ('time', 'action', 'kind', 'title', 'detail')
    _notification_tree = ttk.Treeview(frame, columns=cols, show='headings',
                                      selectmode='browse', height=18)
    for col, head, w in [('time', '时间', 90), ('action', '类型', 100),
                         ('kind', '终端', 80), ('title', '标题', 200),
                         ('detail', '详情', 250)]:
        _notification_tree.heading(col, text=head)
        _notification_tree.column(col, width=w, anchor='w')
    _notification_tree.pack(fill='both', expand=True)

    # 双击跳转到对应终端（如果还存在）
    def _on_dbl(_e):
        item = _notification_tree.focus()
        if item:
            try:
                hwnd = int(_notification_tree.item(item, 'values')[4])  # 隐藏列存 hwnd
                monitor._bring_to_front(hwnd)
            except Exception:
                pass

    _notification_tree.bind('<Double-1>', _on_dbl)


def _refresh_notification_history():
    """刷新通知历史表格：过滤出通知类事件，应用筛选和搜索。"""
    if _notification_tree is None:
        return

    # 获取所有通知类事件（notify/error/idle/unknown）
    all_events = [e for e in monitor.EVENTS if e['action'] in ('notify', 'error', 'idle', 'unknown')]

    # 应用类型过滤
    filter_val = _notification_filter.get() if _notification_filter else '全部'
    filter_map = {'通知': 'notify', '错误': 'error', '空闲': 'idle', '未知': 'unknown'}
    if filter_val != '全部' and filter_val in filter_map:
        all_events = [e for e in all_events if e['action'] == filter_map[filter_val]]

    # 应用搜索
    search_kw = _notification_search.get().strip().lower() if _notification_search else ''
    if search_kw:
        all_events = [e for e in all_events
                      if search_kw in e['title'].lower() or search_kw in e.get('detail', '').lower()]

    # 清空表格
    for iid in _notification_tree.get_children():
        _notification_tree.delete(iid)

    # 填充表格（倒序：最新在上）
    action_icons = {'notify': '🔔 通知', 'error': '❌ 错误', 'idle': '🟠 空闲', 'unknown': '⚠️ 未知'}
    for ev in reversed(all_events[-200:]):  # 只显示最近 200 条
        ts = time.strftime('%H:%M:%S', time.localtime(ev['ts']))
        action = action_icons.get(ev['action'], ev['action'])
        vals = (ts, action, ev['kind'], ev['title'][:30], ev.get('detail', '')[:60])
        # iid 用 hwnd，但表格不显示，方便双击跳转
        _notification_tree.insert('', 'end', iid=str(ev['hwnd']), values=vals)


def _build_about_page(frame):
    global _about_status
    # 关于页内容较多，用滚动容器防止超出窗口被截断
    scroll_frame = ctk.CTkScrollableFrame(frame, fg_color='transparent')
    scroll_frame.pack(fill='both', expand=True)
    ctk.CTkLabel(scroll_frame, text='Claude Auto-Yes',
                 font=ctk.CTkFont(size=20, weight='bold')).pack(anchor='w', pady=(0, 4))
    ctk.CTkLabel(scroll_frame, text=f'版本 v{__version__}').pack(anchor='w')
    ctk.CTkLabel(scroll_frame, text='作者：huangzhuo').pack(anchor='w', pady=(8, 0))

    desc = (
        '后台监控多个终端里的 Claude Code，自动回应「是否继续」类确认框，\n'
        '需人工选择的菜单和错误状态则桌面通知（点击通知跳转到对应终端）。'
    )
    ctk.CTkLabel(scroll_frame, text=desc, justify='left',
                 font=ctk.CTkFont(size=11), text_color='gray').pack(anchor='w', pady=(10, 0))

    feats = (
        '主要功能：\n'
        '· 自动确认默认选中 Yes 的确认框，后台静默发回车\n'
        '· 多选菜单 / 错误 / 未知确认框 → 桌面通知，绝不乱按\n'
        '· 单窗口策略（自动确认 / 仅通知 / 忽略），可按标题持久化\n'
        '· 统计今日/累计动作次数，事件可导出 CSV\n'
        '· 静默时段、声音提示、自定义错误关键词、忽略列表\n'
        '· 定时暂停（30 分 / 1 时 / 2 时）自动恢复\n'
        '· 开机自启、单实例锁、明暗主题跟随系统'
    )
    ctk.CTkLabel(scroll_frame, text=feats, justify='left',
                 font=ctk.CTkFont(size=11)).pack(anchor='w', pady=(10, 0))

    link = ctk.CTkLabel(scroll_frame, text='GitHub 项目主页',
                        text_color=('blue', '#6db3f2'), cursor='hand2')
    link.pack(anchor='w', pady=(12, 0))
    link.bind('<Button-1>',
              lambda _e: webbrowser.open('https://github.com/huangzhuo-ai/claude-auto-confirm'))

    _about_status = ctk.CTkLabel(scroll_frame, text='')
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

    ctk.CTkButton(scroll_frame, text='检查更新', command=_manual_check).pack(anchor='w', pady=(8, 0))


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
    global _root, _tree, _log_box, _stats_labels, _notification_tree, _notification_filter, _notification_search
    cfg = config.load()
    ctk.set_appearance_mode(_THEME_MAP.get(cfg.get('theme', 'system'), 'system'))
    ctk.set_default_color_theme(_COLOR_MAP.get(cfg.get('color', 'blue'), 'blue'))

    root = ctk.CTk()
    _root = root
    root.title('Claude Auto-Yes · 状态面板')
    root.geometry('900x700')  # 增加默认高度以容纳图表
    root.minsize(800, 600)    # 设置最小尺寸
    root.resizable(True, True)  # 允许调整大小

    # 设置窗口图标（任务栏/Alt-Tab 显示）：用 AI 生成的品牌图标
    # 必须用 iconbitmap（不是 iconphoto），这样会设置 customtkinter 的
    # _iconbitmap_method_called 标志，阻止 ctk 内部用默认图标覆盖
    try:
        if getattr(sys, 'frozen', False):
            icon_path = os.path.join(sys._MEIPASS, 'icon.ico')
        else:
            icon_path = os.path.join(os.path.dirname(__file__), 'icon.ico')
        root.iconbitmap(icon_path)
        applog.log(f'  [panel] 窗口图标已设置(iconbitmap): {icon_path}')
    except Exception as e:
        applog.log(f'  [WARN] 窗口图标设置失败: {e}')

    root.withdraw()  # 先隐藏构建（预热场景不闪窗）；_poll_show 见到显示请求再 deiconify

    # 关闭按钮：不销毁窗口（销毁后无法在子线程安全重建），改为隐藏；再次双击托盘 deiconify
    root.protocol('WM_DELETE_WINDOW', root.withdraw)

    sidebar = ctk.CTkFrame(root, width=160, corner_radius=0)
    sidebar.pack(side='left', fill='y')
    sidebar.pack_propagate(False)
    ctk.CTkLabel(sidebar, text='⚡ Auto-Yes',
                 font=ctk.CTkFont(size=16, weight='bold')).pack(pady=(18, 16))

    content = ctk.CTkFrame(root, corner_radius=0, fg_color='transparent')
    content.pack(side='left', fill='both', expand=True)

    pages = {name: ctk.CTkFrame(content, fg_color='transparent')
             for name in ('监控', '日志', '通知历史', '设置', '关于')}

    def show(name):
        for p in pages.values():
            p.pack_forget()
        pages[name].pack(fill='both', expand=True, padx=16, pady=16)

    for name in ('监控', '日志', '通知历史', '设置', '关于'):
        ctk.CTkButton(sidebar, text=name, anchor='w',
                      command=lambda n=name: show(n)).pack(fill='x', padx=10, pady=3)

    status_lbl = ctk.CTkLabel(sidebar, text='', font=ctk.CTkFont(size=11))
    status_lbl.pack(side='bottom', pady=12)

    _build_monitor_page(pages['监控'])
    _build_log_page(pages['日志'])
    _build_notification_history_page(pages['通知历史'])
    _build_settings_page(pages['设置'])
    _build_about_page(pages['关于'])

    show('监控')
    updater.check_in_background(__version__, _on_update_found)

    def _poll_show():
        # 高频轻量轮询：被隐藏时再次双击托盘 → 立即重新显示并置顶（≤200ms 响应）
        if _show_request.is_set():
            _show_request.clear()
            try:
                root.deiconify()
                root.lift()
                root.focus_force()
            except Exception:
                pass
        root.after(200, _poll_show)

    def _refresh():
        # 窗口隐藏时跳过表格/日志的重刷新，省开销；显示时才更新
        try:
            visible = root.state() != 'withdrawn'
        except Exception:
            visible = True
        if visible:
            status_lbl.configure(
                text='⏸ 已暂停' if monitor.PAUSED.is_set()
                else f'监控中 · {monitor.STATS["windows"]} 个终端')
            _refresh_monitor()
            _refresh_log()
            _refresh_notification_history()
        root.after(1000, _refresh)

    root.after(0, _refresh)
    root.after(0, _poll_show)

    try:
        root.mainloop()
    finally:
        # mainloop 退出（异常或显式销毁）：清掉全局引用，让下次 open_panel 能干净重建
        _root = None
        _tree = None
        _log_box = None
        _stats_labels = {}
        _notification_tree = None
        _notification_filter = None
        _notification_search = None
