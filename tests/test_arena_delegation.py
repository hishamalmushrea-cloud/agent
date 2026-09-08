"""Prove the platform executes an Arena-agent-provided runbook end-to-end.

This is the core of "the platform depends on the Arena agent": the Arena agent
returns a plan/runbook, and the platform carries it out with its own tools,
observing, verifying and completing.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from agent_platform.config import Settings
from agent_platform.core.agent import Agent
from agent_platform.core.events import EventBus
from agent_platform.llm.provider import ArenaAgentProvider
from agent_platform.models.schemas import Task, TaskState


def test_arena_runbook_is_executed(registry, settings):
    s = Settings()
    s.arena_endpoint = "http://arena.local"
    provider = ArenaAgentProvider(s)

    # Simulate a live Arena agent returning a runbook.
    provider.plan = lambda goal, tools: {
        "strategy": "arena-plan",
        "steps": [
            {"title": "Write file", "tool": "write_file",
             "arguments": {"path": "x.txt", "content": "hello from arena"},
             "verification": "file exists"},
        ],
    }
    provider.action_for_step = lambda goal, step, tools: {
        "tool": "write_file", "arguments": {"path": "x.txt", "content": "hello from arena"}}

    agent = Agent(settings, registry, provider, EventBus(), approval_mode="auto")
    with tempfile.TemporaryDirectory() as d:
        task = Task(goal="write a file", workspace=d)
        asyncio.run(agent.start(task))
        assert task.state == TaskState.COMPLETED
        # The platform actually created the file (it did the "doing").
        assert os.path.exists(os.path.join(d, "x.txt"))
        with open(os.path.join(d, "x.txt")) as f:
            assert "hello from arena" in f.read()
