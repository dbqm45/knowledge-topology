# Knowledge Topology - local setup on Windows (PowerShell 7+ / Windows PowerShell 5.1)
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-LocalEmbeddings]
param([switch]$LocalEmbeddings)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "==> Python virtual environment" -ForegroundColor Cyan
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv 2>$null; if (-not $?) { python -m venv .venv } }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
$extras = "postgres,dev"
if ($LocalEmbeddings) { $extras += ",local-embeddings" }
& .\.venv\Scripts\python.exe -m pip install -e ".[$extras]"

Write-Host "==> Web UI build" -ForegroundColor Cyan
Set-Location "$root\web"
npm ci --no-audit --no-fund
npm run build

Write-Host "==> Done. Next:" -ForegroundColor Green
Write-Host "   scripts\demo.ps1     # load the demo corpus and start http://127.0.0.1:8000"
