# AGENTS.md — instructions for AI agents working in this repo

This file is read by AI coding/Agent Mode sessions (Arena Agent Mode, Claude
Code, OpenCode, Cline, etc.).  Follow it when contributing.

## What this project is

A **Windows Autonomous Computer Agent platform** (`agent_platform/`).  It is an
*agent engine*, not a chatbot.  The engine (planning, tool selection,
execution loop, observation, verification, recovery, memory, workflows) is OWN
code; the "brain" (an LLM or an Agent Mode session) is a *pluggable provider*.

## Core modules

- `agent_platform/core/agent.py` — the orchestrating loop.
- `agent_platform/core/planner.py` — task decomposition (delegates to provider).
- `agent_platform/tools/` — Tool registry + file/shell/process/system/web/windows.
- `agent_platform/llm/provider.py` — `OpenAIProvider`, `ArenaAgentProvider`,
  `HeuristicProvider`.
- `agent_platform/permission/policy.py` — Safe/Sensitive/Dangerous approvals.
- `agent_platform/tasks/manager.py` — task state machine + persistence.
- `agent_platform/server/app.py` + `ui/` — FastAPI + SSE + GUI.

## Conventions

- Tools return `ToolResult`; **never raise** from a tool.
- The agent **never claims success without verification**; use the Verifier.
- Recovery is bounded; no infinite loops.
- Keep the engine vendor-independent; providers are swappable via env vars.

## Driving the platform (REST)

```bash
# start
uvicorn agent_platform.server.app:app --host 0.0.0.0 --port 8000

# give a goal
curl -X POST http://localhost:8000/api/tasks -H 'Content-Type: application/json' \
  -d '{"goal":"create a python project","workspace":"demo"}'

# watch live events
curl -N http://localhost:8000/api/tasks/<id>/events

# approve a SENSITIVE/DANGEROUS step
curl -X POST http://localhost:8000/api/tasks/<id>/approve \
  -H 'Content-Type: application/json' -d '{"approved":true}'
```

## Testing

```bash
python -m pytest
```

Keep all features covered; add a test for any new tool/feature.
