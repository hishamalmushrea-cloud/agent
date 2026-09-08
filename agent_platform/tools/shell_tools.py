"""Shell tools (Layer 2 — Shell).  PowerShell/CMD on Windows, sh on POSIX.

These let the agent run arbitrary commands.  Because they are powerful they are
classified DANGEROUS by default (fine-grained command allow/deny lists live in
the security/guard layer).  The ``shell`` tool intentionally supports a timeout
and captures stdout/stderr and the exit code so the agent can observe results.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec
from agent_platform.tools.base import Tool


class ShellTool(Tool):
    spec = ToolSpec(
        name="shell",
        description="Run a shell command and return stdout, stderr and exit code. "
        "On Windows use PowerShell (or cmd). On POSIX use /bin/sh. "
        "Used for compiling, installing packages, running tests, git, etc.",
        category="shell",
        parameters={"command": "str (required): the command line",
                     "timeout": "int (optional, default 60): seconds",
                     "cwd": "str (optional): working directory"},
        permission=PermissionLevel.DANGEROUS,
    )

    def run(self, command: str, timeout: int = 60, cwd: str = "", **kwargs: Any) -> ToolResult:
        try:
            shell = _detect_shell()
            run_dir = os.path.expanduser(cwd) if cwd else os.getcwd()
            proc = subprocess.run(
                [shell] + _shell_args(shell, command),
                cwd=run_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
            out = proc.stdout
            err = proc.stderr
            if proc.returncode != 0:
                return self.fail(
                    f"Command failed (exit {proc.returncode})", output=out, exit_code=proc.returncode
                )
            return self.ok(out + (("\n" + err) if err else ""), exit_code=proc.returncode)
        except subprocess.TimeoutExpired:
            return self.fail(f"Command timed out after {timeout}s", output="")
        except FileNotFoundError:
            return self.fail("Shell executable not found")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


def _detect_shell() -> str:
    if sys.platform.startswith("win"):
        # Prefer PowerShell if present, else cmd.
        if shutil.which("powershell"):
            return "powershell"
        return "cmd"
    return "/bin/sh"


def _shell_args(shell: str, command: str) -> list[str]:
    if shell.endswith("powershell"):
        return ["-NoProfile", "-Command", command]
    if shell.endswith("cmd"):
        return ["/C", command]
    return ["-c", command]


ALL_TOOLS: list[type[Tool]] = [ShellTool]
