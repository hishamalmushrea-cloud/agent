"""Permission Matrix — 4-tier risk model with human confirmation.

Tiers:
  SAFE       — read/screenshot/read public files         → auto
  NORMAL     — create/edit file, open app, browser       → auto (but logged)
  PRIVILEGED — install software, modify settings, elevated→ ASK (Allow Once/Always/Deny)
  DANGEROUS  — delete dirs, registry, security, kill    → ASK + strong denylist

Decisions returned:
  * "allow"     — run immediately
  * "grant"     — needs a device grant (per-tool) which the app records
  * "confirm"   — needs Allow Once / Always / Deny from the user
  * "deny"      — never run
"""

from __future__ import annotations

import enum
from typing import Any


class RiskLevel(str, enum.Enum):
    SAFE = "safe"
    NORMAL = "normal"
    PRIVILEGED = "privileged"
    DANGEROUS = "dangerous"


# Tool -> default risk (override by category)
_TOOL_RISK: dict[str, RiskLevel] = {
    # SAFE
    "read_file": RiskLevel.SAFE,
    "list_dir": RiskLevel.SAFE,
    "search_files": RiskLevel.SAFE,
    "system_info": RiskLevel.SAFE,
    "list_processes": RiskLevel.SAFE,
    "inspect_process": RiskLevel.SAFE,
    "network_status": RiskLevel.SAFE,
    "get_env": RiskLevel.SAFE,
    "screenshot": RiskLevel.SAFE,
    "ocr": RiskLevel.SAFE,
    "read_screen": RiskLevel.SAFE,
    "get_clipboard": RiskLevel.SAFE,
    "random_password": RiskLevel.SAFE,
    "wait": RiskLevel.SAFE,
    "fetch_page": RiskLevel.SAFE,
    "web_search": RiskLevel.SAFE,
    # NORMAL
    "create_directory": RiskLevel.NORMAL,
    "write_file": RiskLevel.NORMAL,
    "edit_file": RiskLevel.NORMAL,
    "copy_file": RiskLevel.NORMAL,
    "move_file": RiskLevel.NORMAL,
    "rename_file": RiskLevel.NORMAL,
    "open_application": RiskLevel.NORMAL,
    "focus_window": RiskLevel.NORMAL,
    "inspect_window": RiskLevel.NORMAL,
    "browser_agent": RiskLevel.NORMAL,
    "start_process": RiskLevel.NORMAL,
    "compress": RiskLevel.NORMAL,
    "extract": RiskLevel.NORMAL,
    # PRIVILEGED
    "shell": RiskLevel.PRIVILEGED,
    "run_as": RiskLevel.PRIVILEGED,
    "stop_process": RiskLevel.PRIVILEGED,
    "ui_interact": RiskLevel.PRIVILEGED,
    "install_package": RiskLevel.PRIVILEGED,
    "close_application": RiskLevel.PRIVILEGED,
    # DANGEROUS
    "delete_file": RiskLevel.DANGEROUS,
    "delete_directory": RiskLevel.DANGEROUS,
    "registry_edit": RiskLevel.DANGEROUS,
}

_DEFAULT_RISK = RiskLevel.NORMAL

# Command fragments that are always dangerous (deny).
_ALWAYS_DENY = [
    "format ", "diskpart ", "bcdedit ", "reg delete", "shutdown /s",
    "certutil -", "-ep bypass", "-enc ", ":(){ :|:& };:", "del /f /s /q c:",
]

# Command fragments that require confirmation even if the tool is NORMAL.
_NEEDS_CONFIRM = [
    "del ", "rm -rf", "rmdir /s", "pwsh -enc", "taskkill /f",
    "net user", "netsh", "vssadmin", "wmic", "diskpart",
]


class PermissionMatrix:
    def __init__(self, mode: str = "safe") -> None:
        self.mode = mode  # safe | auto | strict | banned
        self._grants: set[str] = set()
        self._always: set[str] = set()      # "always allow" confirmed tools
        self._denied: set[str] = set()

    # -- grants & confirmations -----------------------------------------
    def grant(self, tool: str) -> None:
        self._grants.add(tool)

    def revoke_grant(self, tool: str) -> None:
        self._grants.discard(tool)

    def has_grant(self, tool: str) -> bool:
        return tool in self._grants or self.mode in ("auto",)

    def confirm_always(self, tool: str) -> None:
        self._always.add(tool)

    def confirm_deny(self, tool: str) -> None:
        self._denied.add(tool)

    # -- evaluate --------------------------------------------------------
    def evaluate(self, tool: str, arguments: dict[str, Any] = {},
                 task_id: str = "", action: str = "") -> tuple[str | RiskLevel, RiskLevel]:
        """Return (decision, risk).  decision is one of allow/grant/confirm/deny."""
        risk = self._tool_risk(tool)

        # Hard deny list (even in auto mode).
        if self._command_denied(arguments):
            return "deny", risk
        if tool in self._denied:
            return "deny", risk

        if self.mode == "banned" and risk in (RiskLevel.PRIVILEGED, RiskLevel.DANGEROUS):
            return "deny", risk

        # Always-allow overrides confirm once user confirmed it.
        if tool in self._always:
            return "allow", risk

        if risk == RiskLevel.SAFE:
            return "allow", risk

        if risk == RiskLevel.NORMAL:
            # NORMAL tools that touch dangerous commands still ask.
            if self._command_needs_confirm(arguments):
                return self._ask_or_allow(risk)
            return "allow", risk

        if risk == RiskLevel.PRIVILEGED:
            return self._ask_or_allow(risk, needs_grant=True)

        # DANGEROUS
        return self._ask_or_allow(risk, needs_grant=True)

    def _ask_or_allow(self, risk: RiskLevel, needs_grant: bool = False):
        if self.mode == "auto":
            return "allow", risk
        if self.mode == "safe" and risk == RiskLevel.PRIVILEGED:
            return ("grant" if needs_grant else "confirm"), risk
        # default / strict
        return "confirm", risk

    def _tool_risk(self, tool: str) -> RiskLevel:
        return _TOOL_RISK.get(tool, _DEFAULT_RISK)

    @staticmethod
    def _command_denied(arguments: dict[str, Any]) -> bool:
        cmd = str(arguments.get("command", "") or "").lower()
        return any(f in cmd for f in _ALWAYS_DENY)

    @staticmethod
    def _command_needs_confirm(arguments: dict[str, Any]) -> bool:
        cmd = str(arguments.get("command", "") or "").lower()
        return any(f in cmd for f in _NEEDS_CONFIRM)

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "grants": sorted(self._grants),
            "always_allow": sorted(self._always),
            "denied": sorted(self._denied),
        }
