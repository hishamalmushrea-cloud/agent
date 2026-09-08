"""Deterministic offline "brain" (heuristic planner + action selection).

This exists so the platform runs and is testable WITHOUT an LLM endpoint, and
so the *engine loop* (plan -> execute -> observe -> verify -> recover) is
exercisable end-to-end.  It recognises a handful of common Windows agent goals
and maps them to tool calls.  When a real provider is configured, the engine
uses the LLM instead.  It is intentionally narrow — it is NOT an LLM.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Intent detection helpers
# ---------------------------------------------------------------------------
def _has(goal: str, *keywords: str) -> bool:
    g = goal.lower()
    return any(kw in g for kw in keywords)


def _extract_path(goal: str, ctx: dict[str, Any]) -> str:
    """Pull an obvious filesystem path out of the goal, or default to cwd."""
    m = re.search(r"([A-Za-z]:[\\/][^\s\"']+|/[^\s\"']+|~\S+|\.\S+)", goal)
    if m:
        return m.group(1)
    return ctx.get("cwd", ".")


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------
def heuristic_plan(goal: str, tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
    names = {t["name"] for t in tool_specs}
    steps: list[dict[str, Any]] = []

    def add(title: str, tool: str | None, arguments: dict[str, Any] | None = None,
            verification: str = "", description: str = "") -> None:
        if tool and tool not in names:
            return  # skip tools not available
        steps.append({
            "title": title,
            "description": description or title,
            "tool": tool,
            "arguments": arguments or {},
            "verification": verification,
        })

    # --- coding / python project ----------------------------------------
    if _has(goal, "python", "project", "create", "scaffold", "init") and _has(goal, "project", "create", "scaffold"):
        add("Understand the goal (system info)", "system_info", {})
        add("Create project directory", "create_directory",
            {"path": "app"}, verification="directory exists")
        add("Write main.py placeholder", "write_file",
            {"path": "app/main.py", "content": 'def main():\n    print("hello from agent")\n\n\nif __name__ == "__main__":\n    main()\n'},
            verification="file exists")
        add("Optional: list the created project", "list_dir",
            {"path": "app", "recursive": True})
        return {"strategy": "Scaffold a small Python project and verify its files.", "steps": steps}

    # --- run / build / test ---------------------------------------------
    if _has(goal, "run", "execute", "test", "build", "pip", "install"):
        cmd = _infer_command(goal)
        add("Run the requested command", "shell", {"command": cmd, "cwd": _extract_path(goal, context(goal))},
            verification="exit code == 0")
        return {"strategy": "Run the requested shell command and capture its result.", "steps": steps}

    # --- web / browser ---------------------------------------------------
    if _has(goal, "chrome", "browser", "open", "search", "web", "internet", "download", "site"):
        add("Open browser / fetch page", "fetch_page", {"url": _infer_url(goal)},
            verification="page text retrieved")
        return {"strategy": "Interact with the web as requested.", "steps": steps}

    # --- organise PDFs ---------------------------------------------------
    if _has(goal, "pdf", "organize", "organise", "files", "folder", "rename", "sort"):
        base = _extract_path(goal, context(goal))
        add("Search for PDF files", "search_files",
            {"path": base, "pattern": "*.pdf", "max_results": 500},
            verification="list of pdfs found")
        add("List directories", "list_dir", {"path": base, "recursive": True})
        return {"strategy": "Find and organise the files as requested.", "steps": steps}

    # --- generic ---------------------------------------------------------
    add("Inspect environment", "system_info", {}, verification="system info")
    if _has(goal, "list", "show", "see", "ls", "dir"):
        add("List files in workspace", "list_dir",
            {"path": _extract_path(goal, context(goal)), "recursive": False})
    return {"strategy": "Generic best-effort: inspect the environment and act.",
            "steps": steps}


def heuristic_action_for_step(goal: str, step: dict[str, Any]) -> dict[str, Any]:
    tool = step.get("tool")
    args = dict(step.get("arguments") or {})
    if tool is None:
        return {"tool": None, "arguments": {}}
    # Fill any blank/inference-dependent argument from the goal.
    return {"tool": tool, "arguments": args}


# ---------------------------------------------------------------------------
# heuristics used inside tool_call (from conversation messages)
# ---------------------------------------------------------------------------
def heuristic_action(messages: list[dict[str, Any]]) -> dict[str, Any]:
    goal = ""
    for m in reversed(messages):
        if m.get("role") in ("user", "assistant"):
            goal = str(m.get("content", ""))
            break
    plan = heuristic_plan(goal, [])
    if plan["steps"]:
        step = plan["steps"][0]
        return {"tool": step["tool"], "arguments": step["arguments"]}
    return {"tool": None, "arguments": {}}


def context(goal: str) -> dict[str, Any]:
    return {"cwd": "."}


def _infer_command(goal: str) -> str:
    g = goal.lower()
    if "pip" in g and "install" in g:
        m = re.search(r"pip install ([a-zA-Z0-9_\-.]+)", goal)
        return f"pip install {m.group(1) if m else 'requests'}"
    if g.startswith("python ") or "python3 " in g:
        m = re.search(r"(python3?[^\n]+)", goal)
        return m.group(1)
    return "python3 --version"


def _infer_url(goal: str) -> str:
    m = re.search(r"https?://[^\s\"']+", goal)
    if m:
        return m.group(0)
    if _has(goal, "search", "google"):
        q = goal.split("search")[-1].strip().strip('"')
        return "https://html.duckduckgo.com/html/?q=" + __import__("urllib.parse", fromlist=["quote"]).quote(q)
    return "https://www.google.com"
