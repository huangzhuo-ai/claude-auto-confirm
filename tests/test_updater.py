# tests/test_updater.py
import sys, os, io, json as _json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import updater


def test_parse_strips_v_prefix():
    assert updater._parse('v0.5.2') == (0, 5, 2)
    assert updater._parse('0.6.0') == (0, 6, 0)


def test_is_newer():
    assert updater._is_newer('v0.5.2', 'v0.5.1') is True
    assert updater._is_newer('v0.5.2', 'v0.5.2') is False
    assert updater._is_newer('v0.5.1', 'v0.5.2') is False
    assert updater._is_newer('v0.6.0', 'v0.5.9') is True


class _FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def _fake_urlopen(payload):
    def _open(url, timeout=None):
        return _FakeResp(_json.dumps(payload).encode())
    return _open


def test_get_latest_version_ok(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, 'urlopen',
                        _fake_urlopen({'tag_name': 'v0.6.0'}))
    assert updater.get_latest_version() == 'v0.6.0'


def test_get_latest_version_network_fail(monkeypatch):
    def _boom(url, timeout=None):
        raise OSError('no network')
    monkeypatch.setattr(updater.urllib.request, 'urlopen', _boom)
    assert updater.get_latest_version() is None


def test_check_returns_tuple(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, 'urlopen',
                        _fake_urlopen({'tag_name': 'v0.6.0'}))
    has, latest = updater.check('v0.5.2')
    assert has is True and latest == 'v0.6.0'
    has2, _ = updater.check('v0.6.0')
    assert has2 is False
