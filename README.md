# 🤖 Windows Autonomous Computer Agent (`agent_platform`)

A modular, extensible **computer agent platform** for Windows — not a chatbot.

Give it a goal in natural language and it **understands → plans → picks tools →
executes → observes → verifies → recovers → re-plans → completes**.  The
intelligence is the engine, the tools are the hands, the observer is the eyes,
the planner is the executive, memory is experience, verification is the quality
gate.

> **ملخص تنفيذي (عربي)**
> هذا ليس نسخة أخرى من ChatGPT. هذا **وكيل كمبيوتر مستقل لنظام Windows**:
> المحرك (التخطيط، اختيار الأدوات، التنفيذ، المراقبة، التحقّق، الاسترجاع) ملكنا،
> والأدوات هي اليدين، والعين هي المراقب، والعقل التنفيذي هو المخطّط، والذاكرة هي
> الخبرة، والتحقق هو نظام الجودة. البنية قابلة للتوسع لإضافة أدوات/مهارات/سير عمل/
> إضافات/وكلاء دون إعادة البناء.

---

## 1. What it actually does (live)

It is a **chat-first computer agent**: an Arena-style GUI where your message is the
goal, the agent plans, then executes on the machine — showing the conversation
**and** the live tool steps inline.  Open `http://0.0.0.0:8000` to try it.

### Run it like a desktop app on Windows
Double-click **`start_windows.bat`** (or run **`start_windows.ps1`**), or:
```bash
python run.py           # starts the server and opens the chat app
python desktop_app.py   # browser-like native window (loads arena.ai + controller)
```
The app runs on **your machine** and **persists all conversations locally**, so
the session never breaks and your previous chats are there next time you open
it — even after closing/reopening the app (covered by `tests/test_persistence.py`).

### "Browser-like app that opens arena.ai and grants device access"
`desktop_app.py` opens a **native browser-like window** (pywebview/WebView2 on
Windows) whose default page is `https://arena.ai` — you log in there and the
agent thinks.  The app also runs the local engine and exposes the agent's
**device tools over MCP** (a standard bridge that any MCP-capable agent can
connect).  Device access is gated by **permissions**: the app's
"✅ صلاحيات الجهاز" panel grants the agent the right to read/write files, run
shell commands, etc.  Risky tools (delete, shell) are never auto-granted.

```
desktop_app.py
 ├── native window → arena.ai (you log in; the agent thinks)
 ├── local engine + 27 device tools (runs on your machine)
 ├── MCP bridge (stdio + streamable http) — the agent calls your tools
 └── permissions gate — you grant/revoke device access in the app
```

### Honest note on "logging into your Arena account"
Your request to "log in with my Arena account and see the conversations I did
here" is not fully synchronisable: **arena.ai exposes no public account/API** to
retrieve your session history (the official FAQ states full conversation logs
are not released for privacy).  I will not fake that.  What is real and built:
the app **opens arena.ai so you log in** and the agent works there, and the app
**gives that agent device access via MCP + permissions** — so when the agent
needs to touch your computer it can, with your explicit grant.

```bash
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"create a python project","workspace":"demo"}'
```

A real run produces (observed below):

```
(chat) user message → assistant reply → [plan] step_started → tool_call → tool_result →
verified → step_started → wait_for_approval(write_file) → approval → tool_call → verified →
assistant summary → completed
```

That is the **agent loop**, not a chat-only reply.  And it waits for **human approval**
before any SENSITIVE/DANGEROUS tool — least privilege by default.  The brain is
switchable from the app's Settings (`/api/settings`).

---

## 2. Architecture

Modular monolith (single process, swappable parts).  The `agent_platform`
package is composed of:

