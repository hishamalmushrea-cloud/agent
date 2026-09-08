"""Desktop host: a browser-like window that is the Agent.

When you open this app it:
  1. Runs the agent engine + tool server (locally, in-process).
  2. Opens a **browser-like window** (pywebview / WebView2 on Windows) whose
     default page is ``https://arena.ai`` so you log in with your account and
     the agent (this very kind of session) does the thinking.
  3. Exposes the agent's **device tools** over MCP (and REST), gated by
     permissions.  When the agent needs to touch your computer, this app asks
     you to GRANT access — that's the "منح الصلاحيات" step.

Run on Windows:
    python desktop_app.py            # opens the browser window + runs the engine
    python desktop_app.py --cli      # no GUI; just run engine + MCP bridge

Because ``https://arena.ai`` uses X-Frame-Options (it cannot be embedded), the
app soft-loads it in the same native window (like a browser tab) so login works
normally.  The agent/tool UI is available at ``http://127.0.0.1:8000``.
"""

from __future__ import annotations

import argparse
import threading
import time

from agent_platform.config import load_settings


ARENA_URL = "https://arena.ai"


def _start_server(host: str, port: int) -> None:
    import uvicorn

    config = uvicorn.Config("agent_platform.server.app:app", host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    server.run()


def _start_mcp_http(host: str, port: int) -> None:
    from agent_platform.mcp_server.server import run_http

    run_http(host, port)


def run_cli() -> None:
    """Headless: start the agent server + MCP bridge (no GUI window)."""
    s = load_settings()
    print("=" * 60)
    print("  Agent engine + device bridge (headless)")
    print(f"  Chat UI:      http://127.0.0.1:{s.port}")
    print(f"  MCP bridge:   http://127.0.0.1:8765/mcp  (stdio also available)")
    print("  Grant device access: open /api/mcp/grants")
    print("=" * 60)
    threading.Thread(target=_start_mcp_http, args=(s.host, 8765), daemon=True).start()
    _start_server(s.host, s.port)


def run_gui() -> None:
    import webview

    s = load_settings()
    # Start the agent server + MCP bridge in background threads.
    threading.Thread(target=_start_mcp_http, args=(s.host, 8765), daemon=True).start()
    threading.Thread(target=_start_server, args=(s.host, s.port), daemon=True).start()

    # Give the servers a moment to start before the window.
    time.sleep(1.0)

    # Permissions controller (exposed to the GUI via js_api).
    grants_api = _PermissionApi()

    # Two panes in one window: the agent/browser (arena.ai) + a control bar.
    # We can't iframe arena.ai, so we open it directly as the main view; the
    # controller (our chat + permissions) is a separate window.
    main_window = webview.create_window(
        "Windows Autonomous Computer Agent",
        ARENA_URL,
        width=1280, height=820,
        min_size=(900, 600),
    )

    # A compact "controller" window with permissions + tool status.
    controller = webview.create_window(
        "Agent Controller — الأذونات والأدوات",
        "http://127.0.0.1:%d/" % s.port,
        width=760, height=640,
        js_api=grants_api,
    )

    webview.start()
    print("Window closed.")


class _PermissionApi:
    """JS bridge for the controller window to grant/revoke device access."""

    def grant(self, tool: str) -> str:
        from agent_platform.mcp_server.grants import get_grant_store

        get_grant_store().grant(tool)
        return f"granted:{tool}"

    def revoke(self, tool: str) -> str:
        from agent_platform.mcp_server.grants import get_grant_store

        get_grant_store().revoke(tool)
        return f"revoked:{tool}"

    def auto_on(self) -> str:
        from agent_platform.mcp_server.grants import get_grant_store

        get_grant_store().set_auto(True)
        return "auto:on"

    def auto_off(self) -> str:
        from agent_platform.mcp_server.grants import get_grant_store

        get_grant_store().set_auto(False)
        return "auto:off"

    def list_grants(self) -> str:
        from agent_platform.mcp_server.grants import get_grant_store

        import json

        return json.dumps(get_grant_store().list_grants())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true", help="headless (no GUI window)")
    args = parser.parse_args()
    if args.cli:
        run_cli()
    else:
        run_gui()


if __name__ == "__main__":
    main()
