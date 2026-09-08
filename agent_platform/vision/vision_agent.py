"""Vision Agent — the agent's "eyes".

A single screen capture → preprocess → OCR → summarize pipeline, exposed as
tools (`screenshot`, `ocr`, `read_screen`) so the agent can see the desktop or a
browser and act on what it actually sees rather than assuming.

Screenshot capture uses ``mss`` (cross-platform) or, on Windows, the native
desktop; OCR goes through the pluggable :class:`OCRRegistry`.  If OCR is
unavailable the tools return an honest LIMITATION (never a fake result).
"""

from __future__ import annotations

import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec
from agent_platform.tools.base import Tool
from agent_platform.vision.ocr import get_ocr_registry


def capture_screen(path: str = "", monitor: int = 0) -> dict[str, Any]:
    """Capture the desktop to a PNG.  Returns {path, size}."""
    import mss

    with mss.MSS() as sct:
        mon = sct.monitors[monitor if monitor < len(sct.monitors) else 0]
        shot = sct.grab(mon)
        if not path:
            path = str(Path(tempfile.gettempdir()) / f"agent_shot_{int(time.time())}.png")
        from PIL import Image

        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        img.save(path)
        return {"path": path, "width": shot.size[0], "height": shot.size[1]}


def preprocess(path: str) -> str:
    """Light preprocessing to improve OCR: grayscale + upscale."""
    from PIL import Image

    img = Image.open(path).convert("L")
    w, h = img.size
    img = img.resize((min(int(w * 1.5), 4000), min(int(h * 1.5), 4000)))
    out = Path(path).with_name(Path(path).stem + "_pre.png")
    img.save(out)
    return str(out)


class ScreenshotTool(Tool):
    spec = ToolSpec(
        name="screenshot",
        description="Capture the current desktop screen to a PNG. Returns the path.",
        category="vision",
        parameters={"path": "str (optional): save location", "monitor": "int (optional, default 0)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, path: str = "", monitor: int = 0, **kwargs: Any) -> ToolResult:
        try:
            info = capture_screen(path, monitor)
            return self.ok(f"Screenshot saved to {info['path']} ({info['width']}x{info['height']})",
                           data=info)
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class OCRTool(Tool):
    spec = ToolSpec(
        name="ocr",
        description="Read the text from an image file using the best available OCR.",
        category="vision",
        parameters={"path": "str (required): image path"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, path: str = "", **kwargs: Any) -> ToolResult:
        try:
            reg = get_ocr_registry()
            text, provider = reg.read_text(path)
            return self.ok(text, data={"provider": provider})
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class ReadScreenTool(Tool):
    spec = ToolSpec(
        name="read_screen",
        description="Capture the screen and read its text (screenshot + OCR). "
        "Use to understand the current desktop state before acting.",
        category="vision",
        parameters={"format": "str (optional, default text)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, format: str = "text", **kwargs: Any) -> ToolResult:
        try:
            shot = capture_screen()
            reg = get_ocr_registry()
            text, provider = reg.read_text(shot["path"])
            if format == "json":
                import json

                return self.ok(json.dumps({"screen": text, "provider": provider}, ensure_ascii=False),
                               data={"screen": text, "provider": provider})
            return self.ok(text, data={"provider": provider, "path": shot["path"]})
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


ALL_TOOLS: list[type[Tool]] = [ScreenshotTool, OCRTool, ReadScreenTool]
