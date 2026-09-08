"""Workflow node types.

A workflow is a directed graph of nodes.  Nodes are single-responsibility
units: triggers, tool actions, conditionals and transformations.  They pass a
mutable execution *context* between them, exactly the "nodes and connections"
model that makes workflows deterministic and observable (unlike pure agentic
reasoning).
"""

from __future__ import annotations

from typing import Any


class NodeContext:
    """Mutable state flowing between nodes during a run."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.log: list[dict[str, Any]] = []
        self.history: list[str] = []
        self.trigger: Any = None


class Node:
    type = "node"

    def __init__(self, node_id: str, config: dict[str, Any]) -> None:
        self.id = node_id
        self.config = config or {}

    def run(self, ctx: NodeContext, registry: Any) -> Any:
        """Synchronous execution.  Async-only nodes override ``run_async``."""
        return None

    def resolve(self, value: Any, ctx: NodeContext) -> Any:
        """Template substitution: {var} reads ctx.data."""
        if isinstance(value, str) and "{" in value:
            out = value
            for k, v in ctx.data.items():
                out = out.replace("{{" + k + "}}", str(v))
                out = out.replace("{" + k + "}", str(v))
            return out
        return value


class TriggerNode(Node):
    type = "trigger"

    def run(self, ctx: NodeContext, registry: Any) -> Any:
        event = self.config.get("event", "manual")
        ctx.trigger = event
        ctx.data.setdefault("_trigger", event)
        return {"event": event}


class ToolNode(Node):
    type = "tool"

    async def run_async(self, ctx: NodeContext, registry: Any) -> Any:
        tool = self.config.get("tool")
        args = {k: self.resolve(v, ctx) for k, v in (self.config.get("arguments") or {}).items()}
        result = await registry.invoke(tool, **args)
        ctx.data[tool] = result.data if result.data is not None else result.output
        ctx.log.append({"node": self.id, "tool": tool, "ok": result.ok})
        ctx.history.append(f"{tool} -> {result.output[:120]}")
        return {"ok": result.ok, "output": result.output, "data": result.data}


class ConditionNode(Node):
    type = "condition"

    def run(self, ctx: NodeContext, registry: Any) -> bool:
        # Simple truthiness on a resolved key; supports "equals" comparisons.
        key = self.resolve(self.config.get("key", ""), ctx)
        operator = self.config.get("operator", "truthy")
        expected = self.config.get("value")
        actual = ctx.data.get(key)
        if operator == "truthy":
            return bool(actual)
        if operator == "equals":
            return actual == expected
        if operator == "gt":
            try:
                return float(actual) > float(expected)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
        if operator == "exists":
            return key in ctx.data
        return bool(actual)


class TransformNode(Node):
    type = "transform"

    def run(self, ctx: NodeContext, registry: Any) -> Any:
        # Python expression evaluated against ctx.data (crude but deterministic).
        expr = self.config.get("expression", "")
        try:
            result = eval(expr, {"__builtins__": {}}, ctx.data)  # noqa: S307
        except Exception as exc:  # noqa: BLE001
            result = None
            ctx.log.append({"node": self.id, "error": str(exc)})
        ctx.data[self.config.get("into", "_transform")] = result
        return {"data": result}


class SleepNode(Node):
    type = "sleep"

    def run(self, ctx: NodeContext, registry: Any) -> Any:
        import time

        time.sleep(float(self.config.get("seconds", 0)))
        return {"slept": self.config.get("seconds", 0)}


NODE_TYPES: dict[str, type[Node]] = {
    "trigger": TriggerNode,
    "tool": ToolNode,
    "condition": ConditionNode,
    "transform": TransformNode,
    "sleep": SleepNode,
}
