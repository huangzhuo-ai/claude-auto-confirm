"""配置备份/恢复模块：自动备份config.toml和state.json，支持导出/导入。

功能：
- 每天自动备份配置和状态文件
- 保留最近30天备份
- 支持手动备份
- 支持导出/导入备份包（.claude-backup.zip）
- 支持恢复到指定日期的备份
"""
import os
import shutil
import zipfile
from pathlib import Path
from datetime import datetime, timedelta
import json
import toml


_BACKUP_DIR = Path('.backup')


def _ensure_backup_dir():
    """确保备份目录存在。"""
    _BACKUP_DIR.mkdir(exist_ok=True)
    return _BACKUP_DIR


def auto_backup():
    """自动备份：每天自动调用（monitor启动时检查）。

    备份策略：
    - 每天最多备份一次（同一天多次启动只保留最新）
    - 保留最近30天的备份
    - 清理超过30天的旧备份
    """
    backup_dir = _ensure_backup_dir()
    today = datetime.now().strftime('%Y-%m-%d')

    # 检查今天是否已备份
    existing = list(backup_dir.glob(f'backup-{today}*'))
    if existing:
        # 今天已备份，跳过
        return

    # 执行备份
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    backup_name = f'backup-{timestamp}'
    backup_path = backup_dir / backup_name
    backup_path.mkdir(exist_ok=True)

    # 备份config.toml
    if Path('config.toml').exists():
        shutil.copy2('config.toml', backup_path / 'config.toml')

    # 备份state.json
    if Path('state.json').exists():
        shutil.copy2('state.json', backup_path / 'state.json')

    # 备份配置方案（config.*.toml）
    for profile in Path('.').glob('config.*.toml'):
        shutil.copy2(profile, backup_path / profile.name)

    # 创建元数据
    meta = {
        'timestamp': timestamp,
        'version': _get_current_version(),
        'files': [f.name for f in backup_path.iterdir()],
    }
    with open(backup_path / 'meta.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    # 清理30天前的旧备份
    cutoff = datetime.now() - timedelta(days=30)
    for old_backup in backup_dir.iterdir():
        if not old_backup.is_dir():
            continue
        try:
            # 从目录名提取日期
            date_str = old_backup.name.replace('backup-', '').split('_')[0]
            backup_date = datetime.strptime(date_str, '%Y-%m-%d')
            if backup_date < cutoff:
                shutil.rmtree(old_backup)
        except Exception:
            pass


def list_backups():
    """列出所有可用的备份。

    Returns:
        list[dict]: 备份列表，每项包含：
            - name: 备份名称
            - timestamp: 时间戳字符串
            - date: 日期（YYYY-MM-DD）
            - time: 时间（HH:MM:SS）
            - files: 包含的文件列表
            - size: 备份大小（字节）
    """
    backup_dir = _ensure_backup_dir()
    backups = []

    for backup_path in sorted(backup_dir.iterdir(), reverse=True):
        if not backup_path.is_dir():
            continue

        # 读取元数据
        meta_file = backup_path / 'meta.json'
        if meta_file.exists():
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        else:
            # 旧备份没有元数据，从目录名推断
            timestamp = backup_path.name.replace('backup-', '')
            meta = {
                'timestamp': timestamp,
                'files': [f.name for f in backup_path.iterdir() if f.name != 'meta.json'],
            }

        # 计算备份大小
        size = sum(f.stat().st_size for f in backup_path.rglob('*') if f.is_file())

        # 解析时间戳
        ts = meta['timestamp']
        if '_' in ts:
            date_part, time_part = ts.split('_')
            time_str = f'{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}'
        else:
            date_part = ts
            time_str = '00:00:00'

        backups.append({
            'name': backup_path.name,
            'path': str(backup_path),
            'timestamp': ts,
            'date': date_part,
            'time': time_str,
            'files': meta.get('files', []),
            'size': size,
            'version': meta.get('version', 'unknown'),
        })

    return backups


def restore_backup(backup_name, overwrite=True):
    """恢复指定的备份。

    Args:
        backup_name: 备份名称（backup-YYYY-MM-DD_HHMMSS）
        overwrite: 是否覆盖现有文件（默认True）

    Returns:
        tuple: (success: bool, message: str)
    """
    backup_dir = _ensure_backup_dir()
    backup_path = backup_dir / backup_name

    if not backup_path.exists():
        return False, f'备份不存在: {backup_name}'

    # 恢复前先备份当前状态（安全网）
    if overwrite:
        auto_backup()

    restored_files = []
    errors = []

    for backup_file in backup_path.iterdir():
        if backup_file.name == 'meta.json':
            continue

        target = Path(backup_file.name)

        if target.exists() and not overwrite:
            continue

        try:
            shutil.copy2(backup_file, target)
            restored_files.append(backup_file.name)
        except Exception as e:
            errors.append(f'{backup_file.name}: {e}')

    if errors:
        return False, f'部分文件恢复失败:\n' + '\n'.join(errors)

    return True, f'成功恢复 {len(restored_files)} 个文件'


def export_backup(backup_name, output_path):
    """导出备份为zip文件。

    Args:
        backup_name: 备份名称
        output_path: 输出zip文件路径

    Returns:
        tuple: (success: bool, message: str)
    """
    backup_dir = _ensure_backup_dir()
    backup_path = backup_dir / backup_name

    if not backup_path.exists():
        return False, f'备份不存在: {backup_name}'

    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file in backup_path.rglob('*'):
                if file.is_file():
                    arcname = file.relative_to(backup_path)
                    zf.write(file, arcname)

        return True, f'已导出到: {output_path}'
    except Exception as e:
        return False, f'导出失败: {e}'


def import_backup(zip_path):
    """导入zip备份文件。

    Args:
        zip_path: zip文件路径

    Returns:
        tuple: (success: bool, message: str, backup_name: str|None)
    """
    if not Path(zip_path).exists():
        return False, f'文件不存在: {zip_path}', None

    backup_dir = _ensure_backup_dir()
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    backup_name = f'backup-imported-{timestamp}'
    backup_path = backup_dir / backup_name
    backup_path.mkdir(exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(backup_path)

        return True, f'导入成功: {backup_name}', backup_name
    except Exception as e:
        # 清理失败的导入
        if backup_path.exists():
            shutil.rmtree(backup_path)
        return False, f'导入失败: {e}', None


def delete_backup(backup_name):
    """删除指定备份。

    Args:
        backup_name: 备份名称

    Returns:
        tuple: (success: bool, message: str)
    """
    backup_dir = _ensure_backup_dir()
    backup_path = backup_dir / backup_name

    if not backup_path.exists():
        return False, f'备份不存在: {backup_name}'

    try:
        shutil.rmtree(backup_path)
        return True, f'已删除备份: {backup_name}'
    except Exception as e:
        return False, f'删除失败: {e}'


def _get_current_version():
    """获取当前程序版本。"""
    try:
        import version
        return version.__version__
    except Exception:
        return 'unknown'


def get_backup_stats():
    """获取备份统计信息。

    Returns:
        dict: 统计信息，包含：
            - total_count: 总备份数
            - total_size: 总大小（字节）
            - oldest: 最老备份日期
            - newest: 最新备份日期
    """
    backups = list_backups()

    if not backups:
        return {
            'total_count': 0,
            'total_size': 0,
            'oldest': None,
            'newest': None,
        }

    return {
        'total_count': len(backups),
        'total_size': sum(b['size'] for b in backups),
        'oldest': backups[-1]['date'],
        'newest': backups[0]['date'],
    }
