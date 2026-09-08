"""Task lifecycle manager.

Owns task state (PENDING -> PLANNING -> EXECUTING -> WAITING/VERIFYING/
RECOVERING -> COMPLETED/FAILED/CANCELLED), persistence (so tasks survive an
app restart and can resume), background execution and the approval bridge.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_platform.core.agent import Agent
from agent_platform.core.events import EventBus
from agent_platform.memory.memory import MemoryManager
from agent_platform.models.schemas import EventKind, Task, TaskState

_RUNNING_STATES = frozenset({
    TaskState.PLANNING, TaskState.EXECUTING, TaskState.WAITING,
    TaskState.VERIFYING, TaskState.RECOVERING,
})


class TaskManager:
    def __init__(self, agent: Agent, memory: MemoryManager, bus: EventBus,
                 storage_dir: Path) -> None:
        self.agent = agent
        self.memory = memory
        self.bus = bus
        self.storage_dir = storage_dir
        self.tasks_dir = storage_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, Task] = {}
        self._runners: dict[str, asyncio.Task] = {}
        self._load_all()

    # -- CRUD ------------------------------------------------------------
    def create(self, goal: str, workspace: str = "", requested_by: str = "local") -> Task:
        task = Task(goal=goal, requested_by=requested_by)
        if workspace:
            task.workspace = workspace
        self._tasks[task.id] = task
        self._persist(task)
        self.bus.emit_kind(task.id, EventKind.TASK_CREATED, "Task created")
        self.memory.record_task(task.id, f"Goal: {goal}")
        return task

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list(self, limit: int = 100) -> list[Task]:
        tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    def delete(self, task_id: str) -> bool:
        task = self._tasks.pop(task_id, None)
        if task is None:
            return False
        self._task_file(task_id).unlink(missing_ok=True)
        self.bus.clear(task_id)
        return True

    # -- execution -------------------------------------------------------
    async def start(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        if task.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
            return False  # terminal, restart as new
        if task.state in _RUNNING_STATES:
            return True
        runner = asyncio.create_task(self.agent.start(task),
                                     name=f"task-{task_id}")
        self._runners[task_id] = runner
        return True

    async def approve(self, task_id: str, approved: bool) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        # Resume in a fresh runner.
        runner = asyncio.create_task(self.agent.resume(task, approved), name=f"resume-{task_id}")
        self._runners[task_id] = runner
        return True

    async def cancel(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        await self.agent.cancel(task)
        runner = self._runners.get(task_id)
        if runner and not runner.done():
            runner.cancel()
        self._persist(task)
        return True

    def is_running(self, task_id: str) -> bool:
        runner = self._runners.get(task_id)
        return bool(runner and not runner.done())

    # -- persistence -----------------------------------------------------
    def _task_file(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _persist(self, task: Task) -> None:
        try:
            self._task_file(task.id).write_text(
                json.dumps(task.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    def _load_all(self) -> None:
        for f in self.tasks_dir.glob("*.json"):
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                task = Task.model_validate(raw)
                self._tasks[task.id] = task
            except Exception:  # noqa: BLE001
                continue

    def resume_pending(self) -> list[Task]:
        """Re-open tasks that were parked waiting approval or running at last
        shutdown, so the app can show them after restart."""
        return [t for t in self._tasks.values()
                if t.state in (TaskState.WAITING, TaskState.EXECUTING, TaskState.PLANNING)]

    async def shutdown(self) -> None:
        for runner in list(self._runners.values()):
            if not runner.done():
                runner.cancel()
        for task in self._tasks.values():
            if task.state not in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                self._persist(task)
