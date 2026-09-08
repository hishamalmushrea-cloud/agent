#!/usr/bin/env bash
# Arena Windows Agent — launcher for Unix-like hosts (dev/sandbox).
# Starts the local engine and opens the GUI.  Press Ctrl+C to stop.
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "[*] First run: creating environment..."
  python3 -m venv .venv
  . .venv/bin/activate
  pip install -r requirements.txt
else
  . .venv/bin/activate
fi
echo "[*] Starting Arena Windows Agent..."
python run.py "$@"
