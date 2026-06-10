"""
状态面板（tkinter）：实时表格 + 事件日志 + 单窗口策略控制。
通过 open_panel() 单例开窗，关掉面板不影响后台监控。
"""
import time
import threading
import tkinter as tk
from tkinter import ttk

import monitor

# ── 状态显示映射 ──────────────────────────────────────────────
_STATE_ICONS = {
    'running':       '🔵 运行中',
    'idle':          '🟡 空闲',
    'idle_notified': '🟠 空闲已通知',
    'confirmed':     '✅ 已自动确认',
    'prompt':        '🔴 需处理',
    'error':         '❌ 错误',
    'unknown':       '⚠️ 未知确认框',
    'ignored':       '⚫ 已忽略',
}
_ACTION_LABELS = {
    'auto_yes': '✅ 自动确认',
    'notify':   '🔔 已通知',
    'error':    '❌ 错误通知',
    'unknown':  '⚠️ 未知框(已记录)',
    'idle':     '🟠 空闲通知',
}

# ── 单例 ─────────────────────────────────────────────────────
_panel_thread: threading.Thread | None = None
_panel_lock = threading.Lock()


def open_panel():
    """从托盘菜单调用：若面板已开则置前台，否则新建。"""
    global _panel_thread
    with _panel_lock:
        if _panel_thread is not None and _panel_thread.is_alive():
            return  # 已在运行，tkinter 无法跨线程置顶，忽略即可
        _panel_thread = threading.Thread(target=_run_panel, daemon=True, name='panel')
        _panel_thread.start()


# ── 面板主体 ─────────────────────────────────────────────────
def _run_panel():
    root = tk.Tk()
    root.title('Claude Auto-Yes · 状态面板')
    root.geometry('860x520')
    root.resizable(True, True)

    # ── 顶部全局控制栏 ────────────────────────────────────────
    bar = tk.Frame(root, pady=4)
    bar.pack(fill='x', padx=8)

    pause_var = tk.BooleanVar(value=monitor.PAUSED.is_set())

    def _toggle_pause():
        if monitor.PAUSED.is_set():
            monitor.PAUSED.clear()
        else:
            monitor.PAUSED.set()
        pause_var.set(monitor.PAUSED.is_set())

    tk.Checkbutton(bar, text='⏸ 暂停监控', variable=pause_var,
                   command=_toggle_pause).pack(side='left', padx=4)

    dry_var = tk.BooleanVar(value=monitor.DRY_RUN)

    def _toggle_dry():
        monitor.DRY_RUN = dry_var.get()

    tk.Checkbutton(bar, text='🧪 干跑（只检测不发键）', variable=dry_var,
                   command=_toggle_dry).pack(side='left', padx=4)

    tk.Label(bar, text='选中行后设策略：').pack(side='left', padx=(16, 2))
    for label, policy in [('自动确认', 'auto'), ('仅通知', 'notify'), ('忽略', 'ignore')]:
        tk.Button(bar, text=label,
                  command=lambda p=policy: _set_selected_policy(tree, p)
                  ).pack(side='left', padx=2)

    tk.Button(bar, text='📁 样本目录', command=_open_misfires_dir
              ).pack(side='right', padx=4)

    # ── 窗口状态表格 ───────────────────────────────────────────
    cols = ('kind', 'title', 'policy', 'state', 'detail', 'ts')
    tree = ttk.Treeview(root, columns=cols, show='headings', height=10,
                        selectmode='browse')
    for col, heading, width in [
        ('kind',   '类型',    90),
        ('title',  '标题',   240),
        ('policy', '策略',    70),
        ('state',  '状态',   130),
        ('detail', '详情',   180),
        ('ts',     '更新时间', 80),
    ]:
        tree.heading(col, text=heading)
        tree.column(col, width=width, anchor='w')
    tree.pack(fill='both', expand=False, padx=8, pady=(2, 0))

    # 双击跳转到对应终端
    def _on_dbl(event):
        item = tree.focus()
        if item:
            try:
                hwnd = int(item)
                monitor._bring_to_front(hwnd)
            except Exception:
                pass

    tree.bind('<Double-1>', _on_dbl)

    # ── 事件日志 ───────────────────────────────────────────────
    tk.Label(root, text='事件日志', anchor='w').pack(fill='x', padx=8, pady=(6, 0))
    log_frame = tk.Frame(root)
    log_frame.pack(fill='both', expand=True, padx=8, pady=(0, 8))
    log_text = tk.Text(log_frame, state='disabled', wrap='none',
                       font=('Consolas', 9), height=8)
    sb_v = tk.Scrollbar(log_frame, orient='vertical', command=log_text.yview)
    sb_h = tk.Scrollbar(log_frame, orient='horizontal', command=log_text.xview)
    log_text.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
    sb_v.pack(side='right', fill='y')
    sb_h.pack(side='bottom', fill='x')
    log_text.pack(side='left', fill='both', expand=True)

    _log_snapshot = [None]  # 上次渲染的事件快照，避免每帧重绘

    # ── 刷新逻辑 ───────────────────────────────────────────────
    def _refresh():
        # 同步全局开关变量（其他地方也可能改）
        pause_var.set(monitor.PAUSED.is_set())
        dry_var.set(monitor.DRY_RUN)

        # 刷新表格：快照 _win_state
        snap = dict(monitor._win_state)
        existing = set(tree.get_children())
        seen = set()
        for hwnd, row in snap.items():
            iid = str(hwnd)
            seen.add(iid)
            vals = (
                row.get('kind', ''),
                row.get('title', '')[:50],
                get_policy_label(hwnd),
                _STATE_ICONS.get(row.get('state', ''), row.get('state', '')),
                row.get('detail', '')[:60],
                time.strftime('%H:%M:%S', time.localtime(row.get('ts', 0))),
            )
            if iid in existing:
                tree.item(iid, values=vals)
            else:
                tree.insert('', 'end', iid=iid, values=vals)
        for iid in existing - seen:
            tree.delete(iid)

        # 刷新日志：仅在内容变化时重绘
        events = list(monitor.EVENTS)
        if events != _log_snapshot[0]:
            _log_snapshot[0] = events
            log_text.configure(state='normal')
            log_text.delete('1.0', 'end')
            for ev in reversed(events):
                ts = time.strftime('%H:%M:%S', time.localtime(ev['ts']))
                action = _ACTION_LABELS.get(ev['action'], ev['action'])
                line = f"{ts}  {action:<12}  [{ev['kind']}] {ev['title'][:35]}  {ev['detail'][:60]}\n"
                log_text.insert('end', line)
            log_text.configure(state='disabled')

        root.after(1000, _refresh)

    root.after(0, _refresh)
    root.mainloop()


def get_policy_label(hwnd: int) -> str:
    return {'auto': '自动', 'notify': '仅通知', 'ignore': '忽略'}.get(
        monitor.get_policy(hwnd), '自动')


def _set_selected_policy(tree: ttk.Treeview, policy: str):
    item = tree.focus()
    if not item:
        return
    try:
        hwnd = int(item)
        monitor.set_policy(hwnd, policy)
        # 立即刷新该行的策略列
        vals = list(tree.item(item, 'values'))
        if len(vals) >= 3:
            vals[2] = get_policy_label(hwnd)
            tree.item(item, values=vals)
    except Exception:
        pass


def _open_misfires_dir():
    """在资源管理器打开漏报样本目录（不存在则先创建）。"""
    import os
    d = monitor._misfires_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))   # Windows 专用：用默认程序（资源管理器）打开
    except Exception:
        pass

