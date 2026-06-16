"""
Claude Code Auto-Yes Monitor
以「终端窗口」为单位扫描：用 UI Automation 读屏，自动回 y/Enter,其余桌面通知。
统一支持 Windows Terminal / 独立 PowerShell·CMD / VS Code 集成终端。
"""
import time, re, sys, argparse, threading, os
from collections import deque
import win32gui, win32con, win32api, win32process
from win11toast import toast
import terminal
import config
from applog import log
from version import __version__


def _asset_path(filename: str) -> str:
    """解析资源文件路径：打包后在 sys._MEIPASS，开发时在项目根。
    用于 icon.png 等打包进 exe 的数据文件。"""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def _find_inner_hwnd(top: int) -> int:
    """找 WT 顶层窗口下真正接收键盘的内层子窗口
    （Windows.UI.Input.InputSite.WindowClass）。找不到则回退到顶层。"""
    found = []
    def cb(h, _):
        cls = win32gui.GetClassName(h)
        if 'INPUT' in cls.upper() or 'XAML' in cls.upper():
            found.append((h, cls))
        return True
    try:
        win32gui.EnumChildWindows(top, cb, None)
    except Exception:
        pass
    for h, cls in found:
        if 'InputSite' in cls:
            return h
    return found[0][0] if found else top


def _post_enter(top: int, inner: int):
    """后台发回车：直接 PostMessage WM_KEYDOWN/UP 到内层 InputSite 窗口。
    隔离实测：纯 PostMessage 即可送达，且完全不抢 OS 前台、不抬升窗口；
    AttachThreadInput/SetFocus 反而会抢前台，故不用。top 仅作签名兼容保留。"""
    WM_KEYDOWN, WM_KEYUP, VK_RETURN = 0x0100, 0x0101, 0x0D
    lp_down, lp_up = 0x001C0001, 0xC01C0001  # Enter 扫描码 0x1C + 释放位
    win32api.PostMessage(inner, WM_KEYDOWN, VK_RETURN, lp_down)
    win32api.PostMessage(inner, WM_KEYUP,   VK_RETURN, lp_up)

AUTO_YES_RE = re.compile(
    r'Do you want to proceed\?|Do you want to create|Do you want to make this edit'
    r'|press enter to continue',
    re.IGNORECASE
)
# 确认框默认已选中「1. Yes」，只需回车；这是真正存在确认菜单的强特征
YES_MENU_RE = re.compile(r'^\s*[>❯]\s*1\.\s*Yes', re.MULTILINE)
# 确认框底部的操作提示——出现它基本可断定这是 Claude Code 的确认框
# 含 AskUserQuestion 风格菜单：Enter to select · ↑/↓ to navigate · Esc to cancel
PROMPT_FOOTER_RE = re.compile(
    r'Esc to cancel|Tab to amend|ctrl\+e to explain|don.t ask again|Enter to select',
    re.IGNORECASE
)
NOTIFY_RE = re.compile(
    r'which .+ (would|do) you|select .+ option|choose .+:|pick .+:|enter .+ number',
    re.IGNORECASE
)
# Claude 卡在错误/需登录状态——需人工介入，只通知不回车。
# 注意：不收录过宽的裸词（如 "Authentication"），否则 git/ssh 等正常输出会误报；
# 登录失效已由 "Please run /login" / "Invalid API key" 精确覆盖。
ERROR_RE = re.compile(
    r'Please run /login|API Error|context (low|left)|超过 ?200K|已达.*限制'
    r'|Credit balance is too low|rate limit|usage limit reached'
    r'|Invalid API key',
    re.IGNORECASE
)

CFG = config.load()
SCAN_INTERVAL = CFG['scan_interval']
WAITING_NOTIFY_SECONDS = CFG['waiting_notify_seconds']
# 忽略列表不在此缓存：_is_ignored() 每轮从 config 读，使面板编辑即时生效。
_last: dict[int, tuple] = {}        # 按 hwnd 去重
_idle_since: dict[int, float] = {}  # hwnd → 进入空闲态的 time.monotonic()
DRY_RUN = False                     # --dry-run 时只打印不发键

