"""
terminal.py —— 终端检测 + 屏幕读取（基于窗口，而非进程树/控制台缓冲）

关键事实（在本机实测得出）：
  * Win11 默认终端 = Windows Terminal，从 Explorer 启动的 cmd 都被 DefTerm
    交接给 WT（ConPTY），AttachConsole+ReadConsoleOutputW 读不到任何内容。
  * claude 的进程树一律是 claude.exe <- cmd.exe <- explorer.exe，无法据此
    区分它显示在哪种终端里。WT 通过交接附着，不是进程树父节点。
  * 唯一可靠的判别信号是**顶层窗口的类名**；UI Automation 的 TextPattern
    能统一读出 wt / VS Code / 经典 conhost 三种窗口的屏幕文本。

所以本模块以「终端窗口」为单位工作，不依赖 pid→窗口 映射。
"""
import win32gui
import win32process
import psutil

# 顶层窗口类名 → 终端类型
WINDOW_CLASSES = {
    'CASCADIA_HOSTING_WINDOW_CLASS': 'windows-terminal',
    'ConsoleWindowClass':            'conhost',   # 经典独立 PS/CMD 窗口
    'Chrome_WidgetWin_1':            'vscode',    # 需再用进程名确认是 Code.exe
}
# 这些不是真正的终端窗口，跳过
IGNORE_CLASSES = {'PseudoConsoleWindow'}

VSCODE_PROCS = {'code.exe', 'code - insiders.exe'}


def _proc_name(pid: int) -> str:
    try:
        return (psutil.Process(pid).name() or '').lower()
    except Exception:
        return ''


def classify_window(hwnd: int) -> str | None:
    """返回 'windows-terminal' | 'conhost' | 'vscode'，非终端返回 None。"""
    cls = win32gui.GetClassName(hwnd)
    if cls in IGNORE_CLASSES:
        return None
    kind = WINDOW_CLASSES.get(cls)
    if kind is None:
        return None
    if kind == 'vscode':
        # Chrome_WidgetWin_1 也可能是别的 Electron 应用，确认进程名
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if _proc_name(pid) not in VSCODE_PROCS:
            return None
    return kind


def list_terminal_windows() -> list[dict]:
    """枚举所有可见终端窗口。返回 [{hwnd, pid, kind, title}]。"""
    out = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        kind = classify_window(hwnd)
        if not kind:
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        out.append({
            'hwnd': hwnd,
            'pid': pid,
            'kind': kind,
            'title': win32gui.GetWindowText(hwnd),
        })

    win32gui.EnumWindows(cb, None)
    return out


# ---- 屏幕读取：UI Automation TextPattern（统一支持 wt / vscode / conhost）----
_auto = None

def _uia():
    global _auto
    if _auto is None:
        import uiautomation as auto
        auto.SetGlobalSearchTimeout(2)
        _auto = auto
    return _auto


def read_window_text(hwnd: int, rows: int = 40) -> str:
    """读取终端窗口当前屏幕文本。取支持 TextPattern 且内容最长的节点。"""
    auto = _uia()
    try:
        root = auto.ControlFromHandle(hwnd)
    except Exception:
        return ''
    best = ''

    def walk(c, depth=0):
        nonlocal best
        if depth > 9:
            return
        try:
            tp = c.GetPattern(auto.PatternId.TextPattern)
            if tp:
                txt = tp.DocumentRange.GetText(-1)
                if txt and len(txt) > len(best):
                    best = txt
        except Exception:
            pass
        # GetChildren() 对正在关闭/无响应的窗口会抛 COM 错误（-2147467259 等），
        # 单独容错：遍历失败就当此节点无子元素，不让整次读取崩掉。
        try:
            children = c.GetChildren()
        except Exception:
            children = []
        for ch in children:
            walk(ch, depth + 1)

    try:
        walk(root)
    except Exception:
        return ''
    if not best:
        return ''
    lines = [ln.rstrip() for ln in best.replace('\r\n', '\n').split('\n')]
    lines = [ln for ln in lines if ln.strip()]
    return '\n'.join(lines[-rows:])


def activate_tab(hwnd: int) -> bool:
    """切换到该窗口对应的标签页（WT 多标签必需：仅 SetForegroundWindow
    不会切 tab，回车会落到当前可见 tab）。用 UIA SelectionItemPattern.Select()。
    非 WT（conhost/vscode 单窗口）没有此问题，返回 True 即可。"""
    auto = _uia()
    try:
        root = auto.ControlFromHandle(hwnd)
    except Exception:
        return False
    try:
        ti = root.TabItemControl(searchDepth=6)
        if ti.Exists(0):
            sel = ti.GetPattern(auto.PatternId.SelectionItemPattern)
            if sel:
                sel.Select()
                return True
    except Exception:
        pass
    return False

