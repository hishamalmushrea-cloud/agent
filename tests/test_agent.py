"""End-to-end engine tests (offline / heuristic brain).

These prove the *loop* — plan, execute, observe, verify, recover — works and
that the agent does not claim success without verification.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from agent_platform.core.agent import Agent
from agent_platform.core.events import EventBus
from agent_platform.llm.provider import HeuristicProvider
from agent_platform.models.schemas import Task, TaskState


def _run(coro):
    return asyncio.run(coro)


def _mk_agent(registry, settings, approval_mode="auto"):
    return Agent(settings, registry, HeuristicProvider(settings), EventBus(), approval_mode=approval_mode)


def test_agent_completes_a_create_task(agent):
    with tempfile.TemporaryDirectory() as d:
        task = Task(goal="create a python project", workspace=d)
        _run(agent.start(task))
        assert task.state == TaskState.COMPLETED
        assert task.result_summary  # non-empty evidence of verification
        # Confirm real files were created *inside the workspace*.
        assert os.path.exists(os.path.join(d, "app", "main.py"))


def test_agent_records_observation_and_tool_calls(agent):
    task = Task(goal="create a python project")
    _run(agent.start(task))
    assert len(task.tool_calls) > 0
    assert task.plan is not None and len(task.plan.steps) > 0
    assert all("tool" in tc for tc in task.tool_calls)


def test_approval_parks_then_resumes(registry, settings):
    agent = _mk_agent(registry, settings, approval_mode="safe")
    task = Task(goal="create a python project")
    _run(agent.start(task))
    # write_file is SENSITIVE -> parks waiting for approval, never claims success.
    assert task.state == TaskState.WAITING
    assert task.approval_needed
    assert not task.result_summary
    # Approve and resume -> should complete.
    _run(agent.resume(task, approved=True))
    assert task.state == TaskState.COMPLETED


def test_denied_approval_does_not_claim_success(registry, settings):
    agent = _mk_agent(registry, settings, approval_mode="safe")
    task = Task(goal="create a python project")
    _run(agent.start(task))
    assert task.state == TaskState.WAITING
    _run(agent.resume(task, approved=False))
    # Denial must not result in a false success.
    assert task.state in (TaskState.FAILED, TaskState.CANCELLED)


def test_failed_tool_marks_task_failed_without_fake_success(registry, settings):
    agent = _mk_agent(registry, settings)
    # Goal that runs a shell command that fails.
    task = Task(goal="run a failing command")
    # Force a failing command by crafting a plan step directly.
    from agent_platform.models.schemas import Plan, PlanStep

    task.plan = Plan(goal="run a failing command", strategy="t", steps=[
        PlanStep(index=0, title="run", tool="shell",
                 arguments={"command": "exit 3"}, verification="exit 0")])
    _run(agent.start(task))
    assert task.state == TaskState.FAILED
    assert task.failed_steps


def test_agent_emits_events_on_bus(registry, settings):
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))
    agent = _mk_agent(registry, settings)
    agent.bus = bus
    task = Task(goal="create a python project")
    _run(agent.start(task))
    kinds = {e.kind.value for e in events}
    assert "plan_ready" in kinds
    assert "tool_call" in kinds
    assert "completed" in kinds
