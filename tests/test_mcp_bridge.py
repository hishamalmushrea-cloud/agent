"""Tests for the MCP device-access bridge and the grant (permission) store.

This is the "grant the agent device access" feature: risky tools require an
explicit user grant before the agent can call them via MCP.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from agent_platform.mcp_server.grants import GrantStore, get_grant_store
from agent_platform.mcp_server.server import build_server
from agent_platform.tools.registry import register_all


def _run(coro):
    return asyncio.run(coro)


def _grants(tmp) -> GrantStore:
    return GrantStore(Path(tmp) / "grants.json")


def test_grant_store_persists(tmp_path):
    g1 = GrantStore(tmp_path / "g.json")
    g1.grant("write_file")
    g1.grant("shell")
    assert g1.has("write_file") and g1.has("shell")
    g2 = GrantStore(tmp_path / "g.json")  # "restart"
    assert g2.has("write_file") and g2.has("shell")
    g2.revoke("write_file")
    assert not GrantStore(tmp_path / "g.json").has("write_file")


def test_auto_approve_revokes_need_for_grant(tmp_path):
    g = GrantStore(tmp_path / "g.json")
    assert not g.has("delete_file")
    g.set_auto(True)
    assert g.has("delete_file")
    g.set_auto(False)
    assert not g.has("delete_file")


def test_mcp_server_exposes_tools():
    reg = register_all()
    mcp = build_server(reg)
    tools = _run(mcp.list_tools())
    names = [t.name for t in tools]
    assert "read_file" in names and "write_file" in names and "shell" in names
    # The capabilities meta-tool is also present.
    assert "list_capabilities" in names


def test_safe_tool_runs_without_grant(tmp_path):
    reg = register_all()
    mcp = build_server(reg, grants=_grants(tmp_path))
    # read_file is SAFE -> runs without a grant (on a bad path it errors, not denies).
    res = _run(mcp.call_tool("read_file", {"path": "/nonexistent/zz.txt"}))
    assert res is not None


def test_risky_tool_requires_grant(tmp_path):
    reg = register_all()
    g = _grants(tmp_path)
    mcp = build_server(reg, grants=g)
    # delete_file is DANGEROUS and not granted.
    res = _run(mcp.call_tool("delete_file", {"path": "x"}))
    # It must NOT run; it returns a needs_grant structure.
    text = str(res)
    assert "needs_grant" in text

    # After granting, it is allowed to be attempted (will fail on missing path,
    # but not because of permission).
    g.grant("delete_file")
    res2 = _run(mcp.call_tool("delete_file", {"path": "/nonexistent/zz.txt"}))
    assert "needs_grant" not in str(res2)
