"""Behavioral tests for the `update` tool (auto-update phase 2).

Driven through the in-memory client against prototype recipes built from shell
builtins, so a live update is deterministic and side-effect free. A few tests use
a version file under tmp_path to exercise the before/after version reporting.
"""
from __future__ import annotations

from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, registry


def _upd(recipe, **kwargs):
    with registry(recipe):
        return call_tool("update", {"recipe_id": recipe["id"], **kwargs})


def _with_update(rid="t", run=TRUE, detect=TRUE, verify=TRUE):
    return cli_recipe(
        rid,
        detect={"command": detect},
        update={"methods": [{"id": "upd", "run": run}]},
        verify=[{"command": verify}],
    )


# --------------------------------------------------------------------------- #
# consent surface / dry-run
# --------------------------------------------------------------------------- #
def test_dry_run_returns_plan_and_runs_nothing():
    out = _upd(_with_update(), dry_run=True)
    assert out["dry_run"] is True
    assert out["phases"] == {}
    assert out["plan"]["update_source"] == "update"
    assert out["plan"]["chosen_method"] == "upd"
    assert "nothing executed" in out["note"].lower()


def test_bad_scope_rejected_before_work():
    out = _upd(_with_update(), scope="bogus", dry_run=True)
    assert "error" in out
    assert "scope must be one of" in out["error"]


# --------------------------------------------------------------------------- #
# no update path declared
# --------------------------------------------------------------------------- #
def test_no_update_path_is_an_error():
    out = _upd(cli_recipe("t"))  # no update block, install not upgrade_safe
    assert "error" in out
    assert "no safe way to update" in out["error"]


def test_install_upgrade_safe_is_used_as_fallback():
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        install={"methods": [{"id": "i", "run": TRUE}], "upgrade_safe": True},
    )
    out = _upd(recipe, dry_run=True)
    assert out["plan"]["update_source"] == "install (upgrade_safe)"
    assert out["plan"]["chosen_method"] == "i"


# --------------------------------------------------------------------------- #
# must be installed
# --------------------------------------------------------------------------- #
def test_not_installed_refuses_update():
    out = _upd(_with_update(detect=FALSE))
    assert out["ok"] is False
    assert "not installed" in out["error"]
    assert "update" not in out["phases"]  # never ran the update command


# --------------------------------------------------------------------------- #
# happy path + verify safety net
# --------------------------------------------------------------------------- #
def test_successful_update_runs_and_reverifies():
    out = _upd(_with_update(run=TRUE, verify=TRUE))
    assert out["phases"]["update"]["status"] == "ok"
    assert out["phases"]["update"]["method"] == "upd"
    assert out["phases"]["verify"][0]["status"] == "ok"
    assert out["ok"] is True
    # a successful update must record the transition (mutation guard: recorded=True)
    assert out["recorded"] is True


def test_verify_failure_after_update_flags_broken():
    out = _upd(_with_update(run=TRUE, verify=FALSE))
    assert out["phases"]["update"]["status"] == "ok"
    assert out["phases"]["verify"][0]["status"] == "failed"
    assert out["ok"] is False
    assert "warning" in out
    assert "may be broken" in out["warning"]


def test_update_command_failure_short_circuits_before_verify():
    out = _upd(_with_update(run=FALSE))
    assert out["phases"]["update"]["status"] == "failed"
    assert out["ok"] is False
    assert "verify" not in out["phases"]


def test_no_eligible_update_method_fails():
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "only", "when": FALSE, "run": TRUE}]},
        verify=[{"command": TRUE}],
    )
    out = _upd(recipe)
    assert out["phases"]["update"]["status"] == "failed"
    assert out["ok"] is False


def test_update_picks_first_eligible_method():
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [
            {"id": "first", "when": TRUE, "run": TRUE},
            {"id": "second", "when": TRUE, "run": TRUE},
        ]},
        verify=[{"command": TRUE}],
    )
    out = _upd(recipe)
    assert out["phases"]["update"]["method"] == "first"


# --------------------------------------------------------------------------- #
# version before/after reporting (uses a version file under tmp_path)
# --------------------------------------------------------------------------- #
def test_reports_version_before_and_after(tmp_path):
    vfile = tmp_path / "v"
    vfile.write_text("1.0.0")
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": f"echo 2.0.0 > {vfile}"}]},
        version={"current": f"cat {vfile}", "latest": "echo 2.0.0"},
        verify=[{"command": TRUE}],
    )
    out = _upd(recipe)
    assert out["version"]["before"] == "1.0.0"
    assert out["version"]["after"] == "2.0.0"
    assert out["ok"] is True
    # versions DIFFER, so the "already at X — no-op" note must NOT appear
    # (mutation guard: the note condition is before AND after AND before==after)
    assert "no-op" not in out.get("note", "")


def test_noop_update_reports_already_current(tmp_path):
    vfile = tmp_path / "v"
    vfile.write_text("1.0.0")
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        update={"methods": [{"id": "u", "run": TRUE}]},  # doesn't change version
        version={"current": f"cat {vfile}", "latest": "echo 1.0.0"},
        verify=[{"command": TRUE}],
    )
    out = _upd(recipe)
    assert out["version"] == {"before": "1.0.0", "after": "1.0.0"}
    assert "no-op" in out["note"]
