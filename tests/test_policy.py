"""Permission / human-approval policy tests (least privilege)."""

from __future__ import annotations

from agent_platform.permission.policy import ApprovalDecision, PermissionPolicy
from agent_platform.models.schemas import PermissionLevel, ToolSpec


def _spec(perm):
    return ToolSpec(name="x", description="x", permission=perm)


def test_safe_is_allowed():
    policy = PermissionPolicy("safe")
    assert policy.check(_spec(PermissionLevel.SAFE)) == ApprovalDecision.ALLOW


def test_sensitive_asks_in_safe_mode():
    policy = PermissionPolicy("safe")
    assert policy.check(_spec(PermissionLevel.SENSITIVE)) == ApprovalDecision.ASK


def test_dangerous_asks_in_safe_mode():
    policy = PermissionPolicy("safe")
    assert policy.check(_spec(PermissionLevel.DANGEROUS)) == ApprovalDecision.ASK


def test_auto_approves_all():
    policy = PermissionPolicy("auto")
    assert policy.check(_spec(PermissionLevel.DANGEROUS)) == ApprovalDecision.ALLOW


def test_strict_asks_everything():
    policy = PermissionPolicy("strict")
    assert policy.check(_spec(PermissionLevel.SAFE)) == ApprovalDecision.ASK


def test_banned_denies_dangerous():
    policy = PermissionPolicy("banned")
    assert policy.check(_spec(PermissionLevel.DANGEROUS)) == ApprovalDecision.DENY


def test_dangerous_command_hard_blocked_in_safe():
    policy = PermissionPolicy("safe")
    shell = ToolSpec(name="shell", description="s", permission=PermissionLevel.DANGEROUS)
    assert policy.check(shell, {"command": "format C:"}) == ApprovalDecision.DENY
    # plain echo is ask (dangerous tool but not hard-banned)
    assert policy.check(shell, {"command": "echo hi"}) == ApprovalDecision.ASK
