"""backup.py 单元测试：配置备份/恢复功能验证。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import backup
from pathlib import Path
import shutil
import zipfile


def test_auto_backup_creates_backup_dir(tmp_path, monkeypatch):
    """测试自动备份创建备份目录。"""
    monkeypatch.setattr(backup, '_BACKUP_DIR', tmp_path / '.backup')

    # 创建测试文件
    (tmp_path / 'config.toml').write_text('[general]\ntest=true')
    (tmp_path / 'state.json').write_text('{"counters": {}}')

    # 修改当前目录为测试目录
    original_cwd = Path.cwd()
    os.chdir(tmp_path)

    try:
        backup.auto_backup()

        backup_dir = tmp_path / '.backup'
        assert backup_dir.exists()
        assert backup_dir.is_dir()

        # 应该有一个备份
        backups = list(backup_dir.iterdir())
        assert len(backups) == 1
        assert backups[0].is_dir()
        assert backups[0].name.startswith('backup-')
    finally:
        os.chdir(original_cwd)


def test_list_backups_returns_empty_list_when_no_backups(tmp_path, monkeypatch):
    """测试没有备份时返回空列表。"""
    monkeypatch.setattr(backup, '_BACKUP_DIR', tmp_path / '.backup')

    backups = backup.list_backups()
    assert backups == []


def test_list_backups_returns_backup_info(tmp_path, monkeypatch):
    """测试列出备份信息。"""
    monkeypatch.setattr(backup, '_BACKUP_DIR', tmp_path / '.backup')

    # 创建测试备份
    backup_dir = tmp_path / '.backup'
    backup_dir.mkdir()

    test_backup = backup_dir / 'backup-2026-06-17_120000'
    test_backup.mkdir()
    (test_backup / 'config.toml').write_text('[test]')
    (test_backup / 'meta.json').write_text('{"timestamp": "2026-06-17_120000", "files": ["config.toml"]}')

    backups = backup.list_backups()
    assert len(backups) == 1
    assert backups[0]['name'] == 'backup-2026-06-17_120000'
    assert backups[0]['date'] == '2026-06-17'
    assert backups[0]['time'] == '12:00:00'
    assert 'config.toml' in backups[0]['files']


def test_restore_backup_success(tmp_path, monkeypatch):
    """测试恢复备份成功。"""
    monkeypatch.setattr(backup, '_BACKUP_DIR', tmp_path / '.backup')

    # 创建测试备份
    backup_dir = tmp_path / '.backup'
    backup_dir.mkdir()

    test_backup = backup_dir / 'backup-2026-06-17_120000'
    test_backup.mkdir()
    (test_backup / 'config.toml').write_text('[restored]\nvalue=123')
    (test_backup / 'meta.json').write_text('{"timestamp": "2026-06-17_120000", "files": ["config.toml"]}')

    # 切换到测试目录
    original_cwd = Path.cwd()
    os.chdir(tmp_path)

    try:
        # 恢复备份
        success, msg = backup.restore_backup('backup-2026-06-17_120000', overwrite=True)

        assert success
        assert '成功恢复' in msg
        assert (tmp_path / 'config.toml').exists()
        content = (tmp_path / 'config.toml').read_text()
        assert 'restored' in content
        assert 'value=123' in content
    finally:
        os.chdir(original_cwd)


def test_restore_backup_nonexistent_fails(tmp_path, monkeypatch):
    """测试恢复不存在的备份失败。"""
    monkeypatch.setattr(backup, '_BACKUP_DIR', tmp_path / '.backup')

    success, msg = backup.restore_backup('backup-nonexistent')

    assert not success
    assert '不存在' in msg


def test_export_backup_creates_zip(tmp_path, monkeypatch):
    """测试导出备份为zip文件。"""
    monkeypatch.setattr(backup, '_BACKUP_DIR', tmp_path / '.backup')

    # 创建测试备份
    backup_dir = tmp_path / '.backup'
    backup_dir.mkdir()

    test_backup = backup_dir / 'backup-2026-06-17_120000'
    test_backup.mkdir()
    (test_backup / 'config.toml').write_text('[export_test]')
    (test_backup / 'meta.json').write_text('{"timestamp": "2026-06-17_120000"}')

    # 导出
    output_zip = tmp_path / 'export.zip'
    success, msg = backup.export_backup('backup-2026-06-17_120000', str(output_zip))

    assert success
    assert output_zip.exists()

    # 验证zip内容
    with zipfile.ZipFile(output_zip, 'r') as zf:
        assert 'config.toml' in zf.namelist()
        assert 'meta.json' in zf.namelist()


def test_import_backup_extracts_zip(tmp_path, monkeypatch):
    """测试导入zip备份文件。"""
    monkeypatch.setattr(backup, '_BACKUP_DIR', tmp_path / '.backup')

    # 创建测试zip
    zip_path = tmp_path / 'import.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('config.toml', '[imported]\ntest=true')
        zf.writestr('meta.json', '{"timestamp": "2026-06-17_120000"}')

    # 导入
    success, msg, backup_name = backup.import_backup(str(zip_path))

    assert success
    assert backup_name.startswith('backup-imported-')

    # 验证导入的备份
    backups = backup.list_backups()
    assert len(backups) == 1
    assert backups[0]['name'] == backup_name


def test_delete_backup_removes_directory(tmp_path, monkeypatch):
    """测试删除备份。"""
    monkeypatch.setattr(backup, '_BACKUP_DIR', tmp_path / '.backup')

    # 创建测试备份
    backup_dir = tmp_path / '.backup'
    backup_dir.mkdir()

    test_backup = backup_dir / 'backup-2026-06-17_120000'
    test_backup.mkdir()
    (test_backup / 'config.toml').write_text('[delete_test]')

    # 删除
    success, msg = backup.delete_backup('backup-2026-06-17_120000')

    assert success
    assert not test_backup.exists()


def test_get_backup_stats_returns_correct_info(tmp_path, monkeypatch):
    """测试获取备份统计信息。"""
    monkeypatch.setattr(backup, '_BACKUP_DIR', tmp_path / '.backup')

    # 创建多个测试备份
    backup_dir = tmp_path / '.backup'
    backup_dir.mkdir()

    for i in range(3):
        test_backup = backup_dir / f'backup-2026-06-{17+i:02d}_120000'
        test_backup.mkdir()
        (test_backup / 'config.toml').write_text(f'[backup{i}]')
        (test_backup / 'meta.json').write_text(f'{{"timestamp": "2026-06-{17+i:02d}_120000", "files": ["config.toml"]}}')

    stats = backup.get_backup_stats()

    assert stats['total_count'] == 3
    assert stats['total_size'] > 0
    assert stats['oldest'] == '2026-06-17'
    assert stats['newest'] == '2026-06-19'
