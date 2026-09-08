"""Planner — turns a user goal into a Plan (task decomposition).

Delegates to the provider's ``plan`` and normalises the structure into
:class:`Plan` / :class:`PlanStep`.  If the provider returns nothing usable we
fall back to a single "understand then act" step so the loop never stalls.
"""

from __future__ import annotations

from typing import Any

from agent_platform.models.schemas import Plan, PlanStep, ToolSpec

_MAX_STEPS = 12


class Planner:
    def __init__(self, provider: Any, max_steps: int = _MAX_STEPS) -> None:
        self.provider = provider
        self.max_steps = max_steps

    def plan(self, goal: str, tool_specs: list[ToolSpec]) -> Plan:
        specs = [ToolSpec.model_validate(s) if isinstance(s, dict) else s for s in tool_specs]
        tool_dicts = [
            {"name": s.name, "description": s.description, "parameters": s.parameters}
            for s in specs
        ]
        try:
            raw = self.provider.plan(goal, tool_dicts)
            steps = self._normalise_steps(raw.get("steps", []), tool_dicts)
            strategy = raw.get("strategy", "")
        except Exception:  # noqa: BLE001 - never let planning crash the engine
            steps = self._fallback_steps()
            strategy = "Fallback plan (planner failed)"
        if not steps:
            steps = self._fallback_steps()
            strategy = strategy or "Best-effort plan"

        return Plan(goal=goal, strategy=strategy, steps=steps, confidence=0.6)

    @staticmethod
    def _normalise_steps(raw_steps: list[Any], tool_dicts: list[dict[str, Any]]) -> list[PlanStep]:
        valid_tools = {t["name"] for t in tool_dicts}
        out: list[PlanStep] = []
        for i, raw in enumerate(raw_steps[: _MAX_STEPS]):
            if isinstance(raw, str):
                raw = {"title": raw}
            title = str(raw.get("title") or raw.get("description") or f"Step {i + 1}")
            tool = raw.get("tool")
            if tool and tool not in valid_tools:
                tool = None
            out.append(
                PlanStep(
                    index=i,
                    title=title,
                    description=str(raw.get("description", "")),
                    tool=tool,
                    arguments=dict(raw.get("arguments", {}) or {}),
                    verification=str(raw.get("verification", "")),
                )
            )
        return out

    @staticmethod
    def _fallback_steps() -> list[PlanStep]:
        return [
            PlanStep(index=0, title="Understand and inspect the environment",
                     tool="system_info", arguments={},
                     verification="system info available"),
            PlanStep(index=1, title="Attempt the requested action",
                     tool=None, arguments={},
                     verification="action completed"),
        ]
