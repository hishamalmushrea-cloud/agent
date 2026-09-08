"""Action Executor — runs a ProtocolAction against the tool registry.

It bridges the unified :class:`ActionKind` protocol to concrete tools, enforcing
the **permission matrix** and **human confirmation** (Allow Once / Always / Deny)
before any privileged/dangerous action runs.  It also records every action in
the audit log.

This is the single choke point the GUI, browser extension, MCP bridge and
WebSocket bridge all pass through, so security and logging are consistent.
"""

from __future__ import annotations

import time
from typing import Any

from agent_platform.actions.protocol import ActionKind, ProtocolAction, ProtocolResult
from agent_platform.audit.audit import AuditLogger
from agent_platform.permission.matrix import PermissionMatrix, RiskLevel
from agent_platform.tools.registry import ToolRegistry


class ActionExecutor:
    def __init__(self, registry: ToolRegistry, permission: PermissionMatrix,
                 audit: AuditLogger | None = None) -> None:
        self.registry = registry
        self.permission = permission
        self.audit = audit or AuditLogger()

        # ActionKind -> (tool_name, arg_mapper)
        self._map: dict[ActionKind, tuple[str, Any]] = self._build_map()

    def _build_map(self) -> dict[ActionKind, tuple[str, Any]]:
        return {
            # Applications
            ActionKind.OPEN_APPLICATION: ("open_application", lambda a: {
                "name": a.target or a.arguments.get("name", ""),
                "args": a.arguments.get("args", [])}),
            ActionKind.CLOSE_APPLICATION: ("close_application", lambda a: {
                "name": a.target or a.arguments.get("name", "")}),
            # Desktop / physical input (Windows, via ui_input)
            ActionKind.CLICK: ("ui_input", lambda a: {
                "action": "click", "x": a.arguments.get("x"),
                "y": a.arguments.get("y"), "clicks": a.arguments.get("clicks", 1),
                "window": a.target or a.arguments.get("window", "")}),
            ActionKind.DOUBLE_CLICK: ("ui_input", lambda a: {
                "action": "double_click", "x": a.arguments.get("x"),
                "y": a.arguments.get("y"), "window": a.target or a.arguments.get("window", "")}),
            ActionKind.RIGHT_CLICK: ("ui_input", lambda a: {
                "action": "right_click", "x": a.arguments.get("x"),
                "y": a.arguments.get("y"), "window": a.target or a.arguments.get("window", "")}),
            ActionKind.MOVE_MOUSE: ("ui_input", lambda a: {
                "action": "move_mouse", "x": a.arguments.get("x"),
                "y": a.arguments.get("y"), "window": a.target or a.arguments.get("window", "")}),
            ActionKind.DRAG: ("ui_input", lambda a: {
                "action": "drag", "x": a.arguments.get("x"),
                "y": a.arguments.get("y"), "text": a.arguments.get("from", ""),
                "window": a.target or a.arguments.get("window", "")}),
            ActionKind.SCROLL: ("ui_input", lambda a: {
                "action": "scroll", "x": a.arguments.get("x"), "y": a.arguments.get("y"),
                "clicks": a.arguments.get("clicks", -3),
                "window": a.target or a.arguments.get("window", "")}),
            ActionKind.TYPE_TEXT: ("ui_input", lambda a: {
                "action": "type_text", "text": a.target or a.arguments.get("text", ""),
                "window": a.arguments.get("window", "")}),
            ActionKind.PRESS_KEY: ("ui_input", lambda a: {
                "action": "press_key", "text": a.target or a.arguments.get("key", ""),
                "window": a.arguments.get("window", "")}),
            ActionKind.HOTKEY: ("ui_input", lambda a: {
                "action": "hotkey", "text": a.target or a.arguments.get("keys", ""),
                "window": a.arguments.get("window", "")}),
            # Filesystem
            ActionKind.READ_FILE: ("read_file", lambda a: {"path": a.target or a.arguments.get("path")}),
            ActionKind.WRITE_FILE: ("write_file", lambda a: {
                "path": a.target or a.arguments.get("path"), "content": a.arguments.get("content", "")}),
            ActionKind.EDIT_FILE: ("edit_file", lambda a: {
                "path": a.target or a.arguments.get("path"),
                "old_text": a.arguments.get("old_text", ""),
                "new_text": a.arguments.get("new_text", "")}),
            ActionKind.CREATE_FILE: ("write_file", lambda a: {
                "path": a.target or a.arguments.get("path"), "content": a.arguments.get("content", "")}),
            ActionKind.DELETE_FILE: ("delete_file", lambda a: {"path": a.target or a.arguments.get("path")}),
            ActionKind.CREATE_DIRECTORY: ("create_directory", lambda a: {"path": a.target or a.arguments.get("path")}),
            ActionKind.DELETE_DIRECTORY: ("delete_file", lambda a: {"path": a.target or a.arguments.get("path")}),
            ActionKind.MOVE_FILE: ("move_file", lambda a: {
                "source": a.target or a.arguments.get("source"),
                "destination": a.arguments.get("destination")}),
            ActionKind.COPY_FILE: ("copy_file", lambda a: {
                "source": a.target or a.arguments.get("source"),
                "destination": a.arguments.get("destination")}),
            ActionKind.SEARCH_FILES: ("search_files", lambda a: {
                "path": a.target or a.arguments.get("path"),
                "pattern": a.arguments.get("pattern", "*"),
                "content": a.arguments.get("content", "")}),
            ActionKind.COMPRESS: ("compress", lambda a: {
                "source": a.target or a.arguments.get("source"),
                "destination": a.arguments.get("destination")}),
            ActionKind.EXTRACT: ("extract", lambda a: {
                "archive": a.target or a.arguments.get("archive"),
                "destination": a.arguments.get("destination")}),
            # Terminal / processes
            ActionKind.RUN_COMMAND: ("shell", lambda a: {
                "command": a.target or a.arguments.get("command", ""),
                "cwd": a.cwd or a.arguments.get("cwd", "")}),
            ActionKind.RUN_POWERSHELL: ("shell", lambda a: {
                "command": a.target or a.arguments.get("command", ""),
                "cwd": a.cwd or a.arguments.get("cwd", "")}),
            ActionKind.RUN_CMD: ("shell", lambda a: {
                "command": a.target or a.arguments.get("command", ""),
                "cwd": a.cwd or a.arguments.get("cwd", "")}),
            ActionKind.START_PROCESS: ("start_process", lambda a: {
                "command": a.target or a.arguments.get("command"),
                "cwd": a.cwd or a.arguments.get("cwd", "")}),
            ActionKind.STOP_PROCESS: ("stop_process", lambda a: {
                "pid": a.arguments.get("pid"), "name": a.target or a.arguments.get("name", "")}),
            ActionKind.LIST_PROCESSES: ("list_processes", lambda a: {"filter": a.arguments.get("filter", "")}),
            ActionKind.INSPECT_PROCESS: ("inspect_process", lambda a: {
                "pid": a.arguments.get("pid"), "name": a.target or a.arguments.get("name", "")}),
            # Browser
            ActionKind.OPEN_URL: ("browser_agent", lambda a: {
                "url": a.target or a.arguments.get("url", ""), "action": "navigate"}),
            ActionKind.BROWSER_NAVIGATE: ("browser_agent", lambda a: {
                "url": a.target or a.arguments.get("url", ""), "action": "navigate"}),
            ActionKind.BROWSER_READ: ("browser_agent", lambda a: {
                "url": a.target or a.arguments.get("url", ""), "action": "extract"}),
            ActionKind.BROWSER_CLICK: ("browser_agent", lambda a: {
                "url": a.target or a.arguments.get("url", ""), "action": "click",
                "selector": a.arguments.get("selector", ""),
                "text": a.arguments.get("text", "")}),
            ActionKind.BROWSER_TYPE: ("browser_agent", lambda a: {
                "url": a.target or a.arguments.get("url", ""), "action": "type",
                "selector": a.arguments.get("selector", ""),
                "value": a.arguments.get("value", "")}),
            ActionKind.BROWSER_SCROLL: ("browser_agent", lambda a: {
                "url": a.target or a.arguments.get("url", ""), "action": "scroll",
                "selector": a.arguments.get("selector", ""),
                "value": a.arguments.get("value", "")}),
            ActionKind.BROWSER_SCREENSHOT: ("browser_agent", lambda a: {
                "url": a.target or a.arguments.get("url", ""), "action": "screenshot",
                "value": a.arguments.get("value", "")}),
            # Vision
            ActionKind.SCREENSHOT: ("screenshot", lambda a: {
                "path": a.arguments.get("path", ""), "monitor": a.arguments.get("monitor", 0)}),
            ActionKind.OCR: ("ocr", lambda a: {"path": a.target or a.arguments.get("path", "")}),
            ActionKind.READ_SCREEN: ("read_screen", lambda a: {"format": a.arguments.get("format", "text")}),
            # Control
            ActionKind.WAIT: ("wait", lambda a: {"seconds": float(a.arguments.get("seconds", 1.0))}),
        }

    # ------------------------------------------------------------------
    async def execute(self, action: ProtocolAction) -> ProtocolResult:
        """Execute one protocol action, enforcing permission + confirmation."""
        started = time.monotonic()
        result = ProtocolResult(id=action.id or action.kind.value, kind=action.kind,
                                ok=False, message="", ts="")

        # Control actions that are purely local meta.
        if action.kind == ActionKind.STOP:
            return self._ok(result, "Emergency stop requested.")
        if action.kind in (ActionKind.ASK_USER,):
            return self._ok(result, "Awaiting user input.")

        # Resolve target tool + args.
        entry = self._map.get(action.kind)
        if entry is None:
            result.ok = False
            result.error = f"No executor registered for action '{action.kind.value}'"
            self.audit.record(action=action.kind.value, target=action.target, result="FAILED",
                              error=result.error)
            return result

        tool_name, mapper = entry
        if tool_name not in self.registry.names():
            result.ok = False
            result.error = f"Required tool '{tool_name}' is not registered"
            self.audit.record(action=action.kind.value, target=action.target, result="FAILED",
                              error=result.error)
            return result

        args = mapper(action)

        # Permission gate ---------------------------------------------------
        decision, risk = self.permission.evaluate(tool_name, args, action=action.kind.value)
        # `decision` is one of the strings allow/grant/confirm/deny.
        decision = decision.value if isinstance(decision, RiskLevel) else str(decision)
        if decision == "deny":
            result.ok = False
            result.error = f"Action '{action.kind.value}' is denied by permission policy"
            self.audit.record(action=action.kind.value, target=action.target, result="DENIED",
                              error="permission denied")
            return result

        if decision == "confirm" and not action.force:
            result.ok = False
            result.needs_confirmation = True
            result.message = f"Confirmation required for '{action.kind.value}' on '{action.target}'"
            self.audit.record(action=action.kind.value, target=action.target, result="WAITING",
                              error="awaiting confirmation")
            return result

        if decision == "grant" and not action.force and not self.permission.has_grant(tool_name):
            result.ok = False
            result.needs_grant = True
            result.message = f"Tool '{tool_name}' requires device grant"
            self.audit.record(action=action.kind.value, target=action.target, result="WAITING",
                              error="awaiting grant")
            return result

        # Execute -----------------------------------------------------------
        try:
            if action.wait_before:
                await _sleep(action.wait_before)
            tool_result = await self.registry.invoke(tool_name, **args)
        except Exception as exc:  # noqa: BLE001 - never crash the executor
            result.ok = False
            result.error = str(exc)
            self.audit.record(action=action.kind.value, target=action.target, result="FAILED",
                              error=str(exc))
            return result

        result.ok = tool_result.ok
        result.output = tool_result.output
        result.error = tool_result.error
        result.data = tool_result.data
        result.exit_code = tool_result.exit_code
        result.duration_ms = int((time.monotonic() - started) * 1000)
        self.audit.record(action=action.kind.value, target=action.target,
                          result="SUCCESS" if tool_result.ok else "FAILED",
                          error=tool_result.error, duration_ms=result.duration_ms,
                          permission=decision if isinstance(decision, str) else decision.value)
        return result

    @staticmethod
    def _ok(result: ProtocolResult, message: str) -> ProtocolResult:
        result.ok = True
        result.message = message
        return result


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
