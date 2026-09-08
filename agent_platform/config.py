"""Runtime configuration.

Configuration is read from environment variables (with sane defaults) and can
be persisted/overridden through a local JSON file (``~/.agent_platform/config.json``)
so the GUI can set the Arena / brain endpoint at runtime without restarting the
process with new env vars.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
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
    host: str = field(default_factory=lambda: _env("AGENT_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("AGENT_PORT", "8000")))
    # Local-agent security: localhost-only by default, random token, origin check.
    bind_localhost_only: bool = field(default_factory=lambda: _env("AGENT_BIND_LOCAL", "1") == "1")
    auth_token: str = field(default_factory=lambda: _env("AGENT_AUTH_TOKEN"))
    allow_origins: str = field(default_factory=lambda: _env("AGENT_ALLOW_ORIGINS", "http://127.0.0.1,http://localhost"))
    # Additional host prefixes allowed alongside loopback when bind_localhost_only.
    allowed_hosts: str = field(default_factory=lambda: _env("AGENT_ALLOWED_HOSTS", ".e2b.app"))

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


_overrides_fields = frozenset({
    "llm_base_url", "llm_api_key", "model", "llm_timeout",
    "arena_endpoint", "arena_api_key", "arena_token", "arena_timeout",
    "approval_mode", "default_workspace",
})


def _config_file() -> Path:
    return Path(os.environ.get("AGENT_CONFIG_FILE", str(Path.home() / ".agent_platform"))) / "config.json"


def load_settings() -> Settings:
    s = Settings()
    # Apply persisted overrides (from a previous GUI save) on top of env defaults.
    f = _config_file()
    if f.exists():
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            for k in _overrides_fields:
                if k in raw and raw[k] is not None:
                    setattr(s, k, raw[k])
        except Exception:  # noqa: BLE001
            pass
    return s


def save_settings(s: Settings) -> None:
    """Persist the overridable fields to the config file (used by the GUI)."""
    f = _config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {k: getattr(s, k) for k in _overrides_fields}
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def settings_to_dict(s: Settings) -> dict:
    return {
        "llm_base_url": s.llm_base_url,
        "llm_api_key": s.llm_api_key,
        "model": s.model,
        "arena_endpoint": s.arena_endpoint,
        "arena_api_key": s.arena_api_key,
        "arena_token": s.arena_token,
        "approval_mode": s.approval_mode,
        "default_workspace": s.default_workspace,
        "provider_name": _provider_name(s),
        "brain": _brain_label(s),
    }


def _provider_name(s: Settings) -> str:
    if s.arena_enabled:
        return "arena"
    if s.llm_base_url and (s.llm_api_key or "local" in s.llm_base_url or "127.0.0.1" in s.llm_base_url):
        return "openai_compatible"
    return "heuristic"


def _brain_label(s: Settings) -> str:
    if s.arena_enabled:
        return "Arena Agent (live) — you decide, platform executes"
    if s.llm_base_url:
        return f"OpenAI-compatible ({s.model})"
    return "Offline heuristic brain (no endpoint set)"
