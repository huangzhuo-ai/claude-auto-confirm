"""
日志封装：同时输出到控制台（开发/--no-tray 时）与 app.log（与 exe 同目录）。

为什么需要它：打包成 console=False 的 exe 后，进程 sys.stdout/stderr 为 None，
代码里的 print(...) 会抛 AttributeError。改用本模块的 log()，既不依赖 stdout，
又把运行记录落盘到 app.log，去掉黑框的同时保留排查线索。
"""
import sys
import logging
import pathlib
from logging.handlers import RotatingFileHandler

_logger: logging.Logger | None = None


def _log_path() -> pathlib.Path:
    """app.log 与可执行文件/脚本同目录（兼容 PyInstaller frozen）。"""
    if getattr(sys, 'frozen', False):
        base = pathlib.Path(sys.executable).parent
    else:
        base = pathlib.Path(__file__).parent
    return base / 'app.log'


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    lg = logging.getLogger('claude-auto-confirm')
    lg.setLevel(logging.INFO)
    lg.propagate = False
    fmt = logging.Formatter('%(asctime)s %(message)s', datefmt='%H:%M:%S')

    # 文件 handler：滚动，单文件上限 1MB，留 2 个备份，防止无限增长
    try:
        fh = RotatingFileHandler(
            _log_path(), maxBytes=1_000_000, backupCount=2, encoding='utf-8')
        fh.setFormatter(fmt)
        lg.addHandler(fh)
    except Exception:
        pass  # 文件不可写（极端情况）也不能拖垮程序

    # 控制台 handler：仅当 stdout 存在（开发模式 / --no-tray）。frozen 无控制台时为 None
    if sys.stdout is not None:
        try:
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(fmt)
            lg.addHandler(sh)
        except Exception:
            pass

    _logger = lg
    return lg


def log(msg: str = '', end: str = '\n'):
    """记录一条日志。兼容原 print 的调用习惯；end 参数被忽略（logging 自带换行），
    保留签名是为了让 print→log 的替换最省心。"""
    try:
        _get_logger().info(msg.rstrip())
    except Exception:
        pass  # 日志永远不该让主流程崩溃
