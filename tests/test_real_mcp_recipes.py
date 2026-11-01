"""Drives each REAL kind: mcp-server recipe through bootstrap with stub `claude`/`uvx`/`npx` on PATH, offline; package resolution lives in the real-bootstrap CI."""
from __future__ import annotations

import os

import pytest

import server
from helpers import call_tool
from stubs import write_claude_stub

# (recipe id -> the exact server launch command its configure step must register)
REAL_MCP_RECIPES = {
    "context7": "npx -y @upstash/context7-mcp",
    "everything": "npx -y @modelcontextprotocol/server-everything",
    "fetch": "uvx mcp-server-fetch",
    "filesystem": "npx -y @modelcontextprotocol/server-filesystem ${project_dir}",
    "git": "uvx mcp-server-git",
    "memory": "npx -y @modelcontextprotocol/server-memory",
    "playwright-mcp": "npx -y @playwright/mcp",
    "sequentialthinking": "npx -y @modelcontextprotocol/server-sequential-thinking",
    "time": "uvx mcp-server-time",
}


@pytest.fixture
def stub_env(tmp_path, monkeypatch):
    """Put stub `claude`, `uvx`, `npx` on PATH; return the claude add-store dir."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    store = tmp_path / "store"
    write_claude_stub(bindir)
    for name in ("uvx", "npx"):
        (bindir / name).write_text("#!/usr/bin/env bash\nexit 0\n")
    for f in bindir.iterdir():
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CLAUDE_STUB_STORE", str(store))
    return store


@pytest.mark.parametrize("rid,launch", sorted(REAL_MCP_RECIPES.items()))
def test_real_mcp_recipe_wires_and_verifies(rid, launch, stub_env, tmp_path, monkeypatch):
    # skip if the recipe isn't in the registry (keeps the test honest if one is renamed)
    if rid not in server._recipe_ids():
        pytest.skip(f"{rid} not in registry")
    monkeypatch.setattr(server, "STATE_DIR", tmp_path / ".erbina")
    proj = str((tmp_path / "proj").resolve())
    (tmp_path / "proj").mkdir()

    report = call_tool("bootstrap", {"recipe_id": rid, "scope": "project", "project_dir": proj})

    assert report["ok"] is True, report
    assert report["phases"]["configure"]["steps"][0]["status"] == "ok"
    assert report["phases"]["verify"][0]["status"] == "ok"
    # The stub received the exact wiring command, ${scope} substituted and the recipe's launch command intact.
    recorded = (stub_env / rid).read_text().strip()
    # A launch may reference ${project_dir} (filesystem's allowed dir); it is substituted with the resolved project dir.
    assert recorded == f"mcp add {rid} --scope project -- {launch.replace('${project_dir}', proj)}"


def test_all_registry_mcp_servers_are_covered():
    # Every mcp-server recipe on disk must appear above, so a new one cannot ship without a real-wiring assertion.
    on_disk = {rid for rid in server._recipe_ids()
               if server._load_recipe(rid).get("kind") == "mcp-server"}
    assert on_disk == set(REAL_MCP_RECIPES), (
        f"uncovered: {on_disk - set(REAL_MCP_RECIPES)}; stale: {set(REAL_MCP_RECIPES) - on_disk}"
    )
