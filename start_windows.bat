@echo off
REM ============================================================
REM  Windows Autonomous Computer Agent - launcher
REM  Creates/uses a local venv, installs deps, starts the app.
REM ============================================================
setlocal

cd /d "%~dp0"

echo [1/4] Checking Python...
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.10+ from https://python.org and re-run.
  pause
  exit /b 1
)

echo [2/4] Preparing virtual environment...
if not exist ".venv" (
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo [3/4] Installing dependencies...
pip install -r requirements.txt --quiet

echo [4/4] Starting the agent...
python run.py

pause
