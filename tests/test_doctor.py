"""Behavioral tests for the `doctor` tool — a health check over the CLI tools
erbina has recorded in its state manifest, symmetric to `find_dead_mcps` for MCP
servers. It re-runs each recorded tool's detect (still installed?) and verify
(still runs?) and classifies healthy / missing / broken. Read-only.

State is isolated to a temp dir by the autouse conftest fixture; recipes are
prototype recipes (builtin commands) so detect/verify are deterministic.
"""
from __future__ import annotations

import server
from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, mcp_recipe, registry


def _record(rid, kind="cli-tool"):
    server._record_tool(rid, kind=kind, installed_version="1.0.0", install_method="m")


# --------------------------------------------------------------------------- #
# nothing recorded
# --------------------------------------------------------------------------- #
def test_empty_state_reports_nothing_to_check():
    with registry(cli_recipe("t")):
        out = call_tool("doctor", {})
    assert out["checked"] == 0
    assert out["healthy"] == []
    assert out["problems"] == []


# --------------------------------------------------------------------------- #
# healthy / missing / broken classification
# --------------------------------------------------------------------------- #
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
    # a missing tool must NOT be probed with verify (it's absent) -> status missing,
    # not broken, even if verify would fail
    r = cli_recipe("t", detect={"command": FALSE}, verify=[{"command": FALSE}])
    with registry(r):
        _record("t")
        out = call_tool("doctor", {})
    assert out["problems"][0]["status"] == "missing"


# --------------------------------------------------------------------------- #
# scope of what's checked
# --------------------------------------------------------------------------- #
def test_only_recorded_tools_are_checked_not_the_whole_registry():
    healthy = cli_recipe("recorded", detect={"command": TRUE}, verify=[{"command": TRUE}])
    other = cli_recipe("not_recorded", detect={"command": FALSE})
    with registry(healthy, other):
        _record("recorded")  # only this one is in state
        out = call_tool("doctor", {})
    assert out["checked"] == 1
    assert {*out["healthy"]} == {"recorded"}


def test_mcp_server_records_are_deferred_to_find_dead_mcps():
    r = mcp_recipe("m")
    with registry(r):
        _record("m", kind="mcp-server")
        out = call_tool("doctor", {})
    # an mcp-server isn't cli-tool-verified here; it's pointed at find_dead_mcps
    assert out["checked"] == 0 or all(p["status"] != "broken" for p in out["problems"])
    assert "find_dead_mcps" in out["hint"] or out["checked"] == 0


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
