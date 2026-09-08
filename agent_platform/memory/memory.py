"""MemoryManager — the layered memory policy.

Layers:
  * Session — this conversation/task's rolling context.
  * Task    — the current task's state and observations.
  * Project — durable facts scoped to a project path.
  * LongTerm— reusable wisdom (what worked, user preferences).
  * Tool    — what a tool returned and whether it worked.

Retention & privacy policy:
  * Session memory is bounded and never persisted.
  * Task memory is persisted while a task is open.
  * Project / LongTerm / Tool memory is persisted but stores only non-secret,
    non-PII summaries by default (the recorder should not push credentials).
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from agent_platform.memory.store import MemoryStore
from agent_platform.models.schemas import MemoryItem, MemoryKind


class MemoryManager:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self._session: dict[str, MemoryItem] = {}

    # -- record ----------------------------------------------------------
    def record_session(self, task_id: str, text: str) -> None:
        self._session[task_id] = MemoryItem(
            kind=MemoryKind.SESSION, key=task_id, text=text, importance=0.4)

    def record_task(self, task_id: str, text: str) -> None:
        self.store.upsert(MemoryItem(
            kind=MemoryKind.TASK, key=task_id, text=text, importance=0.6))

    def record_project(self, scope: str, key: str, value: Any = None, text: str = "") -> None:
        self.store.upsert(MemoryItem(
            kind=MemoryKind.PROJECT, key=_hash_key(scope, key), value=value, text=text,
            importance=0.7, scope=scope))

    def record_long_term(self, key: str, text: str, importance: float = 0.6) -> None:
        self.store.upsert(MemoryItem(
            kind=MemoryKind.LONG_TERM, key=key, text=text, importance=importance,
            ttl_seconds=None, scope="global"))

    def record_tool(self, tool: str, summary: str, ok: bool) -> None:
        self.store.upsert(MemoryItem(
            kind=MemoryKind.TOOL, key=tool, text=summary, value={"ok": ok},
            importance=0.5, scope="tool"))

    # -- recall ----------------------------------------------------------
    def recall(self, query: str, kinds: list[MemoryKind],
               limit: int = 8) -> list[MemoryItem]:
        q = (query or "").lower()
        tokens = [t for t in q.replace("_", " ").split() if len(t) > 2]
        scored: list[tuple[float, MemoryItem]] = []
        for kind in kinds:
            candidates = list(self._session.values()) if kind == MemoryKind.SESSION \
                else self.store.all(kind)
            for item in candidates:
                text = f"{item.text} {item.key}".lower()
                score = 0.0
                for t in tokens:
                    if t in text:
                        score += 1.0
                # Recency & importance bonus.
                if item.importance:
                    score += item.importance * 0.3
                if score > 0:
                    scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [i for _, i in scored[:limit]]

    def forget_project(self, scope: str) -> None:
        for item in self.store.all(MemoryKind.PROJECT):
            if item.scope == scope:
                self.store.delete(MemoryKind.PROJECT, item.key)


def _hash_key(scope: str, key: str) -> str:
    return hashlib.sha1(f"{scope}:{key}".encode("utf-8")).hexdigest()[:16]
