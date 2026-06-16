"""
运行时状态持久化：统计计数器、单窗口策略等需要跨重启保留的数据，
统一存到 exe 同目录的 state.json（与 config.toml / app.log 同套路）。

与 config.toml 分开：config 是用户可手编的设置，state 是程序自动维护的运行数据，
不该让用户手改，也不该污染配置文件。所有 IO 静默失败，绝不拖垮主流程。
"""
import sys
import json
import pathlib


def _state_path() -> pathlib.Path:
    """state.json 与可执行文件/脚本同目录（兼容 PyInstaller frozen）。"""
    if getattr(sys, 'frozen', False):
        base = pathlib.Path(sys.executable).parent
    else:
        base = pathlib.Path(__file__).parent
    return base / 'state.json'


def load() -> dict:
    """读取持久化状态。文件缺失/损坏时返回空 dict（静默）。"""
    p = _state_path()
    if not p.exists():
        return {}
    try:
        with p.open('r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data: dict) -> bool:
    """把状态写回 state.json。成功返回 True，失败静默返回 False。"""
    p = _state_path()
    try:
        with p.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def is_first_run() -> bool:
    """是否首次运行（state.json 里没有 launched 标志）。用于首次启动引导提示。"""
    return not bool(load().get('launched'))


def mark_launched() -> bool:
    """标记已启动过（写 launched=True），保留其余状态。下次 is_first_run 即为 False。"""
    data = load()
    data['launched'] = True
    return save(data)
