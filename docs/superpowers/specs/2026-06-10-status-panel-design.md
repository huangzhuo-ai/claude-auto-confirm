# 状态面板（Status Panel）设计

## 背景与动机

`claude-auto-confirm` 当前在后台静默运行：扫描终端窗口、自动回车、必要时发桌面通知。
用户唯一的「界面」是托盘图标 + 右键菜单（状态行 / 暂停 / 退出）——等于黑盒。

这工具的命脉是**信任**：它替用户按回车。如果用户看不见它在监控哪些窗口、刚才自动
点了哪个、有没有误判/漏判，就会忍不住盯着终端，工具的价值大打折扣。

关键发现：`monitor.py` 里其实已埋了面板的地基——`STATS['rows']`、`_win_state` 字典、
`_set_state()` 函数，注释明写「供托盘 UI 读取 / 供面板表格渲染」，但 `_set_state()`
**从未被调用**，这套数据是空的、没接上。本设计就是把这条线接通并点亮。

## 目标

把后台黑盒变成「玻璃座舱」：
1. 一个可按需打开的窗口，实时显示每个 Claude 窗口的状态。
2. 一条滚动事件日志，记录自动确认/通知了哪个、何时。
3. 单窗口策略：对某个窗口设「自动确认 / 仅通知 / 完全忽略」，解决「只能全局暂停」的痛点。

## 非目标（YAGNI）

- 不做 Web 服务 / 浏览器仪表盘（单机自用，过度）。
- 不做检测正则的可视化编辑器（另一个独立项目）。
- 不改动现有检测逻辑（`detect_prompt` / `is_idle_waiting` / 正则）；只把状态暴露出来。
- 不持久化单窗口策略（hwnd 随窗口生灭，会话级足够）。

## 技术选型

- **tkinter（Python 自带）**：不引入新的重运行时依赖，打包 exe 不变胖。
- 后台扫描循环不变，面板只是观察 + 操作窗口；关掉面板不影响监控。

## 架构

### 共享运行时状态（集中到 monitor.py）

`monitor.py` 是核心，`tray.py` 和新建的 `panel.py` 都依赖它，它不依赖任何一方（无环）。
把所有「运行时控制 + 观测」状态集中在此：

| 名称 | 类型 | 作用 | 现状 |
|------|------|------|------|
| `_win_state` | `dict[hwnd, dict]` | 每窗口最新状态，供面板表格 | 已存在，待接线 |
| `_set_state()` | func | 写 `_win_state` | 已存在，待调用 |
| `EVENTS` | `deque(maxlen=200)` | 事件日志环形缓冲 | 新增 |
| `_log_event()` | func | 追加一条事件 | 新增 |
| `_policy` | `dict[hwnd, str]` | 单窗口策略 auto/notify/ignore | 新增 |
| `get_policy/set_policy` | func | 策略读写 | 新增 |
| `PAUSED` | `threading.Event` | 全局暂停（从 tray 迁来，tray/panel 共用） | 迁移 |
| `DRY_RUN` | `bool` | 干跑开关（已存在，panel 可切） | 已存在 |

线程模型：
- 主线程：`pystray` 托盘（不变，最低风险）。
- 子线程：`monitor.scan_loop`（不变）。
- 面板线程：按需创建，**独占**自己的 `tk.Tk()` + `mainloop()`，用 `root.after()` 轮询。

线程安全：面板线程只**读** `_win_state` / `EVENTS`（快照拷贝），只**写** `_policy` /
`PAUSED` / `DRY_RUN`。监控线程读 `_policy`/`PAUSED`/`DRY_RUN`、写 `_win_state`/`EVENTS`。
两边交换的都是普通 dict/deque/Event，CPython GIL 下这些原子操作无需额外锁。
Tcl 解释器绑定到面板线程且只被该线程访问，因此 tkinter 在子线程运行是安全的。

## 状态机（process() 记录的窗口状态）

每轮扫描对每个窗口落一个状态字符串，供面板表格渲染：

