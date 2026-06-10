# tests/test_config.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def test_defaults_have_theme_color():
    d = config.DEFAULTS
    assert d['theme'] == 'system'
    assert d['color'] == 'blue'


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / 'config.toml'
    monkeypatch.setattr(config, '_config_path', lambda: p)
    cfg = config.load()
    cfg['theme'] = 'dark'
    cfg['color'] = 'green'
    config.save(cfg)
    assert p.exists()
    reloaded = config.load()
    assert reloaded['theme'] == 'dark'
    assert reloaded['color'] == 'green'
