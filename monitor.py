"""
Claude Code Auto-Yes Monitor
以「终端窗口」为单位扫描：用 UI Automation 读屏，自动回 y/Enter，其余桌面通知。
统一支持 Windows Terminal / 独立 PowerShell·CMD / VS Code 集成终端。
"""
import time, re, sys, argparse, threading
import win32gui, win32con, win32api, win32process
from win11toast import toast
import terminal
import config


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
IGNORED_TITLES = CFG['ignored_titles']
_last: dict[int, tuple] = {}        # 按 hwnd 去重
_idle_since: dict[int, float] = {}  # hwnd → 进入空闲态的 time.monotonic()
DRY_RUN = False                     # --dry-run 时只打印不发键

# Claude Code 空闲等待输入：底部输入框是一条「只有提示符」的行（> 或 ❯，
# 后面无文字）。实测真实终端渲染为 '>'；用户正在打字时该行会跟着输入内容，不算空闲。
IDLE_RE = re.compile(r'^\s*[>❯]\s*$', re.MULTILINE)

# 供托盘 UI 读取的运行时状态
STATS = {'windows': 0, 'kinds': {}, 'last_action': ''}


def _tap_enter(hwnd: int) -> bool:
    """纯后台发回车：找到内层窗口 → AttachThreadInput+SetFocus 建立 XAML 焦点 →
    PostMessage 回车。不抢 OS 前台、不切 tab、不抬升窗口。"""
    inner = _find_inner_hwnd(hwnd)
    try:
        _post_enter(hwnd, inner)
        return True
    except Exception as e:
        print(f'  [WARN] PostMessage 失败: {e}')
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
        print(f'  [WARN] 跳转窗口失败: {e}')


def _notify_async(title: str, body: str, hwnd: int):
    """后台线程发通知：win11toast 的 notify() 不回调 Python 函数，
    必须用 toast()（内部 add_activated 注册回调），但它会阻塞等待点击事件，
    故放进守护线程。用户点击通知 → on_click 触发 → 把对应终端带到前台。"""
    def run():
        try:
            toast(title, body, app_id='Claude Auto-Yes',
                  on_click=lambda *_a: _bring_to_front(hwnd))
        except Exception as e:
            print(f'  [WARN] 通知失败: {e}')
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


