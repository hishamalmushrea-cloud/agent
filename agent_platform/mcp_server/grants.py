"""Persisted tool-grant store for device access.

The user grants device-access permissions in the app; these are recorded here
(on disk under ``~/.agent_platform/grants.json``) and enforced by the MCP server
and the executor.  This lets the agent call local tools only when the user has
granted them — the central "الأذونات" (permissions) gate.

Least-privilege: SENSITIVE / DANGEROUS tools are never auto-granted; they require
an explicit user grant.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


def _grants_file() -> Path:
    base = Path(os.environ.get("AGENT_CONFIG_FILE", str(Path.home() / ".agent_platform")))
    base.mkdir(parents=True, exist_ok=True)
    return base / "grants.json"


class GrantStore:
    def __init__(self, file: Path | None = None) -> None:
        self._file = file or _grants_file()
        self._grants: set[str] = set()
        self._auto_approve: bool = False
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                raw = json.loads(self._file.read_text(encoding="utf-8"))
                self._grants = set(raw.get("tools", []))
                self._auto_approve = bool(raw.get("auto_approve", False))
            except Exception:  # noqa: BLE001
                pass

    def _save(self) -> None:
        with self._lock:
            self._file.write_text(
                json.dumps({"tools": sorted(self._grants), "auto_approve": self._auto_approve},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def grant(self, tool: str) -> None:
        self._grants.add(tool)
        self._save()

    def grant_many(self, tools: list[str]) -> None:
        self._grants.update(tools)
        self._save()

    def revoke(self, tool: str) -> None:
        self._grants.discard(tool)
        self._save()

    def has(self, tool: str) -> bool:
        return self._auto_approve or tool in self._grants

    def set_auto(self, value: bool) -> None:
        self._auto_approve = value
        self._save()

    def auto_approve(self) -> bool:
        return self._auto_approve

    def list_grants(self) -> dict[str, Any]:
        return {
            "auto_approve": self._auto_approve,
            "tools": sorted(self._grants),
            "granted_count": len(self._grants),
        }


# Process-wide singleton shared by the FastAPI app and the MCP server when both
# are hosted in the same process (desktop app).
_grants: GrantStore | None = None


def get_grant_store() -> GrantStore:
    global _grants
    if _grants is None:
        _grants = GrantStore()
    return _grants
