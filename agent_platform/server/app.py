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

from agent_platform.models.schemas import Task
from agent_platform.server.components import build_all

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


class Approval(BaseModel):
    approved: bool = False


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
    return {"ok": True, "provider_name": _c()["provider"].name, "tools": len(_c()["registry"].names())}


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
