"""Behavioral tests for recipe `requires:` — prerequisite recipes that must be
bootstrapped before the recipe that depends on them.

All recipes are prototype recipes (POSIX-builtin commands), so a live bootstrap is
deterministic and side-effect-free. The `requires` graph is exercised end-to-end
through the real `bootstrap` tool: ordering, idempotency, transitive + diamond
deps, cycle safety, and failure short-circuiting.
"""
from __future__ import annotations

import pytest

from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, registry


def _boot(*recipes, target=None, **kwargs):
    target = target or recipes[0]["id"]
    with registry(*recipes):
        return call_tool("bootstrap", {"recipe_id": target, **kwargs})


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
import server  # noqa: E402


def test_valid_requires_list_validates_clean():
    assert server.validate_recipe(cli_recipe("a", requires=["b"]), stem="a") == []


@pytest.mark.parametrize("bad", ["b", 1, [1], [""], ["  "], [None], {}])
def test_bad_requires_is_reported(bad):
    errs = server.validate_recipe(cli_recipe("a", requires=bad), stem="a")
    assert any("requires" in e for e in errs), (bad, errs)


def test_self_reference_is_rejected():
    errs = server.validate_recipe(cli_recipe("a", requires=["a"]), stem="a")
    assert any("requires" in e and ("itself" in e or "self" in e) for e in errs), errs


# --------------------------------------------------------------------------- #
# ordering + idempotency
# --------------------------------------------------------------------------- #
def test_prerequisite_is_bootstrapped_before_the_dependent():
    # b is absent (detect FALSE) so it installs; a depends on b
    a = cli_recipe("a", requires=["b"])
    b = cli_recipe("b", detect={"command": FALSE})
    out = _boot(a, b, target="a")
    assert out["ok"] is True
    assert "requires" in out
    assert [r["recipe"] for r in out["requires"]] == ["b"]
    assert out["requires"][0]["phases"]["install"]["status"] == "ok"


def test_present_prerequisite_skips_its_install():
    a = cli_recipe("a", requires=["b"])
    b = cli_recipe("b", detect={"command": TRUE})  # already present
    out = _boot(a, b, target="a")
    assert out["requires"][0]["phases"]["install"]["status"] == "skipped"
    assert out["ok"] is True


# --------------------------------------------------------------------------- #
# failure short-circuits the dependent
# --------------------------------------------------------------------------- #
def test_failed_prerequisite_aborts_the_dependent():
    a = cli_recipe("a", requires=["b"])
    b = cli_recipe("b", detect={"command": FALSE}, install={"methods": [{"id": "x", "run": FALSE}]})
    out = _boot(a, b, target="a")
    assert out["ok"] is False
    assert "b" in out.get("error", "")
    # the dependent's own install must NOT have run
    assert "install" not in out.get("phases", {})


def test_missing_prerequisite_recipe_fails_cleanly():
    a = cli_recipe("a", requires=["ghost"])
    out = _boot(a, target="a")
    assert out["ok"] is False
    assert "ghost" in out.get("error", "")


# --------------------------------------------------------------------------- #
# transitive + diamond
# --------------------------------------------------------------------------- #
def test_transitive_requires_are_resolved_depth_first():
    a = cli_recipe("a", requires=["b"])
    b = cli_recipe("b", requires=["c"], detect={"command": FALSE})
    c = cli_recipe("c", detect={"command": FALSE})
    out = _boot(a, b, c, target="a")
    assert out["ok"] is True
    # a -> requires b -> requires c ; c resolved inside b's report
    breport = out["requires"][0]
    assert breport["recipe"] == "b"
    assert breport["requires"][0]["recipe"] == "c"


def test_diamond_dependency_bootstraps_shared_prereq_once():
    a = cli_recipe("a", requires=["b", "c"])
    b = cli_recipe("b", requires=["d"], detect={"command": FALSE})
    c = cli_recipe("c", requires=["d"], detect={"command": FALSE})
    d = cli_recipe("d", detect={"command": FALSE})
    out = _boot(a, b, c, d, target="a")
    assert out["ok"] is True
    # d appears fully bootstrapped under b; under c it's a skipped "already handled"
    # note (bootstrapped once per top-level call)
    def find_d(reports):
        return [r for r in reports if r["recipe"] == "d"]
    b_d = find_d(out["requires"][0]["requires"])[0]
    c_d = find_d(out["requires"][1]["requires"])[0]
    handled = [b_d, c_d]
    assert sum(1 for r in handled if r.get("status") == "already-handled") == 1


# --------------------------------------------------------------------------- #
# cycle safety
# --------------------------------------------------------------------------- #
def test_cycle_is_detected_and_does_not_recurse_forever():
    a = cli_recipe("a", requires=["b"])
    b = cli_recipe("b", requires=["a"])
    out = _boot(a, b, target="a")  # must terminate
    assert isinstance(out, dict)
    # the back-edge to a is reported as a cycle, not infinitely recursed
    b_report = out["requires"][0]
    a_again = [r for r in b_report.get("requires", []) if r["recipe"] == "a"]
    assert a_again and a_again[0].get("status") == "cycle"


# --------------------------------------------------------------------------- #
# dry-run surfaces prerequisites without executing
# --------------------------------------------------------------------------- #
def test_dry_run_lists_prerequisites_and_runs_nothing():
    a = cli_recipe("a", requires=["b"])
    b = cli_recipe("b", detect={"command": FALSE})
    out = _boot(a, b, target="a", dry_run=True)
    assert out["dry_run"] is True
    assert out["plan"]["requires"] == ["b"]
    assert out["phases"] == {}  # nothing executed for the dependent
