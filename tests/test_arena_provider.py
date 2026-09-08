"""Tests for the Arena Agent Mode provider (delegation / runbook contract)."""

from __future__ import annotations

import httpx

from agent_platform.config import Settings
from agent_platform.llm.provider import ArenaAgentProvider, build_provider


def _settings(**kw) -> Settings:
    s = Settings()
    s.llm_base_url = ""
    s.llm_api_key = ""
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_build_prefers_arena_when_configured():
    s = _settings(arena_endpoint="http://arena.local", arena_api_key="k")
    assert isinstance(build_provider(s), ArenaAgentProvider)


def test_build_falls_back_to_heuristic_without_arena():
    s = _settings()
    from agent_platform.llm.provider import HeuristicProvider

    assert isinstance(build_provider(s), HeuristicProvider)


def test_plan_delegates_to_arena(monkeypatch):
    s = _settings(arena_endpoint="http://arena.local")
    p = ArenaAgentProvider(s)
    monkeypatch.setattr(p, "_post_arena", lambda sub, payload: {
        "strategy": "s",
        "steps": [{"title": "T", "tool": "shell",
                   "arguments": {"command": "echo hi"}, "verification": "exit 0"}],
    })
    res = p.plan("do something", [{"name": "shell", "description": "d", "parameters": {}}])
    assert res["strategy"] == "s"
    assert res["steps"][0]["tool"] == "shell"


def test_action_returns_tool(monkeypatch):
    s = _settings(arena_endpoint="http://arena.local")
    p = ArenaAgentProvider(s)
    monkeypatch.setattr(p, "_post_arena", lambda sub, payload: {
        "tool": "read_file", "arguments": {"path": "x"}})
    res = p.action_for_step("g", {"title": "t", "description": "d"}, tool_specs=[])
    assert res["tool"] == "read_file"
    assert res["arguments"]["path"] == "x"


def test_chat_returns_content(monkeypatch):
    s = _settings(arena_endpoint="http://arena.local")
    p = ArenaAgentProvider(s)
    monkeypatch.setattr(p, "_post_arena", lambda sub, payload: {"content": "hello"})
    assert p.chat([{"role": "user", "content": "Hi"}]) == "hello"


def test_http_contract_makes_correct_post(monkeypatch):
    s = _settings(arena_endpoint="http://arena.local", arena_api_key="k")
    p = ArenaAgentProvider(s)
    captured = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"strategy": "st", "steps": []}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    res = p.plan("hello", [{"name": "a", "description": "d", "parameters": {}}])
    assert captured["url"] == "http://arena.local/plan"
    assert captured["json"]["goal"] == "hello"
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert res["strategy"] == "st"


def test_fallback_to_openai_path_when_no_endpoint(monkeypatch):
    s = _settings()  # no arena endpoint
    p = ArenaAgentProvider(s)
    monkeypatch.setattr(p, "_post", lambda payload: {
        "choices": [{"message": {"content": "fallback"}}]})
    assert p.chat([{"role": "user", "content": "x"}]) == "fallback"
