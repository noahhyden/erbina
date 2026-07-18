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