# Claude Code 空闲等待输入：底部输入框是一条「只有提示符」的行（> 或 ❯，
# 后面无文字）。实测真实终端渲染为 '>'；用户正在打字时该行会跟着输入内容，不算空闲。
IDLE_RE = re.compile(r'^\s*[>❯]\s*$', re.MULTILINE)

# 供托盘 UI 读取的运行时状态。
# windows/kinds：本轮扫描概览；rows：每个窗口的明细行（供面板表格渲染）。
# rows 每项：{hwnd, kind, title, state, detail, ts}
#   state ∈ running|idle|prompt|error|confirmed|idle_notified|watching
STATS = {'windows': 0, 'kinds': {}, 'last_action': '', 'rows': []}
_win_state: dict[int, dict] = {}  # hwnd → 该窗口最新状态（跨轮保留，供 UI 持续显示）

# 事件日志环形缓冲：每次实际动作（自动确认/通知/错误/空闲通知）追加一条，供面板倒序展示。
EVENTS: deque = deque(maxlen=200)

# 统计计数器：累计 + 今日（用于面板统计卡片）。持久化到 state.json，跨重启保留。
COUNTERS = {
    'total': {'auto_yes': 0, 'notify': 0, 'error': 0, 'idle': 0},
    'today': {'auto_yes': 0, 'notify': 0, 'error': 0, 'idle': 0, 'date': time.strftime('%Y-%m-%d')},
}


def load_counters():
    """启动时从 state.json 恢复计数器。若存档的 today 不是今天则今日清零、累计保留。"""
    import state
    data = state.load().get('counters')
    if not isinstance(data, dict):
        return
    today = time.strftime('%Y-%m-%d')
    total = data.get('total')
    if isinstance(total, dict):
        for k in COUNTERS['total']:
            COUNTERS['total'][k] = int(total.get(k, 0))
    saved_today = data.get('today')
    if isinstance(saved_today, dict) and saved_today.get('date') == today:
        for k in ('auto_yes', 'notify', 'error', 'idle'):
            COUNTERS['today'][k] = int(saved_today.get(k, 0))
        COUNTERS['today']['date'] = today
    else:
        # 存档是旧的一天（或缺失）：今日从零开始
        COUNTERS['today'] = {'auto_yes': 0, 'notify': 0, 'error': 0,
                             'idle': 0, 'date': today}


def save_counters():
    """把当前计数器写回 state.json（合并保留其它键，如 policies）。"""
    import state
    data = state.load()
    data['counters'] = COUNTERS
    state.save(data)

# 单窗口策略：hwnd → 'auto' | 'notify' | 'ignore'。缺省 'auto'（现有行为）。
#   auto   ：自动确认 yes 框，choice/error 通知（默认）
#   notify ：即便遇到默认选中 Yes 的框也不回车，改为通知
#   ignore ：完全跳过该窗口（不读屏、不通知）
_policy: dict[int, str] = {}

# 持久化策略：窗口标题 → policy。hwnd 重启会变，无法持久化；标题是稳定属性，
# 故按标题存盘。重启后标题匹配的窗口自动套用（与 ignored_titles 的模型一致）。
_persisted_policies: dict[str, str] = {}

# 全局暂停开关：tray 与 panel 共用同一个 Event（从 tray 迁来，集中到 monitor）。
PAUSED = threading.Event()

# 定时自动恢复：pause_for(秒) 暂停一段时间后自动恢复。重复调用会取消上一个 timer。
_pause_timer: threading.Timer | None = None
_pause_timer_lock = threading.Lock()


def cancel_pause_timer():
    """取消待定的自动恢复 timer（手动恢复/退出时调用，避免旧 timer 误触）。"""
    global _pause_timer
    with _pause_timer_lock:
        if _pause_timer is not None:
            _pause_timer.cancel()
            _pause_timer = None


def pause_for(seconds: float):
    """暂停监控并在 seconds 秒后自动恢复。取消上一个未到期的 timer。"""
    global _pause_timer
    with _pause_timer_lock:
        if _pause_timer is not None:
            _pause_timer.cancel()
        PAUSED.set()

        def _resume():
            global _pause_timer
            PAUSED.clear()
            with _pause_timer_lock:
                _pause_timer = None
            log(f'[RESUME] 定时暂停到期，已自动恢复监控')

        _pause_timer = threading.Timer(seconds, _resume)
        _pause_timer.daemon = True
        _pause_timer.start()
    log(f'[PAUSE] 已暂停，将在 {int(seconds)}s 后自动恢复')


