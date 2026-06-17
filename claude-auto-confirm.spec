# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置。
打包命令：  pyinstaller claude-auto-confirm.spec
产物：      dist/claude-auto-confirm.exe（单文件）
config.toml 不打进 exe，需与 exe 放同目录，用户可直接编辑（config.py 已兼容 frozen 路径）。

console=False：纯托盘无黑框。日志改由 applog 写到 app.log（与 exe 同目录），不依赖 stdout。
"""
from PyInstaller.utils.hooks import collect_all

# 这三个库带隐藏导入/数据文件,静态分析抓不全，全量收集
datas, binaries, hiddenimports = [], [], []
for pkg in ('win11toast', 'uiautomation', 'pystray', 'customtkinter'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 项目资源文件：icon.png（通知用，Windows Toast 需 PNG）
datas.append(('icon.png', '.'))

# 本项目的模块多为懒加载（panel 在 tray 里 import、tray 在 monitor.main 里 import），
# PyInstaller 静态分析抓不到，必须显式声明,否则打包后「打开面板」会崩。
hiddenimports += ['panel', 'tray', 'config', 'terminal', 'applog', 'version', 'autostart', 'singleton', 'updater', 'state', 'iconart', 'hotkeys', 'profiles', 'filters', 'charts', 'backup']

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
    console=False,
    disable_windowed_traceback=False,
    icon='icon.ico',
    version='version_info.txt',
)
