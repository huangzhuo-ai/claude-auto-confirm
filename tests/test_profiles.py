"""profiles.py 单元测试：配置方案的创建、切换、重命名、删除。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import profiles
import config


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    """临时配置目录：隔离测试，不污染真实配置。"""
    # 让 config._config_path() 指向临时目录
    default_cfg = tmp_path / 'config.toml'
    default_cfg.write_text('scan_interval = 1.5\n', encoding='utf-8')
    monkeypatch.setattr(config, '_config_path', lambda: default_cfg)
    yield tmp_path


def test_list_profiles_default_only(tmp_config_dir):
    """只有 config.toml 时，列表只含 default。"""
    profiles_list = profiles.list_profiles()
    assert profiles_list == ['default']


def test_create_profile(tmp_config_dir):
    """创建新方案。"""
    assert profiles.create_profile('work')
    assert 'work' in profiles.list_profiles()
    # 方案文件存在
    assert (tmp_config_dir / 'config.work.toml').exists()


def test_create_profile_duplicate(tmp_config_dir):
    """重复创建应失败。"""
    profiles.create_profile('work')
    assert not profiles.create_profile('work')  # 第二次创建失败


def test_switch_profile(tmp_config_dir):
    """切换方案。"""
    profiles.create_profile('debug')
    assert profiles.switch_profile('debug')
    assert profiles.get_current_profile() == 'debug'


def test_switch_profile_nonexistent(tmp_config_dir):
    """切换到不存在的方案应失败。"""
    assert not profiles.switch_profile('nonexistent')


def test_rename_profile(tmp_config_dir):
    """重命名方案。"""
    profiles.create_profile('old')
    assert profiles.rename_profile('old', 'new')
    assert 'new' in profiles.list_profiles()
    assert 'old' not in profiles.list_profiles()


def test_rename_profile_to_existing(tmp_config_dir):
    """重命名到已存在的名字应失败。"""
    profiles.create_profile('a')
    profiles.create_profile('b')
    assert not profiles.rename_profile('a', 'b')


def test_delete_profile(tmp_config_dir):
    """删除方案。"""
    profiles.create_profile('temp')
    assert profiles.delete_profile('temp')
    assert 'temp' not in profiles.list_profiles()


def test_delete_current_profile_fails(tmp_config_dir):
    """不能删除当前使用的方案。"""
    profiles.create_profile('current')
    profiles.switch_profile('current')
    assert not profiles.delete_profile('current')


def test_save_as_profile(tmp_config_dir):
    """另存为新方案。"""
    # 修改当前配置
    cfg = config.load()
    cfg['scan_interval'] = 2.5
    config.save(cfg)
    # 另存为
    assert profiles.save_as_profile('snapshot')
    # 新方案文件存在
    assert (tmp_config_dir / 'config.snapshot.toml').exists()
    # 读取新方案，验证内容
    profiles.switch_profile('snapshot')
    cfg2 = config.load()
    assert cfg2['scan_interval'] == 2.5
