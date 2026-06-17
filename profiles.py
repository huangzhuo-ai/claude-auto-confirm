"""
配置方案管理：支持多个 config.*.toml 文件（如 config.work.toml, config.debug.toml），
运行时切换、新建、重命名、删除方案。与 config.py 协同工作。
"""
import pathlib
import shutil
import config
from applog import log


def _base_dir() -> pathlib.Path:
    """配置文件所在目录（与 config._config_path() 同目录）。"""
    return config._config_path().parent


def list_profiles() -> list[str]:
    """列出所有可用的配置方案名（不含扩展名）。
    例如 config.toml → 'default', config.work.toml → 'work'。
    按字母序返回，'default' 始终排第一。"""
    base = _base_dir()
    profiles = []
    for p in base.glob('config*.toml'):
        if p.name == 'config.toml':
            profiles.append('default')
        elif p.name.startswith('config.') and p.name.endswith('.toml'):
            # config.work.toml -> work
            name = p.name[7:-5]  # 去掉 'config.' 前缀和 '.toml' 后缀
            profiles.append(name)
    # default 排第一，其余按字母序
    profiles = sorted(set(profiles))
    if 'default' in profiles:
        profiles.remove('default')
        profiles.insert(0, 'default')
    return profiles


def get_current_profile() -> str:
    """获取当前使用的配置方案名。通过检查 config._custom_path 判断。
    如果当前路径是 config.toml → 'default'，config.work.toml → 'work'。"""
    # 优先检查 _custom_path（switch_profile 设置的）
    if hasattr(config, '_custom_path') and config._custom_path is not None:
        p = config._custom_path
        if p.name == 'config.toml':
            return 'default'
        elif p.name.startswith('config.') and p.name.endswith('.toml'):
            return p.name[7:-5]
    # 回退到默认路径
    p = config._config_path()
    if p.name == 'config.toml':
        return 'default'
    elif p.name.startswith('config.') and p.name.endswith('.toml'):
        return p.name[7:-5]
    return 'default'  # 最终回退


def switch_profile(name: str) -> bool:
    """切换到指定配置方案。实现方式：修改 config 模块的 _config_path() 返回值。
    由于 config._config_path() 是函数，无法直接改返回值，需要用 monkeypatch 或全局变量。
    这里采用全局变量方案：config 模块新增 _custom_path，_config_path() 优先返回它。

    返回 True 表示切换成功，False 表示方案不存在。"""
    base = _base_dir()
    if name == 'default':
        target = base / 'config.toml'
    else:
        target = base / f'config.{name}.toml'

    if not target.exists():
        log(f'[profiles] 方案 {name} 不存在')
        return False

    # 设置 config 模块的自定义路径（需要 config.py 支持）
    config._custom_path = target
    log(f'[profiles] 已切换到方案: {name}')
    return True


def create_profile(name: str, copy_from: str = 'default') -> bool:
    """新建配置方案。从 copy_from 方案复制配置，默认从 default 复制。
    name 不能是 'default'（default 是 config.toml，不能重复创建）。
    返回 True 表示成功，False 表示已存在或创建失败。"""
    if name == 'default':
        log('[profiles] 不能创建名为 default 的方案（default 是 config.toml）')
        return False

    base = _base_dir()
    target = base / f'config.{name}.toml'
    if target.exists():
        log(f'[profiles] 方案 {name} 已存在')
        return False

    # 复制源方案
    if copy_from == 'default':
        src = base / 'config.toml'
    else:
        src = base / f'config.{copy_from}.toml'

    if not src.exists():
        log(f'[profiles] 源方案 {copy_from} 不存在')
        return False

    try:
        shutil.copy2(src, target)
        log(f'[profiles] 已创建方案: {name}（从 {copy_from} 复制）')
        return True
    except Exception as e:
        log(f'[profiles] 创建方案失败: {e}')
        return False


def rename_profile(old_name: str, new_name: str) -> bool:
    """重命名配置方案。不能重命名 default，new_name 不能是 default 或已存在。
    返回 True 表示成功，False 表示失败。"""
    if old_name == 'default' or new_name == 'default':
        log('[profiles] 不能重命名 default 方案')
        return False

    base = _base_dir()
    old_path = base / f'config.{old_name}.toml'
    new_path = base / f'config.{new_name}.toml'

    if not old_path.exists():
        log(f'[profiles] 方案 {old_name} 不存在')
        return False
    if new_path.exists():
        log(f'[profiles] 方案 {new_name} 已存在')
        return False

    try:
        old_path.rename(new_path)
        log(f'[profiles] 已重命名方案: {old_name} -> {new_name}')
        # 如果当前方案就是被重命名的，同步更新
        if get_current_profile() == old_name:
            switch_profile(new_name)
        return True
    except Exception as e:
        log(f'[profiles] 重命名方案失败: {e}')
        return False


def delete_profile(name: str) -> bool:
    """删除配置方案。不能删除 default，不能删除当前正在使用的方案。
    返回 True 表示成功，False 表示失败。"""
    if name == 'default':
        log('[profiles] 不能删除 default 方案')
        return False

    if get_current_profile() == name:
        log('[profiles] 不能删除当前正在使用的方案')
        return False

    base = _base_dir()
    target = base / f'config.{name}.toml'

    if not target.exists():
        log(f'[profiles] 方案 {name} 不存在')
        return False

    try:
        target.unlink()
        log(f'[profiles] 已删除方案: {name}')
        return True
    except Exception as e:
        log(f'[profiles] 删除方案失败: {e}')
        return False


def save_as_profile(name: str) -> bool:
    """把当前配置另存为新方案（从内存中的配置写入 config.{name}.toml）。
    返回 True 表示成功，False 表示已存在或保存失败。"""
    if name == 'default':
        log('[profiles] 不能另存为 default（default 是 config.toml）')
        return False

    base = _base_dir()
    target = base / f'config.{name}.toml'
    if target.exists():
        log(f'[profiles] 方案 {name} 已存在')
        return False

    # 读取当前配置，写入新文件
    cfg = config.load()
    try:
        # 直接用 config.save 逻辑，但指向新路径
        import tomli_w
        with target.open('wb') as f:
            tomli_w.dump(cfg, f)
        log(f'[profiles] 已另存为方案: {name}')
        return True
    except ImportError:
        # 回退到手写 toml（与 config.save 逻辑一致）
        try:
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
                elif isinstance(v, dict):
                    # 跳过复杂字典（如 hotkeys, filters），简化处理
                    pass
            target.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            log(f'[profiles] 已另存为方案: {name}')
            return True
        except Exception as e:
            log(f'[profiles] 另存为方案失败: {e}')
            return False
    except Exception as e:
        log(f'[profiles] 另存为方案失败: {e}')
        return False
