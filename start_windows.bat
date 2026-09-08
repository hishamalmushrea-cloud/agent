@echo off
REM ===========================================================================
REM  Arena Windows Agent — desktop launcher (double-click to start).
REM  Starts the local engine and opens the GUI.  Press Ctrl+C to stop.
REM ===========================================================================
cd /d "%~dp0"

if not exist ".venv" (
  echo  [*] First run: creating environment...
  python -m venv .venv
  call ".venv\Scripts\activate.bat"
  pip install -r requirements.txt
) else (
  call ".venv\Scripts\activate.bat"
)

echo  [*] Starting Arena Windows Agent...
python run.py
