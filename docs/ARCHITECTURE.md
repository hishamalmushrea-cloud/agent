# Architecture — General Purpose Windows Computer Agent

Arena Agent Mode drives a **Local Agent** (the hands) on your machine.  The
architecture is layered so each concern is a testable, replaceable component.

```
       ┌────────────────────────────────────────────────────────────┐
       │                         ARENA  =  BRAIN                      │
       │   natural-language goal → reasoning → plan → re-plan          │
       │   (no public conversation-sync API; see CAPABILITY_MATRIX)    │
       └──────────────┬─────────────────────────────────────────────┘
                      │  browser window (desktop_app.py) / your chat
                      ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                   LOCAL AGENT  =  HANDS  (this repo)              │
   │                                                                    │
   │  GUI (chat + Live Activity + Desktop + Timeline + Status + Modes)  │
   │          │                                                         │
   │          ▼                                                         │
   │  /api/*  ── SecurityMiddleware (localhost/token/origin)            │
   │    │                                                               │
   │    ├── /api/mcp            ── MCP bridge (stdio / streamable-http) │
   │    ├── /api/actions        ── Unified Action Protocol (REST)       │
   │    ├── /api/tasks/{id}/events ── SSE (WebSocket-like nervous sys.) │
   │    └── /api/chat, /api/tasks, /api/settings, /api/audit, …         │
   │                                                                    │
   │  ┌──────────────────────────────────────────────────────────────┐ │
   │  │ Agent Loop: UNDERSTAND → PLAN → EXECUTE → OBSERVE → VERIFY    │ │
   │  │                      → RECOVER → REPLAN → COMPLETE            │ │
   │  │   Planner · Executor · Observer · Verifier · RecoveryEngine    │ │
   │  └──────────────────────────────────────────────────────────────┘ │
   │                                                                    │
   │  ┌──────────────────────────────────────────────────────────────┐ │
   │  │ Tool Registry (the hands): file · process · shell · system    │ │
   │  │   · windows · vision (screenshot/OCR) · web/browser           │ │
   │  └──────────────────────────────────────────────────────────────┘ │
   │                                                                    │
   │  Cross-cutting: PermissionMatrix · AuditLogger · MemoryManager     │
   │                 AgentRuntime (stop/reset) · Emergency Stop         │
   └──────────────────────────────────────────────────────────────────┘
```

## Layers

| Layer | Pieces | Responsibility |
| --- | --- | --- |
| **Brain (Arena)** | `desktop_app.py` (+ user session) | Reasoning, planning, natural-language goal |
| **Bridge / nervous system** | `mcp_server/`, `/api/actions`, `/api/tasks/{id}/events` | Translate brain intent ↔ tool calls; stream activity |
| **Local Agent / hands** | `core/agent.py`, `tools/`, `vision/` | Execute, observe, verify, recover |
| **Security & policy** | `permission/`, `audit/`, `server/app.py` SecurityMiddleware | Least privilege, confirmation, redaction, origin/token guard |
| **Experience** | `ui/`, gift-wrapped by `desktop_app.py` | Professional GUI + first-run wizard |

## Unified Action Protocol

`actions/protocol.py` defines `ActionKind` (CLICK, TYPE_TEXT, OPEN_URL,
READ_FILE, RUN_COMMAND, SCREENSHOT, WAIT, …) and `ProtocolAction` /
`ProtocolResult`.  `actions/executor.py` maps each kind to a tool, enforces the
permission matrix + human confirmation, and records to the audit log.  This is
the single choke point for the GUI, browser extension, MCP bridge, and REST
bridge.

## Agent Loop

For each step the agent: picks a tool → executes → observes → *verifies* with a
concrete check (exists / exit-code / output) → on failure asks the
**RecoveryEngine** for a bounded retry (same → expand path → ensure parent dir
→ give up), then replans.  It never claims success without verification
(`UNVERIFIED` is reported honestly).  A human can intercept
SENSITIVE/DANGEROUS tools (Allow Once / Always / Deny) and can trigger an
**Emergency Stop** at any time.

## Extensibility

Components are wired by a composition root (`server/components.py`) using
interfaces (registry, provider, bus).  Adding a tool = register it; adding an
action = add an enum member + executor mapper; swapping the brain = set the
endpoint.  The design is portable to Android/Linux/remote/NAS; the Windows MVP
is prioritized but nothing is Windows-only at the core (Windows-specific tools
are import-guarded).
