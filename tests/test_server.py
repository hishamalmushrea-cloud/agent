"""HTTP server smoke tests (FastAPI TestClient)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_platform.server.app import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["tools"] > 0


def test_tools_endpoint():
    r = client.get("/api/tools")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["summary"]["tools"]}
    assert "shell" in names and "write_file" in names


def test_workflows_endpoint():
    r = client.get("/api/workflows")
    assert r.status_code == 200
    wfs = r.json()
    assert any(w["name"] == "scaffold_python" for w in wfs)


def test_create_task_flow():
    r = client.post("/api/tasks", json={"goal": "create a python project"})
    assert r.status_code == 201
    task = r.json()
    tid = task["id"]
    # Give the background task a moment, then read it.
    import time

    time.sleep(1.0)
    r = client.get(f"/api/tasks/{tid}")
    assert r.status_code == 200
    detail = r.json()
    # Default approval mode is 'safe', so a SENSITIVE tool (e.g. write_file)
    # parks the task WAITING for human approval.  "waiting" is valid here.
    assert detail["state"] in ("completed", "executing", "failed", "verifying", "waiting")


def test_goal_required():
    r = client.post("/api/tasks", json={"goal": ""})
    assert r.status_code == 400
