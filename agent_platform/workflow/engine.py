"""WorkflowEngine — deterministic execution of a node/edge graph.

Complementary to the agent: the *agent* decides the high-level plan (the
"brain"), while a *workflow* executes a fixed, reproducible, observable series
of steps (the "hands" when you want determinism).  This mirrors the n8n idea
of Agent + Workflow + Tools + Events + Automation.
"""

from __future__ import annotations

from typing import Any

from agent_platform.tools.registry import ToolRegistry
from agent_platform.workflow.nodes import NODE_TYPES, Node, NodeContext


class WorkflowValidationError(Exception):
    pass


class Workflow:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.name = spec.get("name", "workflow")
        self.description = spec.get("description", "")
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, list[str]] = {}
        for n in spec.get("nodes", []):
            node_type = NODE_TYPES.get(n.get("type"))
            if node_type is None:
                raise WorkflowValidationError(f"Unknown node type '{n.get('type')}'")
            self.nodes[n["id"]] = node_type(n["id"], n.get("config", {}))
        for e in spec.get("edges", []):
            if isinstance(e, (list, tuple)):
                src, dst = e[0], e[1]
            else:
                src, dst = e.get("from"), e.get("to")
            self.edges.setdefault(src, []).append(dst)
        self.start_id = spec.get("start")
        if self.start_id is None:
            for nid, node in self.nodes.items():
                if node.type == "trigger":
                    self.start_id = nid
                    break
        if self.start_id is None:
            self.start_id = next(iter(self.nodes), None)

    async def run(self, registry: ToolRegistry,
                  bus: Any = None, task_id: str = "") -> NodeContext:
        ctx = NodeContext()
        visited: set[str] = set()
        queue = [self.start_id] if self.start_id else []
        while queue:
            nid = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            node = self.nodes.get(nid)
            if node is None:
                continue
            if bus is not None:
                bus.emit_kind(task_id, "TOOL_CALL" if node.type == "tool" else "LOG",
                              f"workflow node {node.type} '{nid}'",
                              payload={"node_id": nid, "type": node.type})
            result = await self._run_node(node, ctx, registry)
            ctx.data.setdefault(f"_result_{nid}", result)
            if node.type == "condition" and result is False:
                # Follow only the "false" edges later; simplest: skip unless a
                # dedicated false-edge key is used. Here we keep it simple by
                # continuing to all edges.
                pass
            queue.extend(self.edges.get(nid, []))
        return ctx

    async def _run_node(self, node: Node, ctx: NodeContext, registry: ToolRegistry) -> Any:
        if hasattr(node, "run_async"):
            return await node.run_async(ctx, registry)
        return node.run(ctx, registry)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "nodes": [{"id": nid, "type": n.type} for nid, n in self.nodes.items()],
            "start": self.start_id,
        }


class WorkflowEngine:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._workflows: dict[str, Workflow] = {}

    def register(self, wf: Workflow, name: str = "") -> None:
        self._workflows[name or wf.name] = wf

    def get(self, name: str) -> Any:
        return self._workflows.get(name)

    def list(self) -> list[dict[str, Any]]:
        return [wf.to_dict() for wf in self._workflows.values()]

    async def run(self, name: str, bus: Any = None, task_id: str = "") -> NodeContext:
        wf = self._workflows.get(name)
        if wf is None:
            raise WorkflowValidationError(f"Workflow '{name}' not found")
        return await wf.run(self.registry, bus=bus, task_id=task_id)