def _log_event(win: dict, action: str, detail: str = ''):
    """追加一条事件到环形缓冲。action ∈ auto_yes|notify|error|idle。"""
    EVENTS.append({
        'ts': time.time(), 'hwnd': win['hwnd'], 'kind': win['kind'],
        'title': win['title'], 'action': action, 'detail': detail,
    })
    # 更新统计计数器
    today = time.strftime('%Y-%m-%d')
    if COUNTERS['today']['date'] != today:
        # 日期变了，重置今日计数
        COUNTERS['today'] = {'auto_yes': 0, 'notify': 0, 'error': 0, 'idle': 0, 'date': today}
    if action in COUNTERS['total']:
        COUNTERS['total'][action] += 1
        COUNTERS['today'][action] += 1
        save_counters()  # 落盘，跨重启保留


def get_policy(hwnd: int) -> str:
    return _policy.get(hwnd, 'auto')


def set_policy(hwnd: int, policy: str, title: str | None = None):
    """面板调用：设置单窗口策略。policy ∈ auto|notify|ignore。
    title 非空且 persist_policies 开启时同时持久化（按标题存盘，
    重启后标题匹配的窗口自动套用）；开关关闭时仅会话内生效、重启即忘。"""
    persist = title and config.load().get('persist_policies', True)
    if policy == 'auto':
        _policy.pop(hwnd, None)
        if persist:
            _persisted_policies.pop(title, None)
            save_policies()
    else:
        _policy[hwnd] = policy
        if persist:
            _persisted_policies[title] = policy
            save_policies()


def resolve_policy(hwnd: int, title: str) -> str:
    """解析某窗口的有效策略：会话内 hwnd 设置优先，否则回退到按标题持久化的策略。"""
    if hwnd in _policy:
        return _policy[hwnd]
    return _persisted_policies.get(title, 'auto')


def load_policies():
    """启动时从 state.json 恢复按标题的持久化策略。开关关闭时跳过（不读盘）。"""
    if not config.load().get('persist_policies', True):
        return
    import state
    data = state.load().get('policies')
    if isinstance(data, dict):
        _persisted_policies.clear()
        for title, pol in data.items():
            if pol in ('notify', 'ignore'):
                _persisted_policies[str(title)] = pol


def save_policies():
    """把持久化策略写回 state.json（合并保留其它键，如 counters）。"""
    import state
    data = state.load()
    data['policies'] = dict(_persisted_policies)
    state.save(data)


def is_quiet_hours(now=None) -> bool:
    """判断当前是否处于静默时段（只记录不通知）。
    now 可传入 datetime.time 用于测试，缺省取当前时刻。"""
    cfg = config.load()
    if not cfg.get('quiet_hours_enabled', False):
        return False

    try:
        from datetime import datetime
        if now is None:
            now = datetime.now().time()
        start_str = cfg.get('quiet_hours_start', '22:00')
        end_str = cfg.get('quiet_hours_end', '08:00')

        start_time = datetime.strptime(start_str, '%H:%M').time()
        end_time = datetime.strptime(end_str, '%H:%M').time()

        # 跨日情况（如 22:00 - 08:00）
        if start_time > end_time:
            return now >= start_time or now < end_time
        else:
            return start_time <= now < end_time
    except Exception:
        return False


# ── 漏报样本落盘 ──────────────────────────────────────────────
# 「看见确认框 footer 却无法分类」时，把整屏文本存成样本，供改版排查与回归测试。
_misfire_sigs: set[str] = set()  # 已落盘的内容签名，跨轮去重


def _misfires_dir():
    """样本目录：与可执行文件/脚本同目录下的 misfires/（兼容 PyInstaller frozen）。"""
    import pathlib
    if getattr(sys, 'frozen', False):
        base = pathlib.Path(sys.executable).parent
    else:
        base = pathlib.Path(__file__).parent
    return base / 'misfires'


