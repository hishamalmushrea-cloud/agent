"""Composition root — builds every subsystem once and exposes them to the
server and (for tests) to the engine."""

from __future__ import annotations

from agent_platform.config import Settings
from agent_platform.core.agent import Agent
from agent_platform.core.events import EventBus, get_bus
from agent_platform.llm.provider import build_provider
from agent_platform.memory.memory import MemoryManager
from agent_platform.memory.store import MemoryStore
from agent_platform.security.guard import SecurityGuard
from agent_platform.tasks.manager import TaskManager
from agent_platform.tools.registry import ToolRegistry, register_all
from agent_platform.workflow.engine import WorkflowEngine

_registry: ToolRegistry | None = None
_settings: Settings | None = None
_provider = None
_bus: EventBus | None = None
_agent: Agent | None = None
_memory: MemoryManager | None = None
_tasks: TaskManager | None = None
_engine: WorkflowEngine | None = None
_guard: SecurityGuard | None = None


def reload_provider(settings: Settings | None = None) -> dict:
    """Rebuild the brain provider from current settings (used by the GUI
    when the user changes the Arena / model endpoint at runtime)."""
    global _settings, _provider, _agent, _tasks
    if _settings is None and settings is None:
        return build_all()
    if settings is not None:
        _settings = settings
    from agent_platform.llm.provider import build_provider

    _provider = build_provider(_settings)
    # Rebuild the agent with the new provider (keeps registry/tasks/memory).
    if _tasks is not None:
        _agent = Agent(_settings, _registry, _provider, _bus)
        # Re-point the task manager at the new agent (no task loss).
        from agent_platform.tasks.manager import TaskManager

        _tasks = TaskManager(_agent, _memory, _bus, _settings.storage_path)
    return _context()


def build_all(settings: Settings | None = None) -> dict:
    global _registry, _settings, _provider, _bus, _agent, _memory, _tasks, _engine, _guard
    if _agent is not None:
        return _context()

    settings = settings or Settings()
    _settings = settings
    _registry = register_all()
    _bus = get_bus()
    _guard = SecurityGuard()
    _provider = build_provider(settings)
    _memory = MemoryManager(MemoryStore(settings.storage_path))
    _agent = Agent(settings, _registry, _provider, _bus)
    _tasks = TaskManager(_agent, _memory, _bus, settings.storage_path)
    _engine = WorkflowEngine(_registry)
    _register_builtin_workflows(_engine)
    return _context()


def _register_builtin_workflows(engine: WorkflowEngine) -> None:
    from agent_platform.workflow.engine import Workflow

    scaffold = Workflow({
        "name": "scaffold_python",
        "description": "Create a small python project and run it",
        "nodes": [
            {"id": "t", "type": "trigger", "config": {"event": "manual"}},
            {"id": "mk", "type": "tool",
             "config": {"tool": "create_directory", "arguments": {"path": "app"}}},
            {"id": "wf", "type": "tool",
             "config": {"tool": "write_file",
                        "arguments": {"path": "app/main.py",
                                      "content": 'def main():\n    print("hello")\n\nmain()\n'}}},
            {"id": "run", "type": "tool",
             "config": {"tool": "shell", "arguments": {"command": "python3 app/main.py"}}},
        ],
        "edges": [["t", "mk"], ["mk", "wf"], ["wf", "run"]],
        "start": "t",
    })
    engine.register(scaffold)


def _context() -> dict:
    return {
        "registry": _registry,
        "settings": _settings,
        "provider": _provider,
        "bus": _bus,
        "agent": _agent,
        "memory": _memory,
        "tasks": _tasks,
        "workflow_engine": _engine,
        "guard": _guard,
    }


def get(name: str):
    ctx = build_all()
    return ctx.get(name)


# Convenience accessors used by routes / tests.
def registry() -> ToolRegistry:
    return get("registry")


def agent() -> Agent:
    return get("agent")


def task_manager() -> TaskManager:
    return get("tasks")
