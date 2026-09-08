"""Unified Action Protocol.

Arena (the brain) produces high-level intents; the Local Agent translates them
into a typed :class:`ProtocolAction` and executes them via the Action Executor.
The protocol is deliberately small and **extensible**: add a new enum member +
a handler in the executor and it is available everywhere (no core changes).

This is the "nervous system" vocabulary shared by the browser extension, the
MCP bridge, the WebSocket bridge, the chat GUI and the local executor.
"""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


class ActionKind(str, enum.Enum):
    # --- Applications ---------------------------------------------------
    OPEN_APPLICATION = "open_application"
    CLOSE_APPLICATION = "close_application"
    # --- Desktop / input ------------------------------------------------
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    MOVE_MOUSE = "move_mouse"
    DRAG = "drag"
    SCROLL = "scroll"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    HOTKEY = "hotkey"
    # --- Vision ---------------------------------------------------------
    SCREENSHOT = "screenshot"
    OCR = "ocr"
    READ_SCREEN = "read_screen"
    # --- Browser --------------------------------------------------------
    OPEN_URL = "open_url"
    BROWSER_NAVIGATE = "browser_navigate"
    BROWSER_CLICK = "browser_click"
    BROWSER_TYPE = "browser_type"
    BROWSER_SCROLL = "browser_scroll"
    BROWSER_READ = "browser_read"
    BROWSER_SCREENSHOT = "browser_screenshot"
    # --- Filesystem -----------------------------------------------------
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    CREATE_FILE = "create_file"
    DELETE_FILE = "delete_file"
    CREATE_DIRECTORY = "create_directory"
    DELETE_DIRECTORY = "delete_directory"
    MOVE_FILE = "move_file"
    COPY_FILE = "copy_file"
    SEARCH_FILES = "search_files"
    COMPRESS = "compress"
    EXTRACT = "extract"
    # --- Terminal / processes -------------------------------------------
    RUN_COMMAND = "run_command"
    RUN_POWERSHELL = "run_powershell"
    RUN_CMD = "run_cmd"
    START_PROCESS = "start_process"
    STOP_PROCESS = "stop_process"
    LIST_PROCESSES = "list_processes"
    INSPECT_PROCESS = "inspect_process"
    # --- Control --------------------------------------------------------
    WAIT = "wait"
    VERIFY = "verify"
    ASK_USER = "ask_user"
    STOP = "stop"


class ProtocolAction(BaseModel):
    """A single, typed instruction from the brain to the local agent."""

    id: str = Field(default="")
    kind: ActionKind
    target: str = ""                    # app name, url, file path, element label...
    arguments: dict[str, Any] = Field(default_factory=dict)
    cwd: str = ""
    timeout: float | None = None
    verification: str = ""              # what proves success
    wait_before: float = 0.0
    wait_after: float = 0.0
    force: bool = False                 # true if user already approved


class ProtocolResult(BaseModel):
    id: str
    kind: ActionKind
    ok: bool
    output: str = ""
    error: str | None = None
    data: Any = None
    exit_code: int | None = None
    duration_ms: int | None = None
    needs_grant: bool = False
    needs_confirmation: bool = False
    confirmed: bool = False
    message: str = ""
    ts: str = ""


# A compact registry of all action kinds (for the GUI / extension to discover).
def all_action_kinds() -> list[dict[str, str]]:
    return [{"kind": a.value, "name": a.name} for a in ActionKind]
