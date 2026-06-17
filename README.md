# claude-auto-confirm

后台自动监控多个终端里的 Claude Code，对"是否继续"类确认框自动回车，对需要人工选择的菜单和错误状态发送桌面通知（点击通知可直接跳转到对应终端）。

## 功能

- 扫描所有终端窗口（Windows Terminal / PowerShell·CMD / VS Code 集成终端）
- **自动确认**：检测到 `> 1. Yes` 默认选中的确认框 → 后台静默发回车，不抢前台
- **多选菜单**：需要人工选择的菜单（AskUserQuestion 风格）→ 桌面通知，绝不自动回车
- **错误通知**：Claude 卡在登录失效 / API 错误 / 额度耗尽 / 上下文超限等状态 → 桌面通知；错误关键词可在设置页自定义补充
- **全局快捷键**：
  - `Ctrl+Alt+P`：暂停/恢复监控（可自定义）
  - `Ctrl+Alt+C`：打开/显示面板（可自定义）
  - `Ctrl+Alt+M`：临时禁用快捷键（可自定义）
- **通知历史**：独立页面记录所有通知，支持按类型过滤和关键词搜索，双击跳转到对应终端
- **高级过滤规则**：
  - 基于窗口标题的正则表达式匹配
  - 基于屏幕内容关键词的过滤
  - 规则优先级排序，支持启用/禁用
- **多配置方案**：
  - 支持 `config.toml`（默认）、`config.work.toml`、`config.debug.toml` 等多方案
  - 托盘菜单和设置页快速切换
  - 新建/重命名/删除/另存为方案
- **命令行增强**：
  - `--config <path>`：指定配置文件
  - `--profile <name>`：加载指定配置方案
  - `--stats`：打印统计信息后退出
  - `--reset-stats`：重置统计数据
  - `--export-events <path>`：导出事件日志到CSV
- **统计增强**：
  - 按窗口统计（哪个终端确认最多）
  - 按小时统计（哪个时段活动最频繁）
  - 最近7天趋势图
- **声音提示**：发通知时可选播放提示音（设置页开关，受静默时段约束）
- **点击跳转**：点击任意通知，自动把对应终端窗口带到前台
- 按签名去重，同一个状态只通知一次
- **开机自启**：托盘菜单或面板一键开关（在用户「启动」文件夹放快捷方式，无需管理员权限；避开部分安全软件清除 Run 注册表键的问题）
- **托盘菜单**：双击图标打开面板；状态行显示今日已确认次数；可一键暂停或定时暂停（30 分钟 / 1 小时 / 2 小时）到点自动恢复
- **单实例锁**：命名 mutex 保证只跑一个进程，避免开机自启 + 手动双击时两个实例抢着发键
- **状态面板**：CustomTkinter 左侧边栏界面，监控/日志/通知历史/设置/关于五页；明暗主题跟随系统、可在设置页即时切换
- **统计卡片**：监控页顶部显示今日/累计的自动确认、通知、错误、空闲次数
- **事件导出**：日志页可一键「打开日志目录」「打开样本目录」，或把当前事件流「导出」为 CSV
- **忽略列表可视化**：设置页直接增删忽略的窗口标题关键词，无需手改 toml
- **静默时段**：设置页可配置某时段（支持跨日，如 22:00–08:00）只记录日志、不弹桌面通知
- **单窗口策略持久化**：每个窗口可设自动确认/仅通知/忽略，按标题记住跨重启套用；设置页可关闭（关闭则仅本次运行有效）
- **更新检查**：启动后台静默查 GitHub Releases，关于页可手动「检查更新」，发现新版给跳转链接（不自动下载）
- `--dry-run` 模式：只检测打印，不发送按键

## 环境要求

Windows 10/11，Python 3.10+

```
pip install pywin32 psutil uiautomation win11toast pystray pillow customtkinter darkdetect pynput matplotlib
```

或使用 `requirements.txt`：

```bash
pip install -r requirements.txt
```

## 使用

```bash
# 正常运行
python monitor.py

# 只检测，不发键（调试用）
python monitor.py --dry-run

# 允许多开（调试用；正常情况下单实例锁会拦下第二个进程）
python monitor.py --allow-multi

# 指定配置文件
python monitor.py --config custom.toml

# 加载指定配置方案
python monitor.py --profile work

# 打印统计信息后退出
python monitor.py --stats

# 重置统计数据（需确认）
python monitor.py --reset-stats

# 导出事件日志到CSV
python monitor.py --export-events events.csv
```

Ctrl+C 退出。

**全局快捷键（默认）：**
- `Ctrl+Alt+P`：暂停/恢复监控
- `Ctrl+Alt+C`：打开/显示面板
- `Ctrl+Alt+M`：临时禁用快捷键

快捷键可在设置页自定义。

## 文件说明

| 文件 | 说明 |
|------|------|
| `monitor.py` | 主程序：扫描、检测、发键/通知 |
| `terminal.py` | 终端窗口枚举 + UI Automation 屏幕读取 |
| `panel.py` | 状态面板（CustomTkinter）：左侧边栏 5 页（监控/日志/通知历史/设置/关于）+ 主题切换 |
| `updater.py` | 更新检查：查 GitHub Releases latest，版本比较，后台/手动检查 |
| `tray.py` | 系统托盘：状态、打开面板、暂停、配置方案切换、开机自启、退出 |
| `autostart.py` | 开机自启：在用户「启动」文件夹创建/删除 `.lnk` 快捷方式 |
| `singleton.py` | 单实例锁：命名 mutex 保证同一时刻只有一个监控进程 |
| `applog.py` | 日志：同时输出控制台与 `app.log`（打包后无控制台仍可排查） |
| `state.py` | 运行时状态持久化：统计计数器、单窗口策略、按窗口/按小时统计存到 `state.json`，跨重启保留 |
| `hotkeys.py` | 全局快捷键管理：用 pynput 监听系统级热键，无需管理员权限 |
| `profiles.py` | 配置方案管理：支持多个 `config.*.toml` 文件，运行时切换 |
| `filters.py` | 高级过滤规则引擎：正则匹配窗口标题、内容关键词过滤、优先级排序 |

## 打包 / 分发

打包成单文件 exe（无控制台黑框、带图标与版本信息）：

```powershell
.\build.ps1
```

产物 `dist\claude-auto-confirm.exe`。**分发只需把 `claude-auto-confirm.exe` 与
`config.toml` 放在同一目录**，双击 exe 即在后台常驻（托盘图标），无需安装 Python。

运行时会在 exe 同目录生成：
- `app.log`：运行日志（滚动，单文件上限 1MB）。
- `misfires/`：遇到无法识别的确认框时落盘的样本（正常为空）。
- `state.json`：统计计数器与单窗口策略，跨重启保留（自动维护，无需手改）。

当前版本：见 `version.py` 的 `__version__`（同步 `version_info.txt`）。**v0.7.0**

## 工作原理

1. 每 1.5 秒枚举所有可见终端窗口（按窗口类名识别，不依赖进程树）
2. 用 UI Automation TextPattern 读取屏幕文本
3. 检测屏幕底部状态：
   - 错误关键词（`Please run /login`、`API Error`、`超过 200K` 等）→ 通知
   - `Esc to cancel` 等 footer + `> 1. Yes` → 自动回车
   - footer + 编号选项但无 `1. Yes` → 多选菜单，通知
4. 自动回车通过 `PostMessage WM_KEYDOWN/WM_KEYUP` 后台送达，不抢 OS 前台
5. 通知用 `win11toast`（系统原生 Toast），点击回调用 `AttachThreadInput` 把目标窗口提到前台
