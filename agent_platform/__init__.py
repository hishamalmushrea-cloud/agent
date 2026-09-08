"""
agent_platform
==============

A modular, extensible Windows Autonomous Computer Agent platform.

The intelligence *engine* (planning, tool selection, execution loop,
observation, verification, recovery, memory, workflows) is owned by this
package.  The "brain" (an LLM) is a *pluggable* provider: it may be an
OpenAI-compatible endpoint (including an Arena-compatible proxy), a local
model, or a deterministic heuristic provider used for offline runs and tests.

Philosophy
----------
The user gives a natural-language GOAL.  The agent understands it, plans,
picks the right tools, executes, observes, verifies, recovers from errors and
re-plans until the goal is satisfied.  It is NOT a chat reply.
"""

__version__ = "0.1.0"

# Re-export the public surface used by the server and GUI.
from agent_platform.models.schemas import (  # noqa: F401
    ToolSpec,
    ToolResult,
    Observation,
    Plan,
    PlanStep,
    Task,
    TaskState,
    Message,
    Role,
    MemoryItem,
    MemoryKind,
    Event,
    EventKind,
)
from agent_platform.tools.registry import ToolRegistry, register  # noqa: F401

__all__ = [
    "__version__",
    "ToolSpec",
    "ToolResult",
    "Observation",
    "Plan",
    "PlanStep",
    "Task",
    "TaskState",
    "Message",
    "Role",
    "MemoryItem",
    "MemoryKind",
    "Event",
    "EventKind",
    "ToolRegistry",
    "register",
]
