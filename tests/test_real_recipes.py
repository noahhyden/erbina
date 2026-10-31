"""Dry-run plan coverage of the shipped recipes (ataegina, fetch), so a recipe or `_plan`/`_subst` change cannot alter the consent surface silently."""
from __future__ import annotations

import pytest

from helpers import call_tool

SCOPES = ("local", "project", "user")


# ataegina — a cli-tool recipe
def test_ataegina_plan_shape():
    plan = call_tool("inspect_recipe", {"recipe_id": "ataegina"})["will_run"]
    assert plan["detect"] == "ataegina --version"
    # both install methods are surfaced, in order (brew preferred, curl fallback)
    ids = [m["id"] for m in plan["install"]["all_methods"]]
    assert ids == ["homebrew", "curl"]
    # verify names the runtime checks verbatim
    assert "ataegina --version" in plan["verify"]


def test_ataegina_configure_step_carries_needs_project_dir():
    plan = call_tool("inspect_recipe", {"recipe_id": "ataegina"})["will_run"]
    steps = plan["configure"]
    assert len(steps) == 1
    step = steps[0]
    assert step["run"] == "ataegina init --yes"
    # the plan must carry the flags bootstrap acts on (skip when no project_dir)
    assert step["needs_project_dir"] is True
    assert step["optional"] is True


def test_ataegina_cli_recipe_has_no_scope_placeholder():
    # a cli-tool's plan should not contain an unsubstituted ${scope}
    plan = call_tool("inspect_recipe", {"recipe_id": "ataegina", "scope": "project"})["will_run"]
    blob = repr(plan)
    assert "${scope}" not in blob


# fetch — an mcp-server recipe (scope-aware wiring)
@pytest.mark.parametrize("scope", SCOPES)
def test_fetch_configure_substitutes_each_scope(scope):
    out = call_tool("bootstrap", {"recipe_id": "fetch", "scope": scope, "dry_run": True})
    joined = " ".join(s["run"] for s in out["plan"]["configure"])
    assert f"--scope {scope}" in joined
    assert "${scope}" not in joined
    # dry-run really executed nothing
    assert out["phases"] == {}


def test_fetch_configure_command_is_the_expected_wiring():
    out = call_tool("bootstrap", {"recipe_id": "fetch", "scope": "user", "dry_run": True})
    runs = [s["run"] for s in out["plan"]["configure"]]
    assert runs == ["claude mcp add fetch --scope user -- uvx mcp-server-fetch"]


def test_fetch_detect_and_verify_need_project_dir():
    # Project-scope wiring lands in <project_dir>/.mcp.json, so detect and verify must run inside project_dir.
    out = call_tool("inspect_recipe", {"recipe_id": "fetch"})
    # detect command is surfaced verbatim
    assert out["will_run"]["detect"] == "claude mcp get fetch"
    # configure step carries needs_project_dir (bootstrap skips it without one)
    assert out["will_run"]["configure"][0]["needs_project_dir"] is True
