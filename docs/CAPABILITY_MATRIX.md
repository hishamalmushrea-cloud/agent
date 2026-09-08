# Capability Matrix

Honest mapping of **every capability** to its support in **Arena (the brain)** and
**the Local Agent (the hands)**, plus the solution.  We do **not** claim Arena can
do things it cannot.  Arena has **no public API** for conversation sync — it is a
*brain* (reasoning), and the Local Agent supplies everything physical.

> Read this before trusting any feature.  Anything marked `LIMITATION` is not
> faked — a real reason and a real alternative are given.

| Capability | Arena support | Local Agent support | Solution |
| --- | --- | --- | --- |
| **Reasoning / planning** | ✅ Yes (native) | ⚠️ heuristic fallback | Arena (or OpenAI-compatible brain) does reasoning; local heuristic engine used when no endpoint is set |
| **Natural-language goal** | ✅ Yes | ✅ Yes | Chat GUI → `/api/chat` → guard → planner |
| **Long-term conversation memory** | ✅ Arena keeps it | ⚠️ Local keeps a persistent local store | Arena session is the source; Local Agent mirrors to `~/.agent_platform` for continuity |
| **Public API to sync conversation** | ❌ **No** (`LIMITATION`: arena.ai has no public account/API; they don't expose conversation logs) | ✅ Local store | `desktop_app.py` opens `https://arena.ai` in a browser window; the user logs in there and grants device access |
| **Filesystem** (read/write/edit/move/delete/search) | ❌ No | ✅ Yes | Local Agent tools (`read_file`, `write_file`, `edit_file`, …) exposed via `/api/actions` + MCP |
| **Terminal / shell** | ❌ No | ✅ Yes | `shell`, `run_powershell` via Local Agent |
| **Process management** | ❌ No | ✅ Yes | `list_processes`, `start_process`, `stop_process`, `inspect_process` |
| **Open/close apps** | ❌ No | ✅ Yes | `open_application`, `close_application` (Windows) |
| **Mouse/keyboard UI automation** | ❌ No | ✅ Yes (Windows, best-effort) | `click`, `type_text`, `press_key`, `hotkey`, `scroll` (UI-interaction layer) |
| **Vision / screenshot** | ❌ No | ✅ Yes (with honest fallback) | `screenshot`, `ocr`, `read_screen` |
| **Browser control** | ❌ No | ✅ Yes | `browser_agent` (Playwright: navigate/search/click/type/extract/screenshot/scroll) |
| **Network fetch/search** | ❌ No | ✅ Yes | `fetch_page`, `web_search`, `network_status` |
| **Task memory** | ❌ No | ✅ Yes | `MemoryManager` (session/task/project/long-term/tool layers) |
| **Verification** | ❌ No | ✅ Yes | `Verifier` (step + goal; PASS / FAIL / UNVERIFIED) |
| **Recovery / self-healing** | ❌ No | ✅ Yes | `RecoveryEngine` (retry → expand path → ensure parent → give up) |
| **Permission matrix** | ❌ No | ✅ Yes | `PermissionMatrix` (SAFE/NORMAL/PRIVILEGED/DANGEROUS; allow/grant/confirm/deny) |
| **Human confirmation** | ❌ No | ✅ Yes | Allow Once / Always / Deny + Emergency Stop |
| **Audit logging** | ❌ No | ✅ Yes | `AuditLogger` (JSONL, secret-redacting) |
| **Security** | ❌ No | ✅ Yes | localhost-only bind, bearer token, origin allowlist, rate limiting, redaction |
| **Professional GUI** | ❌ No | ✅ Yes | Live Activity, Live Desktop View, Agent Status, Task Timeline, Execution Modes |
| **Installer** | ❌ No | ✅ Yes | Inno Setup `.iss` + `ArenaAgent.exe` (PyInstaller) |
| **First-run wizard** | ❌ No | ✅ Yes | GUI wizard |
| **WebSocket bridge** | ❌ No | ✅ Yes | `/api/tasks/{id}/events` (SSE) + `/api/actions` (the nervous system) |
| **Drive the agent over the internet** | ✅ (it is the brain) | ✅ (bridge is accessible) | Arena brain + Local Agent reachable over the network, protected by token + origin; the user accesses the agent over the internet |

## Capability coverage summary

- **Runs in the sandbox (verified):** engine, planner, executor, observer,
  verifier, recovery, memory, workflow engine, MCP bridge, filesystem tools,
  shell, process tools, `/api/*` server, security middleware, audit, GUI,
  tests (81 passing).
- **Windows-native (requires a Windows host; honest `LIMITATION` here):**
  UI automation (click/type via win32), native app-open, full OCR (WindowsOCR /
  Tesseract), live desktop capture, WebView2 browser window.
- **Requires `mcp<2`:** do not upgrade to mcp 2.x (breaks `FastMCP` import).

## What Arena truly is (honest statement)

- Arena **is a reasoning brain** — it plans, decomposes, and re-plans.
- Arena **cannot** see/control your machine, read files, run commands, take
  screenshots, or operate a browser **by itself**.  All of that is the Local
  Agent's job, reached through the bridge.
- Arena **does not expose a public conversation-sync API**.  That is why the
  app uses a **browser window to `https://arena.ai`** plus **local grants** —
  the user logs into Arena and grants the agent access, and reasoning happens
  there while the Local Agent executes.
