"""Behavioral coverage for find_dead_mcps — the health-check-and-triage tool.

Driven by monkeypatching the two sources it composes: `_parse_mcp_list` (live
`claude mcp list` status) and `_scope_map` (which scope each name lives in). No
subprocess, no real config. The contract: split servers into alive/dead, annotate
each dead one with the scope(s) that removal will need, and hint the confirm-
then-remove workflow.
"""
from __future__ import annotations

import server
from helpers import call_tool


def _patch(monkeypatch, servers, scopes):
    monkeypatch.setattr(server, "_parse_mcp_list", lambda project_dir=None: servers)
    monkeypatch.setattr(server, "_scope_map", lambda project_dir=None: scopes)


def test_splits_alive_and_dead(monkeypatch):
    _patch(
        monkeypatch,
        [
            {"name": "good", "connected": True, "command": "uvx a"},
            {"name": "dead1", "connected": False, "command": "uvx b"},
        ],
        {"good": ["user"], "dead1": ["local"]},
    )
    out = call_tool("find_dead_mcps", {})
    assert out["checked"] == 2
    assert out["alive"] == ["good"]
    assert [d["name"] for d in out["dead"]] == ["dead1"]


def test_dead_entries_are_annotated_with_scopes(monkeypatch):
    _patch(
        monkeypatch,
        [{"name": "dead2", "connected": False, "command": "uvx c"}],
        {"dead2": ["user", "project"]},
    )
    out = call_tool("find_dead_mcps", {})
    assert out["dead"][0]["scopes"] == ["user", "project"]


def test_dead_server_absent_from_scope_map_gets_empty_scopes(monkeypatch):
    # If a listed server isn't found in any scope, annotate [] rather than crash;
    # remove_mcp will then report it can't be located.
    _patch(monkeypatch, [{"name": "orphan", "connected": False, "command": "x"}], {})
    out = call_tool("find_dead_mcps", {})
    assert out["dead"][0]["scopes"] == []


def test_all_alive_gives_reassuring_hint_and_no_dead(monkeypatch):
    _patch(
        monkeypatch,
        [{"name": "good", "connected": True, "command": "x"}],
        {"good": ["user"]},
    )
    out = call_tool("find_dead_mcps", {})
    assert out["dead"] == []
    assert "No dead servers" in out["hint"]


def test_dead_present_hint_points_at_remove_mcp(monkeypatch):
    _patch(monkeypatch, [{"name": "d", "connected": False, "command": "x"}], {"d": ["user"]})
    out = call_tool("find_dead_mcps", {})
    assert "remove_mcp" in out["hint"]
    assert "confirm" in out["hint"].lower()


def test_empty_server_list(monkeypatch):
    _patch(monkeypatch, [], {})
    out = call_tool("find_dead_mcps", {})
    assert out["checked"] == 0
    assert out["alive"] == []
    assert out["dead"] == []
    assert "No dead servers" in out["hint"]
