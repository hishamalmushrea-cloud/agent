"""Tool Registry — the Agent's discoverable "hands".

The registry holds every available tool, its metadata (ToolSpec), its
permission classification and the concrete object that runs it.  The agent
queries the registry to:
  * discover what tools exist (capabilities),
  * read what each tool expects (parameters) and how risky it is,
  * invoke a tool by name with validated arguments.

It is deliberately extensible: new tools/plugins register themselves, and the
GUI can list the registry over the API.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Optional

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec
from agent_platform.tools.base import AsyncTool, PythonFuncTool, Tool


class ToolAlreadyRegistered(Exception):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._specs: dict[str, ToolSpec] = {}

    # -- registration -----------------------------------------------------
    def register(self, tool: Tool, *, replace: bool = False) -> Tool:
        name = tool.spec.name
        if name in self._tools and not replace:
            raise ToolAlreadyRegistered(name)
        self._tools[name] = tool
        self._specs[name] = tool.spec
        return tool

    def register_func(self, spec: ToolSpec, fn: Callable[..., Any], *, replace: bool = False) -> Tool:
        return self.register(PythonFuncTool(spec, fn), replace=replace)

    def register_class(self, cls: type[Tool], *, replace: bool = False) -> Tool:
        return self.register(cls(), replace=replace)

    # -- discovery --------------------------------------------------------
    def list_specs(self, category: Optional[str] = None) -> list[ToolSpec]:
        specs = list(self._specs.values())
        if category:
            specs = [s for s in specs if s.category == category]
        return sorted(specs, key=lambda s: s.name)

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def categories(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self._specs.values():
            seen.setdefault(s.category, None)
        return sorted(seen.keys())

    def summary(self) -> dict[str, Any]:
        return {
            "count": len(self._tools),
            "categories": self.categories(),
            "tools": [self._spec_to_dict(s) for s in self._specs.values()],
        }

    # -- invocation -------------------------------------------------------
    async def invoke(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get_tool(name)
        if tool is None:
            return ToolResult(
                tool=name, ok=False, error=f"Unknown tool '{name}'",
            )
        if isinstance(tool, AsyncTool):
            return await tool.run_async(**kwargs)
        return tool.run(**kwargs)

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _spec_to_dict(spec: ToolSpec) -> dict[str, Any]:
        return {
            "name": spec.name,
            "description": spec.description,
            "category": spec.category,
            "permission": spec.permission.value,
            "parameters": spec.parameters,
            "managed_by": spec.managed_by,
            "version": spec.version,
            "requires_admin": spec.requires_admin,
            "input_example": spec.input_example,
        }


# ---------------------------------------------------------------------------
# A shared process-wide registry.
# ---------------------------------------------------------------------------
_global: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _global
    if _global is None:
        _global = ToolRegistry()
    return _global


def register(tool: Tool, *, replace: bool = False) -> Tool:
    return get_registry().register(tool, replace=replace)


def register_all() -> ToolRegistry:
    """Idempotently register every built-in tool set into the global registry."""
    reg = get_registry()

    def _try(tool: Tool) -> None:
        try:
            reg.register(tool)
        except ToolAlreadyRegistered:
            pass

    from agent_platform.tools import file_tools, process_tools, shell_tools, system_tools
    from agent_platform.vision import vision_agent

    for cls in file_tools.ALL_TOOLS:
        _try(cls())
    for cls in process_tools.ALL_TOOLS:
        _try(cls())
    for cls in shell_tools.ALL_TOOLS:
        _try(cls())
    for cls in system_tools.ALL_TOOLS:
        _try(cls())
    for cls in vision_agent.ALL_TOOLS:
        _try(cls())

    # Windows-specific tools (import guarded; they no-op on non-Windows).
    try:
        from agent_platform.tools import windows_tools

        for cls in windows_tools.ALL_TOOLS:
            _try(cls())
    except Exception:  # noqa: BLE001
        pass

    # Optional web/browser tools (need httpx / playwright).
    try:
        from agent_platform.tools import web_tools

        for cls in web_tools.ALL_TOOLS:
            _try(cls())
    except Exception:  # noqa: BLE001
        pass

    return reg
