# v0.6.0 设计文档：面板重写 + 更新检查 + 关于

## 已敲定决策

| 项目 | 决策 |
|------|------|
| 面板 UI 库 | CustomTkinter（替换 tkinter） |
| 面板布局 | 左侧边栏导航（监控/日志/设置/关于） |
| 默认主题 | 跟随系统（system），GUI 即时可切 |
| 主题配置位置 | 设置页（sidebar 导航进入） |
| 更新检查方式 | 自动（启动后台线程）+ 手动（关于页按钮），两者共存 |
| 发现新版行为 | 只提示 + 打开 GitHub release 页，用户自行下载替换 |
| 网络依赖 | 标准库 urllib.request，不新增依赖 |

## 文件改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `updater.py` | 新建 | 查 GitHub Releases API，对比版本 |
| `panel.py` | 重写 | CustomTkinter 左侧边栏，4 个页面 |
| `requirements.txt` | 改 | 加 customtkinter |
| `claude-auto-confirm.spec` | 改 | hiddenimports 加 customtkinter |
| `config.py` | 改 | 加 theme / color 字段（默认 system / blue） |
| `config.toml`（可选） | 改 | 补示例配置注释 |

## 面板结构（4 个页面）

### 监控状态页
- CTkScrollableFrame 窗口表格：类型/标题/策略/状态/详情/时间
- 表格行选中后：自动确认/仅通知/忽略 三个策略按钮
- 双击行跳转对应终端窗口

### 事件日志页
- CTkTextbox 滚动文本框，倒序追加事件
- 每条格式：时间 · 动作 · [终端类型] 标题 · 详情

### 设置页
- 全局开关区：暂停监控、干跑模式、开机自启（三个 CTkSwitch）
- 外观区：
  - 明暗下拉：跟随系统 / 深色 / 浅色
  - 主题色下拉：蓝 / 绿 / 深蓝
  - 改了立即调用 ctk.set_appearance_mode() / ctk.set_default_color_theme()
  - 同步写入 config.toml 持久化

### 关于页
- 程序名 + 当前版本号（从 version.py 读）
- 作者：huangzhuo
- GitHub 链接（可点击，webbrowser.open）
- 检查更新按钮 → 查完显示结果（已是最新 / 发现新版 vX.X.X 可点跳转）
- 自动检查结果横幅（启动时后台查到新版才显示）

## updater.py 接口

```python
API_URL = "https://api.github.com/repos/huangzhuo-ai/claude-auto-confirm/releases/latest"

def get_latest_version() -> str | None:
    """查 GitHub Releases，返回最新 tag（如 'v0.6.0'），失败返回 None。"""

def has_update(current: str) -> tuple[bool, str | None]:
    """返回 (有新版, 最新版本号)。current 传 __version__。"""

def check_in_background(on_update: Callable[[str], None]) -> None:
    """后台线程查，有新版时回调 on_update(latest_tag)。"""
```

## 版本比较

用 tuple 比较，不引入 packaging：
```python
def _parse(tag: str) -> tuple:
    return tuple(int(x) for x in tag.lstrip('v').split('.'))
# _parse('v0.5.3') > _parse('v0.5.2') → True
```

## config.py 新增字段

```python
DEFAULTS = {
    ...
    'theme': 'system',   # system | dark | light
    'color': 'blue',     # blue | green | dark-blue
}
```

设置页改动后通过 `config.save()` 写回 config.toml。

## 构建顺序

1. 建 GitHub v0.5.2 release（gh CLI）
2. 写 updater.py + 单测
3. 改 config.py（加 theme/color + save()）
4. 重写 panel.py（CustomTkinter）
5. 改 requirements.txt + spec
6. 全套测试通过
7. 版本升 0.6.0，打包实测，提交推送
