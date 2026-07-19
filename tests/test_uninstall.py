"""Behavioral tests for the `uninstall` tool — the teardown counterpart to
bootstrap for cli-tools. It runs the recipe's `uninstall:` methods, confirms the
tool is actually gone (re-runs detect), and forgets it in the state manifest.

State is isolated per-test (conftest). Recipes are prototype recipes; the
state-changing tests use a marker file so detect flips present -> absent exactly
as a real uninstall would.
"""
from __future__ import annotations

import pytest

import server
from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, mcp_recipe, registry


def _uninstall(recipe, **kwargs):
    with registry(recipe):
        return call_tool("uninstall", {"recipe_id": recipe["id"], **kwargs})


def _marker_recipe(rid, marker, uninstall_run):
    # detect = "the marker file exists"; a real uninstall removes it
    return cli_recipe(
        rid,
        detect={"command": f"test -f {marker}"},
        uninstall={"methods": [{"id": "rm", "run": uninstall_run}]},
        verify=[{"command": TRUE}],
    )


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def test_valid_uninstall_block_validates_clean():
    r = cli_recipe("t", uninstall={"methods": [{"id": "u", "run": "brew uninstall t"}]})
    assert server.validate_recipe(r, stem="t") == []


@pytest.mark.parametrize("block,needle", [
    ("not-a-mapping", "uninstall"),
    ({"methods": []}, "methods"),
    ({"methods": [{"run": "x"}]}, "id"),
    ({"methods": [{"id": "u"}]}, "run"),
    ({"methods": [{"id": "u", "run": "echo ${bad}"}]}, "bad"),
])
def test_bad_uninstall_block_is_reported(block, needle):
    r = cli_recipe("t", uninstall=block)
    errs = server.validate_recipe(r, stem="t")
    assert any(needle in e for e in errs), (block, errs)


# --------------------------------------------------------------------------- #
# consent surface / guards
# --------------------------------------------------------------------------- #
def test_dry_run_returns_plan_and_runs_nothing():
    r = cli_recipe("t", uninstall={"methods": [{"id": "u", "run": TRUE}]})
    out = _uninstall(r, dry_run=True)
    assert out["dry_run"] is True
    assert out["phases"] == {}
    assert out["plan"]["chosen_method"] == "u"
    assert "nothing" in out["note"].lower()


def test_no_uninstall_block_is_an_error():
    out = _uninstall(cli_recipe("t"))  # no uninstall block
    assert "error" in out
    assert "no safe way to" in out["error"] or "no `uninstall`" in out["error"]


def test_bad_scope_rejected_before_work():
    r = cli_recipe("t", uninstall={"methods": [{"id": "u", "run": TRUE}]})
    out = _uninstall(r, scope="bogus")
    assert "error" in out and "scope must be one of" in out["error"]


def test_mcp_server_is_pointed_at_remove_mcp():
    r = mcp_recipe("m", uninstall={"methods": [{"id": "u", "run": TRUE}]})
    out = _uninstall(r)
    assert "error" in out
    assert "remove_mcp" in out["error"]


# --------------------------------------------------------------------------- #
# not installed
# --------------------------------------------------------------------------- #
def test_forget_tool_is_a_noop_for_an_unrecorded_tool():
    assert server._forget_tool("never-recorded") is False


def test_not_installed_and_unrecorded_forgets_nothing(tmp_path):
    marker = tmp_path / "m"  # absent -> detect fails; no state record either
    r = _marker_recipe("t", marker, uninstall_run=TRUE)
    out = _uninstall(r)
    assert out["ok"] is True
    assert out["already_absent"] is True
    assert out["forgotten"] is False   # nothing was recorded to forget


def test_not_installed_reports_nothing_to_remove(tmp_path):
    marker = tmp_path / "m"  # never created -> detect fails
    r = _marker_recipe("t", marker, uninstall_run=TRUE)
    with registry(r):
        server._record_tool("t", kind="cli-tool")  # a stale record
        out = call_tool("uninstall", {"recipe_id": "t"})
    assert out["ok"] is True
    assert out.get("already_absent") is True
    # a stale record for an absent tool is cleaned up
    assert "t" not in server._read_state()["tools"]


# --------------------------------------------------------------------------- #
# successful teardown
# --------------------------------------------------------------------------- #
def test_successful_uninstall_removes_tool_and_forgets_it(tmp_path):
    marker = tmp_path / "m"
    marker.write_text("x")  # tool present
    r = _marker_recipe("t", marker, uninstall_run=f"rm {marker}")
    with registry(r):
        server._record_tool("t", kind="cli-tool", installed_version="1.0.0")
        out = call_tool("uninstall", {"recipe_id": "t"})
    assert out["ok"] is True
    assert out["phases"]["uninstall"]["status"] == "ok"
    assert out["phases"]["confirm"]["present"] is False  # detect after -> gone
    assert out["forgotten"] is True
    assert "t" not in server._read_state()["tools"]
    assert not marker.exists()


def test_uninstall_that_leaves_tool_present_is_reported_failed(tmp_path):
    marker = tmp_path / "m"
    marker.write_text("x")
    # the "uninstall" command is a no-op (TRUE) -> marker stays -> still present
    r = _marker_recipe("t", marker, uninstall_run=TRUE)
    with registry(r):
        server._record_tool("t", kind="cli-tool")
        out = call_tool("uninstall", {"recipe_id": "t"})
    assert out["ok"] is False
    assert out["phases"]["confirm"]["present"] is True
    assert out.get("forgotten") is not True     # still installed -> keep the record
    assert "t" in server._read_state()["tools"]


def test_uninstall_command_failure_is_reported(tmp_path):
    marker = tmp_path / "m"
    marker.write_text("x")
    r = _marker_recipe("t", marker, uninstall_run=FALSE)  # command itself fails
    with registry(r):
        out = call_tool("uninstall", {"recipe_id": "t"})
    assert out["ok"] is False
    assert out["phases"]["uninstall"]["status"] == "failed"


def test_no_eligible_uninstall_method_fails(tmp_path):
    marker = tmp_path / "m"
    marker.write_text("x")
    r = cli_recipe(
        "t",
        detect={"command": f"test -f {marker}"},
        uninstall={"methods": [{"id": "only", "when": FALSE, "run": TRUE}]},  # guard never passes
        verify=[{"command": TRUE}],
    )
    with registry(r):
        out = call_tool("uninstall", {"recipe_id": "t"})
    assert out["ok"] is False
    assert "no uninstall method" in out["phases"]["uninstall"]["reason"]
