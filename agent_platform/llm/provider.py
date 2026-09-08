"""Pluggable LLM "brain" providers.

The agent engine owns reasoning about *what to do* and *when to retry*; the
provider only turns prompts/state into a plan and per-step tool choices.  This
keeps the orchestration engine vendor-independent and testable.

About "Arena Agent Mode"
------------------------
There is no stable, documented public SDK that lets an external Windows app
drive Arena's Agent Mode runtime (planning/tools/sandbox) programmatically; the
platform's agent capabilities are exposed via the Agent Mode session itself.
The honest, engine-preserving integration is:

  * keep the agent loop (planning, tool selection, execution, observe, verify,
    recover) as OUR code, and
  * point the reasoning call at an OpenAI-compatible endpoint — which can be an
    Arena-compatible proxy or any vendor — via the *same* provider interface.

So we do NOT silently swap the engine for an external API: the engine is ours,
only model inference is swappable.  See README for the trade-off / confidence.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from agent_platform.config import Settings


class ProviderError(Exception):
    pass


_PLAN_SYSTEM = (
    "You are an autonomous computer agent planner. Given a user goal and the "
    "available tools, produce a JSON plan. Respond with ONLY a JSON object of "
    "this exact shape: "
    '{"strategy": string, "steps": [{"title": string, "description": string, '
    '"tool": string | null, "arguments": object, "verification": string}]}. '
    "Choose tools only from the available tool names. Keep it to at most 8 steps."
)


class LLMProvider(ABC):
    name = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.model

    @abstractmethod
    def chat(self, messages: list[dict[str, Any]], tools: Optional[list[dict[str, Any]]] = None,
             temperature: float = 0.2) -> str:
        """Plain text completion."""

    @abstractmethod
    def plan(self, goal: str, tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        """Return ``{"strategy": str, "steps": [ {title, description, tool,
        arguments, verification}, ... ]}``."""

    @abstractmethod
    def action_for_step(self, goal: str, step: dict[str, Any],
                        tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        """Return ``{"tool": name, "arguments": {...}}`` for the given step."""


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (works with an Arena proxy / vendor / local)
# ---------------------------------------------------------------------------
class OpenAIProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.timeout = settings.llm_timeout

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        try:
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"LLM HTTP {exc.response.status_code}: {exc.response.text[:400]}") from exc
        except httpx.RequestError as exc:
            raise ProviderError(f"LLM request failed: {exc}") from exc

    @staticmethod
    def _tools_payload(tool_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": {"type": "object", "properties": t.get("parameters", {}),
                                   "required": [k for k in t.get("parameters", {}) if not k.endswith("?")]},
                },
            }
            for t in tool_specs
        ]

    def chat(self, messages: list[dict[str, Any]], tools: Optional[list[dict[str, Any]]] = None,
             temperature: float = 0.2) -> str:
        payload = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data = self._post(payload)
        return data["choices"][0]["message"].get("content") or ""

    def plan(self, goal: str, tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        tool_names = ", ".join(t["name"] for t in tool_specs) or "(none)"
        messages = [
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": f"Goal: {goal}\nAvailable tools: {tool_names}"},
        ]
        text = self.chat(messages)
        return _parse_plan_json(text)

    def action_for_step(self, goal: str, step: dict[str, Any],
                        tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        messages = [
            {"role": "system",
             "content": "You choose the single tool call to perform next for this task step."},
            {"role": "user",
             "content": (f"Goal: {goal}\nCurrent step title: {step.get('title')}\nCurrent step "
                         f"description: {step.get('description')}\nChoose a tool and arguments "
                         "to accomplish it.")},
        ]
        tools = self._tools_payload(tool_specs)
        data = self._post({"model": self.model, "messages": messages, "tools": tools,
                           "tool_choice": "auto", "temperature": 0.0})
        message = data["choices"][0]["message"]
        if message.get("tool_calls"):
            tc = message["tool_calls"][0]
            try:
                args = json.loads(tc["function"]["arguments"])
            except Exception:  # noqa: BLE001
                args = {}
            return {"tool": tc["function"]["name"], "arguments": args}
        return {"tool": None, "arguments": {}}


# ---------------------------------------------------------------------------
# Arena Agent Mode provider
# ---------------------------------------------------------------------------
class ArenaAgentProvider(OpenAIProvider):
    """The platform "leans on" a live Arena Agent Mode session as its brain.

    Delegation contract (documented in ARENA.md / AGENTS.md):

      POST {endpoint}/plan  {"goal": str, "tools": [ToolSpec...]}
          -> {"strategy": str, "steps": [ {index,title,description,tool,
                                            arguments,verification}, ... ]}

      POST {endpoint}/chat  {"messages": [...], "tools": [...]}
          -> {"content": str}                      # free text reasoning

      POST {endpoint}/action {"goal": str, "step": {...}, "tools": [...]}
          -> {"tool": str, "arguments": {...}}      # per-step tool choice

    The Arena agent decides; the platform (this repo) executes the returned
    runbook with its own tools, then observes / verifies / recovers.  If no
    endpoint is configured it falls back to the OpenAI-compatible path so the
    platform still works standalone.
    """

    name = "arena"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.endpoint = settings.arena_endpoint.rstrip("/") if settings.arena_endpoint else ""

    def _arena_headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.settings.arena_api_key:
            h["Authorization"] = f"Bearer {self.settings.arena_api_key}"
        if self.settings.arena_token:
            h["X-Arena-Token"] = self.settings.arena_token
        return h

    def _post_arena(self, subpath: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.endpoint}{subpath}"
        try:
            resp = httpx.post(url, json=payload, headers=self._arena_headers(),
                              timeout=self.settings.arena_timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Arena agent HTTP {exc.response.status_code}: {exc.response.text[:400]}") from exc
        except httpx.RequestError as exc:
            raise ProviderError(f"Arena agent request failed: {exc}") from exc

    def chat(self, messages: list[dict[str, Any]], tools: Optional[list[dict[str, Any]]] = None,
             temperature: float = 0.2) -> str:
        if self.endpoint:
            data = self._post_arena("/chat", {"messages": messages, "tools": tools or []})
            return data.get("content", "")
        return super().chat(messages, tools, temperature)

    def plan(self, goal: str, tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        if self.endpoint:
            data = self._post_arena("/plan", {"goal": goal, "tools": tool_specs})
            steps = data.get("steps") or []
            return {"strategy": data.get("strategy", ""), "steps": steps}
        # Fallback: OpenAI-compatible structured planning (no endpoint).
        return super().plan(goal, tool_specs)

    def action_for_step(self, goal: str, step: dict[str, Any],
                        tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        if self.endpoint:
            data = self._post_arena("/action", {"goal": goal, "step": step, "tools": tool_specs})
            tool = data.get("tool")
            if tool:
                return {"tool": tool, "arguments": dict(data.get("arguments", {}) or {})}
            return {"tool": None, "arguments": {}}
        return super().action_for_step(goal, step, tool_specs)


# ---------------------------------------------------------------------------
# Heuristic / offline provider
# ---------------------------------------------------------------------------
class HeuristicProvider(LLMProvider):
    """Deterministic offline brain for running & testing without an API key."""

    name = "heuristic"

    def chat(self, messages: list[dict[str, Any]], tools: Optional[list[dict[str, Any]]] = None,
             temperature: float = 0.2) -> str:
        return "[heuristic provider: no free-text reasoning available]"

    def plan(self, goal: str, tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        from agent_platform.core.heuristics import heuristic_plan

        return heuristic_plan(goal, tool_specs)

    def action_for_step(self, goal: str, step: dict[str, Any],
                        tool_specs: list[dict[str, Any]]) -> dict[str, Any]:
        from agent_platform.core.heuristics import heuristic_action_for_step

        return heuristic_action_for_step(goal, step)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _parse_plan_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM text (strips code fences, finds first {...})."""
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:  # noqa: BLE001
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            pass
    return {"strategy": text.strip(), "steps": []}


def build_provider(settings: Settings) -> LLMProvider:
    """Choose a provider (priority: Arena Agent -> OpenAI-compatible -> heuristic)."""
    if getattr(settings, "arena_enabled", False) or settings.arena_endpoint:
        return ArenaAgentProvider(settings)
    if settings.llm_base_url and (settings.llm_api_key or "local" in settings.llm_base_url or "127.0.0.1" in settings.llm_base_url):
        return OpenAIProvider(settings)
    return HeuristicProvider(settings)
