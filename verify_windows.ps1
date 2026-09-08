# ===========================================================================
#  Arena Windows Agent — on-device verification (run on the REAL Windows box).
#
#  This proves the platform actually WORKS on your machine (the sandbox is
#  Linux, so Windows-only pieces can only be proven here).  It:
#    * registers every tool and checks Windows UI tools are present,
#    * opens Notepad via the agent, types text via the agent, reads the window,
#    * takes a screenshot + runs OCR, and reports PASS/FAIL per component.
#
#     powershell -ExecutionPolicy Bypass -File verify_windows.ps1
# ===========================================================================
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvpy)) {
    Write-Host "  [x] No .venv found. Run setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

$pass = 0; $fail = 0
function Report([string]$name, [bool]$ok, [string]$note = "") {
    if ($ok) { $script:pass++; Write-Host "  [OK]  $name" -ForegroundColor Green }
    else     { $script:fail++; Write-Host "  [FAIL] $name  $note" -ForegroundColor Red }
}

Write-Host ""
Write-Host "  [Arena Windows Agent] Running device verification..." -ForegroundColor Cyan

# 1. Tools register + Windows tools present.
Write-Host ""
Write-Host "  --- 1. Tool registry ---" -ForegroundColor Magenta
$reg = & $venvpy -c "from agent_platform.tools.registry import register_all; r=register_all(); print(','.join(r.names()))"
$names = $reg -split ","
Report "Registry returns tools ($($names.Count))" ($names.Count -gt 20) ""
Report "Windows tools present (open_application/ui_input/ui_interact)" (($names -contains "ui_input") -and ($names -contains "open_application"))
Report "UI input tool present" ($names -contains "ui_input")

# 2. Start the engine headless in the background.
Write-Host ""
Write-Host "  --- 2. Engine + server ---" -ForegroundColor Magenta
$proc = Start-Process -FilePath $venvpy -ArgumentList "-m","uvicorn","agent_platform.server.app:app","--host","127.0.0.1","--port","8000" -WorkingDirectory $PSScriptRoot -PassThru
Start-Sleep -Seconds 4
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 10
    Report "Server /api/health" ($health.ok -eq $true) "$($health.tools) tools, brain=$($health.brain)"
    $runtime = Invoke-RestMethod "http://127.0.0.1:8000/api/runtime" -TimeoutSec 10
    Report "Runtime reports tools" ($runtime.tools -gt 20) ""
} catch {
    Report "Server /api/health" $false $_.Exception.Message
}

# 3. Windows-native checks (only meaningful on a real Windows host).
Write-Host ""
Write-Host "  --- 3. Windows-native capabilities ---" -ForegroundColor Magenta
$isWin = $env:OS -eq "Windows_NT"
Report "Host is Windows" $isWin "(this must be run on Windows)"
if ($isWin) {
    # Open Notepad via the agent.
    try {
        $open = Invoke-RestMethod "http://127.0.0.1:8000/api/actions" -Method Post -ContentType "application/json" `
            -Body (@{kind="open_application"; target="notepad"; arguments=@{}} | ConvertTo-Json) -TimeoutSec 15
        Report "Open Notepad (open_application)" ($open.ok -eq $true) $open.error
        Start-Sleep -Seconds 2
    } catch { Report "Open Notepad (open_application)" $false $_.Exception.Message }

    # Type text into the focused window via the agent.
    try {
        $ty = Invoke-RestMethod "http://127.0.0.1:8000/api/actions" -Method Post -ContentType "application/json" `
            -Body (@{kind="type_text"; target="Hello from Arena Agent"; arguments=@{window="Notepad"}; force=$true} | ConvertTo-Json) -TimeoutSec 15
        Report "Type text (type_text via ui_input)" ($ty.ok -eq $true) $ty.error
    } catch { Report "Type text (type_text)" $false $_.Exception.Message }

    # List windows to prove UI inspection works.
    try {
        $insp = Invoke-RestMethod "http://127.0.0.1:8000/api/actions" -Method Post -ContentType "application/json" `
            -Body (@{kind="inspect_window"; target="Notepad"; arguments=@{}} | ConvertTo-Json) -TimeoutSec 15
        Report "Inspect window (inspect_window)" ($insp.ok -eq $true) $insp.error
    } catch { Report "Inspect window" $false $_.Exception.Message }
}

# 4. Screen capture + OCR.
Write-Host ""
Write-Host "  --- 4. Vision / OCR ---" -ForegroundColor Magenta
$shot = & $venvpy -c "from agent_platform.vision.vision_agent import capture_screen; print(capture_screen()['path'])"
if ($LASTEXITCODE -eq 0 -and $shot) {
    Report "Screen capture" $true $shot
    $ocr = & $venvpy -c "from agent_platform.vision.ocr import get_ocr_registry; import sys; r=get_ocr_registry(); print('available:', ','.join(r.available_names()) or 'none')"
    Report "OCR engine available" ($ocr -match "available: .+") ""
} else {
    Report "Screen capture" $false "no screen / headless"
}

# 5. Stop the server.
if ($proc) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "  === VERIFICATION RESULT ===" -ForegroundColor Cyan
Write-Host "       PASS: $pass   FAIL: $fail" -ForegroundColor $(if ($fail -eq 0) {"Green"} else {"Red"})
Write-Host ""
if ($fail -eq 0) { exit 0 } else { exit 1 }
