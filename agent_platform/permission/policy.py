"""Permission / Human-Approval policy.

The agent may not run everything automatically.  Each tool is classified
SAFE / SENSITIVE / DANGEROUS.  The policy decides, based on the configured
approval mode and the specific arguments (e.g. dangerous commands, deletes),
whether a call is:

  * ALLOW  — run immediately
  * ASK    — surface to the user for confirmation and wait
  * DENY   — never run (e.g. matched a deny-list)

Least privilege is the default: SENSITIVE and DANGEROUS calls require explicit
approval unless the user opts into auto-approval.  Admin elevation is never
requested implicitly.
"""

from __future__ import annotations

import enum
import os
import re
from typing import Any

from agent_platform.models.schemas import PermissionLevel, ToolSpec

# Command prefixes that are always dangerous to run automatically.
_DANGEROUS_COMMAND_PREFIXES = [
    "rm", "rd", "del", "attrib", "format", "diskpart", "shutdown", "restart",
    "reg delete", "taskkill", "powershell -enc", "Invoke-WebRequest",
    "certutil", "netsh", "net user", "wmic", "bcdedit", "vssadmin",
]
# Command prefixes that are safe-ish but still flagged SENSITIVE.
_SENSITIVE_COMMAND_PREFIXES = [
    "pip install", "npm install", "npm i", "choco", "scoop", "winget",
    "git push", "git commit", "brew install", "docker", "kubectl", "curl",
    "wget", "Invoke-Expression",
]


class ApprovalDecision(str, enum.Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionPolicy:
    def __init__(self, mode: str = "safe") -> None:
        # mode: 'safe' (allow safe, ask sensitive/dangerous), 'auto' (allow all),
        #       'strict' (ask everything), 'banned' (deny dangerous).
        self.mode = mode

    def check(self, spec: ToolSpec, arguments: dict[str, Any] = {},
              task_id: str = "") -> ApprovalDecision:
        if self.mode == "strict":
            return ApprovalDecision.ASK
        if self.mode == "banned":
            if self._is_dangerous(spec, arguments):
                return ApprovalDecision.DENY
            return ApprovalDecision.ALLOW

        if spec.permission == PermissionLevel.DANGEROUS:
            if self._is_denied_command(arguments):
                return ApprovalDecision.DENY
            return ApprovalDecision.ASK if self.mode != "auto" else ApprovalDecision.ALLOW
        if spec.permission == PermissionLevel.SENSITIVE:
            return ApprovalDecision.ASK if self.mode != "auto" else ApprovalDecision.ALLOW
        return ApprovalDecision.ALLOW

    def _is_dangerous(self, spec: ToolSpec, arguments: dict[str, Any]) -> bool:
        if spec.permission == PermissionLevel.DANGEROUS:
            return True
        if spec.name == "shell" and arguments:
            return self._command_matches(arguments.get("command", ""), _DANGEROUS_COMMAND_PREFIXES)
        return False

    def _is_denied_command(self, arguments: dict[str, Any]) -> bool:
        command = str(arguments.get("command", "") or "").lower()
        if self.mode == "banned":
            return self._command_matches(command, _DANGEROUS_COMMAND_PREFIXES)
        # In safe mode, hard-block a small set that is never safe to auto-run.
        return self._command_matches(command, ["format ", "diskpart ", "bcdedit ", "shutdown /s", "reg delete"])

    @staticmethod
    def _command_matches(command: str, prefixes: list[str]) -> bool:
        cmd = command.strip().lower()
        return any(cmd.startswith(p) or (" " + p) in cmd for p in prefixes)


# Registry-driven approval decisions that need to be recorded for the GUI.
def describe_requirement(spec: ToolSpec, decision: ApprovalDecision) -> dict[str, Any]:
    return {
        "tool": spec.name,
        "permission": spec.permission.value,
        "decision": decision.value,
    }
