"""In-process event bus.

The agent engine emits :class:`Event` objects as it progresses (planning, tool
calls, observations, verification, recovery, completion...).  The HTTP server
subscribes and forwards them to the GUI over Server-Sent Events so the user can
watch the agent *live* — the execution timeline.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Callable

from agent_platform.models.schemas import Event, EventKind


class EventBus:
    def __init__(self, history_limit: int = 500) -> None:
        self._subscribers: list[Callable[[Event], None]] = []
        self._by_task: dict[str, deque[Event]] = defaultdict(lambda: deque(maxlen=history_limit))
        self._lock: Any = None
        try:
            import threading

            self._lock = threading.Lock()
        except Exception:  # noqa: BLE001
            pass

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._subscribers.append(fn)

    def unsubscribe(self, fn: Callable[[Event], None]) -> None:
        if fn in self._subscribers:
            self._subscribers.remove(fn)

    def emit(self, event: Event) -> None:
        self._by_task[event.task_id].append(event)
        for fn in list(self._subscribers):
            try:
                fn(event)
            except Exception:  # noqa: BLE001
                pass

    # -- helpers ----------------------------------------------------------
    def emit_kind(self, task_id: str, kind: EventKind | str, message: str = "",
                  payload: dict[str, Any] | None = None) -> Event:
        if not isinstance(kind, EventKind):
            # Accept by attribute name or value (e.g. "TOOL_CALL" or "tool_call").
            try:
                kind = EventKind[str(kind)]
            except KeyError:
                kind = EventKind(kind) if kind in {e.value for e in EventKind} else EventKind.LOG
        ev = Event(task_id=task_id, kind=kind, message=message, payload=payload or {})
        self.emit(ev)
        return ev

    def history(self, task_id: str, limit: int = 200) -> list[Event]:
        dq = self._by_task.get(task_id, deque())
        return list(dq)[-limit:]

    def iter_history(self, task_id: str):
        return self._by_task.get(task_id, deque())

    def clear(self, task_id: str) -> None:
        if task_id in self._by_task:
            self._by_task[task_id].clear()


# Process-wide bus.
_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
