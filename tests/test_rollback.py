"""Tests for phase 3c: rollback on a post-update verify failure.

When `update` upgrades a tool but the re-verify fails, erbina either auto-rolls
back (if the recipe declares a `rollback:` command) or surfaces a manual plan and
marks the tool broken in state. Rollback commands receive the previous version
via the $ERBINA_ROLLBACK_VERSION environment variable.

Recipes here use a version file under tmp_path so we can make verify pass/fail
based on the file's contents, exercising the real orchestration deterministically.
"""
from __future__ import annotations

import server
from helpers import call_tool
from prototype import TRUE, cli_recipe, registry


# --------------------------------------------------------------------------- #
# no rollback declared -> plan + mark broken
# --------------------------------------------------------------------------- #
def test_no_rollback_surfaces_plan_and_marks_broken(tmp_path):
    vfile = tmp_path / "v"
    vfile.write_text("1.0.0")
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": f"echo 2.0.0 > {vfile}"}]},
        version={"current": f"cat {vfile}", "latest": "echo 2.0.0"},
        verify=[{"command": "false"}],  # verify fails after update
    )
    with registry(recipe):
        out = call_tool("update", {"recipe_id": "t"})
    assert out["ok"] is False
    assert out["rollback_plan"]["previous_version"] == "1.0.0"
    assert "may be broken" in out["warning"]
    assert server._read_state()["tools"]["t"]["broken"] is True


# --------------------------------------------------------------------------- #
# rollback declared -> auto-rollback that RECOVERS
# --------------------------------------------------------------------------- #
def test_rollback_recovers_and_restores_previous_version(tmp_path):
    vfile = tmp_path / "v"
    vfile.write_text("1.0.0")
    # update writes a "bad" version that fails verify; rollback restores the
    # previous version (passed via $ERBINA_ROLLBACK_VERSION), after which verify
    # passes (verify checks the file contains a version < 2, i.e. not the bad one).
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": f"echo 2.0.0-bad > {vfile}"}]},
        rollback={"methods": [{"id": "rb", "run": f'echo "$ERBINA_ROLLBACK_VERSION" > {vfile}'}]},
        version={"current": f"cat {vfile}", "latest": "echo 2.0.0"},
        verify=[{"command": f"grep -qv bad {vfile}"}],  # fails while file says '...bad'
    )
    with registry(recipe):
        out = call_tool("update", {"recipe_id": "t"})
    assert out["ok"] is False                       # the update itself did not succeed
    assert out["phases"]["rollback"]["status"] == "ok"
    assert out["rolled_back_to"] == "1.0.0"
    assert vfile.read_text().strip() == "1.0.0"     # rollback actually restored it
    rec = server._read_state()["tools"]["t"]
    assert rec["installed_version"] == "1.0.0"
    assert rec.get("broken") is False


def test_rollback_receives_previous_version_via_env(tmp_path):
    # Prove $ERBINA_ROLLBACK_VERSION is injected into the rollback command's env.
    vfile = tmp_path / "v"
    vfile.write_text("0.9.0")
    capture = tmp_path / "captured"
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": f"echo 1.0.0 > {vfile}"}]},
        rollback={"methods": [{"id": "rb", "run": f'echo "$ERBINA_ROLLBACK_VERSION" > {capture}'}]},
        version={"current": f"cat {vfile}", "latest": "echo 1.0.0"},
        verify=[{"command": "false"}],  # always fail -> trigger rollback
    )
    with registry(recipe):
        call_tool("update", {"recipe_id": "t"})
    assert capture.read_text().strip() == "0.9.0"  # the previous version reached the command


# --------------------------------------------------------------------------- #
# rollback declared but itself fails -> mark broken
# --------------------------------------------------------------------------- #
def test_rollback_command_succeeds_but_verify_still_fails_marks_broken(tmp_path):
    # The rollback COMMAND exits 0 but doesn't actually fix the tool, so the
    # post-rollback re-verify still fails -> not recovered -> broken. (Guards the
    # `and rb_ok` half of the recovery condition.)
    vfile = tmp_path / "v"
    vfile.write_text("1.0.0")
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": TRUE}]},
        rollback={"methods": [{"id": "rb", "run": TRUE}]},  # succeeds but fixes nothing
        version={"current": f"cat {vfile}", "latest": "echo 2.0.0"},
        verify=[{"command": "false"}],  # still fails after the (no-op) rollback
    )
    with registry(recipe):
        out = call_tool("update", {"recipe_id": "t"})
    assert out["phases"]["rollback"]["status"] == "failed"
    assert "rolled_back_to" not in out
    assert out["ok"] is False
    assert server._read_state()["tools"]["t"]["broken"] is True


def test_rollback_failure_marks_broken(tmp_path):
    vfile = tmp_path / "v"
    vfile.write_text("1.0.0")
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": TRUE}]},
        rollback={"methods": [{"id": "rb", "run": "false"}]},  # rollback command fails
        version={"current": f"cat {vfile}", "latest": "echo 2.0.0"},
        verify=[{"command": "false"}],  # verify fails
    )
    with registry(recipe):
        out = call_tool("update", {"recipe_id": "t"})
    assert out["phases"]["rollback"]["status"] == "failed"
    assert out["ok"] is False
    assert server._read_state()["tools"]["t"]["broken"] is True
