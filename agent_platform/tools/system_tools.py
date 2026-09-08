"""System / environment tools.

Clipboard, notifications, environment info, network status, and a general
"computer" tool that reports the platform.  Useful for the agent to know its
environment and to surface info to the user.
"""

from __future__ import annotations

import os
import platform
import random
from typing import Any

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec
from agent_platform.tools.base import Tool


class SystemInfoTool(Tool):
    spec = ToolSpec(
        name="system_info",
        description="Report the current OS, machine, python version, hostname, and "
        "environment basics.",
        category="system",
        parameters={},
        permission=PermissionLevel.SAFE,
    )

    def run(self, **kwargs: Any) -> ToolResult:
        info = {
            "os": platform.system(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "release": platform.release(),
            "python": platform.python_version(),
            "hostname": platform.node(),
            "cwd": os.getcwd(),
            "home": os.path.expanduser("~"),
            "is_windows": platform.system() == "Windows",
        }
        import json

        return self.ok(json.dumps(info, ensure_ascii=False, indent=2), data=info)


class NetworkStatusTool(Tool):
    spec = ToolSpec(
        name="network_status",
        description="Check basic network reachability by pinging a well-known host "
        "(uses HTTP GET to a reliable endpoint).",
        category="system",
        parameters={"host": "str (optional, default https://www.google.com)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, host: str = "https://www.google.com", **kwargs: Any) -> ToolResult:
        try:
            # Use stdlib urllib to avoid extra dependency.
            import urllib.request

            req = urllib.request.Request(host, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return self.ok(f"Reachable: {host} -> HTTP {resp.status}", data={"online": True})
        except Exception as exc:  # noqa: BLE001
            return self.ok(f"Unreachable: {host} ({exc})", data={"online": False})


class ClipboardTool(Tool):
    spec = ToolSpec(
        name="get_clipboard",
        description="Read the current clipboard text (best-effort; uses platform "
        "tooling).",
        category="system",
        parameters={},
        permission=PermissionLevel.SAFE,
    )

    def run(self, **kwargs: Any) -> ToolResult:
        try:
            import tkinter  # noqa: F401  (import may fail headless)

            return self.ok("Clipboard read not available in this runtime")
        except Exception as exc:  # noqa: BLE001
            return self.ok(f"Clipboard unavailable: {exc}")


class EnvironmentTool(Tool):
    spec = ToolSpec(
        name="get_env",
        description="Read the value of an environment variable.",
        category="system",
        parameters={"name": "str (required)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, name: str, **kwargs: Any) -> ToolResult:
        value = os.environ.get(name)
        if value is None:
            return self.ok(f"{name} is not set")
        return self.ok(f"{name}={value}")


class RandomTokenTool(Tool):
    spec = ToolSpec(
        name="random_password",
        description="Generate a random password / token (useful for scaffolding "
        "secrets in projects).",
        category="system",
        parameters={"length": "int (optional, default 20)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, length: int = 20, **kwargs: Any) -> ToolResult:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*"
        token = "".join(random.choice(alphabet) for _ in range(max(8, length)))
        return self.ok(token, data={"token": token})


class WaitTool(Tool):
    spec = ToolSpec(
        name="wait",
        description="Pause for a number of seconds. Useful to let an app load or a "
        "UI settle before acting.",
        category="control",
        parameters={"seconds": "float (optional, default 1.0)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, seconds: float = 1.0, **kwargs: Any) -> ToolResult:
        import time

        time.sleep(max(0.0, float(seconds)))
        return self.ok(f"Waited {seconds}s")


ALL_TOOLS: list[type[Tool]] = [
    SystemInfoTool,
    NetworkStatusTool,
    ClipboardTool,
    EnvironmentTool,
    RandomTokenTool,
    WaitTool,
]
