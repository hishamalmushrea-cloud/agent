"""Tool abstraction.

A tool is a single, self-contained capability the agent can invoke.  Each tool
declares a :class:`ToolSpec` (name, description, parameters, permission level)
so the registry can advertise it to the LLM (discovery) and so the permission
layer can classify how risky it is.
"""

from __future__ import annotations

import abc
import time
from typing import Any, Awaitable, Callable

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec


class Tool(abc.ABC):
    """Base class for synchronous tools."""

    spec: ToolSpec

    @abc.abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool.  Must always return a ToolResult (never raise)."""

    # Convenience helpers --------------------------------------------------
    def ok(self, output: str, **extra: Any) -> ToolResult:
        return ToolResult(
            tool=self.spec.name,
            ok=True,
            output=output,
            data=extra.get("data"),
            exit_code=extra.get("exit_code"),
            duration_ms=extra.get("duration_ms"),
            meta=extra.get("meta", {}),
        )

    def fail(self, error: str, output: str = "", **extra: Any) -> ToolResult:
        return ToolResult(
            tool=self.spec.name,
            ok=False,
            output=output,
            error=error,
            exit_code=extra.get("exit_code"),
            duration_ms=extra.get("duration_ms"),
            meta=extra.get("meta", {}),
        )


class AsyncTool(Tool):
    """Optional base for async tools.  If you subclass this the executor will
    await :meth:`run_async`; the sync path falls back to ``run``."""

    async def run_async(self, **kwargs: Any) -> ToolResult:
        return await _run_as_async(self.run, **kwargs)


async def _run_as_async(fn: Callable[..., ToolResult], **kwargs: Any) -> ToolResult:
    import asyncio

    return await asyncio.to_thread(fn, **kwargs)


class PythonFuncTool(Tool):
    """Wrap a plain callable into a Tool with a declared spec."""

    def __init__(self, spec: ToolSpec, fn: Callable[..., Any]):
        self.spec = spec
        self._fn = fn

    def run(self, **kwargs: Any) -> ToolResult:
        started = time.monotonic()
        try:
            data = self._fn(**kwargs)
            return ToolResult(
                tool=self.spec.name,
                ok=True,
                output=_stringify(data),
                data=data,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 - tools must not raise
            return self.fail(str(exc), duration_ms=int((time.monotonic() - started) * 1000))


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, dict)):
        import json

        return json.dumps(value, ensure_ascii=False, default=str, indent=2)
    return str(value)
