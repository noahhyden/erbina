"""Coverage for the scope-audit surface: _scope_map, audit_scopes, remove_mcp.

These read Claude Code config (`~/.claude.json` and `<project>/.mcp.json`). We
never touch the real files: `_claude_json` is monkeypatched to return a
controlled dict, the project scope is fed via a temp `.mcp.json`, and
`remove_mcp`'s scope resolution is driven through a monkeypatched `_scope_map`.
Nothing shells out (remove_mcp is only exercised on dry-run / error paths).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import server
from helpers import call_tool


def _fake_claude_json(monkeypatch, data: dict) -> None:
    monkeypatch.setattr(server, "_claude_json", lambda: data)


# --------------------------------------------------------------------------- #
# _claude_json — must degrade to {} rather than raise on a missing/broken file
# --------------------------------------------------------------------------- #
def test_claude_json_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(server.Path, "home", staticmethod(lambda: tmp_path))
    assert server._claude_json() == {}  # no ~/.claude.json present


def test_claude_json_malformed_returns_empty(tmp_path, monkeypatch):
    (tmp_path / ".claude.json").write_text("{ not valid json ")
    monkeypatch.setattr(server.Path, "home", staticmethod(lambda: tmp_path))
    assert server._claude_json() == {}  # parse error swallowed, not raised


def test_claude_json_valid_is_parsed(tmp_path, monkeypatch):
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {"x": {}}}))
    monkeypatch.setattr(server.Path, "home", staticmethod(lambda: tmp_path))
    assert server._claude_json() == {"mcpServers": {"x": {}}}


# --------------------------------------------------------------------------- #
# _scope_map — name -> which scope(s) define it
# --------------------------------------------------------------------------- #
def test_scope_map_aggregates_all_three_scopes(tmp_path, monkeypatch):
    proj = str(Path(tmp_path).resolve())
    _fake_claude_json(monkeypatch, {
        "mcpServers": {"u1": {}},                       # user scope
        "projects": {proj: {"mcpServers": {"l1": {}}}},  # local scope
    })
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"p1": {}}}))  # project

    smap = server._scope_map(project_dir=proj)
    assert smap["u1"] == ["user"]
    assert smap["l1"] == ["local"]
    assert smap["p1"] == ["project"]


def test_scope_map_reports_a_name_in_multiple_scopes(tmp_path, monkeypatch):
    proj = str(Path(tmp_path).resolve())
    _fake_claude_json(monkeypatch, {
        "mcpServers": {"dup": {}},
        "projects": {proj: {"mcpServers": {"dup": {}}}},
    })
    smap = server._scope_map(project_dir=proj)
    assert set(smap["dup"]) == {"user", "local"}


def test_scope_map_tolerates_broken_project_mcp_json(tmp_path, monkeypatch):
    proj = str(Path(tmp_path).resolve())
    _fake_claude_json(monkeypatch, {"mcpServers": {"u1": {}}})
    (tmp_path / ".mcp.json").write_text("{ not valid json ")
    smap = server._scope_map(project_dir=proj)  # must not raise on invalid JSON
    assert smap["u1"] == ["user"]
    # the unreadable project file contributes no entries (swallowed, not fatal)
    assert not any("project" in scopes for scopes in smap.values())


def test_scope_map_tolerates_a_project_dir_that_is_a_regular_file(tmp_path, monkeypatch):
    # a project_dir routed THROUGH a regular file (afile/subdir) => ENOTDIR; Path
    # handles this by returning False from .exists(), so it already degrades.
    _fake_claude_json(monkeypatch, {"mcpServers": {"u1": {}}})
    f = tmp_path / "afile"
    f.write_text("x")
    smap = server._scope_map(project_dir=str(f / "subdir"))
    assert smap["u1"] == ["user"]


# --------------------------------------------------------------------------- #
# FINDING #7 (FIXED): a pathological project_dir used to crash the scope surface
# with a raw exception instead of degrading to the user-scope map — the code
# tolerated a missing/malformed .mcp.json but not an OS-level bad path. Two
# vectors: an over-long path component -> OSError (ENAMETOOLONG) at
# mcp_json.exists(), and an embedded NUL byte -> ValueError at
# Path(project_dir).resolve(). The read is now funneled through the shared
# `_resolve_project_root` / `_project_mcp_names` helpers, which both degrade to
# "no project scope" instead of raising — fixing _scope_map AND audit_scopes
# (which had duplicated the pattern).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_dir", [
    "a" * 300,          # over-long single component -> ENAMETOOLONG at .exists()
    "/tmp/a\x00b",      # embedded NUL -> ValueError from resolve()
    "a" * 5000,         # far past the limit
])
def test_scope_map_tolerates_a_pathological_project_dir(bad_dir, monkeypatch):
    _fake_claude_json(monkeypatch, {"mcpServers": {"u1": {}}})
    smap = server._scope_map(project_dir=bad_dir)
    assert isinstance(smap, dict)
    assert smap.get("u1") == ["user"]  # user scope still reported; project skipped


@pytest.mark.parametrize("bad_dir", ["a" * 300, "/tmp/a\x00b"])
def test_audit_scopes_tolerates_a_pathological_project_dir(bad_dir, monkeypatch):
    # both vectors must NOT crash and must still report the user scope + degrade
    # the project scope to [] (the two vectors fail at different points — NUL at
    # resolve(), the over-long path only at .exists() — but neither is fatal).
    _fake_claude_json(monkeypatch, {"mcpServers": {"u1": {}}})
    out = call_tool("audit_scopes", {"project_dir": bad_dir})
    assert isinstance(out, dict) and "error" not in out
    assert out["scopes"]["user"]["servers"] == ["u1"]   # user scope still reported
    assert out["scopes"]["project"]["servers"] == []    # project degraded, not crashed


def test_audit_scopes_reports_unresolvable_root_for_nul_byte(monkeypatch):
    # a NUL byte fails at resolve() -> proj_root None -> the root is annotated
    _fake_claude_json(monkeypatch, {"mcpServers": {"u1": {}}})
    out = call_tool("audit_scopes", {"project_dir": "/tmp/a\x00b"})
    assert "could not be resolved" in out["project_root"]


def test_resolve_project_root_helper():
    # NUL byte fails at resolve() -> None; an over-long path RESOLVES (resolve()
    # doesn't touch the fs) and only trips later at .exists(); None -> cwd.
    assert server._resolve_project_root("/tmp/a\x00b") is None
    assert isinstance(server._resolve_project_root("a" * 300), Path)
    assert isinstance(server._resolve_project_root(None), Path)


def test_project_mcp_names_tolerates_non_object_json(tmp_path):
    # .mcp.json holding a JSON array (not an object) must degrade to [], not raise
    (tmp_path / ".mcp.json").write_text("[1, 2, 3]")
    assert server._project_mcp_names(Path(tmp_path).resolve()) == []


# --------------------------------------------------------------------------- #
# audit_scopes — the read-only report
# --------------------------------------------------------------------------- #
def test_audit_scopes_buckets_each_scope(tmp_path, monkeypatch):
    proj = str(Path(tmp_path).resolve())
    _fake_claude_json(monkeypatch, {
        "mcpServers": {"u1": {}},
        "projects": {proj: {"mcpServers": {"l1": {}}}},
    })
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"p1": {}}}))

    out = call_tool("audit_scopes", {"project_dir": proj})
    assert out["scopes"]["user"]["servers"] == ["u1"]
    assert out["scopes"]["local"]["servers"] == ["l1"]
    assert out["scopes"]["project"]["servers"] == ["p1"]
    assert out["total_distinct"] == 3


def test_audit_scopes_flags_shadowing(tmp_path, monkeypatch):
    proj = str(Path(tmp_path).resolve())
    _fake_claude_json(monkeypatch, {
        "mcpServers": {"dup": {}},
        "projects": {proj: {"mcpServers": {"dup": {}}}},
    })
    out = call_tool("audit_scopes", {"project_dir": proj})
    assert "dup" in out["shadowed"]
    assert set(out["shadowed"]["dup"]) == {"user", "local"}


def test_audit_scopes_no_shadowing_is_a_clear_message(tmp_path, monkeypatch):
    proj = str(Path(tmp_path).resolve())
    _fake_claude_json(monkeypatch, {"mcpServers": {"only": {}}})
    out = call_tool("audit_scopes", {"project_dir": proj})
    assert out["shadowed"] == "none — no server name is defined in more than one scope"


def test_audit_scopes_flags_name_in_all_three_scopes(tmp_path, monkeypatch):
    proj = str(Path(tmp_path).resolve())
    _fake_claude_json(monkeypatch, {
        "mcpServers": {"tri": {}},                        # user
        "projects": {proj: {"mcpServers": {"tri": {}}}},  # local
    })
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"tri": {}}}))  # project
    out = call_tool("audit_scopes", {"project_dir": proj})
    assert set(out["shadowed"]["tri"]) == {"user", "project", "local"}
    # counted once despite living in three scopes
    assert out["total_distinct"] == 1


def test_audit_scopes_empty_config_reports_nothing(tmp_path, monkeypatch):
    proj = str(Path(tmp_path).resolve())
    _fake_claude_json(monkeypatch, {})
    out = call_tool("audit_scopes", {"project_dir": proj})
    assert out["scopes"]["user"]["servers"] == []
    assert out["scopes"]["project"]["servers"] == []
    assert out["scopes"]["local"]["servers"] == []
    assert out["total_distinct"] == 0
    assert "none" in out["shadowed"]


def test_audit_scopes_states_precedence_and_where(tmp_path, monkeypatch):
    proj = str(Path(tmp_path).resolve())
    _fake_claude_json(monkeypatch, {"mcpServers": {"u": {}}})
    out = call_tool("audit_scopes", {"project_dir": proj})
    # precedence is surfaced so a user can reason about shadowing
    assert "local > project > user" in out["precedence"]
    assert out["project_root"] == proj
    # each scope names WHERE it is stored
    assert ".claude.json" in out["scopes"]["user"]["where"]
    assert ".mcp.json" in out["scopes"]["project"]["where"]
    assert proj in out["scopes"]["local"]["where"]


# --------------------------------------------------------------------------- #
# remove_mcp — scope resolution + guardrails (dry-run / error paths only)
# --------------------------------------------------------------------------- #
def _fake_scope_map(monkeypatch, mapping: dict) -> None:
    monkeypatch.setattr(server, "_scope_map", lambda *a, **k: mapping)


def test_remove_mcp_resolves_single_scope_and_dry_runs(monkeypatch):
    _fake_scope_map(monkeypatch, {"dead": ["user"]})
    out = call_tool("remove_mcp", {"name": "dead", "dry_run": True})
    assert out["scope"] == "user"
    assert out["would_run"] == "claude mcp remove dead -s user"
    assert "nothing was removed" in out["note"].lower()


def test_remove_mcp_errors_when_name_in_multiple_scopes(monkeypatch):
    _fake_scope_map(monkeypatch, {"dup": ["user", "local"]})
    out = call_tool("remove_mcp", {"name": "dup"})
    assert "error" in out
    assert "multiple scopes" in out["error"]


def test_remove_mcp_errors_when_name_absent(monkeypatch):
    _fake_scope_map(monkeypatch, {})
    out = call_tool("remove_mcp", {"name": "ghost"})
    assert "error" in out
    assert "no MCP server named" in out["error"]


def test_remove_mcp_rejects_bad_explicit_scope(monkeypatch):
    _fake_scope_map(monkeypatch, {"x": ["user"]})
    out = call_tool("remove_mcp", {"name": "x", "scope": "bogus", "dry_run": True})
    assert "error" in out
    assert "scope must be one of" in out["error"]


def test_remove_mcp_explicit_scope_skips_resolution(monkeypatch):
    # Even if _scope_map says otherwise, an explicit valid scope is honored.
    _fake_scope_map(monkeypatch, {"x": ["user", "local"]})
    out = call_tool("remove_mcp", {"name": "x", "scope": "local", "dry_run": True})
    assert out["scope"] == "local"
    assert out["would_run"] == "claude mcp remove x -s local"


def test_remove_mcp_shell_quotes_a_name_with_spaces(monkeypatch):
    _fake_scope_map(monkeypatch, {"weird name": ["user"]})
    out = call_tool("remove_mcp", {"name": "weird name", "dry_run": True})
    # shlex.quote must protect the name so it isn't split into two args
    assert "'weird name'" in out["would_run"]


# --------------------------------------------------------------------------- #
# remove_mcp — LIVE (non-dry) exit-code mapping. `_run` is monkeypatched so the
# `claude` CLI is never actually invoked; we only assert how remove_mcp turns a
# process result into its report shape (server.py:1112-1118, previously only the
# dry-run/error paths were exercised).
# --------------------------------------------------------------------------- #
def _fake_run(monkeypatch, exit_code: int):
    captured = {}

    def fake(cmd, *a, **k):
        captured["cmd"] = cmd
        return {"cmd": cmd, "exit": exit_code, "stdout": "", "stderr": ""}

    monkeypatch.setattr(server, "_run", fake)
    return captured


def test_remove_mcp_live_success_reports_removed_ok(monkeypatch):
    _fake_scope_map(monkeypatch, {"dead": ["user"]})
    captured = _fake_run(monkeypatch, 0)
    out = call_tool("remove_mcp", {"name": "dead"})  # dry_run defaults False -> live
    assert captured["cmd"] == "claude mcp remove dead -s user"  # it actually ran the cmd
    assert out["removed"] == "dead"
    assert out["status"] == "ok"
    assert out["scope"] == "user"
    assert out["exit"] == 0  # process result spread into the report


def test_remove_mcp_live_failure_reports_not_removed(monkeypatch):
    _fake_scope_map(monkeypatch, {"dead": ["user"]})
    _fake_run(monkeypatch, 1)
    out = call_tool("remove_mcp", {"name": "dead"})
    # a nonzero exit must NOT claim the server was removed
    assert out["removed"] is None
    assert out["status"] == "failed"
    assert out["exit"] == 1