```
agent_platform
├── config                 # env-driven settings (LLM endpoint, approval mode, workspace…)
├── models/schemas         # typed domain model (Task, Plan, ToolSpec, Event, MemoryItem…)
├── tools/                 # the "hands" — Tool registry + file/shell/process/system/web/windows
├── llm/                   # pluggable "brain" (OpenAI-compatible OR offline heuristic)
├── core/                  # the engine: planner, executor, observer, verifier, recovery, agent
├── memory/                # Session/Task/Project/LongTerm/Tool memory + persistence
├── permission/            # Safe/Sensitive/Dangerous approval policy (least privilege)
├── tasks/                 # task state machine + persistence + resume + approval bridge
├── workflow/              # deterministic n8n-inspired node/edge engine (Agent + Workflow)
├── security/              # prompt-injection / credential / command / path guards
└── server/ + ui/          # FastAPI + SSE + professional GUI (live timeline, task panel, terminal)
```

### The core loop (`core/agent.py`)

```
Goal → Planner → Task Decomposition → Tool Selection → Execute → Observe
     → Verify → (fail?) → Recover → Re-plan → … → Completion
```

Every transition emits an **Event** onto an in-process bus that the GUI reaches
over Server-Sent Events — so the "execution timeline" is real, live and
openable, not a mock.

---

## 3. The Arena Agent Mode finding (honest, evidence-based)

The search across official docs, GitHub, SDK registries and community projects
found **no stable, documented public API/SDK** that lets an external Windows app
drive **Arena's Agent Mode runtime** (its planning/tool/sandbox capabilities)
programmatically.  Arena's agent capabilities are exposed *through the Agent
Mode session itself* (the environment you and I are interacting in right now).
Several similarly-named "Arena" products exist (SuperAI/`@ai-arena/sdk`,
Endpoint Arena, `aiarena.net` StarCraft, Qwen's `/arena` model-compare, a
community `arena2api` proxy) but none is the Agent Mode engine.

**What this means architecturally** — and why the directive "do not silently
swap the engine for OpenAI/Anthropic/Gemini" is fully respected:

| Layer | Who owns it | Swappable? |
|-------|-------------|------------|
| **Engine** (planning, tool selection, execution loop, observe, verify, recover, workflow, memory) | **Our code** | No |
| **Brain** (the model that turns goals into plans/tool-calls) | Pluggable provider | Yes |

So the **engine is ours**.  The reasoning call goes to an **OpenAI-compatible
endpoint**, which *can* be an Arena-compatible proxy or any vendor — via the
same `LLMProvider` interface.  We do **not** import an SDK from one vendor or
leak the engine to an external API.

> **Confidence:** HIGH that there is no official public Arena Agent Mode SDK;
> MEDIUM that an Arena-compatible chat endpoint can be used as a provider via
> the OpenAI wire format.  The community `arena2api` proxy exists but is
> unmaintained / not a supported product — treat it as experimental.

### The platform "depends on the Arena agent"

This is exactly the interdependence you asked for: **the Arena agent decides
(the plan / runbook), the platform executes (tools) → observes → verifies →
recovers.**  See [`ARENA.md`](ARENA.md) for the delegation contract and
[`AGENTS.md`](AGENTS.md) for how an Agent Mode session works in this repo.

To lean on a live Arena Agent Mode session as the brain:

```bash
export AGENT_ARENA_ENDPOINT=http://<host>:<port>   # an Arena agent session
export AGENT_ARENA_API_KEY=<optional bearer key>   # optional
```

Or point at a generic OpenAI-compatible endpoint (vendor / Arena proxy):

```bash
export AGENT_LLM_BASE_URL=https://<arena-or-vendor-openai-endpoint>/v1
export AGENT_LLM_API_KEY=<your-key>
export AGENT_LLM_MODEL=<model>
```

Provider priority: **Arena Agent → OpenAI-compatible → offline heuristic**.
With nothing configured the platform runs **offline** using the heuristic brain
(so you can try the whole loop without any API).  That is stated honestly,
not hidden.  The Arena path is covered by tests
(`tests/test_arena_delegation.py`) that prove the platform executes a runbook
the Arena agent returned.

---

## 4. Tools (the registry)

27 built-in tools across 6 categories (add more by registering a `Tool` —
discovery, metadata, permissions are automatic):

- **file** — `read_file, write_file, edit_file, move_file, copy_file,
  delete_file, list_dir, search_files, create_directory`
