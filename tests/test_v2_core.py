"""Tests for the V2 Master Engineering Specification core modules.

Covers:
  * Permission matrix (4-tier risk, denylist, confirmation/grant semantics)
  * Audit log (secret redaction, stats, recent)
  * Unified action protocol + executor (permission/confirmation gating)
  * AgentRuntime facade (describe, stop, reset)
  * Verification engine (step + goal)
  * Recovery engine (escalating strategies)
  * Config security settings
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from agent_platform.actions.executor import ActionExecutor
from agent_platform.actions.protocol import ActionKind, ProtocolAction, all_action_kinds
from agent_platform.agent_runtime import AgentRuntime
from agent_platform.audit.audit import AuditLogger, redact
from agent_platform.config import Settings
from agent_platform.core.recovery import RecoveryEngine
from agent_platform.core.verifier import Verdict, Verifier
from agent_platform.models.schemas import Observation, PlanStep, Task, ToolResult
from agent_platform.permission.matrix import PermissionMatrix, RiskLevel
from agent_platform.tools.registry import ToolRegistry, register_all


# ---------------------------------------------------------------------------
# Permission matrix
# ---------------------------------------------------------------------------
def test_permission_risk_tiers():
    pm = PermissionMatrix("safe")
    assert pm._tool_risk("read_file") == RiskLevel.SAFE
    assert pm._tool_risk("write_file") == RiskLevel.NORMAL
    assert pm._tool_risk("shell") == RiskLevel.PRIVILEGED
    assert pm._tool_risk("delete_file") == RiskLevel.DANGEROUS
    assert pm._tool_risk("unknown_tool") == RiskLevel.NORMAL  # default


def test_permission_safe_auto_allow():
    pm = PermissionMatrix("safe")
    decision, risk = pm.evaluate("read_file", {"path": "/tmp/x"})
    assert decision == "allow"
    assert risk == RiskLevel.SAFE


def test_permission_normal_auto_allow():
    pm = PermissionMatrix("safe")
    decision, _ = pm.evaluate("write_file", {"path": "/tmp/x", "content": "y"})
    assert decision == "allow"


def test_permission_privileged_needs_grant_in_safe_mode():
    pm = PermissionMatrix("safe")
    decision, risk = pm.evaluate("shell", {"command": "echo hi"})
    assert risk == RiskLevel.PRIVILEGED
    assert decision in ("grant", "confirm")


def test_permission_privileged_confirms_in_strict():
    pm = PermissionMatrix("strict")
    decision, _ = pm.evaluate("shell", {"command": "echo hi"})
    assert decision == "confirm"


def test_permission_auto_allows_privileged():
    pm = PermissionMatrix("auto")
    decision, _ = pm.evaluate("shell", {"command": "echo hi"})
    assert decision == "allow"


def test_permission_banned_denies_privileged():
    pm = PermissionMatrix("banned")
    decision, _ = pm.evaluate("shell", {"command": "echo hi"})
    assert decision == "deny"


def test_permission_hard_denylist_even_in_auto():
    pm = PermissionMatrix("auto")
    decision, _ = pm.evaluate("shell", {"command": "format c:"})
    assert decision == "deny"


def test_permission_dangerous_fragment_needs_confirm():
    pm = PermissionMatrix("safe")
    decision, _ = pm.evaluate("shell", {"command": "rm -rf /tmp/thing"})
    assert decision in ("confirm", "grant")


def test_permission_grant_and_confirm_flows():
    pm = PermissionMatrix("safe")
    pm.grant("shell")
    assert pm.has_grant("shell")
    pm.confirm_always("delete_file")
    decision, _ = pm.evaluate("delete_file", {"path": "/tmp/x"})
    assert decision == "allow"
    pm.confirm_deny("shell")
    decision, _ = pm.evaluate("shell", {"command": "echo x"})
    assert decision == "deny"


# ---------------------------------------------------------------------------
# Audit log redaction
# ---------------------------------------------------------------------------
def test_redact_api_key():
    assert "sk-[REDACTED]" in redact("key is sk-abcdefghijklmnopqrstuvwxyz123456")
    assert "[REDACTED]" in redact("api_key=supersecretvalue")
    assert "supersecret" not in redact("api_key=supersecretvalue")
    assert "[REDACTED]" in redact("password=superSecret123")


def test_redact_bearer_token():
    out = redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789")
    assert "[REDACTED]" in out
    assert "abcde" not in out
    # Standalone bearer still keeps the label readable.
    assert "Bearer [REDACTED]" in redact("use Bearer abcdefghijklmnopqrstuvwxyz0123456789")


def test_audit_records_and_stats(tmp_path):
    log = AuditLogger(path=tmp_path)
    log.record(action="read_file", target="/tmp/x", result="SUCCESS")
    log.record(action="shell", target="", result="FAILED", error="api_key=supersecretvalue")
    assert log.stats().get("SUCCESS") == 1
    assert log.stats().get("FAILED") == 1
    recent = log.recent()
    assert recent[0]["action"] == "read_file"
    assert "supersecret" not in str(recent[1])
    # File is durable.
    assert (tmp_path / "audit.jsonl").exists()


def test_audit_clear(tmp_path):
    log = AuditLogger(path=tmp_path)
    log.record(action="x", result="INFO")
    log.clear()
    assert log.stats() == {}


# ---------------------------------------------------------------------------
# Action protocol + executor
# ---------------------------------------------------------------------------
def test_all_action_kinds_complete():
    kinds = {k["kind"] for k in all_action_kinds()}
    assert "run_command" in kinds
    assert "read_file" in kinds
    assert "screenshot" in kinds
    assert "open_url" in kinds
    # Cover all v2 families.
    for needed in ("click", "type_text", "open_application", "write_file",
                   "run_command", "screenshot", "wait", "press_key"):
        assert needed in kinds


def test_executor_read_file(tmp_path):
    p = tmp_path / "hello.txt"
    p.write_text("hello world", encoding="utf-8")
    reg = register_all()
    pm = PermissionMatrix("safe")
    ex = ActionExecutor(reg, pm, AuditLogger(path=tmp_path))
    result = asyncio.run(ex.execute(ProtocolAction(
        kind=ActionKind.READ_FILE, target=str(p))))
    assert result.ok
    assert "hello world" in result.output
    assert result.kind == ActionKind.READ_FILE


def test_executor_unknown_action(tmp_path):
    reg = register_all()
    ex = ActionExecutor(reg, PermissionMatrix("safe"), AuditLogger(path=tmp_path))
    result = asyncio.run(ex.execute(ProtocolAction(kind=ActionKind.STOP)))
    assert result.ok  # STOP is allowed control action


def test_executor_denied_command(tmp_path):
    reg = register_all()
    pm = PermissionMatrix("auto")
    ex = ActionExecutor(reg, pm, AuditLogger(path=tmp_path))
    result = asyncio.run(ex.execute(ProtocolAction(
        kind=ActionKind.RUN_COMMAND, target="format c:")))
    assert not result.ok
    assert "denied" in result.error.lower()


def test_executor_needs_grant_for_shell_in_safe_mode(tmp_path):
    reg = register_all()
    pm = PermissionMatrix("safe")
    ex = ActionExecutor(reg, pm, AuditLogger(path=tmp_path))
    result = asyncio.run(ex.execute(ProtocolAction(
        kind=ActionKind.RUN_COMMAND, target="echo hi", arguments={})))
    # Safe mode + privileged tool => not auto-run, either grant or confirm.
    assert not result.ok
    assert result.needs_grant or result.needs_confirmation


def test_executor_force_skips_confirm(tmp_path):
    reg = register_all()
    pm = PermissionMatrix("safe")
    pm.grant("shell")
    ex = ActionExecutor(reg, pm, AuditLogger(path=tmp_path))
    # With force=True (user pre-approved) it should run.
    result = asyncio.run(ex.execute(ProtocolAction(
        kind=ActionKind.RUN_COMMAND, target="echo hi", force=True)))
    # On this platform echo exists everywhere; assert it either ran or error is
    # a genuine runtime issue, not a permission gate.
    assert not (result.needs_grant or result.needs_confirmation)


# ---------------------------------------------------------------------------
# AgentRuntime facade
# ---------------------------------------------------------------------------
def _settings() -> Settings:
    s = Settings()
    s.storage_dir = tempfile.mkdtemp()
    return s


def test_runtime_describe_and_stop():
    reg = register_all()
    settings = _settings()
    rt = AgentRuntime(reg, settings, PermissionMatrix("safe"))
    d = rt.describe()
    assert "status" in d and "tools" in d and "permissions" in d
    assert d["stopped"] is False
    rt.stop()
    assert rt.should_stop() is True
    assert rt.status == "STOPPED"
    rt.reset()
    assert rt.should_stop() is False


def test_runtime_run_stopped_action():
    reg = register_all()
    settings = _settings()
    rt = AgentRuntime(reg, settings, PermissionMatrix("safe"))
    rt.stop()
    res = asyncio.run(rt.run_action(ProtocolAction(kind=ActionKind.READ_FILE, target="/nope")))
    assert not res.ok
    assert "stopped" in res.error.lower()


# ---------------------------------------------------------------------------
# Verification engine
# ---------------------------------------------------------------------------
def test_verifier_shell_pass():
    v = Verifier()
    step = PlanStep(id="s1", index=0, title="run", tool="shell", arguments={})
    obs = Observation(step_id="s1", tool="shell",
                      result=ToolResult(tool="shell", ok=True, output="ok", exit_code=0))
    verdict = v.verify_step(step, obs, {})
    assert verdict.verdict == Verdict.PASS


def test_verifier_shell_fail():
    v = Verifier()
    step = PlanStep(id="s1", index=0, title="run", tool="shell", arguments={})
    obs = Observation(step_id="s1", tool="shell",
                      result=ToolResult(tool="shell", ok=False, error="boom", exit_code=1))
    verdict = v.verify_step(step, obs, {})
    assert verdict.verdict == Verdict.FAIL


def test_verifier_goal_all_steps():
    v = Verifier()
    task = Task(goal="test")
    task.plan = type("P", (), {"steps": [
        PlanStep(id="a", index=0, title="a", tool="x", arguments={}, status="ok"),
        PlanStep(id="b", index=1, title="b", tool="y", arguments={}, status="ok"),
    ]})()
    verdict = v.verify_goal(task)
    assert verdict.verdict == Verdict.PASS


def test_verifier_goal_unverified():
    v = Verifier()
    task = Task(goal="test")
    task.plan = type("P", (), {"steps": [
        PlanStep(id="a", index=0, title="a", tool="x", arguments={}, status="ok"),
        PlanStep(id="b", index=1, title="b", tool="y", arguments={}, status="pending"),
    ]})()
    verdict = v.verify_goal(task)
    assert verdict.verdict == Verdict.UNVERIFIED


# ---------------------------------------------------------------------------
# Recovery engine
# ---------------------------------------------------------------------------
def test_recovery_retry_same():
    r = RecoveryEngine(max_retries=4)
    out = r.build_retry("shell", {"command": "x"}, "timeout", attempt=0)
    assert out is not None
    assert out.strategy == "retry_same"


def test_recovery_ensures_parent_dir():
    r = RecoveryEngine(max_retries=4)
    out = r.build_retry("write_file", {"path": "/tmp/a/b/out.txt"}, "no dir", attempt=2)
    assert out is not None
    assert out.strategy == "ensure_parent_dir"


def test_recovery_gives_up():
    r = RecoveryEngine(max_retries=4)
    out = r.build_retry("shell", {"command": "x"}, "err", attempt=4)
    assert out is None


# ---------------------------------------------------------------------------
# Heuristic plan / action selection (sum-1-100 flow)
# ---------------------------------------------------------------------------
def test_heuristic_sum_program_generation():
    from agent_platform.core.heuristics import _python_content_for

    content = _python_content_for("create a python project that prints the sum of 1 to 100")
    assert "sum(range(1, 101))" in content
    assert "Sum of 1 to 100" in content
    assert "5050" in content


def test_heuristic_plan_adds_run_step_for_run_goal():
    from agent_platform.core.heuristics import heuristic_plan

    specs = [{"name": n} for n in ("system_info", "create_directory", "write_file",
                                   "shell", "list_dir")]
    plan = heuristic_plan("create a python project and run it", specs)
    tools = [s["tool"] for s in plan["steps"]]
    assert "shell" in tools          # a run step exists
    assert "write_file" in tools


def test_heuristic_plan_without_run_goal_has_no_shell():
    from agent_platform.core.heuristics import heuristic_plan

    specs = [{"name": n} for n in ("system_info", "create_directory", "write_file", "list_dir")]
    plan = heuristic_plan("scaffold a python project", specs)
    tools = [s["tool"] for s in plan["steps"]]
    assert "shell" not in tools


# ---------------------------------------------------------------------------
# Config security settings
# ---------------------------------------------------------------------------
def test_config_security_defaults():
    s = Settings()
    assert s.bind_localhost_only is True
    assert "localhost" in s.allow_origins
    assert "127.0.0.1" in s.allow_origins
    assert s.host == "127.0.0.1"