def detect_prompt(text: str):
    """判定当前屏幕**底部**是否有活动的确认框。
    返回 'yes' (默认选中Yes，可自动回车) | 'choice' (需人工选) | None。

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
    if any(ERROR_RE.search(l) for l in lines[-15:]):
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
        return 'choice' if has_numbered_opts else None
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
    text = terminal.read_window_text(hwnd, rows=40)
    if not text or not looks_like_claude(text):
        _idle_since.pop(hwnd, None)
        return
    kindp = detect_prompt(text)
    if not kindp:
        # 无确认框：检测「空闲等待输入」是否已持续超过阈值，是则通知一次
        if is_idle_waiting(text):
            now = time.monotonic()
            t0 = _idle_since.get(hwnd)
            if t0 is None:
                _idle_since[hwnd] = now
            elif (now - t0) >= WAITING_NOTIFY_SECONDS and _last.get(hwnd) != ('idle',):
                print(f'[WAITING]  [{kind}] hwnd={hwnd} 已空闲 {int(now - t0)}s，等你输入')
                _notify_async(
                    f'Claude 在等你输入 [{kind}]',
                    f'{win["title"][:40]}\n已完成，空闲 {int(now - t0)}s',
                    hwnd,
                )
                _last[hwnd] = ('idle',)
        else:
            _idle_since.pop(hwnd, None)  # 又开始跑了，重置计时
        return
    # 有活动确认框：清掉空闲计时
    _idle_since.pop(hwnd, None)
    sig = _prompt_signature(text)

    if kindp == 'yes':
        if _last.get(hwnd) != ('yes', sig):
            if DRY_RUN:
                print(f'[AUTO-YES][DRY-RUN 不发键] [{kind}] hwnd={hwnd}')
                _last[hwnd] = ('yes', sig)
            else:
                r = send_enter(hwnd)
                msg = {'ok': '✅已确认', 'still': '⚠发了回车但框还在',
                       'nofocus': '⚠无法切到该窗口'}.get(r, r)
                print(f'[AUTO-YES] [{kind}] hwnd={hwnd} → {msg}')
                # 成功才记忆去重；失败下轮重试
                if r == 'ok':
                    _last[hwnd] = ('yes', sig)
    else:  # choice / error → 通知，不自动操作
        if _last.get(hwnd) != ('notify', sig):
            if kindp == 'error':
                print(f'[ERROR]    [{kind}] hwnd={hwnd} Claude 遇到错误需处理')
                _notify_async(
                    f'Claude 遇到错误 [{kind}]',
                    f'{win["title"][:40]}\n{sig.strip()[-180:]}',
                    hwnd,
                )
            else:
                print(f'[NOTIFY]   [{kind}] hwnd={hwnd} 需要你选方案')
                _notify_async(
                    f'Claude 需要你选方案 [{kind}]',
                    f'{win["title"][:40]}\n{sig.strip()[-180:]}',
                    hwnd,
                )
            _last[hwnd] = ('notify', sig)


def _is_ignored(title: str) -> bool:
    """窗口标题含任一 IGNORED_TITLES 子串时跳过（不监控、不通知）。"""
    return any(s and s in title for s in IGNORED_TITLES)


def scan_once():
    """扫描一轮所有终端窗口并处理。更新 STATS 供托盘读取。"""
    wins = [w for w in terminal.list_terminal_windows()
            if not _is_ignored(w['title'])]
    kinds = {}
    for w in wins:
        kinds[w['kind']] = kinds.get(w['kind'], 0) + 1
    STATS['windows'] = len(wins)
    STATS['kinds'] = kinds
    # 清理已关闭窗口的去重记录与空闲计时
    alive = {w['hwnd'] for w in wins}
    for h in list(_last):
        if h not in alive:
            _last.pop(h, None)
    for h in list(_idle_since):
        if h not in alive:
            _idle_since.pop(h, None)
    for w in wins:
        try:
            process(w)
        except Exception as e:
            import traceback
            print(f'\n[ERROR] hwnd={w["hwnd"]}: {e}')
            traceback.print_exc()


def scan_loop(stop_event=None, paused_event=None):
    """循环扫描。stop_event 置位时退出；paused_event 置位时跳过处理（暂停）。
    两个参数都为 None 时退化为 v1 的纯循环（Ctrl+C 退出）。"""
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            if paused_event is not None and paused_event.is_set():
                print('[PAUSED] 已暂停                    ', end='\r')
            else:
                scan_once()
                print(f'[SCAN] {STATS["windows"]} 个终端窗口 {STATS["kinds"]}        ', end='\r')
        except KeyboardInterrupt:
            print('\n退出')
            sys.exit(0)
        except Exception as e:
            print(f'[ERROR] {e}')
        time.sleep(SCAN_INTERVAL)


def main():
    global DRY_RUN
    ap = argparse.ArgumentParser(description='Claude Code Auto-Yes Monitor')
    ap.add_argument('--dry-run', action='store_true',
                    help='只检测并打印，不真正发送按键')
    ap.add_argument('--no-tray', action='store_true',
                    help='不启用系统托盘，退化为纯命令行模式')
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    mode = ' [DRY-RUN：只检测不发键]' if DRY_RUN else ''

    if args.no_tray:
        print(f'Claude Auto-Yes 启动（命令行模式）{mode}，扫描间隔 {SCAN_INTERVAL}s，Ctrl+C 退出\n')
        scan_loop()
    else:
        print(f'Claude Auto-Yes 启动（托盘模式）{mode}，扫描间隔 {SCAN_INTERVAL}s\n')
        import tray
        tray.run(DRY_RUN)


if __name__ == '__main__':
    main()