def _save_misfire(win: dict, text: str) -> str | None:
    """落盘一个未知确认框样本（带内容去重）。返回文件路径，跳过则 None。"""
    sig = _prompt_signature(text)
    if sig in _misfire_sigs:
        return None
    if len(_misfire_sigs) > 200:   # 极端防膨胀，正常用不到
        _misfire_sigs.clear()
    _misfire_sigs.add(sig)
    try:
        d = _misfires_dir()
        d.mkdir(parents=True, exist_ok=True)
        ts = time.strftime('%Y%m%d-%H%M%S')
        path = d / f'{ts}-{win["hwnd"]}.txt'
        header = (
            f'# kind: {win["kind"]}\n'
            f'# title: {win["title"]}\n'
            f'# time: {time.strftime("%Y-%m-%d %H:%M:%S")}\n'
            f'# reason: footer matched but classification fell through\n'
            f'----\n'
        )
        path.write_text(header + text, encoding='utf-8')
        return str(path)
    except Exception as e:
        log(f'  [WARN] 样本落盘失败: {e}')
        return None


def _set_state(win: dict, state: str, detail: str = ''):
    """记录某窗口的最新状态，供状态面板读取。"""
    _win_state[win['hwnd']] = {
        'hwnd': win['hwnd'], 'kind': win['kind'],
        'title': win['title'], 'state': state, 'detail': detail,
        'ts': time.time(),
    }


def _tap_enter(hwnd: int) -> bool:
    """纯后台发回车：找到内层窗口 → AttachThreadInput+SetFocus 建立 XAML 焦点 →
    PostMessage 回车。不抢 OS 前台、不切 tab、不抬升窗口。"""
    inner = _find_inner_hwnd(hwnd)
    try:
        _post_enter(hwnd, inner)
        return True
    except Exception as e:
        log(f'  [WARN] PostMessage 失败: {e}')
        return False


def send_enter(hwnd: int) -> str:
    """发 Enter，发后验证确认框是否消失。返回 'ok' | 'still' | 'nofocus'。"""
    if not _tap_enter(hwnd):
        return 'nofocus'
    time.sleep(0.8)
    after = terminal.read_window_text(hwnd, rows=40)
    return 'ok' if detect_prompt(after) is None else 'still'


def _bring_to_front(hwnd: int):
    """把指定窗口带到前台（点击通知后跳转到对应终端）。
    WT 提前台常被系统拦截，故先 AttachThreadInput 借用前台线程输入队列。"""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        fg = win32gui.GetForegroundWindow()
        cur_tid = win32api.GetCurrentThreadId()
        fg_tid = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
        tgt_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
        attached = [t for t in {fg_tid, tgt_tid} if t and t != cur_tid]
        for tid in attached:
            win32process.AttachThreadInput(cur_tid, tid, True)
        try:
            win32gui.SetForegroundWindow(hwnd)
        finally:
            for tid in attached:
                win32process.AttachThreadInput(cur_tid, tid, False)
    except Exception as e:
        log(f'  [WARN] 跳转窗口失败: {e}')


def _winsound_beep():
    """播放系统提示音。单独抽出便于测试打桩。"""
    import winsound
    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)


def _play_sound():
    """按 config.sound_enabled 播放提示音。任何失败静默吞掉，绝不拖垮通知。"""
    try:
        if config.load().get('sound_enabled', False):
            _winsound_beep()
    except Exception:
        pass


