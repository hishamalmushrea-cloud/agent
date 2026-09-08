"""Verification Engine tests — the agent never claims success without evidence."""

from __future__ import annotations

import os
import tempfile

from agent_platform.core.verifier import Verdict, Verifier
from agent_platform.models.schemas import Observation, PlanStep, ToolResult


def _step(tool="write_file"):
    return PlanStep(index=0, title="write", tool=tool, arguments={}, verification="")


def test_file_write_verified_by_existence():
    v = Verifier()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.txt")
        # Simulate a successful write result.
        result = ToolResult(tool="write_file", ok=True, output="wrote")
        obs = Observation(step_id="s", tool="write_file", result=result)
        verdict = v.verify_step(_step(), obs, {"path": path})
        # File does not actually exist -> UNVERIFIED (honest).
        assert verdict.verdict == Verdict.UNVERIFIED
        # Now create it.
        open(path, "w").close()
        verdict = v.verify_step(_step(), obs, {"path": path})
        assert verdict.verdict == Verdict.PASS


def test_shell_exit_code():
    v = Verifier()
    ok = ToolResult(tool="shell", ok=True, output="ok", exit_code=0)
    bad = ToolResult(tool="shell", ok=False, output="", exit_code=2, error="boom")
    assert v.verify_step(_step("shell"), Observation(step_id="s", tool="shell", result=ok), {}) .verdict == Verdict.PASS
    assert v.verify_step(_step("shell"), Observation(step_id="s", tool="shell", result=bad), {}).verdict == Verdict.FAIL


def test_tool_failure_is_fail():
    v = Verifier()
    result = ToolResult(tool="read_file", ok=False, error="file not found")
    obs = Observation(step_id="s", tool="read_file", result=result)
    assert v.verify_step(_step("read_file"), obs, {}).verdict == Verdict.FAIL
