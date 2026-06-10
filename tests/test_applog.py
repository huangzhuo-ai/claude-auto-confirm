"""
applog 的单元测试：重点验证 frozen 无控制台（sys.stdout=None）时不抛异常、
且仍能写入 app.log；以及 version 可导入。
"""
import sys, os, types, importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_version_importable():
    import version
    assert isinstance(version.__version__, str)
    assert version.__version__  # 非空


def test_log_writes_file(tmp_path, monkeypatch):
    import applog
    importlib.reload(applog)  # 重置模块级 _logger，避免跨测试污染
    log_file = tmp_path / 'app.log'
    monkeypatch.setattr(applog, '_log_path', lambda: log_file)
    applog.log('hello world')
    # logging 默认即时 flush 到文件
    assert log_file.exists()
    assert 'hello world' in log_file.read_text(encoding='utf-8')


def test_log_no_crash_when_stdout_none(tmp_path, monkeypatch):
    """模拟 console=False 的 frozen 进程：sys.stdout 为 None。log() 不得抛异常。"""
    import applog
    importlib.reload(applog)
    monkeypatch.setattr(applog, '_log_path', lambda: tmp_path / 'app.log')
    monkeypatch.setattr(sys, 'stdout', None)
    # 不应抛 AttributeError
    applog.log('frozen mode line')
    assert (tmp_path / 'app.log').read_text(encoding='utf-8').strip().endswith('frozen mode line')