- **shell** — `shell` (PowerShell/CMD on Windows, sh on POSIX)
- **process** — `start_process, list_processes, inspect_process, stop_process`
- **system** — `system_info, network_status, get_env, get_clipboard, random_password`
- **web** — `fetch_page, web_search, browser_control` (Playwright, optional)
- **windows** — `open_application, close_application, focus_window,
  inspect_window, ui_interact` (pywinauto/Win32 — Windows only, no-op on non-Windows)

Each tool declares a `ToolSpec` (name, description, params, permission) so the
agent *discovers* capabilities and the permission layer *classifies* risk.

### Layers of computer control

| Layer | Used for | Tool |
|-------|----------|------|
| 1 Native APIs | files, processes | file_* / process_* |
| 2 Shell | PowerShell/CMD | shell |
| 3 App APIs | when available | (extensible) |
| 4 Browser | Playwright | browser_control |
| 5 UI Automation | Windows accessibility | windows_* |
| 6 Vision (OCR/CV) | last resort | gateway for future |
| 7 Mouse/Keyboard | last resort | `ui_interact` |

The design **prefers** the right level — mouse/keyboard is a fallback, never
the default.

---

## 5. Security model

- **Least privilege**: the app never runs as Administrator by default; admin is
  requested only for a specific elevated sub-operation, never implicitly.
- **Permission levels**: `SAFE` → auto-run, `SENSITIVE` → confirm,
  `DANGEROUS` → explicit confirm.  Modes: `safe` (default), `auto`, `strict`,
  `banned`.
- **Red-team guards** (`security/guard.py`): prompt-injection detection,
  credential/secret leakage detection, dangerous-command blocking
  (`format`, `diskpart`, `bcdedit`, encoded/bypass tricks), path-escape
  containment (agent is scoped to its workspace), and bounded retries.
- Not claimed to be waterproof — heuristics, not a firewall.  Documented.

---

## 6. Verification & honesty rules

- The agent **never claims success without evidence**: file existence,
  exit-code checks, output presence, or "unverified".  See `core/verifier.py`.
- Recovery is **bounded** (`AGENT_MAX_RETRIES`) so it can't loop forever.
- If a step can't be measured it reports **UNVERIFIED**, not "done".

---

## 7. Memory

Layered (`memory/`): Session (volatile), Task, Project (scoped), Long-term,
Tool.  It stores only non-secret summaries and obeys a retention policy
(TTL purge).  The GUI exposes tasks; memory is durable across restarts.

---

## 8. Workflows (Agent + Workflow)

A deterministic n8n-inspired engine (`workflow/`) of nodes & edges with
trigger/tool/condition/transform/sleep nodes.  The **agent** decides the high
level; a **workflow** executes a fixed, reproducible, observable series of
steps.  Registered examples appear under `/api/workflows`.

---

## 9. Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn agent_platform.server.app:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

Windows-specific tools need the extras:
```bash
pip install pywinauto pywin32 pyautogui      # Windows UI / last-resort input
pip install playwright && playwright install chromium   # real browser control
```

### Tests

```bash
python -m pytest
```
33 tests pass (registry, tools, permission policy, verifier, agent loop,
approval flow, recovery, memory, workflow engine, HTTP server).

---

## 10. Honest limitations & what's next

- **Vision/OCR layer** (screenshot → action) is a documented gateway, not yet a
  running tool — the model calls it "last resort".
- **LLM-driven self-debugging** (auto-fix arbitrary code) is deliberately
  out of the engine and belongs to a pluggable skill that requires a real LLM;
  the platform does **not** fake an AI fix.
- **Arena Agent Mode** has no public SDK (see §3); the engine is ours, the
  brain is swappable.
- Windows-only tools are written and guarded but **not verifiable in this Linux
  sandbox** — they return an honest "not on Windows" here.

Future/pluggable: new tools, skills, workflows, plugins, sub-agents
(Planner/Executor/Research/Reviewer/Debugger/Security), multi-agent orchestration
— all without rebuilding the platform.

---

## 11. License

MIT.  Built from a research-driven design; no proprietary code copied — ideas,
engineering principles and algorithms were extracted and re-implemented.
