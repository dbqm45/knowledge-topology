# Loads the demo corpus (two snapshots) and starts the API + web UI on http://127.0.0.1:8000
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
$env:KT_WEB_DIST_DIR = "$root\web\dist"
& .\.venv\Scripts\kt.exe demo
Write-Host "Open http://127.0.0.1:8000 - identity switcher in the top-right corner (dev keys)." -ForegroundColor Green
& .\.venv\Scripts\kt.exe serve
