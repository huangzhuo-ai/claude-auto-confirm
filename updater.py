"""GitHub Releases 更新检查：查 latest release tag，与当前版本比较。
用标准库 urllib，不引入网络依赖。所有网络调用静默失败（返回 None），不打断主流程。"""
import json
import threading
import urllib.request
from applog import log

API_URL = ('https://api.github.com/repos/'
           'huangzhuo-ai/claude-auto-confirm/releases/latest')
RELEASES_PAGE = 'https://github.com/huangzhuo-ai/claude-auto-confirm/releases'
_TIMEOUT = 6  # 秒，网络慢时不拖死后台线程


def _parse(tag: str) -> tuple:
    """'v0.5.2' / '0.5.2' → (0, 5, 2)。非法段记 0。"""
    out = []
    for p in tag.lstrip('vV').split('.'):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def _is_newer(latest: str, current: str) -> bool:
    return _parse(latest) > _parse(current)


def get_latest_version() -> str | None:
    """查 GitHub latest release 的 tag_name。任何失败返回 None（静默）。"""
    try:
        req = urllib.request.Request(
            API_URL, headers={'Accept': 'application/vnd.github+json',
                              'User-Agent': 'claude-auto-confirm'})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode())
        return data.get('tag_name')
    except Exception as e:
        log(f'[updater] 查询失败: {e}')
        return None


def check(current: str) -> tuple[bool, str | None]:
    """返回 (有新版, 最新tag)。查询失败返回 (False, None)。"""
    latest = get_latest_version()
    if not latest:
        return False, None
    return _is_newer(latest, current), latest


def check_in_background(current: str, on_update) -> None:
    """后台线程查更新，有新版时回调 on_update(latest_tag)。"""
    def run():
        has, latest = check(current)
        if has and latest:
            log(f'[updater] 发现新版 {latest}')
            try:
                on_update(latest)
            except Exception as e:
                log(f'[updater] 回调失败: {e}')
    threading.Thread(target=run, daemon=True, name='updater').start()
