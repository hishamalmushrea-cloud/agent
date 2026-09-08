# ===========================================================================
#  Arena Windows Agent — Windows setup (run in PowerShell as your user).
#  Creates a venv, installs ALL dependencies (core + Windows UI + browser),
#  and preflights the platform.
#
#     powershell -ExecutionPolicy Bypass -File setup_windows.ps1
# ===========================================================================
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "  [Arena Windows Agent] Setting up on Windows..." -ForegroundColor Cyan

# 1. Locate Python.
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "  [x] Python 3.10+ not found. Install from https://python.org (check 'Add to PATH')." -ForegroundColor Red
    exit 1
}
Write-Host "  [*] Using $($py.Source)" -ForegroundColor Gray

# 2. Create/refresh a virtual environment.
if (-not (Test-Path ".venv")) {
    Write-Host "  [*] Creating virtual environment..." -ForegroundColor Gray
    python -m venv .venv
}
$venvpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvpy)) {
    Write-Host "  [x] Virtualenv python not found at $venvpy" -ForegroundColor Red
    exit 1
}

# 3. Install core requirements.
Write-Host "  [*] Installing core requirements..." -ForegroundColor Gray
& $venvpy -m pip install --upgrade pip | Out-Null
& $venvpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [x] Core dependency install failed." -ForegroundColor Red
    exit 1
}

# 4. Windows-native dependencies (UI automation + Win32 + browser).
Write-Host "  [*] Installing Windows UI / Win32 / browser deps..." -ForegroundColor Gray
& $venvpy -m pip install pywinauto pywin32 pyautogui
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [i] UI/Win32 packages failed (ok to continue, they are best-effort)." -ForegroundColor Yellow
}

# 5. Real browser control (Playwright) + Chromium.
Write-Host "  [*] Installing Playwright + Chromium browser..." -ForegroundColor Gray
& $venvpy -m pip install playwright
& $venvpy -m playwright install chromium

# 6. Preflight.
Write-Host "  [*] Preflight..." -ForegroundColor Gray
& $venvpy -c "from agent_platform.tools.registry import register_all; r=register_all(); print('  Platform OK — tools:', len(r.names()))"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [x] Preflight failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  [OK] Setup complete. Launch with:" -ForegroundColor Green
Write-Host "       .venv\Scripts\activate; python run.py" -ForegroundColor Green
Write-Host "   or double-click start_windows.bat" -ForegroundColor Green
Write-Host ""
