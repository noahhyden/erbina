"""Live-bootstrap coverage of needs_project_dir propagation across every phase
(detect / configure / verify) and the phase-gating rules.

We prove *where* a phase runs by using a marker file that exists only inside the
supplied project_dir: a command like `test -f <marker>` passes iff it executed
in project_dir. The marker name is deliberately improbable so a bare-CWD run
never finds it by accident.
"""
from __future__ import annotations

from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, registry

MARKER = "__erbina_proto_marker__"
MARKER_CMD = f"test -f {MARKER}"


def _boot(recipe, **kwargs):
    with registry(recipe):
        return call_tool("bootstrap", {"recipe_id": recipe["id"], **kwargs})


# --------------------------------------------------------------------------- #
# detect
# --------------------------------------------------------------------------- #
def test_detect_runs_inside_project_dir(tmp_path):
    (tmp_path / MARKER).write_text("x")
    recipe = cli_recipe(detect={"command": MARKER_CMD, "needs_project_dir": True})
    out = _boot(recipe, project_dir=str(tmp_path))
    assert out["phases"]["detect"]["present"] is True  # marker found -> ran in project_dir


def test_detect_without_needs_project_dir_ignores_project_dir(tmp_path):
    # marker present in project_dir, but detect is NOT flagged -> runs in CWD,
    # does not see the marker.
    (tmp_path / MARKER).write_text("x")
    recipe = cli_recipe(detect={"command": MARKER_CMD})  # no needs_project_dir
    out = _boot(recipe, project_dir=str(tmp_path))
    assert out["phases"]["detect"]["present"] is False


# --------------------------------------------------------------------------- #
# configure
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def test_verify_runs_inside_project_dir(tmp_path):
    (tmp_path / MARKER).write_text("x")
    recipe = cli_recipe(
        detect={"command": TRUE},
        verify=[{"command": MARKER_CMD, "needs_project_dir": True}],
    )
    out = _boot(recipe, project_dir=str(tmp_path))
    assert out["phases"]["verify"][0]["status"] == "ok"
    assert out["ok"] is True


# --------------------------------------------------------------------------- #
# CANDIDATE FINDING #3 (documented, not yet fixed): configure vs verify handle a
# missing project_dir ASYMMETRICALLY, and a non-optional configure failure does
# NOT gate `ok`. These characterization tests pin CURRENT behavior so a future
# fix is a deliberate, visible change (they are named CURRENT_ on purpose).
# --------------------------------------------------------------------------- #
def test_CURRENT_configure_needing_project_dir_is_skipped_without_one():
    recipe = cli_recipe(
        detect={"command": FALSE},
        configure={"steps": [{"run": TRUE, "needs_project_dir": True}]},
    )
    out = _boot(recipe)  # no project_dir
    assert out["phases"]["configure"]["steps"][0]["status"] == "skipped"


def test_CURRENT_verify_needing_project_dir_runs_in_cwd_not_skipped():
    # Asymmetry vs configure: verify does NOT skip when project_dir is absent; it
    # runs in CWD (where the marker is absent) and thus fails.
    recipe = cli_recipe(
        detect={"command": TRUE},
        verify=[{"command": MARKER_CMD, "needs_project_dir": True}],
    )
    out = _boot(recipe)  # no project_dir
    assert out["phases"]["verify"][0]["status"] == "failed"
    assert out["ok"] is False


def test_CURRENT_nonoptional_configure_failure_does_not_gate_ok():
    # A REQUIRED (optional=false) configure step that fails is recorded 'failed'
    # but bootstrap still reports ok=True when verify passes. Likely should gate
    # ok — see candidate finding #3. Pins current behavior.
    recipe = cli_recipe(
        detect={"command": FALSE},
        configure={"steps": [{"run": FALSE}]},  # non-optional, fails
        verify=[{"command": TRUE}],             # passes
    )
    out = _boot(recipe)
    assert out["phases"]["configure"]["steps"][0]["status"] == "failed"
    assert out["ok"] is True  # <-- the surprising part
