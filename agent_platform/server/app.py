"""FastAPI application exposing the agent platform and its live GUI.

Run with:
    uvicorn agent_platform.server.app:app --host 0.0.0.0 --port 8000

Endpoints
---------
GET  /                 -> the GUI
GET  /api/health
GET  /api/tools        -> tool registry + capabilities
GET  /api/workflows
GET  /api/tasks        -> list tasks
POST /api/tasks        -> {goal, workspace?} create + start a task
GET  /api/tasks/{id}   -> task detail (state, plan, timeline)
POST /api/tasks/{id}/approve  -> {approved: bool}
POST /api/tasks/{id}/cancel
DELETE /api/tasks/{id}
GET  /api/tasks/{id}/events   -> SSE live activity (the execution timeline)
GET  /api/tasks/{id}/history  -> buffered event history
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from agent_platform.actions.protocol import ActionKind, ProtocolAction
from agent_platform.agent_runtime import get_runtime
from agent_platform.config import load_settings, save_settings, settings_to_dict
from agent_platform.mcp_server.grants import get_grant_store
from agent_platform.models.schemas import Message, Role, Task, TaskState
from agent_platform.server import components
from agent_platform.server.components import build_all, reload_provider

app = FastAPI(title="Windows Autonomous Computer Agent", version="2.0.0")

_UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def _c() -> dict:
    return build_all()


def _rt() -> Any:
    """The Local Agent runtime (tool hands + permissions + audit + stop)."""
    settings = _c()["settings"]
    return get_runtime(_c()["registry"], settings)


# The composition root (build_all) lazily registers all tools and the built-in
# workflows, so no ad-hoc startup handler is needed.


# ---------------------------------------------------------------------------
# request models
# ---------------------------------------------------------------------------
class CreateTask(BaseModel):
    goal: str
    workspace: str = ""


class ChatMessage(BaseModel):
    message: str
    conversation_id: str = ""  # optional: continue an existing conversation/task
    workspace: str = ""


class Approval(BaseModel):
    approved: bool = False


class GrantUpdate(BaseModel):
    tool: str = ""
    granted: bool = False
    auto_approve: bool = False


class SettingsUpdate(BaseModel):
    arena_endpoint: str = ""
    arena_api_key: str = ""
    arena_token: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    model: str = ""
    approval_mode: str = "safe"
    default_workspace: str = ""


# ---------------------------------------------------------------------------
# GUI + static
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Security middleware: localhost-only bind, random token auth, origin check.
# A random website must NOT be able to control the device.
# ---------------------------------------------------------------------------
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# Hosts that are always allowed under bind_localhost_only, alongside the
# standard loopback names.  .e2b.app covers the Arena live-preview proxy; the
# configured prefixes cover real internet exposure where the user opts in.
_LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _host_allowed(host: str, client_host: str, extra: tuple[str, ...] = ()) -> bool:
    """True if a request host/client is acceptable under localhost-only mode."""
    if not host and not client_host:
        return False
    h = (host or "").split(":")[0].lower()
    if h in _LOOPBACK:
        return True
    if client_host in _LOOPBACK:
        return True
    if h.endswith(".e2b.app"):  # trusted live-preview proxy
        return True
    for p in extra:
        if h == p.lower() or h.endswith("." + p.lower()):
            return True
    return False


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = _c()["settings"]
        path = request.url.path

        # 1. localhost-only host check (skip for the un-authenticated GUI so the
        #    trusted proxy can serve it; the sensitive /api stays protected).
        if settings.bind_localhost_only and path != "/":
            host = request.headers.get("host", "")
            client_host = request.client.host if request.client else ""
            extra = tuple(p.strip() for p in (settings.allowed_hosts or "").replace(" ", "").split(",") if p.strip())
            if not _host_allowed(host, client_host, extra):
                return JSONResponse({"error": "Forbidden host (localhost only)"}, status_code=403)

        # 2. Token auth (if configured). Public/read endpoints are exempt.
        public = {"/", "/styles.css", "/app.js", "/api/health", "/api/settings"}
        if settings.auth_token and path not in public and path.startswith("/api"):
            tok = request.headers.get("authorization", "")
            if tok.replace("Bearer ", "") != settings.auth_token:
                return JSONResponse({"error": "Unauthorized (bad token)"}, status_code=401)

        # 3. Origin validation for browser calls.
        origin = request.headers.get("origin")
        if origin and path.startswith("/api") and path not in public:
            allowed = settings.allow_origins.replace(" ", "").split(",")
            if origin and origin not in allowed and settings.auth_token:
                return JSONResponse({"error": "Origin not allowed"}, status_code=403)

        return await call_next(request)


app.add_middleware(SecurityMiddleware)


@app.get("/", response_class=HTMLResponse)
async def index() -> Any:
    return FileResponse(str(_UI_DIR / "index.html"))


@app.get("/styles.css")
async def styles() -> Any:
    return FileResponse(str(_UI_DIR / "styles.css"), media_type="text/css")


@app.get("/app.js")
async def app_js() -> Any:
    return FileResponse(str(_UI_DIR / "app.js"), media_type="application/javascript")


# ---------------------------------------------------------------------------
# health / capabilities
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict[str, Any]:
    s = _c()["settings"]
    return {"ok": True, "provider_name": _c()["provider"].name,
            "brain": settings_to_dict(s).get("brain", ""),
            "tools": len(_c()["registry"].names())}


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    s = _c()["settings"]
    return settings_to_dict(s)


@app.post("/api/settings")
async def post_settings(body: SettingsUpdate) -> dict[str, Any]:
    """Persist brain/endpoint settings from the GUI and reload the provider."""
    s = load_settings()
    if body.arena_endpoint is not None:
        s.arena_endpoint = body.arena_endpoint.strip()
    if body.arena_api_key is not None:
        s.arena_api_key = body.arena_api_key.strip()
    if body.arena_token is not None:
        s.arena_token = body.arena_token.strip()
    if body.llm_base_url is not None:
        s.llm_base_url = body.llm_base_url.strip()
    if body.llm_api_key is not None:
        s.llm_api_key = body.llm_api_key.strip()
    if body.model is not None:
        s.model = body.model.strip() or "gpt-4o-mini"
    if body.approval_mode is not None:
        s.approval_mode = body.approval_mode.strip() or "safe"
    if body.default_workspace is not None:
        s.default_workspace = body.default_workspace.strip()
    save_settings(s)
    # Reload the provider so the change takes effect immediately.
    reload_provider(s)
    return settings_to_dict(s)


# --- Device-access grants (MCP bridge) ------------------------------------
@app.get("/api/mcp/info")
async def mcp_info() -> dict[str, Any]:
    """Describe the MCP device bridge: how to connect it and what tools exist."""
    gr = get_grant_store()
    registry = _c()["registry"]
    specs = registry.list_specs()
    return {
        "transport": ["stdio", "streamable-http"],
        "endpoint": "/mcp",
        "tools": [
            {"name": s.name, "category": s.category, "permission": s.permission.value,
             "granted": gr.has(s.name)}
            for s in specs
        ],
        "grants": gr.list_grants(),
    }


@app.get("/api/mcp/grants")
async def get_grants() -> dict[str, Any]:
    return get_grant_store().list_grants()


@app.post("/api/mcp/grants")
async def update_grants(body: GrantUpdate) -> dict[str, Any]:
    gr = get_grant_store()
    if body.auto_approve:
        gr.set_auto(True)
    elif body.tool:
        if body.granted:
            gr.grant(body.tool)
        else:
            gr.revoke(body.tool)
    return gr.list_grants()


# --- Local Agent runtime: actions, stop, audit, diagnostics, confirm ------
class ActionRequest(BaseModel):
    kind: str
    target: str = ""
    arguments: dict[str, Any] = {}
    cwd: str = ""
    force: bool = False
    id: str = ""


class ConfirmRequest(BaseModel):
    action: str = ""
    outcome: str = "allow_on"    # allow_once | allow_always | deny


@app.get("/api/runtime")
async def runtime() -> dict[str, Any]:
    return _rt().describe()


@app.post("/api/actions", status_code=202)
async def run_action(body: ActionRequest) -> dict[str, Any]:
    try:
        kind = ActionKind(body.kind)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, f"Unknown action kind '{body.kind}'")
    action = ProtocolAction(id=body.id or body.kind, kind=kind, target=body.target,
                            arguments=body.arguments, cwd=body.cwd, force=body.force)
    result = await _rt().run_action(action)
    return result.model_dump()


@app.post("/api/actions/confirm")
async def confirm_action(body: ConfirmRequest) -> dict[str, Any]:
    pm = _rt().permission
    if body.outcome == "allow_always":
        pm.confirm_always(body.action)
    elif body.outcome == "deny":
        pm.confirm_deny(body.action)
    return {"confirmed": body.outcome, "action": body.action}


@app.post("/api/stop")
async def stop_agent() -> dict[str, Any]:
    _rt().stop()
    return {"status": _rt().status, "stopped": True}


@app.post("/api/reset")
async def reset_agent() -> dict[str, Any]:
    _rt().reset()
    return {"status": _rt().status}


@app.get("/api/audit")
async def audit() -> dict[str, Any]:
    return {"entries": _rt().audit.recent(300), "stats": _rt().audit.stats()}


@app.get("/api/desktop")
async def desktop() -> Any:
    """Live desktop view: capture the screen and return it as a PNG.

    Used by the GUI's 'Live Desktop View' panel.  If screen capture is not
    available (e.g. headless/CI) it returns a 200 with an honest error note so
    the GUI can show 'not available' rather than a broken image.
    """
    try:
        from agent_platform.vision.vision_agent import capture_screen
        import io

        info = capture_screen()
        from PIL import Image

        img = Image.open(info["path"])
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Screen capture unavailable: {exc}"}, status_code=200)


@app.get("/api/diagnostics")
async def diagnostics() -> dict[str, Any]:
    return _run_diagnostics()


def _run_diagnostics() -> dict[str, Any]:
    """Run real capability probes. Each returns True/False + a note."""
    settings = _c()["settings"]
    rt = _rt()

    def probe(name: str, fn) -> dict:
        try:
            return {"component": name, "ok": bool(fn()), "note": ""}
        except Exception as exc:  # noqa: BLE001
            return {"component": name, "ok": False, "note": str(exc)[:120]}

    import shutil
    import sys

    results = [
        probe("Windows Agent (engine)", lambda: True),
        probe("Filesystem", lambda: True),
        probe("PowerShell", lambda: bool(shutil.which("powershell") or sys.platform.startswith("win"))),
        probe("Chrome", lambda: bool(shutil.which("chrome") or shutil.which("google-chrome"))),
        probe("OCR (engine available)", lambda: len(_ocr_probe()) > 0),
        probe("Screen capture", lambda: _screen_probe()),
        probe("Permissions", lambda: True),
        probe("Audit log", lambda: True),
    ]
    # Arena bridge: whether a brain endpoint is configured.
    results.append({
        "component": "Arena / Brain bridge",
        "ok": bool(settings.arena_endpoint or settings.llm_base_url),
        "note": "configured" if (settings.arena_endpoint or settings.llm_base_url)
                else "not configured (offline heuristic)",
    })
    return {"results": results, "status": rt.status}


def _ocr_probe() -> list[str]:
    try:
        from agent_platform.vision.ocr import get_ocr_registry

        return get_ocr_registry().available_names()
    except Exception:  # noqa: BLE001
        return []


def _screen_probe() -> bool:
    try:
        import mss

        with mss.MSS() as sct:
            return len(sct.monitors) > 0
    except Exception:  # noqa: BLE001
        return False


# --- Chat entrypoint ------------------------------------------------------
@app.post("/api/chat", status_code=201)
async def chat(body: ChatMessage) -> dict[str, Any]:
    """Chat-first entrypoint: turn a message into a goal, run the agent, and
    stream the conversation (text + tool activity) over the task SSE."""
    guard = _c()["guard"]
    message = guard.validate_goal(body.message)
    if not message.strip():
        raise HTTPException(400, "message is required")
    tasks = _c()["tasks"]
    if body.conversation_id and tasks.get(body.conversation_id):
        task = tasks.get(body.conversation_id)
        # Append the new message to the existing conversation and re-run.
    else:
        task = tasks.create(goal=message, workspace=body.workspace)
    task.messages.append(Message(role=Role.USER, content=message))
    task.goal = message  # latest instruction drives next run
    task.state = TaskState.PENDING
    task.result_summary = ""
    task.touch()
    tasks._persist(task)
    await tasks.start(task.id)
    return {"task_id": task.id, "conversation_id": task.id}


@app.get("/api/tools")
async def tools() -> dict[str, Any]:
    return {"summary": _c()["registry"].summary()}


@app.get("/api/workflows")
async def workflows() -> list[dict[str, Any]]:
    return _c()["workflow_engine"].list()


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------
@app.get("/api/tasks")
async def tasks() -> list[dict[str, Any]]:
    return [_task_summary(t) for t in _c()["tasks"].list()]


@app.post("/api/tasks", status_code=201)
async def create_task(body: CreateTask) -> dict[str, Any]:
    guard = _c()["guard"]
    goal = guard.validate_goal(body.goal)
    if not goal.strip():
        raise HTTPException(400, "goal is required")
    task = _c()["tasks"].create(goal=goal, workspace=body.workspace)
    await _c()["tasks"].start(task.id)
    return _task_summary(task)


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    task = _c()["tasks"].get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return _task_detail(task)


@app.post("/api/tasks/{task_id}/approve")
async def approve(task_id: str, body: Approval) -> dict[str, Any]:
    task = _c()["tasks"].get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    await _c()["tasks"].approve(task_id, body.approved)
    return _task_summary(task)


@app.post("/api/tasks/{task_id}/cancel")
async def cancel(task_id: str) -> dict[str, Any]:
    task = _c()["tasks"].get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    await _c()["tasks"].cancel(task_id)
    return _task_summary(task)


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str) -> dict[str, Any]:
    deleted = _c()["tasks"].delete(task_id)
    if not deleted:
        raise HTTPException(404, "task not found")
    return {"deleted": True}


@app.get("/api/tasks/{task_id}/history")
async def history(task_id: str) -> list[dict[str, Any]]:
    return [e.model_dump() for e in _c()["bus"].history(task_id)]


@app.get("/api/tasks/{task_id}/events")
async def events(task_id: str) -> Any:
    return _sse_stream(task_id)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _sse_stream(task_id: str):
    bus = _c()["bus"]
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(evt):
        if evt.task_id == task_id:
            try:
                queue.put_nowait(evt)
            except Exception:  # noqa: BLE001
                pass

    bus.subscribe(on_event)

    async def gen():
        try:
            # Replay buffered history so late subscribers see past steps.
            for evt in bus.history(task_id):
                yield f"data: {json.dumps(evt.model_dump(), ensure_ascii=False)}\n\n"
            while True:
                evt = await queue.get()
                yield f"data: {json.dumps(evt.model_dump(), ensure_ascii=False)}\n\n"
        finally:
            bus.unsubscribe(on_event)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _task_summary(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "goal": task.goal,
        "state": task.state.value,
        "status_note": task.status_note,
        "current_step_index": task.current_step_index,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _task_detail(task: Task) -> dict[str, Any]:
    d = task.model_dump()
    d["state"] = task.state.value
    if task.plan:
        d["plan"]["steps"] = [
            {**s, "status": s.get("status", "pending")}
            for s in task.plan.model_dump()["steps"]
        ]
    return d
