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


def test_chat_creates_conversation():
    r = client.post("/api/chat", json={"message": "system info", "workspace": "chat_test"})
    assert r.status_code == 201
    body = r.json()
    assert body["task_id"] and body["conversation_id"] == body["task_id"]
    # User message is persisted into the conversation thread.
    import time

    time.sleep(0.6)
    d = client.get(f"/api/tasks/{body['task_id']}").json()
    assert any(m["role"] == "user" for m in d["messages"])


def test_chat_requires_message():
    r = client.post("/api/chat", json={"message": ""})
    assert r.status_code == 400


def test_settings_roundtrip_and_brain_switch():
    r = client.post("/api/settings", json={
        "arena_endpoint": "http://127.0.0.1:9400", "arena_api_key": "k", "approval_mode": "safe"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider_name"] == "arena"
    # Turn it back off so we do not leave the test process in a bad state.
    client.post("/api/settings", json={"arena_endpoint": "", "llm_base_url": ""})
    h = client.get("/api/health").json()
    assert h["provider_name"] in ("heuristic", "openai_compatible")
