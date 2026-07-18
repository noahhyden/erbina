"""Behavioral tests for the LIVE bootstrap orchestration engine.

Unlike test_tools.py (which only touches dry-run / read-only paths), these run
`bootstrap` with dry_run=False against prototype recipes whose every command is
a POSIX shell builtin with a fixed exit code. That makes a real bootstrap fully
deterministic and side-effect-free — nothing is installed or wired — so we can
assert on the orchestration logic itself:

  detect (idempotency gate) -> install (first eligible `when` method) ->
  configure (skipped when already present) -> verify (must exit expect_exit).

This is the code path with the most branching in server.py:bootstrap and thus
the most room for regressions.
"""
from __future__ import annotations

from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, exit_code, mcp_recipe, registry


def _boot(recipe, **kwargs):
    """Live (non-dry) bootstrap of a single prototype recipe."""
    with registry(recipe):
        return call_tool("bootstrap", {"recipe_id": recipe["id"], **kwargs})


# --------------------------------------------------------------------------- #
# detect gates install (the core idempotency contract)
# --------------------------------------------------------------------------- #
def test_detect_present_skips_install():
    out = _boot(cli_recipe(detect={"command": TRUE}))
    assert out["phases"]["detect"]["present"] is True
    assert out["phases"]["install"]["status"] == "skipped"
    assert out["phases"]["install"]["reason"] == "already present"


def test_detect_absent_runs_install():
    out = _boot(cli_recipe(detect={"command": FALSE}))
    assert out["phases"]["detect"]["present"] is False
    assert out["phases"]["install"]["status"] == "ok"
    assert out["phases"]["install"]["method"] == "always"


def test_detect_expect_exit_custom_code():
    # A recipe can declare a non-zero "present" exit code; detect honors it.
    out = _boot(cli_recipe(detect={"command": exit_code(3), "expect_exit": 3}))
    assert out["phases"]["detect"]["present"] is True
    assert out["phases"]["install"]["status"] == "skipped"


# --------------------------------------------------------------------------- #
# guarded, ordered install-method selection
# --------------------------------------------------------------------------- #
def test_install_skips_ineligible_method_for_eligible_one():
    recipe = cli_recipe(
        detect={"command": FALSE},
        install={"methods": [
            {"id": "skipme", "when": FALSE, "run": TRUE},
            {"id": "chosen", "when": TRUE, "run": TRUE},
        ]},
    )
    out = _boot(recipe)
    assert out["phases"]["install"]["method"] == "chosen"


def test_install_picks_earliest_among_multiple_eligible_methods():
    # Both guards pass; ORDER must decide (prefer brew over curl, etc.). A test
    # with only one eligible method can't tell 'first' from 'last' — this one can.
    recipe = cli_recipe(
        detect={"command": FALSE},
        install={"methods": [
            {"id": "first", "when": TRUE, "run": TRUE},
            {"id": "second", "when": TRUE, "run": TRUE},
        ]},
    )
    out = _boot(recipe)
    assert out["phases"]["install"]["method"] == "first"


def test_install_fails_when_no_guard_passes():
    recipe = cli_recipe(
        detect={"command": FALSE},
        install={"methods": [
            {"id": "a", "when": FALSE, "run": TRUE},
            {"id": "b", "when": FALSE, "run": TRUE},
        ]},
    )
    out = _boot(recipe)
    assert out["phases"]["install"]["status"] == "failed"
    assert out["ok"] is False
    # short-circuits: verify never runs when install can't proceed
    assert "verify" not in out["phases"]


def test_install_command_failure_short_circuits_before_verify():
    recipe = cli_recipe(detect={"command": FALSE}, install={"methods": [{"id": "m", "run": FALSE}]})
    out = _boot(recipe)
    assert out["phases"]["install"]["status"] == "failed"
    assert out["ok"] is False
    assert "verify" not in out["phases"]


# --------------------------------------------------------------------------- #
# configure phase
# --------------------------------------------------------------------------- #
def test_configure_skipped_when_already_present():
    recipe = cli_recipe(
        detect={"command": TRUE},
        configure={"steps": [{"run": TRUE}]},
    )
    out = _boot(recipe)
    assert out["phases"]["configure"]["status"] == "skipped"


def test_configure_reruns_when_force_configure():
    recipe = cli_recipe(
        detect={"command": TRUE},
        configure={"steps": [{"run": TRUE}]},
    )
    out = _boot(recipe, force_configure=True)
    assert "steps" in out["phases"]["configure"]
    assert out["phases"]["configure"]["steps"][0]["status"] == "ok"


def test_configure_step_needing_project_dir_is_skipped_without_one():
    recipe = cli_recipe(
        detect={"command": FALSE},  # so configure actually runs
        configure={"steps": [{"run": TRUE, "needs_project_dir": True}]},
    )
    out = _boot(recipe)
    step = out["phases"]["configure"]["steps"][0]
    assert step["status"] == "skipped"
    assert "no project_dir" in step["reason"]


# --------------------------------------------------------------------------- #
# verify phase
# --------------------------------------------------------------------------- #
def test_verify_failure_fails_bootstrap():
    recipe = cli_recipe(detect={"command": TRUE}, verify=[{"command": FALSE}])
    out = _boot(recipe)
    assert out["phases"]["verify"][0]["status"] == "failed"
    assert out["ok"] is False


def test_optional_verify_failure_does_not_fail_bootstrap():
    recipe = cli_recipe(
        detect={"command": TRUE},
        verify=[{"command": TRUE}, {"command": FALSE, "optional": True}],
    )
    out = _boot(recipe)
    statuses = [v["status"] for v in out["phases"]["verify"]]
    assert statuses == ["ok", "failed"]
    assert out["ok"] is True  # the failing verify was optional


def test_verify_expect_exit_custom_code_passes():
    recipe = cli_recipe(detect={"command": TRUE}, verify=[{"command": exit_code(7), "expect_exit": 7}])
    out = _boot(recipe)
    assert out["phases"]["verify"][0]["status"] == "ok"
    assert out["ok"] is True


# --------------------------------------------------------------------------- #
# mcp-server specifics
# --------------------------------------------------------------------------- #
def test_mcp_server_success_emits_reload_hint():
    out = _boot(mcp_recipe(detect={"command": TRUE}))
    assert out["ok"] is True
    assert "next" in out
    assert "reload" in out["next"].lower()


def test_cli_tool_success_has_no_reload_hint():
    out = _boot(cli_recipe(detect={"command": TRUE}))
    assert out["ok"] is True
    assert "next" not in out
