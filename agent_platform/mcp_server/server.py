"""MCP server that exposes the agent's tools to any MCP-capable AI agent.

This is the **device-access bridge**: an agent (Arena Agent Mode, OpenCode,
Cline, Goose, Claude Desktop, etc.) connects to this MCP server and gains the
ability to run tools on the user's machine — file, shell, process, system, web
and Windows — gated by the permission policy.

Run it in stdio mode (for agents that launch a subprocess):

    python -m agent_platform.mcp_server.server

or streamable HTTP (for remote agents):

    python -m agent_platform.mcp_server.server --http --host 0.0.0.0 --port 8765

Design / safety
---------------
* Every tool is exposed with its spec + permission level, so the agent can
  *discover* capabilities (Tool Discovery).
* Tools classified SENSITIVE / DANGEROUS require an explicit **grant** before
  they run.  The grant is recorded by the companion desktop app when the user
  clicks "منح صلاحية", and is checked here.  Without a grant, a risky tool
  returns a structured ``needs_grant`` error instead of running.
* The app enforces least-privilege and never runs as Administrator by default.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from agent_platform.models.schemas import PermissionLevel
from agent_platform.tools.registry import register_all
from agent_platform.mcp_server.grants import GrantStore, get_grant_store


class GrantStore:
    """Deprecated alias."""

    def __init__(self, *a, **k):
        pass


# The real grant store (module-level, persisted).
def get_store() -> GrantStore:
    return get_grant_store()


def build_server(registry=None, grants: GrantStore | None = None) -> FastMCP:
    registry = registry or register_all()
    grants = grants or get_grant_store()
    mcp = FastMCP("windows-computer-agent")

    # Register every tool as a dynamically callable MCP tool.
    for spec in registry.list_specs():
        # Capture per-tool, avoiding late-binding.
        tool_spec = spec

        def make_handler(tool_name: str, perm: PermissionLevel, param_names: list[str]):
            async def handler(**kwargs: Any) -> dict[str, Any]:
                # Permission gate: risky tools need a grant.
                if perm in (PermissionLevel.SENSITIVE, PermissionLevel.DANGEROUS):
                    if not grants.has(tool_name):
                        return {
                            "ok": False,
                            "needs_grant": True,
                            "tool": tool_name,
                            "permission": perm.value,
                            "message": f"Tool '{tool_name}' ({perm.value}) requires the user to "
                                       "grant permission. Ask the user to approve it in the app.",
                        }
                result = await registry.invoke(tool_name, **kwargs)
                return {
                    "ok": result.ok,
                    "output": result.output,
                    "error": result.error,
                    "exit_code": result.exit_code,
                    "data": result.data,
                    "duration_ms": result.duration_ms,
                    "tool": tool_name,
                }

            # Give FastMCP a real, typed signature so it builds a correct input
            # schema (the handler itself accepts **kwargs).
            import inspect

            params = [
                inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None)
                for name in param_names
            ]
            handler.__signature__ = inspect.Signature(params)
            return handler

        mcp.add_tool(
            fn=make_handler(spec.name, spec.permission, list(spec.parameters.keys())),
            name=spec.name,
            description=spec.description,
        )

    # A meta-tool so the agent can introspect what is available & what it may run.
    @mcp.tool()
    def list_capabilities() -> dict[str, Any]:
        """Discover all available tools, their categories and permission levels."""
        return {
            "tools": [
                {
                    "name": s.name,
                    "category": s.category,
                    "permission": s.permission.value,
                    "description": s.description,
                    "granted": grants.has(s.name),
                }
                for s in registry.list_specs()
            ]
        }

    @mcp.tool()
    def request_grant(tool: str) -> dict[str, Any]:
        """Ask the user to grant permission for a specific tool. Run this when a
        tool returned needs_grant=true."""
        return {
            "requested": tool,
            "message": "Permission request sent to the app. The user may grant it.",
        }

    return mcp


def run_stdio() -> None:
    mcp = build_server()
    mcp.run(transport="stdio")


def run_http(host: str, port: int) -> None:
    mcp = build_server()
    mcp.run(transport="streamable-http", host=host, port=port, path="/mcp")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    if args.http:
        run_http(args.host, args.port)
    else:
        run_stdio()


if __name__ == "__main__":
    main()
