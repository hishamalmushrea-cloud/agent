"""Runtime configuration.

Configuration is read from environment variables (with sane defaults) so the
platform can run without a config file, and so that pointing it at a real
model endpoint (including an Arena-compatible proxy) is just two env vars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


@dataclass
class Settings:
    # --- LLM "brain" -----------------------------------------------------
    # Leave these empty to run offline with the heuristic provider.
    llm_base_url: str = field(default_factory=lambda: _env("AGENT_LLM_BASE_URL"))
    llm_api_key: str = field(default_factory=lambda: _env("AGENT_LLM_API_KEY"))
    model: str = field(default_factory=lambda: _env("AGENT_LLM_MODEL", "gpt-4o-mini"))
    llm_timeout: float = field(default_factory=lambda: float(_env("AGENT_LLM_TIMEOUT", "120")))

    # --- Arena Agent Mode integration -----------------------------------
    # When set, the platform delegates the *reasoning* to a live Arena
    # Agent Mode session (like the one driving this project).  The Arena
    # agent plans; the platform executes with its own tools.
    arena_endpoint: str = field(default_factory=lambda: _env("AGENT_ARENA_ENDPOINT"))
    arena_api_key: str = field(default_factory=lambda: _env("AGENT_ARENA_API_KEY"))
    arena_token: str = field(default_factory=lambda: _env("AGENT_ARENA_TOKEN"))
    arena_timeout: float = field(default_factory=lambda: float(_env("AGENT_ARENA_TIMEOUT", "120")))

    @property
    def arena_enabled(self) -> bool:
        return bool(self.arena_endpoint)

    # --- Agent behaviour ---------------------------------------------------
    max_retries: int = field(default_factory=lambda: int(_env("AGENT_MAX_RETRIES", "4")))
    max_steps: int = field(default_factory=lambda: int(_env("AGENT_MAX_STEPS", "25")))
    approval_mode: str = field(default_factory=lambda: _env("AGENT_APPROVAL_MODE", "safe"))
    # 'safe'  -> auto-approve SAFE, prompt for SENSITIVE, block DANGEROUS w/ prompt
    # 'auto'  -> auto-approve everything (not recommended)
    # 'strict'-> prompt for everything

    allow_network: bool = field(default_factory=lambda: _env("AGENT_ALLOW_NETWORK", "1") == "1")
    sandbox_dir: Optional[str] = field(default_factory=lambda: (_env("AGENT_SANDBOX") or None))
    default_workspace: str = field(
        default_factory=lambda: _env("AGENT_WORKSPACE", str(Path.home() / "agent_workspace"))
    )

    # --- Server -----------------------------------------------------------
    host: str = field(default_factory=lambda: _env("AGENT_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("AGENT_PORT", "8000")))

    # --- Storage ----------------------------------------------------------
    storage_dir: str = field(
        default_factory=lambda: _env("AGENT_STORAGE", str(Path.home() / ".agent_platform"))
    )

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def workspace_path(self) -> Path:
        p = Path(self.default_workspace)
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_settings() -> Settings:
    return Settings()
