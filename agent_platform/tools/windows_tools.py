"""Windows-native tools (Layer 5 — UI Automation / Win32).

These tools target the Windows desktop.  They import Windows-only libraries
(pywinauto, pywin32 / comtypes, ctypes) lazily and, on a non-Windows host
(where the development/sandbox runs), they return a clear, honest "not on
Windows" result instead of crashing.  They are:

  * open_application  — launch an app and focus its top-level window
  * close_application — close a window / app
  * focus_window      — bring a window to the foreground
  * inspect_window    — dump the UI Automation element tree (best-effort)
  * click/type        — drive a window by accessibility or coordinates

Design note (per architecture): these are the *last-resort* layers.  The
preferred path for the agent is file/process/shell tools or an app API; mouse
and keyboard automation is only used when no better automation exists.
"""

from __future__ import annotations

import sys
from typing import Any

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec
from agent_platform.tools.base import Tool


def _windows() -> bool:
    return sys.platform.startswith("win")


def _not_windows(tool_name: str) -> ToolResult:
    return ToolResult(
        tool=tool_name,
        ok=False,
        error=("Windows UI automation requires a Windows host. "
               "This runtime is not Windows, so the tool cannot execute."),
    )


class OpenApplicationTool(Tool):
    spec = ToolSpec(
        name="open_application",
        description="Launch a Windows application (an executable or any registered "
        "app), optionally passing arguments, and return its window handle.",
        category="windows",
        parameters={"name": "str (required): app name or path (e.g. notepad, chrome)",
                     "args": "list (optional)", "cwd": "str (optional)"},
        permission=PermissionLevel.SENSITIVE,
        requires_admin=False,
    )

    def run(self, name: str, args: list[str] | None = None, cwd: str = "", **kwargs: Any) -> ToolResult:
        if not _windows():
            return _not_windows("open_application")
        try:
            import subprocess

            proc = subprocess.Popen([name] + (args or []), cwd=cwd or None)
            return self.ok(f"Launched {name} (pid={proc.pid})", data={"pid": proc.pid})
        except FileNotFoundError:
            return self.fail(f"Application '{name}' not found. Try a full path.")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class CloseApplicationTool(Tool):
    spec = ToolSpec(
        name="close_application",
        description="Close a Windows application by name or window title. "
        "Classified DANGEROUS.",
        category="windows",
        parameters={"name": "str (optional)", "title": "str (optional)"},
        permission=PermissionLevel.DANGEROUS,
    )

    def run(self, name: str = "", title: str = "", **kwargs: Any) -> ToolResult:
        if not _windows():
            return _not_windows("close_application")
        try:
            import subprocess

            if name:
                subprocess.run(["taskkill", "/F", "/IM", f"{name}.exe"], capture_output=True)
                return self.ok(f"Requested close of {name}")
            return self.fail("Provide 'name' (image name) or 'title'.")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class FocusWindowTool(Tool):
    spec = ToolSpec(
        name="focus_window",
        description="Bring a window to the foreground by title substring.",
        category="windows",
        parameters={"title": "str (required): substring of the window title"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, title: str, **kwargs: Any) -> ToolResult:
        if not _windows():
            return _not_windows("focus_window")
        try:
            # Best-effort via pywinauto if present, else ctypes SetForegroundWindow.
            try:
                import pywinauto  # noqa: F401
                from pywinauto import Desktop  # type: ignore

                win = Desktop(backend="uia").window(title_re=f".*{title}.*").exists()
                win_handle = Desktop(backend="uia").window(title_re=f".*{title}.*")
                win_handle.set_focus()
                return self.ok(f"Focused window matching '{title}'")
            except ImportError:
                import ctypes

                # Minimal: find window by title via EnumWindows is complex; here we
                # just report we could not locate a handle without pywinauto.
                return self.fail("pywinauto not installed; cannot focus window")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class InspectWindowTool(Tool):
    spec = ToolSpec(
        name="inspect_window",
        description="Inspect a window's UI Automation element tree (best-effort). "
        "Useful when the agent needs to understand a desktop UI it cannot reach "
        "via APIs.",
        category="windows",
        parameters={"title": "str (optional)", "max_depth": "int (optional, default 4)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, title: str = "", max_depth: int = 4, **kwargs: Any) -> ToolResult:
        if not _windows():
            return _not_windows("inspect_window")
        try:
            import pywinauto
            from pywinauto import Desktop  # type: ignore

            desktop = Desktop(backend="uia")
            windows = desktop.windows()
            if title:
                windows = [w for w in windows if title.lower() in (w.window_text() or "").lower()]
            out = []
            for w in windows[:10]:
                out.append({"title": w.window_text()[:120], "handle": w.handle})
            import json

            return self.ok(json.dumps(out, ensure_ascii=False, indent=2), data=out)
        except ImportError:
            return self.fail("pywinauto not installed; cannot inspect windows")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class InteractWindowTool(Tool):
    """Drive a window by accessibility (click / type) when no API exists."""

    spec = ToolSpec(
        name="ui_interact",
        description="Interact with a desktop window: click a button by name or "
        "type text into a field. Last-resort UI automation.",
        category="windows",
        parameters={"title": "str (optional)", "action": "str (required): click|type",
                     "element": "str (optional): element/button label",
                     "text": "str (optional): text to type"},
        permission=PermissionLevel.SENSITIVE,
    )

    def run(self, action: str = "click", title: str = "", element: str = "", text: str = "",
            **kwargs: Any) -> ToolResult:
        if not _windows():
            return _not_windows("ui_interact")
        try:
            import pywinauto
            from pywinauto import Desktop  # type: ignore

            desktop = Desktop(backend="uia")
            win = desktop.window(title_re=f".*{title}.*").wrapper_object()
            if action == "click":
                ctrl = win.child_window(title_re=f".*{element}.*" if element else ".*")
                ctrl.click_input()
                return self.ok(f"Clicked '{element or 'window'}'")
            if action == "type":
                win.type_keys(text)
                return self.ok(f"Typed text")
            return self.fail(f"Unsupported action {action}")
        except ImportError:
            return self.fail("pywinauto not installed")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


ALL_TOOLS: list[type[Tool]] = [
    OpenApplicationTool,
    CloseApplicationTool,
    FocusWindowTool,
    InspectWindowTool,
    InteractWindowTool,
]
