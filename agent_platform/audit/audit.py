"""Audit Log — structured, secret-redacting record of agent actions.

Every action is logged with time/action/target/result/permission/error/duration.
Secrets (passwords, API keys, tokens, cookies) are **redacted** before writing so
they never hit the log.  The log is durable (JSONL) and queryable for the GUI's
"السجلّ" tab and Diagnostics.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from agent_platform.config import Settings

_SECRET_PATTERNS = [
    # 1. Authorization headers with a scheme + token (Bearer / Basic / ...).
    (re.compile(r"""(?i)\b(authorization)\s*[:=]\s*(?:basic|bearer|token)\s*"""
                r"""['"]?[-\w=+/.]{4,}['"]?\b"""),
     r"\1=[REDACTED]"),
    # 2. Standalone Bearer tokens.
    (re.compile(r"\bBearer [A-Za-z0-9\-\\._~\+\\/]{12,}"), "Bearer [REDACTED]"),
    # 3. Known opaque token formats.
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "sk-[REDACTED]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), "ghp_[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA[REDACTED]"),
    # 4. Quoted secret values: key="value" or key='value'.
    (re.compile(r"""(?i)\b(api[_-]?key|password|passwd|secret|token|access[_-]?token|"""
                r"""refresh[_-]?token|cookie|session[_-]?id)\s*[:=]\s*"""
                r"""['"][^'"]+['"]"""),
     r"\1=[REDACTED]"),
    # 5. Bare secret values: key=value / key: value.  The value must be a
    #    single complete token (followed by a boundary, never a partial word),
    #    and it must not be a scheme word (Bearer/Basic) already handled above.
    (re.compile(r"""(?i)\b(api[_-]?key|password|passwd|secret|token|access[_-]?token|"""
                r"""refresh[_-]?token|cookie)\s*[:=]\s*"""
                r"""(?!(?:bearer|basic)\b)['"]?[-\w.~@/+=]{4,}['"]?"""
                r"""(?=$|[\s,;)\]!?.])"""),
     r"\1=[REDACTED]"),
]


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


class AuditLogger:
    def __init__(self, settings: Settings | None = None, path: Path | None = None) -> None:
        base = path or (settings.storage_path if settings else Settings().storage_path)
        self._file = base / "audit.jsonl"
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []

    def record(self, action: str, target: str = "", result: str = "INFO",
               error: str | None = None, duration_ms: int | None = None,
               permission: str = "", **extra: Any) -> dict[str, Any]:
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "action": redact(action),
            "target": redact(target or ""),
            "result": result,
            "permission": redact(permission or ""),
            "error": redact(error or ""),
            "duration_ms": duration_ms,
        }
        entry.update({k: redact(str(v)) for k, v in extra.items()})
        with self._lock:
            self._entries.append(entry)
            try:
                with open(self._file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:  # noqa: BLE001
                pass
        return entry

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._entries[-limit:]

    def stats(self) -> dict[str, int]:
        d: dict[str, int] = {}
        for e in self._entries:
            d[e["result"]] = d.get(e["result"], 0) + 1
        return d

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            try:
                self._file.write_text("", encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
