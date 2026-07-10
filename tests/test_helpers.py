"""Unit tests for the server's pure-ish helpers: _subst, _load_recipe traversal
guard, and the deliberately brittle _parse_mcp_list (documents issue #3).
"""
from __future__ import annotations

import pytest

import server


# --------------------------------------------------------------------------- #
# _subst
# --------------------------------------------------------------------------- #
def test_subst_expands_scope():
    out = server._subst("claude mcp add x --scope ${scope}", "project", None)
    assert out == "claude mcp add x --scope project"


def test_subst_expands_project_dir():
    out = server._subst("cd ${project_dir} && go", "user", "/repos/thing")
    assert out == "cd /repos/thing && go"


def test_subst_missing_project_dir_falls_back_to_dot():
    # The documented fallback (per the code) is '.' when project_dir is None.
    out = server._subst("run in ${project_dir}", "user", None)
    assert out == "run in ."


def test_subst_expands_both_placeholders_together():
    out = server._subst(
        "claude mcp add f --scope ${scope} in ${project_dir}", "local", "/tmp/p"
    )
    assert out == "claude mcp add f --scope local in /tmp/p"


def test_subst_none_command_returns_empty_string():
    assert server._subst(None, "user", None) == ""


# --------------------------------------------------------------------------- #
# _load_recipe path-traversal guard (helper level)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_id", ["../server", "../../etc/passwd", "/etc/passwd", "..%2f..%2fetc"])
def test_load_recipe_rejects_traversal(bad_id):
    # Path(recipe_id).name strips any directory component, so a traversal id
    # collapses to a basename that has no matching <name>.yaml -> FileNotFoundError.
    with pytest.raises(FileNotFoundError) as exc:
        server._load_recipe(bad_id)
    # The error names the missing recipe, not a system file's contents.
    assert "no recipe" in str(exc.value).lower()


def test_load_recipe_loads_real_recipe():
    r = server._load_recipe("ataegina")
    assert r["id"] == "ataegina"
    assert r["kind"] == "cli-tool"


# --------------------------------------------------------------------------- #
# _parse_mcp_list — the brittle parser (issue #3). We drive it by monkeypatching
# server._run so no real `claude mcp list` (or any subprocess) is invoked.
# --------------------------------------------------------------------------- #
# A realistic multi-line `claude mcp list` capture: a header line, one healthy
# server, one failed server, ANSI colour codes, and a trailing blank line.
SAMPLE_MCP_LIST = (
    "Checking MCP server health...\n"
    "\n"
    "erbina: uv run --script /Users/x/erbina/server.py - \x1b[32m✔ Connected\x1b[0m\n"
    "ataegina: uvx ataegina-mcp - \x1b[31m✘ Failed to connect\x1b[0m\n"
    "\n"
)


def test_parse_mcp_list_classifies_connected_and_failed(monkeypatch):
    def fake_run(cmd, cwd=None, timeout=600):  # noqa: ARG001
        assert cmd == "claude mcp list"  # confirm it's the health-check command
        return {"cmd": cmd, "exit": 0, "stdout": SAMPLE_MCP_LIST, "stderr": ""}

    monkeypatch.setattr(server, "_run", fake_run)

    servers = server._parse_mcp_list()
    by_name = {s["name"]: s for s in servers}

    # Exactly the two status lines are parsed — header/blank lines are dropped.
    assert set(by_name) == {"erbina", "ataegina"}
    assert by_name["erbina"]["connected"] is True
    assert by_name["ataegina"]["connected"] is False
    # ANSI codes are stripped from the surfaced command.
    assert "\x1b" not in by_name["erbina"]["command"]
    assert by_name["erbina"]["command"] == "uv run --script /Users/x/erbina/server.py"


def test_parse_mcp_list_ignores_lines_without_status(monkeypatch):
    def fake_run(cmd, cwd=None, timeout=600):  # noqa: ARG001
        return {
            "cmd": cmd,
            "exit": 0,
            # a line with a colon but no ✔/✘/Connected/Failed marker
            "stdout": "Some heading: with a colon but no status marker\n",
            "stderr": "",
        }

    monkeypatch.setattr(server, "_run", fake_run)
    assert server._parse_mcp_list() == []