def _notify_async(title: str, body: str, hwnd: int, scenario: str = 'default'):
    """后台线程发通知：toast() 阻塞等待点击，故放守护线程。点击通知 → 终端提前。
    静默时段：只记录日志，不发送桌面通知（也不响铃）。

    scenario 分场景优化（标题/正文/时长/按钮），消除「黑窗口」（加 icon）：
    - 'error': 错误关键词检测到，需要干预
    - 'idle': 空闲提醒（17s 未输入）
    - 'multi': 多选题需手动选
    - 'default': 其他（自动确认成功等）
    """
    if is_quiet_hours():
        log(f'  [静默时段] {title}: {body}')
        return
    _play_sound()

    # 图标：消除「黑窗口」——icon.png 是产品 logo(PNG 圆形)，toast appLogoOverride 需 PNG
    icon_path = _asset_path('icon.png')

    # 按场景定制：时长 + 按钮（Windows Toast 最佳实践）
    duration = 'short'  # short | long
    buttons = []

    if scenario == 'error':
        # 错误场景：长时长 + 跳转按钮，吸引注意
        duration = 'long'
        buttons = [{'activationType': 'protocol', 'arguments': f'jump:{hwnd}',
                    'content': '跳转终端', 'activationArgs': hwnd}]
        title = '⚠️ ' + title  # 前缀警告 emoji
    elif scenario == 'idle':
        # 空闲提醒：普通时长，无按钮（点击通知本身就跳转了）
        duration = 'short'
    elif scenario == 'multi':
        # 多选题：长时长 + 跳转按钮
        duration = 'long'
        buttons = [{'activationType': 'protocol', 'arguments': f'jump:{hwnd}',
                    'content': '去选择', 'activationArgs': hwnd}]
    # default 场景无特殊处理（短时长、无按钮）

    def run():
        try:
            # 按钮参数：win11toast 0.36+ 支持 buttons list
            kwargs = {'icon': icon_path, 'duration': duration, 'app_id': 'Claude Auto-Yes',
                      'on_click': lambda *_a: _bring_to_front(hwnd)}
            if buttons:
                # buttons 格式：[{'activationType': 'protocol', 'arguments': '...', 'content': 'text'}]
                # 但 win11toast 的 notify 参数名是 'button'/'buttons'，需查文档确认。
                # 保守起见先不传（toast 简单签名不一定支持），后续验证再开
                pass
            toast(title, body, **kwargs)
        except Exception as e:
            log(f'  [WARN] 通知失败: {e}')
    threading.Thread(target=run, daemon=True).start()


# Claude Code 输入框/状态行的 footer 特征行——普通 shell 不会出现，
# 是「这是 Claude 窗口」的强信号（即便回复滚走、底部只剩空输入框也成立）。
CLAUDE_FOOTER_RE = re.compile(
    r'for shortcuts|for agents|accept edits|esc to interrupt|to manage|shift\+tab to cycle',
    re.IGNORECASE
)


def looks_like_claude(text: str) -> bool:
    """粗判该终端窗口里跑的是不是 claude（避免对无关终端发键）。
    回复完滚走后底部可能只剩空输入框、无 claude 关键词，
    故把 Claude 输入框/确认框的 footer 特征也纳入判据。"""
    return bool(re.search(r'claude|esc to interrupt|accept edits|tell Claude', text, re.I)
                or PROMPT_FOOTER_RE.search(text)
                or CLAUDE_FOOTER_RE.search(text))


def _matches_error(line: str) -> bool:
    """该行是否命中错误特征：内置 ERROR_RE，或用户在 config 配置的额外关键词。
    自定义词按大小写不敏感的子串匹配（用户填裸词即可，无需懂正则）。"""
    if ERROR_RE.search(line):
        return True
    try:
        extra = config.load().get('extra_error_keywords', [])
    except Exception:
        extra = []
    low = line.lower()
    return any(kw and kw.lower() in low for kw in extra)


def detect_prompt(text: str):
    """判定当前屏幕**底部**是否有活动的确认框。
    返回 'yes' (默认选中Yes，可自动回车) | 'choice' (需人工选)
        | 'error' (卡死需人工) | 'unknown' (有框但不认识，落盘+通知) | None (无框)。

    关键：确认框必须紧贴屏幕底部——footer(Esc to cancel等)在最后 2 行内，
    否则就是已翻篇、滚到历史里的残留，不能误判。
    """
    lines = [l for l in text.splitlines()]
    # 去掉尾部纯空行
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 3:
        return None
    # 优先检测错误/卡死状态（登录失效、API错误、额度耗尽等）——需人工介入。
    # 这类提示常被任务挂件/输入框边框挤到偏上，故放宽到最后 15 行内即认定。
    if any(_matches_error(l) for l in lines[-15:]):
        return 'error'
    # footer 必须靠近底部（最后 6 行内）——容纳确认框下方可能挂着的任务列表挂件
    # （形如 "N tasks (...)" + "■ 当前任务"），但仍排除滚到历史里的旧框。
    tail = lines[-6:]
    if not any(PROMPT_FOOTER_RE.search(l) for l in tail):
        return None
    # footer 上方若干行里找选项菜单（窗口放宽到 12 行，覆盖菜单+挂件尾巴）
    window = lines[-12:]
    has_yes1 = any(YES_MENU_RE.search(l) for l in window)
    has_proceed = any(re.search(r'Do you want to|Would you like', l, re.I) for l in window)
    if not (has_yes1 or has_proceed):
        # 没有标准确认问句，但有编号选项 → AskUserQuestion 风格菜单，需人工
        has_numbered_opts = any(re.match(r'\s*[>❯]?\s*\d+\.', l) for l in window)
        if has_numbered_opts:
            return 'choice'
        # footer 命中（确实是个确认框）却无任何可识别菜单/问句 → 未知框。
        # 这是 Claude Code 改版后会掉进来的「沉默裂缝」：旧代码此处 return None，
        # 工具静默不动作；现改为 unknown，落盘样本 + 通知，绝不静默失效。
        return 'unknown'
    # 选项里是否含「实质性选择」——多个非 Yes/No 的有意义选项 → 需人工
    opts = [l for l in window if re.match(r'\s*[>❯]?\s*\d+\.', l)]
    nontrivial = [l for l in opts
                  if not re.search(r'\b(Yes|No)\b', l, re.I)
                  or re.search(r'tell .*what to do|edit .*script|amend', l, re.I)]
    if has_yes1:
        # 默认已选中 1.Yes：直接回车确认
        return 'yes'
    if nontrivial:
        return 'choice'
    # has_proceed=True 但没有 > 1.Yes 菜单，保守处理，通知用户
    return 'choice'


