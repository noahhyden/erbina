"""Behavioral tests for `doctor`, which re-runs detect and verify on recorded tools (CLI by detect/verify, mcp-server by connection) and classifies healthy / missing / broken, read-only."""
from __future__ import annotations

import server
from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, mcp_recipe, registry


def _record(rid, kind="cli-tool"):
    server._record_tool(rid, kind=kind, installed_version="1.0.0", install_method="m")


# nothing recorded
def test_empty_state_reports_nothing_to_check():
    with registry(cli_recipe("t")):
        out = call_tool("doctor", {})
    assert out["checked"] == 0
    assert out["healthy"] == []
    assert out["problems"] == []


# healthy / missing / broken classification
def test_healthy_tool_is_reported_healthy():
    r = cli_recipe("t", detect={"command": TRUE}, verify=[{"command": TRUE}])
    with registry(r):
        _record("t")
        out = call_tool("doctor", {})
    assert out["checked"] == 1
    assert out["healthy"] == ["t"]
    assert out["problems"] == []


def test_missing_tool_is_flagged():
    # recorded, but detect now fails -> was installed, now gone
    r = cli_recipe("t", detect={"command": FALSE}, verify=[{"command": TRUE}])
    with registry(r):
        _record("t")
        out = call_tool("doctor", {})
    prob = out["problems"][0]
    assert prob["recipe"] == "t"
    assert prob["status"] == "missing"
    assert out["healthy"] == []


def test_broken_tool_is_flagged():
    # present (detect ok) but verify fails -> installed but doesn't run correctly
    r = cli_recipe("t", detect={"command": TRUE}, verify=[{"command": FALSE}])
    with registry(r):
        _record("t")
        out = call_tool("doctor", {})
    prob = out["problems"][0]
    assert prob["recipe"] == "t"
    assert prob["status"] == "broken"


def test_verify_not_run_when_tool_is_missing():
    # A missing tool must NOT be probed with verify, so its status is missing, not broken, even if verify would fail.
    r = cli_recipe("t", detect={"command": FALSE}, verify=[{"command": FALSE}])
    with registry(r):
        _record("t")
        out = call_tool("doctor", {})
    assert out["problems"][0]["status"] == "missing"


# scope of what's checked
def test_only_recorded_tools_are_checked_not_the_whole_registry():
    healthy = cli_recipe("recorded", detect={"command": TRUE}, verify=[{"command": TRUE}])
    other = cli_recipe("not_recorded", detect={"command": FALSE})
    with registry(healthy, other):
        _record("recorded")  # only this one is in state
        out = call_tool("doctor", {})
    assert out["checked"] == 1
    assert {*out["healthy"]} == {"recorded"}


def _fake_mcp_list(monkeypatch, servers):
    monkeypatch.setattr(server, "_parse_mcp_list", lambda project_dir=None: servers)


def test_mcp_server_records_are_health_checked_by_connection(monkeypatch):
    _fake_mcp_list(monkeypatch, [
        {"name": "up", "connected": True, "command": "x"},
        {"name": "down", "connected": False, "command": "x"},
    ])
    with registry(mcp_recipe("up"), mcp_recipe("down"), mcp_recipe("absent")):
        for rid in ("up", "down", "absent"):
            _record(rid, kind="mcp-server")
        out = call_tool("doctor", {})
    assert out["checked"] == 3
    assert out["healthy"] == ["up"]
    assert {p["recipe"]: p["status"] for p in out["problems"]} == {"down": "broken", "absent": "missing"}


def test_mcp_list_is_not_queried_without_an_mcp_record(monkeypatch):
    def boom(project_dir=None):
        raise AssertionError("claude mcp list was run")

    monkeypatch.setattr(server, "_parse_mcp_list", boom)
    with registry(cli_recipe("t", detect={"command": TRUE}, verify=[{"command": TRUE}])):
        _record("t")
        assert call_tool("doctor", {})["healthy"] == ["t"]


def test_recorded_tool_whose_recipe_vanished_is_flagged():
    with registry(cli_recipe("present")):
        _record("present")
        _record("ghost")  # recorded but no ghost.yaml in the registry
        out = call_tool("doctor", {})
    statuses = {p["recipe"]: p["status"] for p in out["problems"]}
    assert statuses.get("ghost") == "recipe-missing"


def test_mixed_fleet_splits_healthy_and_problems():
    good = cli_recipe("good", detect={"command": TRUE}, verify=[{"command": TRUE}])
    gone = cli_recipe("gone", detect={"command": FALSE})
    broke = cli_recipe("broke", detect={"command": TRUE}, verify=[{"command": FALSE}])
    with registry(good, gone, broke):
        for rid in ("good", "gone", "broke"):
            _record(rid)
        out = call_tool("doctor", {})
    assert out["checked"] == 3
    assert out["healthy"] == ["good"]
    assert {p["recipe"]: p["status"] for p in out["problems"]} == {
        "gone": "missing", "broke": "broken",
    }
    assert "bootstrap" in out["hint"]  # points at the fix
