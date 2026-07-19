"""Behavioral tests for `kind: profile` — a meta-recipe that installs nothing
itself and just bundles a curated set of other recipes via `requires`. Bootstrap
resolves the bundle (reusing the requires machinery) and reports done.
"""
from __future__ import annotations

import pytest

import server
from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, profile_recipe, registry


def _boot(*recipes, target, **kwargs):
    with registry(*recipes):
        return call_tool("bootstrap", {"recipe_id": target, **kwargs})


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def test_valid_profile_validates_clean():
    assert server.validate_recipe(profile_recipe("p", requires=["a", "b"]), stem="p") == []


def test_profile_without_requires_is_rejected():
    p = profile_recipe("p")
    p.pop("requires")
    errs = server.validate_recipe(p, stem="p")
    assert any("requires" in e for e in errs)


def test_profile_with_empty_requires_is_rejected():
    errs = server.validate_recipe(profile_recipe("p", requires=[]), stem="p")
    assert any("requires" in e for e in errs)


@pytest.mark.parametrize("key,value", [
    ("detect", {"command": "true"}),
    ("install", {"methods": [{"id": "m", "run": "true"}]}),
    ("verify", [{"command": "true"}]),
    ("version", {"current": "x --version", "latest": "echo 1"}),
    ("uninstall", {"methods": [{"id": "u", "run": "true"}]}),
])
def test_profile_with_a_lifecycle_key_is_rejected(key, value):
    p = profile_recipe("p", requires=["a"])
    p[key] = value
    errs = server.validate_recipe(p, stem="p")
    assert any("installs nothing" in e and key in e for e in errs), errs


def test_profile_kind_is_accepted_in_the_enum():
    assert "profile" in server.VALID_KINDS


# --------------------------------------------------------------------------- #
# bootstrap resolves the bundle
# --------------------------------------------------------------------------- #
def test_bootstrapping_a_profile_bootstraps_its_members():
    p = profile_recipe("p", requires=["a", "b"])
    a = cli_recipe("a", detect={"command": FALSE})  # both absent -> installed
    b = cli_recipe("b", detect={"command": FALSE})
    out = _boot(p, a, b, target="p")
    assert out["ok"] is True
    assert [r["recipe"] for r in out["requires"]] == ["a", "b"]
    assert all(r["ok"] for r in out["requires"])


def test_profile_runs_none_of_its_own_lifecycle_phases():
    p = profile_recipe("p", requires=["a"])
    a = cli_recipe("a", detect={"command": TRUE})
    out = _boot(p, a, target="p")
    assert out["ok"] is True
    # a profile has no detect/install/configure/verify of its own
    assert out["phases"] == {}
    assert "profile" in out["note"].lower()


def test_profile_fails_if_a_member_fails():
    p = profile_recipe("p", requires=["broken"])
    broken = cli_recipe("broken", detect={"command": FALSE},
                        install={"methods": [{"id": "x", "run": FALSE}]})
    out = _boot(p, broken, target="p")
    assert out["ok"] is False
    assert "broken" in out.get("error", "")


def test_profile_dry_run_lists_members_and_runs_nothing():
    p = profile_recipe("p", requires=["a", "b"])
    a = cli_recipe("a")
    b = cli_recipe("b")
    out = _boot(p, a, b, target="p", dry_run=True)
    assert out["dry_run"] is True
    assert out["plan"]["requires"] == ["a", "b"]
    assert out["phases"] == {}


def test_profile_appears_in_list_recipes_with_its_kind():
    p = profile_recipe("p", requires=["a"])
    a = cli_recipe("a")
    with registry(p, a):
        recs = {r["id"]: r["kind"] for r in call_tool("list_recipes", {})}
    assert recs.get("p") == "profile"
