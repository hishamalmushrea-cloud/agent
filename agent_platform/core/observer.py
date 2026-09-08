"""Observer — turns a raw ToolResult into an Observation and a short summary.

The observer is the "eyes": it records what actually happened (not what the
agent assumed would happen).  Its summary is fed back into the plan/context so
the agent can react to reality.
"""

from __future__ import annotations

from typing import Any

from agent_platform.models.schemas import Observation, ToolResult


class Observer:
    def observe(self, step_id: str, tool: str, result: ToolResult) -> Observation:
        summary = self._summarise(tool, result)
        return Observation(step_id=step_id, tool=tool, result=result, summary=summary)

    @staticmethod
    def _summarise(tool: str, result: ToolResult) -> str:
        if not result.ok:
            return f"{tool} FAILED: {result.error or 'unknown error'}"
        output = (result.output or "").strip()
        if tool in ("shell", "start_process", "stop_process", "list_processes",
                    "inspect_process", "read_file", "fetch_page", "web_search",
                    "list_dir", "search_files", "system_info", "write_file",
                    "edit_file"):
            head = output[:300]
            if len(output) > 300:
                head += " …"
            return f"{tool} OK: {head}"
        return f"{tool} OK"

    def to_dict(self, obs: Observation) -> dict[str, Any]:
        return {
            "step_id": obs.step_id,
            "tool": obs.tool,
            "summary": obs.summary,
            "ok": obs.result.ok,
            "output": obs.result.output,
            "error": obs.result.error,
            "exit_code": obs.result.exit_code,
            "duration_ms": obs.result.duration_ms,
        }
