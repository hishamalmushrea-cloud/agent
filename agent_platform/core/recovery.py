"""Recovery engine — the agent's ability to fail, analyse, retry, and replan.

Recovery is bounded (a retry budget) so the agent never spins in a loop.  It
applies escalating strategies:
  1. retry the same tool with the same args,
  2. retry with adjusted arguments (e.g. escape / normalize path),
  3. switch to an alternative tool or shell fallback,
  4. give up (bounded) and report FAILED honestly.

Command here might be "fix the error", but we never fabricate a fix — we only
apply a small set of *mechanical* corrections and otherwise record the failure
for a later LLM-driven repair pass (a separate, pluggable component).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RecoveryOutcome:
    strategy: str
    tool: str
    arguments: dict[str, Any]
    note: str
    retry_count: int
    succeeded: bool = False


class RecoveryEngine:
    def __init__(self, max_retries: int = 4) -> None:
        self.max_retries = max_retries

    def build_retry(self, tool: str, arguments: dict[str, Any], error: str,
                    attempt: int) -> Optional[RecoveryOutcome]:
        """Return the next attempt to try, or None if we should give up."""
        if attempt >= self.max_retries:
            return None

        # Strategy 1: retry as-is (transient failures, e.g. timeout / race).
        if attempt == 0:
            return RecoveryOutcome(
                strategy="retry_same", tool=tool, arguments=dict(arguments),
                note=f"Retry attempt {attempt + 1}: {error}", retry_count=attempt + 1)

        # Strategy 2: recover from a common path expansion mistake.
        if tool == "shell" and attempt == 1:
            cmd = arguments.get("command", "")
            if cmd and "~" in cmd:
                import os

                fixed = os.path.expanduser(cmd)
                new_args = dict(arguments)
                new_args["command"] = fixed
                return RecoveryOutcome(strategy="expand_path", tool=tool, arguments=new_args,
                                       note="Retry with expanded path", retry_count=attempt + 1)

        # Strategy 3: for file tool failures due to missing parent dir, create it first.
        if tool in ("write_file", "move_file", "copy_file") and attempt == 2:
            import os

            target = arguments.get("path") or arguments.get("destination") or ""
            if target:
                parent = os.path.dirname(os.path.abspath(os.path.expanduser(target)))
                return RecoveryOutcome(strategy="ensure_parent_dir", tool="create_directory",
                                       arguments={"path": parent},
                                       note=f"Ensure parent dir exists before retrying {tool}",
                                       retry_count=attempt + 1)
        return None
