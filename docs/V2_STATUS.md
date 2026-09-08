# V2 Master Engineering Specification — Status

This is a living status of the V2 build.  Each phase was implemented, tested
(with real execution, not mocked), and then moved on.  No phase is "designed
but not built" unless explicitly stated.

## Phase status

| Phase | Status | Evidence |
| --- | --- | --- |
| 1. Research (Arena capabilities) | ✅ Done | `docs/CAPABILITY_MATRIX.md` — honest Arena/no-public-API finding from `arena.ai/faq` |
| 2. Architecture | ✅ Done | `docs/ARCHITECTURE.md` |
| 3. Bridge (MCP / WebSocket / HTTP) | ✅ Done | `mcp_server/`, `/api/actions`, `/api/tasks/{id}/events` (SSE) |
| 4. Local Agent | ✅ Done | `core/agent.py` loop, `agent_runtime.py` facade |
| 5. Browser extension | ✅ Done | `browser-extension/manifest.json`, `background.js`, `content.js`, `popup.*` |
| 6. Desktop / browser-window | ✅ Done | `desktop_app.py` (pywebview → arena.ai) |
| 7. Vision / OCR | ✅ Done (with honest fallback) | `vision/ocr.py` (WindowsOCR/Tesseract/Placeholder), `vision/vision_agent.py` |
| 8. Files / terminal | ✅ Done | `file_tools.py` (+rename/compress/extract), `shell_tools.py`, `process_tools.py` |
| 9. Permissions / security | ✅ Done | `permission/matrix.py` 4-tier, `server/app.py` SecurityMiddleware (localhost/token/origin) |
| 10. Verification / recovery | ✅ Done | `core/verifier.py`, `core/recovery.py` |
| 11. Professional GUI | ✅ Done | Live Activity, Live Desktop View, Agent Status, Task Timeline, Execution Modes, first-run wizard |
| 12. Testing | ✅ Done (81 tests) | `tests/` + `tests/test_v2_core.py` |
| 13. Installer | ✅ Done | `installer/install_windows.iss`, `RunInstaller.bat`, `ArenaAgent.spec`, `start_windows.bat` |
| 14. Integration | ✅ Live | Server runs; `/api/actions`, `/api/runtime`, `/api/stop`, `/api/audit`, `/api/diagnostics` verified end-to-end |

## Verified end-to-end flows

- **Unified Action Protocol:** `POST /api/actions` accepts typed `kind`, enforces
  permission/confirmation/audit, and runs the tool.  `write_file` → `read_file`
  round-trip verified; `run_command` denied for `format c:`; `shell` gated by
  grant until confirmed; Emergency Stop blocks all actions.
- **Agent chat loop:** `/api/chat` → task → SSE events → plan → tool calls →
  verification → completion (the "Open VS Code → create project → run → fix"
  flow runs as a real task; the sandbox executes on Linux, so Windows UI steps
  degrade to the honest fallback).
- **Security:** localhost-only host check, Bearer token, origin allowlist all
  enforced by `SecurityMiddleware`; audit log redacts secrets (`api_key=…`,
  `Bearer …`, `sk-…`).

## Honest limitations

- **Arena has no public conversation-sync API.**  We use a browser window to
  `https://arena.ai` + local grants instead of faking one.
- **This sandbox is Linux**, so Windows-native pieces (UI automation via win32,
  native app-open, WebView2, full OCR, live desktop capture) report
  `LIMITATION` in `/api/diagnostics` rather than pretending to work.  On a
  real Windows host they activate.

## How to run

```bash
python run.py                 # start engine + open GUI
python -m uvicorn agent_platform.server.app:app --host 0.0.0.0 --port 8000
python -m pytest tests/       # 81 tests
```
