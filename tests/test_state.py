"""Tests for the state manifest (~/.erbina/state.json) and the recording that
bootstrap / update do into it.

The autouse `_isolate_erbina_state` fixture (conftest.py) points server.STATE_DIR
at a fresh temp dir per test, so nothing here touches the real home directory.
"""
from __future__ import annotations

import json

import server
from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, registry


# --------------------------------------------------------------------------- #
# read/write helpers
# --------------------------------------------------------------------------- #
def test_read_missing_state_returns_default():
    assert server._read_state() == {"version": 1, "tools": {}}


def test_write_then_read_roundtrips():
    server._write_state({"version": 1, "tools": {"x": {"installed_version": "1.0.0"}}})
    assert server._read_state()["tools"]["x"]["installed_version"] == "1.0.0"


def test_write_is_atomic_leaves_no_temp_file():
    server._write_state({"version": 1, "tools": {}})
    names = sorted(p.name for p in server.STATE_DIR.iterdir())
    assert names == ["state.json"]  # no leftover .tmp


def test_malformed_state_degrades_to_default():
    server.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (server.STATE_DIR / "state.json").write_text("{ broken json")
    assert server._read_state() == {"version": 1, "tools": {}}


def test_wrong_shape_state_degrades_to_default():
    server.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (server.STATE_DIR / "state.json").write_text(json.dumps(["not", "a", "dict"]))
    assert server._read_state() == {"version": 1, "tools": {}}


# --------------------------------------------------------------------------- #
# _record_tool
# --------------------------------------------------------------------------- #
def test_record_sets_timestamps_and_fields():
    rec = server._record_tool("t", kind="cli-tool", installed_version="1.0.0")
    assert rec["kind"] == "cli-tool"
    assert rec["installed_version"] == "1.0.0"
    assert "installed_at" in rec and "updated_at" in rec


def test_record_skips_none_fields():
    rec = server._record_tool("t", kind="cli-tool", installed_version=None)
    assert "installed_version" not in rec


def test_record_preserves_unrelated_fields_like_pins():
    server._record_tool("t", kind="cli-tool", pinned=True)
    rec = server._record_tool("t", installed_version="2.0.0")  # re-record, no pin arg
    assert rec["pinned"] is True  # pin survived the second record
    assert rec["installed_version"] == "2.0.0"


def test_record_keeps_first_installed_at():
    first = server._record_tool("t", kind="cli-tool")["installed_at"]
    second = server._record_tool("t", installed_version="2.0.0")
    assert second["installed_at"] == first  # installed_at is not overwritten


# --------------------------------------------------------------------------- #
# bootstrap records into state
# --------------------------------------------------------------------------- #
def test_successful_bootstrap_records_the_tool():
    recipe = cli_recipe("t", detect={"command": FALSE})  # install runs
    with registry(recipe):
        out = call_tool("bootstrap", {"recipe_id": "t"})
    assert out["ok"] is True
    assert out.get("recorded") is True
    rec = server._read_state()["tools"]["t"]
    assert rec["kind"] == "cli-tool"
    assert rec["install_method"] == "always"


def test_bootstrap_records_version_when_recipe_has_version_block():
    recipe = cli_recipe(
        "t",
        detect={"command": FALSE},
        version={"current": "echo 1.2.3", "latest": "echo 1.2.3"},
    )
    with registry(recipe):
        call_tool("bootstrap", {"recipe_id": "t"})
    assert server._read_state()["tools"]["t"]["installed_version"] == "1.2.3"


def test_failed_bootstrap_does_not_record():
    recipe = cli_recipe("t", detect={"command": TRUE}, verify=[{"command": FALSE}])
    with registry(recipe):
        out = call_tool("bootstrap", {"recipe_id": "t"})
    assert out["ok"] is False
    assert server._read_state()["tools"] == {}


def test_dry_run_bootstrap_does_not_record():
    with registry(cli_recipe("t")):
        call_tool("bootstrap", {"recipe_id": "t", "dry_run": True})
    assert server._read_state()["tools"] == {}


# --------------------------------------------------------------------------- #
# update records before/after into state
# --------------------------------------------------------------------------- #
def test_successful_update_records_before_and_after(tmp_path):
    vfile = tmp_path / "v"
    vfile.write_text("1.0.0")
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": f"echo 2.0.0 > {vfile}"}]},
        version={"current": f"cat {vfile}", "latest": "echo 2.0.0"},
        verify=[{"command": TRUE}],
    )
    with registry(recipe):
        out = call_tool("update", {"recipe_id": "t"})
    assert out["ok"] is True
    rec = server._read_state()["tools"]["t"]
    assert rec["installed_version"] == "2.0.0"
    assert rec["previous_version"] == "1.0.0"
    assert rec["update_method"] == "u"


def test_failed_update_with_no_rollback_marks_broken(tmp_path):
    # Behavior since phase 3c: a verify failure after update (with no rollback
    # path) marks the tool broken in state rather than recording success.
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": TRUE}]},
        verify=[{"command": FALSE}],  # verify fails after update
    )
    with registry(recipe):
        out = call_tool("update", {"recipe_id": "t"})
    assert out["ok"] is False
    rec = server._read_state()["tools"]["t"]
    assert rec["broken"] is True


def test_failed_update_command_does_not_mark_broken(tmp_path):
    # If the update COMMAND itself fails (the upgrade never ran), the tool is
    # still at its old version — not broken — so nothing is recorded.
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": FALSE}]},  # command fails
        verify=[{"command": TRUE}],
    )
    with registry(recipe):
        out = call_tool("update", {"recipe_id": "t"})
    assert out["ok"] is False
    assert server._read_state()["tools"] == {}
