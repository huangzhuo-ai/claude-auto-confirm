# v3：检测健壮性 + 漏报诊断 设计

## 背景与动机

`claude-auto-confirm` 的全部价值是「无人值守自动确认」。但它的检测完全依赖
`monitor.py` 里一组硬编码正则去匹配 Claude Code 的界面文字
（`Esc to cancel` / `> 1. Yes` / `Do you want to` 等）。

**致命弱点——静默失效：** 一旦 Claude Code 改版、措辞变化，`detect_prompt`
会直接 `return None`，与「根本没有确认框」走同一条路。工具不报错、不通知、不留痕，
就是悄悄不干活了。对一个「装了就忘」的产品，静默失效是最致命的罪。

**已定位的沉默裂缝（monitor.py:229-232）：** 当屏幕底部确实有确认框 footer
（`PROMPT_FOOTER_RE` 命中＝强信号「这是个确认框」），但既没匹配 `1. Yes`、
也没有 `Do you want to`、又没有编号选项时，函数静默 `return None`。
这正是改版后会掉进去的坑：看见了框，却不认识，然后假装无事发生。

## 目标

把「看见了确认框 footer、却无法自信分类」从**沉默**变成**响亮**：

1. 新增第四种判定结果 `unknown`——「这里有个我不认识的框」。
2. 把 `unknown` 的整屏文字**落盘**成样本文件，供回归测试与改版排查。
3. 面板里标红告警 + 一键打开样本目录。
4. 每个真实样本都能直接转成回归测试夹具（复利：用得越久，越改不坏）。

## 非目标（YAGNI）

- **不做跨平台/多工具抽象。** 这一版只针对 Windows + Claude Code 做实。将来扩展
  时，本版收集的真实样本正是设计适配层最需要的数据——现在造抽象是空中楼阁。
- 不自动「猜」未知框该怎么操作——`unknown` 永远只通知、绝不自动回车。
- 不做样本上传/云端（单机自用）。
- 不改动已能正确分类的 yes/choice/error 逻辑。

## 检测改造

### detect_prompt 返回值扩展

`'yes' | 'choice' | 'error' | 'unknown' | None`

- `None`：底部无确认框 footer（真正的「没有框」）。
- `unknown`：**有** footer，但现有规则无法分类成 yes/choice/error。

把现行 229-232 行那条静默 `return None` 改为 `return 'unknown'`——前提是
此刻 footer 已命中（函数已过了 223 行的 footer 检查），所以「有框但不认识」
唯一的归宿就是 `unknown`，不再混入 `None`。

注意边界：223 行 footer 未命中时仍 `return None`（确实没框），不受影响。

### process() 对 unknown 的处理

走通知路径（同 choice），但：
- 状态记 `unknown`（面板标红，区别于普通 `prompt`）。
- 事件 action 记 `unknown`。
- **额外**：调用 `_save_misfire(win, text)` 落盘整屏样本（带去重，见下）。
- 通知文案明确提示「遇到未知确认框，已记录样本」，引导用户反馈。

## 样本落盘

### 位置

`misfires/` 目录，与可执行文件/脚本同目录（复用 config.py 的 frozen 路径逻辑，
保证打包后也写在 exe 旁，用户找得到）。`.gitignore` 忽略该目录（样本含用户屏幕内容，
不入库）。

### 文件格式

每个样本一个文件：`misfires/YYYYMMDD-HHMMSS-<hwnd>.txt`，内容：

```
# kind: windows-terminal
# title: <窗口标题>
# time: 2026-06-10 14:32:01
# reason: footer matched but classification fell through
----
<完整屏幕文本（read_window_text 原样，含 footer 与上下文）>
```

### 去重

同一未知框在多轮扫描里会反复出现，不能每轮写一个文件。复用现有 `_prompt_signature`
做内容签名：模块级 `_misfire_sigs: set[str]` 记已落盘签名，签名已存在则跳过。
窗口关闭时不清理该 set（样本本就该留存）；但用 `maxlen` 思路控制：set 超过 200 条
时清空（极端防膨胀，正常用不到）。

### 内容安全

样本含用户屏幕文本，可能有敏感信息。措施：
- 仅写本地 `misfires/`，永不上传。
- `.gitignore` 排除，绝不进版本库。
- 不在桌面通知正文里塞完整屏幕内容（仅提示「已记录样本」+ 末尾少量字符）。

## 面板改造

- 状态映射加 `unknown` → 「⚠️ 未知确认框」，用醒目标记（emoji + 后续可加行底色）。
- 事件日志 action 映射加 `unknown` → 「⚠️ 未知框（已记录）」。
- 顶部控制栏加按钮「打开样本目录」→ `os.startfile(misfires_dir)`（Windows 资源管理器
  打开该目录）；目录不存在时先创建。

## 涉及文件

- `monitor.py`（改）：
  - `detect_prompt`：229-232 的静默 `return None` 改为 `return 'unknown'`。
  - `process`：新增 `unknown` 分支（通知 + `_save_misfire` + 状态/事件）。
  - 新增 `_misfires_dir()` / `_save_misfire(win, text)` / `_misfire_sigs`。
- `panel.py`（改）：状态/动作映射加 `unknown`；加「打开样本目录」按钮。
- `.gitignore`（改）：加 `misfires/`。
- `tests/test_monitor_state.py`（改）：加 unknown 检测、落盘、去重、内容格式的测试。

## 测试策略

- **单元测试**：
  - 一屏「有 footer 但无任何可识别菜单/问句」的文本 → `detect_prompt` 返回 `unknown`。
  - 边界：无 footer 的普通屏 → 仍返回 `None`（不误报）。
  - 已知 yes/choice/error 屏 → 分类不变（回归保护）。
  - `process(unknown)` → 不发键、状态 `unknown`、事件 `unknown`、`misfires/` 落盘一个文件。
  - 同一 unknown 屏连续两轮 → 只落盘一个文件（去重）。
  - 落盘文件含 header（kind/title/time）+ 原始屏幕文本。
  - 落盘目录用 tmp_path 隔离（monkeypatch `_misfires_dir`），不污染真实目录。
- **真机自测**：实现者运行，确认面板能开、「打开样本目录」按钮可用；
  （无法真造 Claude 改版，故 unknown 路径主要靠单元测试 + 用一段构造文本验证落盘。）
- **回归**：全部既有测试通过。
