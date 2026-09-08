"""Memory subsystem tests (layered persistence + recall)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_platform.memory.memory import MemoryManager
from agent_platform.memory.store import MemoryStore
from agent_platform.models.schemas import MemoryKind


def _manager(tmp) -> MemoryManager:
    return MemoryManager(MemoryStore(Path(tmp)))


def test_record_and_recall_long_term():
    with tempfile.TemporaryDirectory() as d:
        mem = _manager(d)
        mem.record_long_term("user_pref", "prefers ruff over black", importance=0.8)
        hits = mem.recall("ruff formatting", [MemoryKind.LONG_TERM])
        assert any("ruff" in h.text for h in hits)


def test_tool_memory_stores_ok():
    with tempfile.TemporaryDirectory() as d:
        mem = _manager(d)
        mem.record_tool("shell", "exit 0", ok=True)
        item = mem.store.get(MemoryKind.TOOL, "shell")
        assert item is not None and item.value["ok"] is True


def test_project_scoped_forget():
    with tempfile.TemporaryDirectory() as d:
        mem = _manager(d)
        mem.record_project("proj/a", "framework", value="fastapi")
        assert mem.recall("framework", [MemoryKind.PROJECT])
        mem.forget_project("proj/a")
        assert not mem.recall("framework", [MemoryKind.PROJECT])


def test_ttl_purge():
    with tempfile.TemporaryDirectory() as d:
        store = MemoryStore(Path(d))
        from agent_platform.models.schemas import MemoryItem

        store.upsert(MemoryItem(kind=MemoryKind.TASK, key="old", text="x", ttl_seconds=0))
        store.upsert(MemoryItem(kind=MemoryKind.TASK, key="keep", text="y"))
        assert store.purge_expired(MemoryKind.TASK) == 1
        assert store.get(MemoryKind.TASK, "keep") is not None
