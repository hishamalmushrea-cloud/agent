"""Agent — the orchestrator.

Implements the full autonomous loop:

    Goal -> Plan -> Decompose -> Pick tool -> Execute -> Observe -> Verify
          -> (failure?) -> Recover -> Replan -> ... -> Completion

It emits :class:`Event` objects on every transition, so the GUI timeline and
the SSE stream reflect *reality* — not a single chat reply.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from agent_platform.config import Settings
from agent_platform.core.context import ContextBuilder
from agent_platform.core.events import EventBus
from agent_platform.core.executor import Executor
from agent_platform.core.observer import Observer
from agent_platform.core.planner import Planner
from agent_platform.core.recovery import RecoveryEngine, RecoveryOutcome
from agent_platform.core.verifier import Verdict, Verifier
from agent_platform.models.schemas import (
    EventKind,
    Observation,
    PermissionLevel,
    Role,
    Task,
    TaskState,
)
from agent_platform.permission.policy import ApprovalDecision, PermissionPolicy
from agent_platform.tools.registry import ToolRegistry

_SYSTEM_PROMPT = (
    "You are an autonomous Windows computer agent. You are given a goal and a "
    "tool registry. Your job is to plan, execute, observe, verify and recover — "
    "not to just reply. Never claim a task succeeded unless it was verified. "
    "Prefer the least-privilege tool; use mouse/keyboard UI automation only as a "
    "last resort. Work in the task workspace."
)


class Agent:
    def __init__(self, settings: Settings, registry: ToolRegistry, provider: Any,
                 bus: EventBus, *, approval_mode: Optional[str] = None) -> None:
        self.settings = settings
        self.registry = registry
        self.provider = provider
        self.bus = bus

        self.policy = PermissionPolicy(approval_mode or settings.approval_mode)
        self.planner = Planner(provider)
        self.executor = Executor(registry, self.policy)
        self.observer = Observer()
        self.verifier = Verifier()
        self.recovery = RecoveryEngine(settings.max_retries)
        self.context = ContextBuilder()

        # Resume / approval state.
        self._pending: dict[str, dict[str, Any]] = {}
        self._cursor: dict[str, int] = {}
        self._forced: set[str] = set()

    # ------------------------------------------------------------------
    async def start(self, task: Task, workspace: str = "") -> None:
        """Begin (or restart) a task from its current plan state."""
        if workspace:
            task.workspace = workspace
        elif not task.workspace:
            task.workspace = self.settings.workspace_path.as_posix()
        if task.plan is None:
            await self._plan(task)
        start_index = self._cursor.get(task.id, 0)
        await self._loop(task, start_index=start_index)

    async def resume(self, task: Task, approved: bool) -> None:
        """Continue after a human approval decision."""
        pending = self._pending.pop(task.id, None)
        if not pending:
            return
        idx = pending["step_index"]
        if approved:
            self._cursor[task.id] = idx
            self._forced.add(task.id)
            self.bus.emit_kind(task.id, EventKind.APPROVAL_RESOLVED, "Approved — resuming", {"approved": True})
            await self._loop(task, start_index=idx)
        else:
            # Denial: mark the pending step failed and move past it.  Never run
            # a denied sensitive/dangerous tool, and never claim success.
            self.bus.emit_kind(task.id, EventKind.APPROVAL_RESOLVED,
                               "Denied — marking step failed", {"approved": False})
            if task.plan and idx < len(task.plan.steps):
                step = task.plan.steps[idx]
                step.status = "failed"
                task.failed_steps.append(step.id)
            self._cursor[task.id] = idx + 1
            await self._loop(task, start_index=idx + 1)

    async def cancel(self, task: Task) -> None:
        task.state = TaskState.CANCELLED
        self._pending.pop(task.id, None)
        self.bus.emit_kind(task.id, EventKind.CANCELLED, "Task cancelled")

    # ------------------------------------------------------------------
    async def _plan(self, task: Task) -> None:
        task.state = TaskState.PLANNING
        self.bus.emit_kind(task.id, EventKind.PLANNING, f"Planning: {task.goal}")
        specs = self.registry.list_specs()
        plan = self.planner.plan(task.goal, specs)
        task.plan = plan
        self._cursor[task.id] = 0
        self.bus.emit_kind(task.id, EventKind.PLAN_READY,
                           f"Plan ready ({len(plan.steps)} steps): {plan.strategy}",
                           payload={"plan": plan.model_dump()})

    async def _loop(self, task: Task, start_index: int = 0) -> None:
        if not task.plan or not task.plan.steps:
            task.state = TaskState.FAILED
            task.errors.append("No plan was generated")
            self.bus.emit_kind(task.id, EventKind.FAILED, "Failed: no plan generated")
            return

        steps = task.plan.steps
        force = task.id in self._forced
        self._forced.discard(task.id)

        for idx in range(max(start_index, 0), len(steps)):
            if task.state in (TaskState.CANCELLED, TaskState.FAILED):
                return
            step = steps[idx]
            if step.status in ("ok", "skipped"):
                continue
            task.state = TaskState.EXECUTING
            task.current_step_index = idx
            task.touch()
            self.bus.emit_kind(task.id, EventKind.STEP_STARTED,
                               f"[{idx + 1}/{len(steps)}] {step.title}",
                               payload={"index": idx, "step": step.model_dump()})

            tool, args = await self._choose_action(task, step)
            if tool is None:
                step.status = "skipped"
                task.touch()
                continue

            args = self._scope_paths(tool, args, task.workspace or "")
            result = await self.executor.execute(tool, args, task.id, workspace=task.workspace or "", force=force)
            task.tool_calls.append({"tool": tool, "arguments": args, "ok": result.ok})

            # Approval needed -> park the task.
            if result.meta.get("needs_approval"):
                self._pending[task.id] = {"tool": tool, "arguments": args, "step_index": idx}
                task.state = TaskState.WAITING
                task.approval_needed.append({"tool": tool, "arguments": args, "step_index": idx})
                task.touch()
                self.bus.emit_kind(task.id, EventKind.WAITING_APPROVAL,
                                   f"Waiting approval for: {tool}",
                                   payload={"tool": tool, "arguments": args})
                return  # park until resumed

            obs = self.observer.observe(step.id, tool, result)
            step.observation = obs
            task.touch()
            self.bus.emit_kind(task.id, EventKind.TOOL_CALL, f"tool call: {tool}",
                               payload={"tool": tool, "arguments": args})
            self.bus.emit_kind(task.id, EventKind.TOOL_RESULT, obs.summary,
                               payload={"tool": tool, "observation": self.observer.to_dict(obs)})

            verdict = self.verifier.verify_step(step, obs, args)
            if verdict.verdict == Verdict.PASS:
                step.status = "ok"
                task.completed_steps.append(step.id)
                self.bus.emit_kind(task.id, EventKind.VERIFIED, f"Verified: {step.title}",
                                   payload={"step": step.id})
            else:
                handled = await self._recover(task, step, tool, args, result, verdict)
                if not handled:
                    # Recovery exhausted -> record failure and stop the loop.
                    task.failed_steps.append(step.id)
                    task.state = TaskState.FAILED
                    task.errors.append(f"Step '{step.title}' failed after retries")
                    self.bus.emit_kind(task.id, EventKind.FAILED,
                                       f"Failed at step '{step.title}': {verdict.reason}")
                    return

        # All steps done -> goal verification.
        task.state = TaskState.VERIFYING
        self.bus.emit_kind(task.id, EventKind.VERIFYING, "Verifying overall goal")
        goal_v = self.verifier.verify_goal(task)
        if goal_v.verdict == Verdict.PASS:
            task.state = TaskState.COMPLETED
            task.result_summary = goal_v.reason
            self.bus.emit_kind(task.id, EventKind.COMPLETED, f"Completed: {goal_v.reason}",
                               payload={"summary": goal_v.reason})
        else:
            task.state = TaskState.FAILED
            task.errors.append(goal_v.reason or "Goal not verified")
            self.bus.emit_kind(task.id, EventKind.FAILED,
                               f"Goal not fully verified: {goal_v.reason}")

    async def _choose_action(self, task: Task, step: Any) -> tuple[Optional[str], dict[str, Any]]:
        # Prefer the tool the planner chose.
        if step.tool:
            tool = step.tool
            args = dict(step.arguments or {})
            return tool, args
        # Ask the provider to choose.
        specs = [
            {"name": s.name, "description": s.description, "parameters": s.parameters}
            for s in self.registry.list_specs()
        ]
        try:
            choice = await asyncio.to_thread(self.provider.action_for_step, task.goal,
                                             {"title": step.title, "description": step.description},
                                             specs)
        except Exception:  # noqa: BLE001
            choice = {"tool": None, "arguments": {}}
        if choice.get("tool"):
            return choice["tool"], dict(choice.get("arguments", {}))
        # Deterministic fallback for the heuristic provider.
        from agent_platform.core.heuristics import heuristic_action_for_step

        fallback = heuristic_action_for_step(task.goal, step.model_dump())
        return fallback["tool"], fallback["arguments"]

    @staticmethod
    def _scope_paths(tool: str, args: dict[str, Any], workspace: str) -> dict[str, Any]:
        """Scope file-path arguments to the task workspace.

        This keeps the agent working inside its project directory (least
        privilege / containment) and makes relative paths deterministic.
        """
        if not workspace:
            return args
        import os

        path_keys = {f: k for f in ("path", "source", "destination") for k in (f,)}
        out = dict(args)
        for key in ("path", "source", "destination"):
            val = out.get(key)
            if val and isinstance(val, str) and not os.path.isabs(val) and not val.startswith("~"):
                out[key] = os.path.join(workspace, os.path.expanduser(val))
        # Shell: resolve its cwd to the workspace when relative.
        cwd = out.get("cwd")
        if cwd and isinstance(cwd, str) and not os.path.isabs(cwd) and not cwd.startswith("~"):
            out["cwd"] = os.path.join(workspace, cwd)
        return out

    async def _recover(self, task: Task, step: Any, tool: str, args: dict[str, Any],
                       result: Any, verdict: Any) -> bool:
        """Attempt recovery; returns True if the step was retried, False to give up."""
        if step.retries >= self.settings.max_retries:
            return False
        outcome = self.recovery.build_retry(tool, args, result.error or verdict.reason, step.retries)
        if outcome is None:
            return False
        step.retries += 1
        task.state = TaskState.RECOVERING
        task.touch()
        self.bus.emit_kind(task.id, EventKind.RECOVERING,
                           f"Recovering ({outcome.strategy}): {outcome.note}",
                           payload={"tool": tool, "strategy": outcome.strategy})

        # A recovery may be a prep step (e.g. ensure dir) before the real one.
        if outcome.strategy == "ensure_parent_dir":
            prep = await self.executor.execute(outcome.tool, outcome.arguments, task.id, force=True)
            if not prep.ok:
                task.errors.append(f"Recovery prep failed: {prep.error}")
                return False
            # Re-use original tool with args now that the parent exists.
            await self._loop_from_step(task, step, tool, args)
            return True

        # Retry the (possibly modified) command.
        await self._loop_from_step(task, step, outcome.tool, outcome.arguments)
        return True

    async def _loop_from_step(self, task: Task, step: Any, tool: str, args: dict[str, Any]) -> None:
        """Re-execute a single step and update its status, then re-verify."""
        idx = step.index
        args = self._scope_paths(tool, args, task.workspace or "")
        result = await self.executor.execute(tool, args, task.id, workspace=task.workspace or "", force=True)
        task.tool_calls.append({"tool": tool, "arguments": args, "ok": result.ok})
        obs = self.observer.observe(step.id, tool, result)
        step.observation = obs
        verdict = self.verifier.verify_step(step, obs, args)
        if verdict.verdict == Verdict.PASS:
            step.status = "ok"
            task.completed_steps.append(step.id)
            self.bus.emit_kind(task.id, EventKind.RECOVERED, f"Recovered step '{step.title}'",
                               payload={"step": step.id, "tool": tool})
            self._cursor[task.id] = idx + 1
            return
        # Still failing — do not auto-fix beyond our mechanical corrections.
        step.status = "failed"
        task.failed_steps.append(step.id)
        self.bus.emit_kind(task.id, EventKind.RECOVERING, f"Recovery did not fix step '{step.title}'")


# Reasonable model of a "self-debugging" repair is out of scope for the engine
# itself; it belongs to a pluggable skill and requires a real LLM.  That is
# deliberately kept separate so the platform does not fake an LLM fix.