| state | 含义 | 触发 |
|-------|------|------|
| `ignored` | 单窗口策略=忽略 | `_policy[hwnd]=='ignore'` |
| `running` | Claude 正在跑 | 非空闲、无确认框 |
| `idle` | 空闲等输入（未到通知阈值） | `is_idle_waiting` 且未超时 |
| `idle_notified` | 空闲已通知 | 空闲超 `waiting_notify_seconds` |
| `confirmed` | 刚自动回车确认 | `detect_prompt=='yes'` 且策略=auto，发送 ok |
| `prompt` | 需人工处理 | `choice` / 仅通知模式 / 回车失败 |
| `error` | 卡死/错误 | `detect_prompt=='error'` |

非 Claude 窗口：从 `_win_state` 移除（面板只显示 Claude 窗口）。
窗口关闭：在 `scan_once` 清理阶段一并从 `_win_state`/`_policy`/`_last`/`_idle_since` 移除。

## 事件日志

每发生一次实际动作就追加一条（去重命中、未真正动作时不记）：

```
{'ts': float, 'hwnd': int, 'kind': str, 'title': str, 'action': str, 'detail': str}
```

`action ∈ {'auto_yes', 'notify', 'error', 'idle'}`。面板底部按时间倒序展示最近若干条。

## 单窗口策略

`_policy[hwnd]` 默认 `'auto'`，可设为：
- `'auto'`：现有行为（自动确认 yes 框，通知 choice/error）。
- `'notify'`：即使遇到默认选中 Yes 的确认框也**不**自动回车，改为通知（去重键 `('notify', sig)`）。
- `'ignore'`：完全跳过该窗口（不读屏、不通知），状态记 `ignored`。

与现有的标题级 `IGNORED_TITLES` 和全局 `PAUSED` 互补、不冲突。

## 面板 UI

- **上半部**：`ttk.Treeview` 表格，列＝类型 / 标题 / 状态 / 最近动作 / 时间。每行 iid＝hwnd。
- **下半部**：只读 `Text`，事件日志（倒序）。
- **行操作**：选中某行后三个按钮「自动确认 / 仅通知 / 忽略」写该 hwnd 策略；双击行
  调 `monitor._bring_to_front(hwnd)` 跳到对应终端。
- **全局**：暂停/恢复按钮（切 `PAUSED`）、干跑开关（切 `DRY_RUN`）。
- 刷新：`root.after(1000, refresh)` 每秒重画表格与日志。
- 单例：托盘「打开面板」若面板线程已存活则不重复开。

## 测试策略

- **单元测试（pytest，新建 `tests/`）**：monkeypatch `terminal.read_window_text`
  返回预设屏幕文本、`monitor._notify_async` 记录调用、`monitor.send_enter` 打桩，
  驱动 `process()`，断言 `_win_state` 状态、`EVENTS` 内容、策略分支、去重行为。
  覆盖 yes/choice/error/idle/running 五种屏幕 × auto/notify/ignore 策略。
- **手动真机验证（实现者自测）**：实际运行 `python monitor.py`，开真实 Claude 终端，
  打开面板，确认表格实时更新、日志滚动、双击跳转、三个策略按钮、暂停/干跑开关都生效。
- **回归**：现有自动回车/通知/空闲/去重行为不被破坏（由单元测试 + 真机验证共同保证）。

## 涉及文件

- `monitor.py`（改）：新增 `EVENTS/_log_event/_policy/get_policy/set_policy/PAUSED`；
  在 `process()` 各分支调用 `_set_state` + `_log_event`、尊重 `_policy`；`scan_once`
  清理 `_policy`。
- `panel.py`（新建）：tkinter 面板，`open_panel()` 单例开窗。
- `tray.py`（改）：菜单加「打开面板」；`_paused` 改用 `monitor.PAUSED`。
- `tests/test_monitor_state.py`（新建）：上述单元测试。
- `claude-auto-confirm.spec`：通常无需改（panel 经 import 链自动纳入，tkinter 有内置 hook）；
  打包时验证。
```
