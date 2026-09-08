"""Workflow engine tests (deterministic node/edge graphs)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from agent_platform.tools.registry import ToolRegistry
from agent_platform.workflow.engine import Workflow, WorkflowEngine


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    for mod in ("file_tools", "shell_tools", "process_tools", "system_tools"):
        m = __import__(f"agent_platform.tools.{mod}", fromlist=["ALL_TOOLS"])
        for cls in m.ALL_TOOLS:
            reg.register(cls())
    return reg


def test_workflow_runs_and_creates_file():
    reg = _registry()
    with tempfile.TemporaryDirectory() as d:
        wf = Workflow({
            "name": "t",
            "nodes": [
                {"id": "t", "type": "trigger", "config": {}},
                {"id": "dir", "type": "tool",
                 "config": {"tool": "create_directory", "arguments": {"path": f"{d}/x"}}},
                {"id": "file", "type": "tool",
                 "config": {"tool": "write_file",
                            "arguments": {"path": f"{d}/x/a.txt", "content": "hi"}}},
            ],
            "edges": [["t", "dir"], ["dir", "file"]],
            "start": "t",
        })
        ctx = asyncio.run(wf.run(reg))
        assert (Path(d) / "x" / "a.txt").exists()
        assert "write_file" in ctx.data


def test_workflow_engine_register_and_run():
    reg = _registry()
    eng = WorkflowEngine(reg)
    wf = Workflow({"name": "w", "nodes": [
        {"id": "t", "type": "trigger", "config": {}},
        {"id": "s", "type": "transform", "config": {"expression": "1 + 1", "into": "sum"}},
    ], "edges": [["t", "s"]], "start": "t"})
    eng.register(wf)
    ctx = asyncio.run(eng.run("w"))
    assert ctx.data.get("sum") == 2
