"""Runtime facade — the single "Local Agent" object.

Holds the tools, the permission matrix, the audit log, the action executor and
the emergency-stop state, and exposes high-level methods used by the chat GUI,
the /actions API, the browser extension bridge and the MCP bridge.  This is the
"Local Agent = Hands" component that Arena delegates to.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from agent_platform.actions.executor import ActionExecutor
from agent_platform.actions.protocol import ActionKind, ProtocolAction
from agent_platform.audit.audit import AuditLogger
from agent_platform.config import Settings
from agent_platform.permission.matrix import PermissionMatrix
from agent_platform.tools.registry import ToolRegistry


class AgentRuntime:
    def __init__(self, registry: ToolRegistry, settings: Settings,
                 permission: PermissionMatrix | None = None,
                 audit: AuditLogger | None = None) -> None:
        self.registry = registry
        self.settings = settings
        self.permission = permission or PermissionMatrix(settings.approval_mode)
        self.audit = audit or AuditLogger(settings)
        self.executor = ActionExecutor(registry, self.permission, self.audit)

        # Emergency stop.
        self._stop_event = threading.Event()
        self._status = "IDLE"

    # --- status ---------------------------------------------------------
    @property
    def status(self) -> str:
        return self._status

    def set_status(self, status: str) -> None:
        self._status = status

    def stop(self) -> None:
        """Emergency stop: set the flag. Adopters must echo this back by checking
        ``should_stop`` between steps and by not starting new actions."""
        self._stop_event.set()
        self._status = "STOPPED"
        self.audit.record(action="STOP", target="all", result="STOPPED")

    def reset(self) -> None:
        self._stop_event.clear()
        self._status = "IDLE"

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    # --- actions --------------------------------------------------------
    async def run_action(self, action: ProtocolAction) -> Any:
        if self.should_stop():
            from agent_platform.actions.protocol import ProtocolResult

            return ProtocolResult(id=action.id or action.kind.value, kind=action.kind,
                                  ok=False, error="Agent is stopped (emergency stop).")
        self.set_status("EXECUTING")
        result = await self.executor.execute(action)
        if result.ok:
            self.set_status("IDLE")
        elif result.needs_confirmation:
            self.set_status("WAITING_FOR_USER")
        return result

    def describe(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "stopped": self._stop_event.is_set(),
            "tools": len(self.registry.names()),
            "permissions": self.permission.summary(),
            "audit": self.audit.stats(),
            "ocr_engines": _ocr_engines(),
        }


def _ocr_engines() -> list[str]:
    try:
        from agent_platform.vision.ocr import get_ocr_registry

        return get_ocr_registry().available_names()
    except Exception:  # noqa: BLE001
        return []


# Process-wide runtime.
_runtime: AgentRuntime | None = None


def get_runtime(registry: ToolRegistry | None = None, settings: Settings | None = None) -> AgentRuntime:
    global _runtime
    if _runtime is None:
        settings = settings or Settings()
        registry = registry or _import_registry()
        _runtime = AgentRuntime(registry, settings)
    return _runtime


def _import_registry() -> ToolRegistry:
    from agent_platform.tools.registry import register_all

    return register_all()
