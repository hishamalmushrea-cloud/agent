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
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from agent_platform.config import load_settings, save_settings, settings_to_dict
from agent_platform.models.schemas import Message, Role, Task, TaskState
from agent_platform.server import components
from agent_platform.server.components import build_all, reload_provider

app = FastAPI(title="Windows Autonomous Computer Agent", version="0.1.0")

_UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def _c() -> dict:
    """Lazy composition-root accessor (safe before/without startup)."""
    return build_all()


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
