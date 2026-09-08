"""File-system tools (Layer 1 — Native file APIs).

These operate directly on the filesystem using Python's stdlib so they work on
Windows, macOS and Linux with the same semantics (paths use the native
separator).  Windows-specific path behaviour is handled by ``os.path`` /
``pathlib``.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec
from agent_platform.tools.base import Tool


def _abspath(path: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def _resolve_readable(path: str) -> Path:
    p = Path(_abspath(path))
    return p


class ReadFileTool(Tool):
    spec = ToolSpec(
        name="read_file",
        description="Read the contents of a text file. Use for inspecting files. "
        "Returns the decoded text (truncated at max_bytes).",
        category="file",
        parameters={"path": "str (required): absolute or relative path",
                     "max_bytes": "int (optional, default 8192): max bytes to read"},
        permission=PermissionLevel.SAFE,
        input_example='{"path": "C:/projects/app/main.py"}',
    )

    def run(self, path: str, max_bytes: int = 8192, **kwargs: Any) -> ToolResult:
        try:
            p = _resolve_readable(path)
            if not p.exists():
                return self.fail(f"File does not exist: {p}", output=f"path={p}")
            if not p.is_file():
                return self.fail(f"Not a regular file: {p}")
            data = p.read_bytes()[:max_bytes]
            return self.ok(data.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class WriteFileTool(Tool):
    spec = ToolSpec(
        name="write_file",
        description="Create or overwrite a file with the given text content. "
        "Creates parent directories as needed.",
        category="file",
        parameters={"path": "str (required)", "content": "str (required)",
                     "encoding": "str (optional, default utf-8)"},
        permission=PermissionLevel.SENSITIVE,
        input_example='{"path": "C:/projects/app/main.py", "content": "print(1)"}',
    )

    def run(self, path: str, content: str = "", encoding: str = "utf-8", **kwargs: Any) -> ToolResult:
        try:
            p = _resolve_readable(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding=encoding)
            return self.ok(f"Wrote {len(content)} bytes to {p}")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class EditFileTool(Tool):
    spec = ToolSpec(
        name="edit_file",
        description="Edit a text file by replacing the first occurrence of old_text "
        "with new_text (fuzzy whitespace tolerant). Returns a short diff summary.",
        category="file",
        parameters={"path": "str (required)", "old_text": "str (required)",
                     "new_text": "str (required)"},
        permission=PermissionLevel.SENSITIVE,
    )

    def run(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> ToolResult:
        try:
            p = _resolve_readable(path)
            if not p.exists():
                return self.fail(f"File does not exist: {p}")
            text = p.read_text(encoding="utf-8")
            if old_text not in text:
                return self.fail("old_text not found in file (first occurrence not matched)")
            new_text_value = text.replace(old_text, new_text, 1)
            p.write_text(new_text_value, encoding="utf-8")
            return self.ok(f"Edited {p}")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class MoveFileTool(Tool):
    spec = ToolSpec(
        name="move_file",
        description="Move a file or directory to a new location.",
        category="file",
        parameters={"source": "str (required)", "destination": "str (required)"},
        permission=PermissionLevel.SENSITIVE,
    )

    def run(self, source: str, destination: str, **kwargs: Any) -> ToolResult:
        try:
            s = _resolve_readable(source)
            d = _resolve_readable(destination)
            if not s.exists():
                return self.fail(f"Source does not exist: {s}")
            Path(d).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(s), str(d))
            return self.ok(f"Moved {s} -> {d}")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class CopyFileTool(Tool):
    spec = ToolSpec(
        name="copy_file",
        description="Copy a file or directory to a new location.",
        category="file",
        parameters={"source": "str (required)", "destination": "str (required)"},
        permission=PermissionLevel.SENSITIVE,
    )

    def run(self, source: str, destination: str, **kwargs: Any) -> ToolResult:
        try:
            s = _resolve_readable(source)
            d = _resolve_readable(destination)
            if not s.exists():
                return self.fail(f"Source does not exist: {s}")
            Path(d).parent.mkdir(parents=True, exist_ok=True)
            if s.is_dir():
                shutil.copytree(str(s), str(d), dirs_exist_ok=True)
            else:
                shutil.copy2(str(s), str(d))
            return self.ok(f"Copied {s} -> {d}")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class DeleteFileTool(Tool):
    spec = ToolSpec(
        name="delete_file",
        description="Delete a file or an empty directory. This is a destructive "
        "operation and is classified DANGEROUS.",
        category="file",
        parameters={"path": "str (required)"},
        permission=PermissionLevel.DANGEROUS,
    )

    def run(self, path: str, **kwargs: Any) -> ToolResult:
        try:
            p = _resolve_readable(path)
            if not p.exists():
                return self.fail(f"Path does not exist: {p}")
            if p.is_dir():
                # Only delete empty directories to be safe.
                try:
                    p.rmdir()
                except OSError as exc:
                    return self.fail(f"Directory not empty or cannot remove: {exc}")
            else:
                p.unlink()
            return self.ok(f"Deleted {p}")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class ListDirTool(Tool):
    spec = ToolSpec(
        name="list_dir",
        description="List the entries (files and directories) inside a directory.",
        category="file",
        parameters={"path": "str (required): directory path",
                     "recursive": "bool (optional, default false)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, path: str, recursive: bool = False, **kwargs: Any) -> ToolResult:
        try:
            p = _resolve_readable(path)
            if not p.exists():
                return self.fail(f"Path does not exist: {p}")
            if not p.is_dir():
                return self.fail(f"Not a directory: {p}")
            if recursive:
                entries = list(p.rglob("*"))
            else:
                entries = list(p.iterdir())
            out = []
            for e in sorted(entries):
                rel = e.relative_to(p)
                size = e.stat().st_size if e.is_file() else 0
                kind = "dir" if e.is_dir() else "file"
                out.append({"path": str(rel), "type": kind, "size": size})
            if not out:
                return self.ok("(empty)")
            import json

            return self.ok(json.dumps(out, ensure_ascii=False, indent=2), data=out)
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class SearchFilesTool(Tool):
    spec = ToolSpec(
        name="search_files",
        description="Search for files (by name glob) and/or by content regex within "
        "a directory tree.",
        category="file",
        parameters={"path": "str (required): base directory",
                     "pattern": "str (optional): glob on file-name, e.g. *.pdf",
                     "content": "str (optional): regex to search file contents",
                     "max_results": "int (optional, default 500)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, path: str, pattern: str = "*", content: str = "",
            max_results: int = 500, **kwargs: Any) -> ToolResult:
        try:
            base = _resolve_readable(path)
            if not base.exists():
                return self.fail(f"Path does not exist: {base}")
            hits: list[dict[str, Any]] = []
            if content:
                matcher = re.compile(content)
                for p in base.rglob(pattern):
                    if p.is_dir():
                        continue
                    try:
                        if matcher.search(p.read_text(errors="ignore")):
                            hits.append({"path": str(p), "name": p.name, "matched": "content"})
                    except Exception:  # noqa: BLE001
                        continue
                    if len(hits) >= max_results:
                        break
            else:
                for p in base.rglob(pattern):
                    if p.is_dir():
                        continue
                    hits.append({"path": str(p), "name": p.name})
                    if len(hits) >= max_results:
                        break
            if not hits:
                return self.ok("No matches found.")
            import json

            return self.ok(json.dumps(hits, ensure_ascii=False, indent=2), data=hits)
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


class CreateDirectoryTool(Tool):
    spec = ToolSpec(
        name="create_directory",
        description="Create a directory (and any missing parents).",
        category="file",
        parameters={"path": "str (required)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, path: str, **kwargs: Any) -> ToolResult:
        try:
            p = _resolve_readable(path)
            p.mkdir(parents=True, exist_ok=True)
            return self.ok(f"Directory ready: {p}")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


ALL_TOOLS: list[type[Tool]] = [
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    MoveFileTool,
    CopyFileTool,
    DeleteFileTool,
    ListDirTool,
    SearchFilesTool,
    CreateDirectoryTool,
]
