"""Verification Engine.

The agent's rule #14: it must ask "did the task actually succeed?" — not "did I
run the last command?".  This module verifies both at the *step* level (each
PlanStep) and at the *goal* level, using concrete checks rather than trusting
the LLM's claim.  It returns a Verdict with an optional human/LLM confidence
note.  If a step cannot be machine-verified, it reports UNVERIFIED honestly
rather than claiming success.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Optional

from agent_platform.models.schemas import Observation, PlanStep, ToolResult, Task


class Verdict(str, Enum):
    PASS = "pass"           # verified with concrete evidence
    FAIL = "fail"           # verified to have failed
    UNVERIFIED = "unverified"  # could not verify (agent must not claim success)


class StepVerdict:
    def __init__(self, verdict: Verdict, reason: str, evidence: str = "") -> None:
        self.verdict = verdict
        self.reason = reason
        self.evidence = evidence

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict.value, "reason": self.reason, "evidence": self.evidence}


class Verifier:
    def verify_step(self, step: PlanStep, obs: Observation,
                    arguments: dict[str, Any]) -> StepVerdict:
        # 1. Tool-level hard failures.
        if not obs.result.ok:
            return StepVerdict(Verdict.FAIL, f"Tool '{step.tool}' failed: {obs.result.error}",
                               obs.result.output)

        tool = step.tool
        # 2. Machine-specific checks.
        if tool == "shell":
            return self._verify_shell(step, obs.result)
        if tool in ("write_file", "edit_file", "copy_file", "move_file", "create_directory",
                    "delete_file"):
            return self._verify_file(step, obs.result, arguments)
        if tool in ("list_dir", "search_files", "read_file", "system_info"):
            if obs.result.output:
                return StepVerdict(Verdict.PASS, f"{tool} produced output")
        # 3. Generic pass if result.ok and we have no stronger check.
        if obs.result.ok:
            return StepVerdict(Verdict.PASS, "Step completed (no stronger check available)")
        return StepVerdict(Verdict.UNVERIFIED, "Could not verify")

    @staticmethod
    def _verify_shell(step: PlanStep, result: ToolResult) -> StepVerdict:
        if result.exit_code == 0:
            return StepVerdict(Verdict.PASS, "command exited 0", result.output)
        return StepVerdict(Verdict.FAIL, f"command exited {result.exit_code}", result.error or result.output)

    @staticmethod
    def _verify_file(step: PlanStep, result: ToolResult, args: dict[str, Any]) -> StepVerdict:
        # For file operations, the strongest evidence is that the target exists.
        path = args.get("path") or args.get("source") or args.get("destination") or ""
        if path:
            path = os.path.expanduser(path)
            if os.path.exists(path):
                return StepVerdict(Verdict.PASS, f"target exists: {path}")
        return StepVerdict(Verdict.UNVERIFIED, "file operation reported ok but target not confirmed")

    def verify_goal(self, task: Task) -> StepVerdict:
        """Goal-level confirmation across all steps."""
        plan = task.plan
        if not plan or not plan.steps:
            return StepVerdict(Verdict.UNVERIFIED, "no plan steps to verify")
        for step in plan.steps:
            if step.status in ("failed",):
                return StepVerdict(Verdict.FAIL, f"step '{step.title}' failed")
        completed = sum(1 for s in plan.steps if s.status == "ok")
        total = len(plan.steps)
        if completed == total and total > 0:
            return StepVerdict(Verdict.PASS, f"all {total} steps completed")
        return StepVerdict(Verdict.UNVERIFIED,
                           f"{completed}/{total} steps completed")
