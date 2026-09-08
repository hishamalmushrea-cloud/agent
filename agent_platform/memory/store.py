"""Persistent memory store.

MemoryItems are stored per *kind* as JSON files inside the platform storage
directory.  Writes are append-friendly and thread-safe (a global lock).  This
keeps memory durable across restarts so long-running tasks can resume and the
agent can learn from prior runs.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

from agent_platform.models.schemas import MemoryItem, MemoryKind

_LOCK = threading.Lock()


class MemoryStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _file_for(self, kind: MemoryKind) -> Path:
        return self.base_dir / f"memory_{kind.value}.json"

    def _load(self, kind: MemoryKind) -> dict[str, dict[str, Any]]:
        f = self._file_for(kind)
        if not f.exists():
            return {}
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save(self, kind: MemoryKind, data: dict[str, dict[str, Any]]) -> None:
        f = self._file_for(kind)
        with _LOCK:
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- CRUD ------------------------------------------------------------
    def upsert(self, item: MemoryItem) -> None:
        data = self._load(item.kind)
        data[item.key] = item.model_dump()
        self._save(item.kind, data)

    def get(self, kind: MemoryKind, key: str) -> Optional[MemoryItem]:
        data = self._load(kind)
        raw = data.get(key)
        return MemoryItem.model_validate(raw) if raw else None

    def all(self, kind: MemoryKind) -> list[MemoryItem]:
        data = self._load(kind)
        return [MemoryItem.model_validate(v) for v in data.values() if v]

    def delete(self, kind: MemoryKind, key: str) -> bool:
        data = self._load(kind)
        if key in data:
            del data[key]
            self._save(kind, data)
            return True
        return False

    def purge_expired(self, kind: MemoryKind) -> int:
        now = time.time()
        data = self._load(kind)
        removed = 0
        for k in list(data.keys()):
            raw = data[k]
            ttl = raw.get("ttl_seconds")
            created = raw.get("created_at", "")
            try:
                import datetime

                created_ts = datetime.datetime.fromisoformat(created).timestamp()
            except Exception:  # noqa: BLE001
                created_ts = now
            if ttl is not None and (now - created_ts) > ttl:
                del data[k]
                removed += 1
        if removed:
            self._save(kind, data)
        return removed
