"""Process tools.

Launch and inspect processes.  Uses subprocess for launching and, on POSIX,
``ps``/``kill``; on Windows it uses ``tasklist`` and ``taskkill`` via the shell
tool for cross-platform reliability.  The agent uses these to start and observe
long-running programs (e.g. a dev server) and to recover from crashes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec
from agent_platform.tools.base import Tool


class StartProcessTool(Tool):
    spec = ToolSpec(
        name="start_process",
        description="Start a background program. Returns the process id (pid) and "
        "whether it was launched. Used for servers, browsers, long-running jobs.",
        category="process",
        parameters={"command": "str (required): command to run",
                     "args": "list (optional): extra arguments",
                     "cwd": "str (optional): working directory"},
        permission=PermissionLevel.SENSITIVE,
    )

    def run(self, command: str, args: list[str] | None = None, cwd: str = "", **kwargs: Any) -> ToolResult:
        try:
            run_dir = os.path.expanduser(cwd) if cwd else os.getcwd()
            cmd = [command] + (args or [])
            proc = subprocess.Popen(
                cmd,
                cwd=run_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return self.ok(f"Started pid={proc.pid}", data={"pid": proc.pid})
        except FileNotFoundError:
            return self.fail("Command not found")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class ListProcessesTool(Tool):
    spec = ToolSpec(
        name="list_processes",
        description="List running processes with pid, name and a short summary of "
        "the command line.",
        category="process",
        parameters={"filter": "str (optional): substring to match the process name"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, filter: str = "", **kwargs: Any) -> ToolResult:
        try:
            procs = _list_processes()
            if filter:
                procs = [p for p in procs if filter.lower() in p["name"].lower()]
            import json

            return self.ok(json.dumps(procs, ensure_ascii=False, indent=2), data=procs)
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class StopProcessTool(Tool):
    spec = ToolSpec(
        name="stop_process",
        description="Stop (kill) a process by pid or by matching a name. "
        "Dangerous — classified DANGEROUS.",
        category="process",
        parameters={"pid": "int (optional)", "name": "str (optional)"},
        permission=PermissionLevel.DANGEROUS,
    )

    def run(self, pid: int | None = None, name: str = "", **kwargs: Any) -> ToolResult:
        try:
            if pid is not None:
                _kill_pid(pid)
                return self.ok(f"Killed pid={pid}")
            if name:
                for p in _list_processes():
                    if name.lower() in p["name"].lower() or name.lower() in p.get("cmd", "").lower():
                        _kill_pid(p["pid"])
                        return self.ok(f"Killed pid={p['pid']} ({p['name']})")
                return self.fail(f"No matching process for '{name}'")
            return self.fail("Provide either pid or name")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class InspectProcessTool(Tool):
    spec = ToolSpec(
        name="inspect_process",
        description="Check if a process is still alive (by pid or name) and report "
        "basic state.",
        category="process",
        parameters={"pid": "int (optional)", "name": "str (optional)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, pid: int | None = None, name: str = "", **kwargs: Any) -> ToolResult:
        try:
            procs = _list_processes()
            if pid is not None:
                match = [p for p in procs if p["pid"] == pid]
                if match:
                    return self.ok(f"pid {pid} is running", data={"running": True, **match[0]})
                return self.ok(f"pid {pid} is NOT running", data={"running": False})
            if name:
                match = [p for p in procs if name.lower() in p["name"].lower()]
                if match:
                    return self.ok(f"Found {len(match)} process(es)", data={"running": True, "count": len(match)})
                return self.ok(f"No process '{name}'", data={"running": False})
            return self.fail("Provide either pid or name")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


# -- platform helpers ------------------------------------------------------
def _list_processes() -> list[dict[str, Any]]:
    if sys.platform.startswith("win"):
        try:
            out = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True, text=True).stdout
            rows = []
            for line in out.splitlines()[1:]:
                parts = line.split('","')
                if len(parts) < 2:
                    continue
                name = parts[0].strip('"')
                pid = int(parts[1].strip('"'))
                rows.append({"pid": pid, "name": name, "cmd": ""})
            return rows
        except Exception:  # noqa: BLE001
            return []

    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,comm,args"], capture_output=True, text=True
        ).stdout
        rows = []
        for line in out.splitlines()[1:]:
            parts = line.split(None, 2)
            if len(parts) < 2:
                continue
            rows.append({"pid": int(parts[0]), "name": parts[1], "cmd": parts[2] if len(parts) > 2 else ""})
        return rows
    except Exception:  # noqa: BLE001
        return []


def _kill_pid(pid: int) -> None:
    if sys.platform.startswith("win"):
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, 9)  # SIGKILL


ALL_TOOLS: list[type[Tool]] = [StartProcessTool, ListProcessesTool, StopProcessTool, InspectProcessTool]
