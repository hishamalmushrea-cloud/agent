"""Tests for the tool system: registry discovery + core file/shell tools."""

from __future__ import annotations

import asyncio
import os
import tempfile

from agent_platform.models.schemas import PermissionLevel


def invoke(registry, name, **kwargs):
    return asyncio.run(registry.invoke(name, **kwargs))


def test_registry_discovers_tools(registry):
    names = registry.names()
    assert "read_file" in names
    assert "write_file" in names
    assert "shell" in names
    assert "list_dir" in names
    cats = registry.categories()
    assert "file" in cats
    assert "shell" in cats


def test_registry_spec_has_metadata(registry):
    spec = registry.get_spec("delete_file")
    assert spec is not None
    assert spec.permission == PermissionLevel.DANGEROUS
    assert spec.category == "file"
    assert "path" in spec.parameters


def test_write_read_list(registry):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "hello.txt")
        assert invoke(registry, "write_file", path=path, content="hi there").ok
        res = invoke(registry, "read_file", path=path)
        assert res.ok and "hi there" in res.output
        res = invoke(registry, "list_dir", path=d)
        assert res.ok and "hello.txt" in res.output
        res = invoke(registry, "create_directory", path=os.path.join(d, "sub"))
        assert res.ok
        assert os.path.isdir(os.path.join(d, "sub"))


def test_search_files(registry):
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "a"))
        with open(os.path.join(d, "a", "report.txt"), "w") as f:
            f.write("secret keyword here")
        res = invoke(registry, "search_files", path=d, content="secret")
        assert res.ok
        assert "report.txt" in res.output


def test_shell_tool(registry):
    res = invoke(registry, "shell", command="echo agent_ok", timeout=10)
    assert res.ok
    assert res.exit_code == 0
    assert "agent_ok" in res.output


def test_unknown_tool_returns_error(registry):
    res = invoke(registry, "does_not_exist")
    assert not res.ok
