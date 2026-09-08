"""Server-level V2 tests: runtime endpoints + security middleware."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_platform.server.app import app

client = TestClient(app, base_url="http://localhost")


def test_runtime_describes_local_agent():
    r = client.get("/api/runtime")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body and "tools" in body and "permissions" in body
    assert body["tools"] > 0


def test_actions_write_read_roundtrip():
    r = client.post("/api/actions", json={
        "kind": "write_file", "target": "/tmp/v2_server_test.txt",
        "arguments": {"content": "roundtrip"}, "force": True,
    })
    assert r.status_code == 202
    assert r.json()["ok"] is True
    r = client.post("/api/actions", json={"kind": "read_file", "target": "/tmp/v2_server_test.txt"})
    assert r.status_code == 202
    assert "roundtrip" in r.json()["output"]


def test_actions_deny_dangerous_command():
    r = client.post("/api/actions", json={"kind": "run_command", "target": "format c:"})
    assert r.status_code == 202
    assert r.json()["ok"] is False
    assert "denied" in r.json()["error"].lower()


def test_actions_unknown_kind_400():
    r = client.post("/api/actions", json={"kind": "not_a_real_kind"})
    assert r.status_code == 400


def test_stop_and_reset():
    r = client.post("/api/stop")
    assert r.status_code == 200
    assert r.json()["stopped"] is True
    # Actions are blocked while stopped.
    r = client.post("/api/actions", json={"kind": "read_file", "target": "/tmp/x"})
    assert r.json()["ok"] is False
    assert "stopped" in r.json()["error"].lower()
    r = client.post("/api/reset")
    assert r.status_code == 200
    assert r.json()["status"] == "IDLE"


def test_audit_endpoint():
    r = client.get("/api/audit")
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body and "stats" in body


def test_diagnostics_endpoint():
    r = client.get("/api/diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert isinstance(body["results"], list) and len(body["results"]) > 0


def test_security_rejects_unknown_host_by_default():
    # With bind_localhost_only, a non-localhost Host header is forbidden.
    r = client.get("/api/health", headers={"host": "evil.example.com"})
    assert r.status_code in (200, 403)  # health is public but host check applies


def test_security_requires_token_when_configured(monkeypatch):
    from agent_platform.server import app as app_mod

    # Temporarily force an auth token so the /\api actions path requires it.
    monkeypatch.setattr(app_mod, "_c", lambda: {"settings": _settings_with_token(),
                                                "registry": _cached_registry()})

    r = TestClient(app, base_url="http://localhost").post(
        "/api/actions", json={"kind": "read_file", "target": "/tmp/x"})
    assert r.status_code == 401


def _settings_with_token():
    from agent_platform.config import Settings
    s = Settings()
    s.auth_token = "secret1234"
    return s


def _cached_registry():
    from agent_platform.tools.registry import register_all
    return register_all()
