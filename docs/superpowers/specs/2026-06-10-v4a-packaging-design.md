# v4-a：打包打磨 设计

## 背景与动机

v3 让工具「值得信任」。下一步是让它「别人能轻松用起来」。第一块拼图是**分发物**——
把 exe 从「能跑的脚本产物」打磨成「双击即用、不会崩」的成品。

当前 `dist/claude-auto-confirm.exe` 有几个硬伤（实测确认）：

1. **过时**：打于 v2 面板和 v3 检测之前，exe 里没有 `panel.py`、没有 unknown 检测。
2. **panel 漏打包风险（最致命）**：`panel` 在 `tray._open_panel()` 里懒加载，
   `tray` 又在 `monitor.main()` 里懒加载。PyInstaller 静态分析很可能抓不到
   `panel` 模块，打出的 exe 一点「打开面板」就崩。spec 的 hiddenimports 未列 panel。
3. **黑控制台窗口**：`console=True`，双击弹黑框，不像成品。
4. **无图标**：无 `.ico`，`icon=None`，用默认灰图标。
5. **无版本信息**：exe 属性里无版本号/产品名。

## 目标

打出一个干净、双击即用、不会崩的 exe，附一键打包脚本与分发说明。

## 设计

### 1. 修复 panel 漏打包（最关键）

`claude-auto-confirm.spec` 的 `hiddenimports` 显式加入 `'panel'`、`'tray'`、`'config'`、
`'terminal'`。tkinter 由 PyInstaller 内置 hook 处理（自动收 `_tkinter` + Tcl/Tk 数据），
无需手动；但打包后必须真机验证「打开面板」不崩，作为本版验收硬指标。

### 2. 去掉控制台黑框 + 日志落盘

- spec：`console=True` → `console=False`（纯托盘常驻，双击不弹黑框）。
- **配套防护**：`console=False` 的 frozen 进程 `sys.stdout/stderr` 为 `None`，
  现有大量 `print(...)` 会抛 `AttributeError`。解决：新建 `applog.py`，提供 `log()`，
  内部用 Python `logging`，同时输出到：
  - 控制台（开发模式 / `--no-tray` 时有 stdout）；
  - `app.log` 文件（与 exe 同目录，复用 config 的 frozen 路径逻辑，滚动上限 1MB）。
  - 把 `monitor.py` 里的 `print(...)` 改为 `applog.log(...)`；既去黑框又留排查线索。
  - 文件 handler 用 `RotatingFileHandler`，避免日志无限增长。

### 3. 图标

- 用现有托盘图标那套（紫底白对勾，见 `tray._make_icon`）生成多尺寸 `.ico`。
  写一个一次性脚本 `make_icon.py`（用 Pillow 画图导出 256/128/64/48/32/16），
  产物 `icon.ico` 提交入库（小文件、构建依赖它）。
- spec：`icon='icon.ico'`；exe 与托盘图标视觉统一。

### 4. 版本信息

- 新建 `version.py`：`__version__ = '0.4.0'`（单一事实源，applog 启动打印它，
  README 也引用）。
- spec：用 PyInstaller 的 `version_file` 给 exe 写 Windows 版本资源
  （属性→详细信息显示版本号/产品名/版权）。生成 `version_info.txt`（PyInstaller
  VSVersionInfo 格式），spec 引用。

### 5. 一键打包脚本 + 文档

- `build.ps1`：清理 `build/`、`dist/`（保留用户的 `dist/config.toml`）→ 跑
  `pyinstaller claude-auto-confirm.spec` → 打印产物路径与大小。
- README 补「打包 / 分发」一节：如何打包、分发只需 `exe + config.toml` 同目录。

## 非目标（YAGNI）

- 不做安装程序（NSIS/Inno）——单文件 exe + config.toml 拷贝即用。
- 不做代码签名（自用无需）、不做自动更新。
- 不重构现有逻辑，只为打包成品所需做最小改动（print→log 是必要配套，非重构）。

## 涉及文件

- `claude-auto-confirm.spec`（改）：hiddenimports 加 panel/tray/config/terminal；
  console=False；icon='icon.ico'；version='version_info.txt'。
- `applog.py`（新）：logging 封装，控制台 + RotatingFileHandler(app.log)。
- `version.py`（新）：`__version__`。
- `monitor.py`（改）：`print(...)` → `applog.log(...)`；启动打印版本。
- `make_icon.py`（新）：一次性生成 icon.ico。
- `icon.ico`（新，入库）：图标产物。
- `version_info.txt`（新，入库）：Windows 版本资源。
- `build.ps1`（新）：一键打包脚本。
- `.gitignore`（改）：加 `app.log`。
- `README.md`（改）：打包/分发说明 + 版本。

## 测试策略

- **单元测试**：`applog.log()` 在 stdout 为 None（模拟 frozen 无控制台）时不抛异常、
  且能写入指定 log 文件；`version.__version__` 可导入。监控逻辑无新分支，沿用现有 19 测试做回归。
- **真机验证（实现者，硬指标）**：
  1. `python make_icon.py` 生成 icon.ico。
  2. `build.ps1` 打包成功，dist 出 exe。
  3. 双击 exe：**无黑框**、托盘图标出现且为新图标。
  4. 托盘「打开面板」→ **面板正常弹出**（验证 panel 打包成功，本版核心验收）。
  5. 触发一次自动确认仍工作；`app.log` 生成且有内容。
  6. exe 属性→详细信息显示版本号。
- 因 exe 真机验证需 GUI 交互，实现者执行并如实汇报结果，再交用户复测。