def _prompt_signature(text: str) -> str:
    """生成确认框去重签名：锚定『footer 及其上方的命令/问题/菜单』，
    排除 footer 下方会变化的任务挂件（"N tasks..."/"■ 当前任务"）。
    关键：不同命令必须产生不同签名，否则第一次回车后会把后续不同的确认框误去重。"""
    lines = [l for l in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    # 定位 footer 行（从底部往上 6 行内）
    foot = None
    for i in range(len(lines) - 1, max(-1, len(lines) - 7), -1):
        if PROMPT_FOOTER_RE.search(lines[i]):
            foot = i
            break
    if foot is None:
        # 没找到 footer 就退回最后 6 行（不应发生，detect_prompt 已先过滤）
        return '\n'.join(lines[-6:])[-200:]
    # 取 footer 及上方 11 行（含命令+问题+菜单），截断到 footer，剔除挂件
    body = lines[max(0, foot - 11): foot + 1]
    return '\n'.join(body)[-300:]


def is_idle_waiting(text: str) -> bool:
    """判断终端是否停在「Claude 空闲等待你输入」态。需同时满足：
      1) 没有运行中标志（esc to interrupt）；
      2) 底部 6 行内有一条「只有提示符」的空输入框行（> 或 ❯，后无文字）；
      3) 底部确为 Claude 输入框（有 CLAUDE_FOOTER 特征），排除普通 shell 的 '>'。
    用户正在输入框打字时（> 后跟内容）不匹配空行，自然排除，不会打扰。"""
    if re.search(r'esc to interrupt', text, re.I):
        return False  # 正在跑，不算空闲
    lines = [l for l in text.splitlines() if l.strip() != '']
    tail = lines[-6:]
    has_empty_prompt = any(IDLE_RE.match(l) for l in tail)
    is_claude_box = any(CLAUDE_FOOTER_RE.search(l) for l in tail)
    return has_empty_prompt and is_claude_box


def process(win: dict):
    hwnd, kind = win['hwnd'], win['kind']

    # 单窗口策略：会话内 hwnd 设置优先，否则回退到按标题持久化的策略。ignore → 完全跳过
    policy = resolve_policy(hwnd, win.get('title', ''))
    if policy == 'ignore':
        _set_state(win, 'ignored')
        _idle_since.pop(hwnd, None)
        return

    text = terminal.read_window_text(hwnd, rows=40)
    if not text or not looks_like_claude(text):
        _idle_since.pop(hwnd, None)
        _win_state.pop(hwnd, None)
        return

    kindp = detect_prompt(text)
    if not kindp:
        # 无确认框：检测「空闲等待输入」是否已持续超过阈值，是则通知一次
        if is_idle_waiting(text):
            now = time.monotonic()
            t0 = _idle_since.get(hwnd)
            if t0 is None:
                _idle_since[hwnd] = now
                _set_state(win, 'idle')
            elif (now - t0) >= WAITING_NOTIFY_SECONDS and _last.get(hwnd) != ('idle',):
                log(f'[WAITING]  [{kind}] hwnd={hwnd} 已空闲 {int(now - t0)}s，等你输入')
                _notify_async(
                    f'Claude 在等你输入 [{kind}]',
                    f'{win["title"][:40]}\n已完成，空闲 {int(now - t0)}s',
                    hwnd,
                    scenario='idle',
                )
                _last[hwnd] = ('idle',)
                _set_state(win, 'idle_notified', f'空闲 {int(now - t0)}s')
                _log_event(win, 'idle', f'空闲 {int(now - t0)}s')
            else:
                _set_state(win, 'idle')
        else:
            _idle_since.pop(hwnd, None)  # 又开始跑了，重置计时
            _set_state(win, 'running')
        return

    # 有活动确认框：清掉空闲计时
    _idle_since.pop(hwnd, None)
    sig = _prompt_signature(text)

    if kindp == 'yes':
        if policy == 'notify' and not DRY_RUN:
            # 仅通知模式：不回车，改发通知。按 ('notify', sig) 去重，
            # 同一确认框只通知一次，不随扫描轮次重复弹窗。
            if _last.get(hwnd) != ('notify', sig):
                log(f'[AUTO-YES][策略=notify 不发键] [{kind}] hwnd={hwnd}')
                _notify_async(
                    f'Claude 需要确认 [{kind}]（仅通知模式）',
                    f'{win["title"][:40]}\n{sig.strip()[-180:]}',
                    hwnd,
                    scenario='default',
                )
                _last[hwnd] = ('notify', sig)
                _set_state(win, 'prompt', '仅通知模式')
                _log_event(win, 'notify', '仅通知模式')
        elif DRY_RUN:
            if _last.get(hwnd) != ('yes', sig):
                log(f'[AUTO-YES][DRY-RUN 不发键] [{kind}] hwnd={hwnd}')
                _last[hwnd] = ('yes', sig)
                _set_state(win, 'prompt', 'DRY-RUN')
        else:
            if _last.get(hwnd) != ('yes', sig):
                r = send_enter(hwnd)
                msg = {'ok': '✅已确认', 'still': '⚠发了回车但框还在',
                       'nofocus': '⚠无法切到该窗口'}.get(r, r)
                log(f'[AUTO-YES] [{kind}] hwnd={hwnd} → {msg}')
                if r == 'ok':
                    _last[hwnd] = ('yes', sig)
                    _set_state(win, 'confirmed', msg)
                    _log_event(win, 'auto_yes', sig.strip()[-80:])
                else:
                    _set_state(win, 'prompt', msg)
    else:  # choice / error / unknown → 通知，绝不自动操作
        if _last.get(hwnd) != ('notify', sig):
            if kindp == 'error':
                log(f'[ERROR]    [{kind}] hwnd={hwnd} Claude 遇到错误需处理')
                _notify_async(
                    f'Claude 遇到错误 [{kind}]',
                    f'{win["title"][:40]}\n{sig.strip()[-180:]}',
                    hwnd,
                    scenario='error',
                )
                _set_state(win, 'error', sig.strip()[-80:])
                _log_event(win, 'error', sig.strip()[-80:])
            elif kindp == 'unknown':
                # 看见确认框 footer 却无法分类 → 落盘样本 + 通知，绝不静默。
                saved = _save_misfire(win, text)
                log(f'[UNKNOWN]  [{kind}] hwnd={hwnd} 未知确认框'
                    f'{"（已记录样本）" if saved else "（样本已存在）"}')
                _notify_async(
                    f'Claude 出现未知确认框 [{kind}]',
                    f'{win["title"][:40]}\n已记录样本，请手动处理并反馈',
                    hwnd,
                    scenario='default',
                )
                _set_state(win, 'unknown', sig.strip()[-80:])
                _log_event(win, 'unknown', sig.strip()[-80:])
            else:
                log(f'[NOTIFY]   [{kind}] hwnd={hwnd} 需要你选方案')
                _notify_async(
                    f'Claude 需要你选方案 [{kind}]',
                    f'{win["title"][:40]}\n{sig.strip()[-180:]}',
                    hwnd,
                    scenario='multi',
                )
                _set_state(win, 'prompt', sig.strip()[-80:])
                _log_event(win, 'notify', sig.strip()[-80:])
            _last[hwnd] = ('notify', sig)


def _is_ignored(title: str) -> bool:
    """窗口标题含任一忽略子串时跳过（不监控、不通知）。
    每次从 config 读取，使面板里的编辑无需重启即时生效。"""
    titles = config.load().get('ignored_titles', [])
    return any(s and s in title for s in titles)


def scan_once():
    """扫描一轮所有终端窗口并处理。更新 STATS 供托盘读取。"""
    wins = [w for w in terminal.list_terminal_windows()
            if not _is_ignored(w['title'])]
    kinds = {}
    for w in wins:
        kinds[w['kind']] = kinds.get(w['kind'], 0) + 1
    STATS['windows'] = len(wins)
    STATS['kinds'] = kinds
    # 清理已关闭窗口的去重记录、空闲计时、状态与策略
    alive = {w['hwnd'] for w in wins}
    for h in list(_last):
        if h not in alive:
            _last.pop(h, None)
    for h in list(_idle_since):
        if h not in alive:
            _idle_since.pop(h, None)
    for h in list(_win_state):
        if h not in alive:
            _win_state.pop(h, None)
    for h in list(_policy):
        if h not in alive:
            _policy.pop(h, None)
    for w in wins:
        try:
            process(w)
        except Exception as e:
            import traceback
            log(f'[ERROR] hwnd={w["hwnd"]}: {e}')
            log(traceback.format_exc())


def _status(line: str):
    """终端原地刷新状态行（每轮覆盖）。仅在有控制台时输出；
    frozen 无控制台（sys.stdout is None）时静默跳过——这行高频刷新不该进 app.log。"""
    if sys.stdout is not None:
        try:
            print(line, end='\r')
        except Exception:
            pass


def scan_loop(stop_event=None, paused_event=None):
    """循环扫描。stop_event 置位时退出；paused_event 兼容旧签名但已弃用——
    统一改用模块级 PAUSED Event（tray / panel 共用）。"""
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            if PAUSED.is_set():
                _status('[PAUSED] 已暂停                    ')
            else:
                scan_once()
                _status(f'[SCAN] {STATS["windows"]} 个终端窗口 {STATS["kinds"]}        ')
        except KeyboardInterrupt:
            log('退出')
            sys.exit(0)
        except Exception as e:
            log(f'[ERROR] {e}')
        time.sleep(SCAN_INTERVAL)


def main():
    global DRY_RUN
    ap = argparse.ArgumentParser(description='Claude Code Auto-Yes Monitor')
    ap.add_argument('--dry-run', action='store_true',
                    help='只检测并打印，不真正发送按键')
    ap.add_argument('--no-tray', action='store_true',
                    help='不启用系统托盘，退化为纯命令行模式')
    ap.add_argument('--allow-multi', action='store_true',
                    help='允许多开（跳过单实例锁，调试用）')
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    # 单实例锁：开机自启 + 手动双击可能拉起两个进程，两者会抢着发回车。
    # 拿不到锁说明已有实例在跑，提示后退出。--allow-multi 可跳过（调试用）。
    if not args.allow_multi:
        import singleton
        if not singleton.acquire():
            log('已有一个 Claude Auto-Yes 实例在运行，本次启动退出。'
                '（如需多开请加 --allow-multi）')
            if not args.no_tray:
                try:
                    toast('Claude Auto-Yes', '已有一个实例在运行，本次启动已退出')
                except Exception:
                    pass
            sys.exit(0)

    # 恢复持久化的统计计数器与单窗口策略（跨重启保留）
    load_counters()
    load_policies()

    mode = ' [DRY-RUN：只检测不发键]' if DRY_RUN else ''

    if args.no_tray:
        log(f'Claude Auto-Yes v{__version__} 启动（命令行模式）{mode}，扫描间隔 {SCAN_INTERVAL}s，Ctrl+C 退出')
        scan_loop()
    else:
        log(f'Claude Auto-Yes v{__version__} 启动（托盘模式）{mode}，扫描间隔 {SCAN_INTERVAL}s')
        import tray
        tray.run(DRY_RUN)


if __name__ == '__main__':
    main()
