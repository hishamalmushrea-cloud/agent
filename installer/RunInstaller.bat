@echo off
REM ===========================================================================
REM  Arena Windows Agent — environment setup, run by the installer.
REM  Creates a .venv, installs requirements, and preflights the platform.
REM ===========================================================================
echo.
echo  [Arena Windows Agent] Setting up environment...
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo  [!] Python 3.10+ not found. Install it from https://python.org and re-run.
  pause
  exit /b 1
)

REM Create a virtualenv if missing.
if not exist ".venv" (
  echo  [*] Creating virtual environment...
  python -m venv .venv
)

echo  [*] Installing dependencies...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
  echo  [!] Dependency install failed.
  pause
  exit /b 1
)

echo  [*] Preflighting modules...
python -c "import agent_platform; from agent_platform.tools.registry import register_all; register_all(); print('Platform OK')"
if errorlevel 1 (
  echo  [!] Preflight failed.
  pause
  exit /b 1
)

echo.
echo  [OK] Setup complete.
echo.
pause
