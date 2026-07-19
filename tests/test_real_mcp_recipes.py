"""Real mcp-server recipes wired end-to-end against stub CLIs.

The recipes in recipes/*.yaml (kind: mcp-server) wire a server via `claude mcp add
… -- <launch cmd>`. This drives each REAL recipe through bootstrap with a stub
`claude` (records add / answers get) and stub `uvx`/`npx` on PATH, so we assert
the actual recipe's detect→install→configure→verify commands are well-formed and
the exact launch command reaches `claude mcp add` — offline and deterministic.

(The real-bootstrap CI workflow additionally resolves each server PACKAGE against
PyPI/npm; that needs the network and lives there, not here.)
"""
from __future__ import annotations

import os

import pytest

import server
from helpers import call_tool

# (recipe id -> the exact server launch command its configure step must register)
REAL_MCP_RECIPES = {
    "everything": "npx -y @modelcontextprotocol/server-everything",
    "fetch": "uvx mcp-server-fetch",
    "git": "uvx mcp-server-git",
    "memory": "npx -y @modelcontextprotocol/server-memory",
    "sequentialthinking": "npx -y @modelcontextprotocol/server-sequential-thinking",
    "time": "uvx mcp-server-time",
}

_STUB_CLAUDE = """#!/usr/bin/env bash
STORE="${CLAUDE_STUB_STORE}"
mkdir -p "$STORE"
if [ "$1" = "mcp" ] && [ "$2" = "add" ]; then echo "$*" > "$STORE/$3"; exit 0; fi
if [ "$1" = "mcp" ] && [ "$2" = "get" ]; then [ -f "$STORE/$3" ] && exit 0 || exit 1; fi
exit 0
"""


@pytest.fixture
def stub_env(tmp_path, monkeypatch):
    """Put stub `claude`, `uvx`, `npx` on PATH; return the claude add-store dir."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    store = tmp_path / "store"
    (bindir / "claude").write_text(_STUB_CLAUDE)
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
    # the stub received the exact wiring command, with ${scope} substituted and the
    # recipe's real launch command intact
    recorded = (stub_env / rid).read_text().strip()
    assert recorded == f"mcp add {rid} --scope project -- {launch}"


def test_all_registry_mcp_servers_are_covered():
    # every kind: mcp-server recipe on disk must appear above, so a new one can't
    # ship without a real-wiring assertion for its launch command.
    on_disk = {rid for rid in server._recipe_ids()
               if server._load_recipe(rid).get("kind") == "mcp-server"}
    assert on_disk == set(REAL_MCP_RECIPES), (
        f"uncovered: {on_disk - set(REAL_MCP_RECIPES)}; stale: {set(REAL_MCP_RECIPES) - on_disk}"
    )
