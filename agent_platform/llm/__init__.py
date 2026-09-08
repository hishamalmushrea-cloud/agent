"""LLM / "brain" providers.

The agent *engine* (planning loop, tool selection, execution, verification,
recovery) is owned by ``agent_platform.core``.  The engine asks a pluggable
:class:`LLMProvider` for reasoning.  Providers:

  * :class:`OpenAIProvider`  — any OpenAI-compatible endpoint, including a
    community Arena-compatible proxy.  This is how you point the Windows agent
    at an Arena-backed model without hard-coding a vendor SDK.
  * :class:`HeuristicProvider` — a deterministic, offline brain that lets the
    platform run and be tested without any network / API key.
"""
from __future__ import annotations
