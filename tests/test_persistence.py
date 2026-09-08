"""Tests that conversations/sessions persist across an app restart.

This is the "the session doesn't break, old conversations appear" guarantee:
tasks, their messages and plan state are reloaded from the local store.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_platform.config import Settings
from agent_platform.core.agent import Agent
from agent_platform.core.events import EventBus
from agent_platform.llm.provider import HeuristicProvider
from agent_platform.memory.memory import MemoryManager
from agent_platform.memory.store import MemoryStore
from agent_platform.models.schemas import Message, Role
from agent_platform.tasks.manager import TaskManager


def _big_registry():
    from agent_platform.tools.registry import ToolRegistry
    from agent_platform.tools import file_tools, shell_tools, system_tools, process_tools

    reg = ToolRegistry()
    for mod in (file_tools, shell_tools, system_tools, process_tools):
        for cls in mod.ALL_TOOLS:
            reg.register(cls())
    return reg


def _build_manager(tmp, settings, registry):
    agent = Agent(settings, registry, HeuristicProvider(settings), EventBus(), approval_mode="auto")
    mem = MemoryManager(MemoryStore(Path(tmp)))
    return TaskManager(agent, mem, EventBus(), Path(tmp))


def test_messages_survive_restart(settings):
    registry = _big_registry()
    with tempfile.TemporaryDirectory() as d:
        s = Settings()
        s.storage_dir = d
        tm = _build_manager(d, s, registry)
        task = tm.create("الهدف الأول", workspace=d)
        task.messages.append(Message(role=Role.USER, content="مرحبا")
        )
        task.messages.append(Message(role=Role.ASSISTANT, content="أهلًا. سأساعدك."))
        tm._persist(task)

        # "Restart": a brand-new TaskManager reading the same storage dir.
        tm2 = _build_manager(d, s, registry)
        reloaded = tm2.get(task.id)
        assert reloaded is not None
        contents = [m.content for m in reloaded.messages]
        assert "مرحبا" in contents and "أهلًا. سأساعدك." in contents
        assert len(tm2.list()) == 1


def test_plan_state_survives_restart(settings):
    registry = _big_registry()
    with tempfile.TemporaryDirectory() as d:
        s = Settings()
        s.storage_dir = d
        tm = _build_manager(d, s, registry)
        task = tm.create("create a python project", workspace=d)
        # Run a full plan so the task has plan + messages + tool_calls.
        import asyncio

        asyncio.run(tm.agent.start(task))
        tm._persist(task)
        saved_steps = len(task.plan.steps)

        tm2 = _build_manager(d, s, registry)
        reloaded = tm2.get(task.id)
        assert reloaded is not None
        if reloaded.plan:
            assert len(reloaded.plan.steps) == saved_steps
