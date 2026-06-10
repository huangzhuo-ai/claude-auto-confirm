# One-click build script.  Usage:  .\build.ps1
# Output: dist\claude-auto-confirm.exe (single file, no console, with icon + version info).
# Note: preserves dist\config.toml (user config); clears and rebuilds the rest of build/dist.
# ASCII-only on purpose: Windows PowerShell 5.1 mis-parses UTF-8 files without a BOM.

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host '[1/4] Backing up user config (if any)...'
$cfgBak = $null
if (Test-Path 'dist\config.toml') {
    $cfgBak = Get-Content 'dist\config.toml' -Raw -Encoding UTF8
}

Write-Host '[2/4] Cleaning build/ and dist/ ...'
if (Test-Path 'build') { Remove-Item 'build' -Recurse -Force }
if (Test-Path 'dist')  { Remove-Item 'dist'  -Recurse -Force }

Write-Host '[3/4] Generating icon and packaging (PyInstaller)...'
python make_icon.py
pyinstaller claude-auto-confirm.spec --noconfirm

Write-Host '[4/4] Restoring config.toml into dist/ ...'
if ($null -ne $cfgBak) {
    $cfgBak | Out-File 'dist\config.toml' -Encoding UTF8 -NoNewline
} elseif (Test-Path 'config.toml') {
    Copy-Item 'config.toml' 'dist\config.toml'
}

$exe = 'dist\claude-auto-confirm.exe'
if (Test-Path $exe) {
    $sizeMB = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ''
    Write-Host "[OK] Build done: $exe ($sizeMB MB)" -ForegroundColor Green
    Write-Host '     Distribute: put claude-auto-confirm.exe + config.toml in the same folder.'
} else {
    Write-Host '[FAIL] Build failed: exe not found' -ForegroundColor Red
    exit 1
}
