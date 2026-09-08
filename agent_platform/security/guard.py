"""Security guardrail layer (red-team thinking).

These are the checks that stop the agent from being socially engineered into a
prompt-injection attack, leaking credentials, running an obviously destructive
command, or looping forever.  They are heuristics, not a perfect firewall — the
README states that honestly.  The point is that we *do* defend by default and
surface violations, rather than pretend the system is safe.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Prompt injection heuristics
# ---------------------------------------------------------------------------
_INJECTION_MARKERS = [
    "ignore all previous instructions",
    "ignore your instructions",
    "disregard previous",
    "you are now",            # attempts to take over persona
    "reveal your system prompt",
    "print your instructions",
    "you are free",           # jailbreak style
    "do anything you want",
    "no restrictions",
    "forget your rules",
    "treat this as",
    "system prompt",
    "developer message",
    "override your",
    "act as a different",
]

# ---------------------------------------------------------------------------
# Credential leakage heuristics
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"ghp_[A-Za-z0-9]{36}",
    r"xox[baprs]-[A-Za-z0-9-]{10,}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"-----BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY-----",
    r"Bearer [A-Za-z0-9\-\._~\+\/]{20,}",
    r"password\s*=\s*['\"][^'\"]+['\"]",
    r"api[_-]?key\s*=\s*['\"][^'\"]+['\"]",
]

_CREDENTIAL_FILE_HINT = re.compile(r"\.env\b|credentials|secrets\.json|id_rsa|\.pem\b", re.I)


class SecurityGuard:
    def sanitize_input(self, text: str) -> str:
        """Strip control chars used in terminal injection; return bounded text."""
        text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
        return text[:20000]

    def check_injection(self, text: str) -> Optional[str]:
        low = text.lower()
        for marker in _INJECTION_MARKERS:
            if marker in low:
                return f"Possible prompt injection: '{marker}'"
        return None

    def check_secrets(self, text: str) -> list[str]:
        found: list[str] = []
        for pat in _SECRET_PATTERNS:
            if re.search(pat, text):
                found.append(f"Possible credential/secret matched: {pat[:24]}")
        return found

    def check_command(self, command: str) -> Optional[str]:
        from agent_platform.permission.policy import (
            _DANGEROUS_COMMAND_PREFIXES,
            PermissionPolicy,
        )

        if PermissionPolicy._command_matches(command, ["format ", "diskpart ", "bcdedit "]):
            return "Command may be destructive to disks (denied)"
        if PermissionPolicy._command_matches(command, ["certutil -", "powershell -ep bypass", "-enc "]):
            return "Command looks like a bypass/encoding trick (denied)"
        return None

    def check_path_escape(self, path: str, workspace: str) -> Optional[str]:
        """Warn if the agent tries to escape the workspace (defense-in-depth)."""
        try:
            real_ws = os.path.realpath(workspace)
            real_path = os.path.realpath(os.path.expanduser(path))
            if real_path and not real_path.startswith(real_ws) and workspace:
                return f"Path escapes workspace: {path}"
        except Exception:  # noqa: BLE001
            pass
        return None

    def validate_goal(self, goal: str) -> str:
        return self.sanitize_input(goal)
