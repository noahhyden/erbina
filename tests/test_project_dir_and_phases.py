"""Live-bootstrap coverage of needs_project_dir across detect/configure/verify, proven by an improbable marker file that exists only inside project_dir."""
from __future__ import annotations

from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, registry

MARKER = "__erbina_proto_marker__"
MARKER_CMD = f"test -f {MARKER}"


def _boot(recipe, **kwargs):
    with registry(recipe):
        return call_tool("bootstrap", {"recipe_id": recipe["id"], **kwargs})


# detect
def test_detect_runs_inside_project_dir(tmp_path):
    (tmp_path / MARKER).write_text("x")
    recipe = cli_recipe(detect={"command": MARKER_CMD, "needs_project_dir": True})
    out = _boot(recipe, project_dir=str(tmp_path))
    assert out["phases"]["detect"]["present"] is True  # marker found -> ran in project_dir


def test_detect_without_needs_project_dir_ignores_project_dir(tmp_path):
    # Marker is in project_dir but detect is NOT flagged, so it runs in CWD and does not see it.
    (tmp_path / MARKER).write_text("x")
    recipe = cli_recipe(detect={"command": MARKER_CMD})  # no needs_project_dir
    out = _boot(recipe, project_dir=str(tmp_path))
    assert out["phases"]["detect"]["present"] is False


# configure
def test_configure_step_runs_inside_project_dir(tmp_path):
    (tmp_path / MARKER).write_text("x")
    recipe = cli_recipe(
        detect={"command": FALSE},  # force install+configure to run
        configure={"steps": [{"run": MARKER_CMD, "needs_project_dir": True}]},
    )
    out = _boot(recipe, project_dir=str(tmp_path))
    assert out["phases"]["configure"]["steps"][0]["status"] == "ok"


def test_optional_configure_failure_is_ok(tmp_path):
    recipe = cli_recipe(
        detect={"command": FALSE},
        configure={"steps": [{"run": FALSE, "optional": True}]},
    )
    out = _boot(recipe)
    assert out["phases"]["configure"]["steps"][0]["status"] == "ok"
    assert out["ok"] is True


# verify
def test_verify_runs_inside_project_dir(tmp_path):
    (tmp_path / MARKER).write_text("x")
    recipe = cli_recipe(
        detect={"command": TRUE},
        verify=[{"command": MARKER_CMD, "needs_project_dir": True}],
    )
    out = _boot(recipe, project_dir=str(tmp_path))
    assert out["phases"]["verify"][0]["status"] == "ok"
    assert out["ok"] is True


# Candidate finding #3: configure and verify handle a missing project_dir asymmetrically; these CURRENT_ tests pin today's behavior so a fix is a visible change.
def test_CURRENT_configure_needing_project_dir_is_skipped_without_one():
    recipe = cli_recipe(
        detect={"command": FALSE},
        configure={"steps": [{"run": TRUE, "needs_project_dir": True}]},
    )
    out = _boot(recipe)  # no project_dir
    assert out["phases"]["configure"]["steps"][0]["status"] == "skipped"


def test_CURRENT_verify_needing_project_dir_runs_in_cwd_not_skipped():
    # Asymmetry vs configure: verify does NOT skip without project_dir, runs in CWD, misses the marker, and fails.
    recipe = cli_recipe(
        detect={"command": TRUE},
        verify=[{"command": MARKER_CMD, "needs_project_dir": True}],
    )
    out = _boot(recipe)  # no project_dir
    assert out["phases"]["verify"][0]["status"] == "failed"
    assert out["ok"] is False


def test_nonoptional_configure_failure_gates_ok():
    # Finding #3(2) (fixed): a REQUIRED configure step that fails gates report.ok and short-circuits before verify, like a failed install.
    recipe = cli_recipe(
        detect={"command": FALSE},
        configure={"steps": [{"run": FALSE}]},  # non-optional, fails
        verify=[{"command": TRUE}],             # would pass, but must not run
    )
    out = _boot(recipe)
    assert out["phases"]["configure"]["steps"][0]["status"] == "failed"
    assert out["ok"] is False
    assert "verify" not in out["phases"]  # short-circuited before verify


def test_configure_failure_still_lets_optional_step_pass_through():
    # Only NON-optional failures gate ok; an optional failing step beside a passing required one must not fail the bootstrap.
    recipe = cli_recipe(
        detect={"command": FALSE},
        configure={"steps": [{"run": TRUE}, {"run": FALSE, "optional": True}]},
        verify=[{"command": TRUE}],
    )
    out = _boot(recipe)
    statuses = [s["status"] for s in out["phases"]["configure"]["steps"]]
    assert statuses == ["ok", "ok"]  # optional failure recorded as ok
    assert out["ok"] is True
    assert "verify" in out["phases"]  # not short-circuited
