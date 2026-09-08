"""Executor — runs a single step's tool call through the registry.

It enforces the permission policy before invoking a tool: a DANGEROUS (or, in
strict mode, SENSITIVE) tool is routed for human approval.  Unapproved tools
are not run.  Results are always wrapped in a :class:`ToolResult`.
"""

from __future__ import annotations

import time
from typing import Any

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec
from agent_platform.tools.registry import ToolRegistry
from agent_platform.permission.policy import PermissionPolicy, ApprovalDecision


class Executor:
    def __init__(self, registry: ToolRegistry, policy: PermissionPolicy) -> None:
        self.registry = registry
        self.policy = policy

    async def execute(self, tool: str, arguments: dict[str, Any],
                      task_id: str, workspace: str = "", force: bool = False) -> ToolResult:
        spec = self.registry.get_spec(tool)
        started = time.monotonic()

        if spec is None:
            return ToolResult(tool=tool, ok=False, error=f"Unknown tool '{tool}'")

        # Permission gate ---------------------------------------------------
        # force=True is only set after explicit human approval.
        if not force:
            decision = self.policy.check(spec, arguments=arguments, task_id=task_id)
            if decision == ApprovalDecision.DENY:
                return ToolResult(tool=tool, ok=False, error="Denied by permission policy",
                                  meta={"decision": decision.value})
            if decision == ApprovalDecision.ASK:
                # Surface for approval and wait (the task manager parks the task).
                return ToolResult(tool=tool, ok=False, error="Awaiting human approval",
                                  meta={"decision": decision.value, "needs_approval": True})

        # Normalise boolean / numeric args as strings where needed ------------
        cleaned = self._coerce_args(spec, arguments)

        result = await self.registry.invoke(tool, **cleaned)
        result.tool = tool
        result.duration_ms = result.duration_ms or int((time.monotonic() - started) * 1000)
        return result

    @staticmethod
    def _coerce_args(spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        """Basic type coercion from the spec's declared parameters (best-effort).
        Parameters are declared as 'name': '<type> (required): description'."""
        params = spec.parameters or {}
        cleaned: dict[str, Any] = {}
        for key, value in arguments.items():
            decl = str(params.get(key, ""))
            if "int" in decl and not isinstance(value, bool) and not isinstance(value, int):
                try:
                    cleaned[key] = int(value)
                except (TypeError, ValueError):
                    cleaned[key] = value
            elif "bool" in decl and not isinstance(value, bool):
                cleaned[key] = str(value).lower() in ("1", "true", "yes", "on")
            else:
                cleaned[key] = value
        # Also include any declared parameter we have a default for and agent omitted.
        return cleaned
