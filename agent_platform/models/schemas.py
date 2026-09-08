"""Typed domain models for the agent platform.

These are the vocabulary used across the agent core, the tool system, the
permission layer, memory, the workflow engine and the HTTP/SSE server.
Everything is JSON-serialisable so that the GUI (a browser shell) and any
external adapter can consume the same structures.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Roles / participants
# ---------------------------------------------------------------------------
class Role(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Tool system
# ---------------------------------------------------------------------------
class PermissionLevel(str, enum.Enum):
    """How risky a tool is; drives the human-approval policy."""

    SAFE = "safe"                       # execute immediately
    SENSITIVE = "sensitive"             # require confirmation
    DANGEROUS = "dangerous"             # require explicit confirmation


class ToolSpec(BaseModel):
    """Static description of a tool.  Registration metadata (advertised to
    the LLM via the tool registry / discovery)."""

    name: str
    description: str
    category: str = "general"
    parameters: dict[str, Any] = Field(default_factory=dict)
    permission: PermissionLevel = PermissionLevel.SAFE
    managed_by: str = "builtin"         # tool provider / plugin name
    version: str = "1.0.0"
    requires_admin: bool = False
    input_example: str = ""


class ToolResult(BaseModel):
    """The result returned by a tool invocation."""

    tool: str
    ok: bool
    output: str = ""
    data: Any = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Observation(BaseModel):
    """An observation produced by the observer after a tool call."""

    step_id: str
    tool: str
    result: ToolResult
    summary: str = ""
    ts: str = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: new_id("step"))
    index: int = 0
    title: str
    description: str = ""
    tool: Optional[str] = None          # suggested tool
    arguments: dict[str, Any] = Field(default_factory=dict)
    verification: str = ""              # what must be true for the step to pass
    status: str = "pending"             # pending|running|ok|failed|skipped
    retries: int = 0
    observation: Optional[Observation] = None


class Plan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("plan"))
    goal: str
    strategy: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    confidence: float = 0.0
    created_at: str = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Task state machine
# ---------------------------------------------------------------------------
class TaskState(str, enum.Enum):
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"          # waiting for human approval / input
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    goal: str
    state: TaskState = TaskState.PENDING
    status_note: str = ""
    plan: Optional[Plan] = None
    messages: list[Message] = Field(default_factory=list)
    current_step_index: int = 0
    completed_steps: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)
    retry_map: dict[str, int] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    result_summary: str = ""
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    errors: list[str] = Field(default_factory=list)
    workspace: Optional[str] = None
    requested_by: str = "local"
    approval_needed: list[dict[str, Any]] = Field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = _now()


class Message(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    role: Role
    content: str
    created_at: str = Field(default_factory=_now)
    meta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
class MemoryKind(str, enum.Enum):
    SESSION = "session"
    TASK = "task"
    PROJECT = "project"
    LONG_TERM = "long_term"
    TOOL = "tool"


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mem"))
    kind: MemoryKind
    key: str
    value: Any = None
    text: str = ""
    importance: float = 0.5
    ttl_seconds: Optional[int] = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    scope: Optional[str] = None   # e.g. project path / task id


# ---------------------------------------------------------------------------
# Live events (for the GUI timeline / SSE)
# ---------------------------------------------------------------------------
class EventKind(str, enum.Enum):
    TASK_CREATED = "task_created"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    STEP_STARTED = "step_started"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    OBSERVATION = "observation"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    WAITING_APPROVAL = "waiting_approval"
    APPROVAL_RESOLVED = "approval_resolved"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ASSISTANT = "assistant"      # a natural-language reply shown as chat text
    HEARTBEAT = "heartbeat"
    LOG = "log"


class Event(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    task_id: str
    kind: EventKind
    payload: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    ts: str = Field(default_factory=_now)
