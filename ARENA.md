# ARENA.md — Arena Agent Mode integration (the "brain" contract)

This platform is designed to **depend on an Arena Agent Mode session as its
brain** — that is, on the same kind of agent you are using right now to build
this project.  The division of labour is explicit:

> **The Arena agent decides (plan / per-step action).**
> **The platform executes (tools) → observes → verifies → recovers.**

This keeps the *engine* owned by the repo (so the platform is safe, testable
and tool-verified) while letting it lean on the best available reasoning at
runtime.

## Enabling Arena as the brain

```bash
export AGENT_ARENA_ENDPOINT=http://<host>:<port>     # where an Arena agent session listens
export AGENT_ARENA_API_KEY=<optional bearer key>
# Optional: AGENT_ARENA_TOKEN=<optional X-Arena-Token header>
```

When `AGENT_ARENA_ENDPOINT` is set, `build_provider()` returns an
`ArenaAgentProvider` and the platform routes its reasoning there.  Without it,
the platform falls back to an OpenAI-compatible provider, then to the offline
heuristic brain.

## Delegation contract (v1)

These live under the Arena endpoint.  `tool_specs` items use
`{name, description, parameters}`.

### `POST {endpoint}/plan`

Request:
```json
{
  "goal": "create a python project",
  "tools": [ { "name": "write_file", "description": "...", "parameters": { "...": "..." } } ]
}
```
Response (a **runbook** the platform executes):
```json
{
  "strategy": "Scaffold a small python project and verify its files.",
  "steps": [
    { "index": 0, "title": "Create directory", "description": "...",
      "tool": "create_directory", "arguments": {"path": "app"},
      "verification": "directory exists" },
    { "index": 1, "title": "Write main.py", "description": "...",
      "tool": "write_file", "arguments": {"path": "app/main.py", "content": "...\n"},
      "verification": "file exists" }
  ]
}
```

### `POST {endpoint}/chat`

Request: `{ "messages": [{"role":"user","content":"..."}], "tools": [...] }`
Response: `{ "content": "free-text reasoning" }`

### `POST {endpoint}/action` (when a plan step has no tool picked)

Request: `{ "goal": "...", "step": {"title":"...","description":"..."}, "tools": [...] }`
Response: `{ "tool": "read_file", "arguments": {"path": "x"} }`

## Contract requirements

1. Steps reference **only** tool names present in the `tools` argument.
2. `arguments` are JSON-serialisable.
3. Max ~8 steps per plan (the platform caps at 12).
4. Return an empty `steps` list to have the platform fall back to its own plan.

## Feeding the result back

After the platform finishes a run, it records observations and, optionally,
writes memory.  A caller can read `/api/tasks/{id}` / `/api/tasks/{id}/history`
or `POST` a fresh goal anytime — the platform is stateless across goals except
for persisted task/memory state.
