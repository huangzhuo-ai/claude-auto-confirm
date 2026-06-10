# claude-auto-confirm

后台自动监控多个终端里的 Claude Code，对"是否继续"类确认框自动回车，对需要人工选择的菜单和错误状态发送桌面通知（点击通知可直接跳转到对应终端）。

## 功能

- 扫描所有终端窗口（Windows Terminal / PowerShell·CMD / VS Code 集成终端）
- **自动确认**：检测到 `> 1. Yes` 默认选中的确认框 → 后台静默发回车，不抢前台
- **多选菜单**：需要人工选择的菜单（AskUserQuestion 风格）→ 桌面通知，绝不自动回车
- **错误通知**：Claude 卡在登录失效 / API 错误 / 额度耗尽 / 上下文超限等状态 → 桌面通知
- **点击跳转**：点击任意通知，自动把对应终端窗口带到前台
- 按签名去重，同一个状态只通知一次
- **开机自启**：托盘菜单或面板一键开关（写当前用户注册表 Run 键，无需管理员权限）
- `--dry-run` 模式：只检测打印，不发送按键

## 环境要求

Windows 10/11，Python 3.10+

```
pip install pywin32 psutil uiautomation win11toast
```

## 使用

```bash
# 正常运行
python monitor.py

# 只检测，不发键（调试用）
python monitor.py --dry-run
```

Ctrl+C 退出。

## 文件说明

| 文件 | 说明 |
|------|------|
| `monitor.py` | 主程序：扫描、检测、发键/通知 |
| `terminal.py` | 终端窗口枚举 + UI Automation 屏幕读取 |
| `panel.py` | 状态面板（tkinter）：实时表格 + 事件日志 + 单窗口策略 |
| `tray.py` | 系统托盘：状态、打开面板、暂停、开机自启、退出 |
| `autostart.py` | 开机自启：读写 `HKCU\...\Run` 注册表项 |
| `applog.py` | 日志：同时输出控制台与 `app.log`（打包后无控制台仍可排查） |

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

当前版本：见 `version.py` 的 `__version__`（同步 `version_info.txt`）。

## 工作原理

1. 每 1.5 秒枚举所有可见终端窗口（按窗口类名识别，不依赖进程树）
2. 用 UI Automation TextPattern 读取屏幕文本
3. 检测屏幕底部状态：
   - 错误关键词（`Please run /login`、`API Error`、`超过 200K` 等）→ 通知
   - `Esc to cancel` 等 footer + `> 1. Yes` → 自动回车
   - footer + 编号选项但无 `1. Yes` → 多选菜单，通知
4. 自动回车通过 `PostMessage WM_KEYDOWN/WM_KEYUP` 后台送达，不抢 OS 前台
5. 通知用 `win11toast`（系统原生 Toast），点击回调用 `AttachThreadInput` 把目标窗口提到前台
