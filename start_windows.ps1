# Windows Autonomous Computer Agent - launcher (PowerShell)
# Right-click -> Run with PowerShell, or:  powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
Set-Location $PSScriptRoot

Write-Host "[1/4] Checking Python..." -ForegroundColor Cyan
try { python --version | Out-Null } catch { Write-Host "Python not found. Install 3.10+."; return }

Write-Host "[2/4] Preparing venv..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1

Write-Host "[3/4] Installing dependencies..." -ForegroundColor Cyan
& pip install -r requirements.txt --quiet

Write-Host "[4/4] Starting the agent..." -ForegroundColor Cyan
& python run.py
