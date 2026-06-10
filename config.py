"""配置加载：从 config.toml 读取，缺失项用默认值补齐。"""
import tomllib
import pathlib

DEFAULTS = {
    'scan_interval': 1.5,          # 扫描间隔（秒）
    'waiting_notify_seconds': 15,  # 等待输入持续多久触发通知
    'ignored_titles': [],          # 忽略含这些字串的窗口标题
    'theme': 'system',             # 外观明暗：system | dark | light
    'color': 'blue',               # 主题色：blue | green | dark-blue
}


def _config_path() -> pathlib.Path:
    """config.toml 与可执行文件/脚本同目录（兼容 PyInstaller 打包）。"""
    import sys
    if getattr(sys, 'frozen', False):
        base = pathlib.Path(sys.executable).parent
    else:
        base = pathlib.Path(__file__).parent
    return base / 'config.toml'


def load() -> dict:
    p = _config_path()
    if p.exists():
        try:
            with p.open('rb') as f:
                user = tomllib.load(f)
            return {**DEFAULTS, **user}
        except Exception as e:
            print(f'[WARN] 读取 config.toml 失败，用默认配置: {e}')
    return DEFAULTS.copy()


def save(cfg: dict) -> bool:
    """把配置写回 config.toml。成功返回 True。
    优先用 tomli_w；环境无该库时手写最简 toml（本项目配置仅含 str/num/bool/list[str]）。"""
    p = _config_path()
    try:
        import tomli_w
        with p.open('wb') as f:
            tomli_w.dump(cfg, f)
        return True
    except ImportError:
        lines = []
        for k, v in cfg.items():
            if isinstance(v, bool):
                lines.append(f'{k} = {"true" if v else "false"}')
            elif isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, (int, float)):
                lines.append(f'{k} = {v}')
            elif isinstance(v, list):
                items = ', '.join(f'"{x}"' for x in v)
                lines.append(f'{k} = [{items}]')
        p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return True
    except Exception as e:
        print(f'[WARN] 保存 config.toml 失败: {e}')
        return False
