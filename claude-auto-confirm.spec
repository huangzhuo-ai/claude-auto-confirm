# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置。
打包命令：  pyinstaller claude-auto-confirm.spec
产物：      dist/claude-auto-confirm.exe（单文件）
config.toml 不打进 exe，需与 exe 放同目录，用户可直接编辑（config.py 已兼容 frozen 路径）。

console=True 便于首次排错看日志；确认无误后改 console=False 即为纯托盘无窗口模式。
"""
from PyInstaller.utils.hooks import collect_all

# 这三个库带隐藏导入/数据文件，静态分析抓不全，全量收集
datas, binaries, hiddenimports = [], [], []
for pkg in ('win11toast', 'uiautomation', 'pystray'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['monitor.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='claude-auto-confirm',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    icon=None,
)
