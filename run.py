"""Desktop launcher for the Windows Autonomous Computer Agent.

Starts the agent server and opens the chat app in your browser.  On Windows you
can double-click ``start_windows.bat`` (or run this file) to use it like a
desktop app.

    python run.py          # starts server + opens browser
    python run.py --no-open  # starts server without opening the browser
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import webbrowser

from agent_platform.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", default=None, type=int)
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    parser.add_argument("--reload", action="store_true", help="dev auto-reload")
    args = parser.parse_args()

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print("  Windows Autonomous Computer Agent (locally hosted)")
    print(f"  Engine + tools run on THIS machine.")
    print(f"  Open:  {url}")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    if not args.no_open:
        webbrowser.open(url)

    cmd = [
        sys.executable, "-m", "uvicorn", "agent_platform.server.app:app",
        "--host", host, "--port", str(port),
    ]
    if args.reload:
        cmd.append("--reload")
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
