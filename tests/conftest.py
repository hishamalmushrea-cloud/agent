"""Shared fixtures.

We build isolated components so unit tests never depend on the global server
state or on a network / LLM.  The agent uses the *heuristic* provider (offline)
unless environment variables for a real endpoint are set.
"""

from __future__ import annotations

import asyncio
import pytest

from agent_platform.config import Settings
from agent_platform.core.agent import Agent
from agent_platform.core.events import EventBus
from agent_platform.llm.provider import HeuristicProvider
from agent_platform.tools.registry import ToolRegistry, register_all


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    for mod in ("file_tools", "shell_tools", "process_tools", "system_tools"):
        mod = __import__(f"agent_platform.tools.{mod}", fromlist=["ALL_TOOLS"])
        for cls in mod.ALL_TOOLS:
            reg.register(cls())
    return reg


@pytest.fixture()
def settings() -> Settings:
    s = Settings()
    s.max_retries = 2
    s.max_steps = 20
    return s


@pytest.fixture()
def agent(registry, settings) -> Agent:
    # auto-approve so execution-completion tests can run end-to-end offline.
    return Agent(settings, registry, HeuristicProvider(settings), EventBus(), approval_mode="auto")


def run(coro):
    return asyncio.run(coro)
