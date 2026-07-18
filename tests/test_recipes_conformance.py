"""Conformance / hardening tests applied to EVERY recipe in recipes/.

These are stricter than `validate_recipe` (the schema contract): they encode
curated-registry *policy* so a new recipe can't ship half-baked. Every recipe
file is discovered dynamically, so adding recipes/<id>.yaml automatically opts it
into all of these checks.
"""
from __future__ import annotations

import pytest

import server
from helpers import call_tool

# discovered once, from the real recipes/ dir (RECIPES_DIR isn't monkeypatched here)
RECIPE_IDS = server._recipe_ids()


def test_registry_is_not_empty():
    assert RECIPE_IDS, "no recipes found in recipes/"


@pytest.mark.parametrize("rid", RECIPE_IDS)
def test_recipe_loads_and_validates_clean(rid):
    recipe = server._load_recipe(rid)  # raises if malformed
    recipe.pop("_path", None)
    assert server.validate_recipe(recipe, stem=rid) == []
    assert recipe["id"] == rid  # id equals the filename stem


@pytest.mark.parametrize("rid", RECIPE_IDS)
def test_recipe_has_human_title_and_description(rid):
    recipe = server._load_recipe(rid)
    assert isinstance(recipe.get("title"), str) and recipe["title"].strip(), f"{rid}: needs a title"
    assert isinstance(recipe.get("description"), str) and recipe["description"].strip(), (
        f"{rid}: needs a description"
    )


@pytest.mark.parametrize("rid", RECIPE_IDS)
def test_every_install_method_is_guarded(rid):
    # Never run a package manager unconditionally — each method must gate on a
    # `when:` guard (e.g. `command -v brew`) so it only fires where it applies.
    recipe = server._load_recipe(rid)
    for m in recipe["install"]["methods"]:
        assert isinstance(m.get("when"), str) and m["when"].strip(), (
            f"{rid}: install method {m.get('id')!r} needs a `when:` guard"
        )


@pytest.mark.parametrize("rid", RECIPE_IDS)
def test_mcp_server_recipe_is_scope_aware(rid):
    recipe = server._load_recipe(rid)
    if recipe["kind"] != "mcp-server":
        pytest.skip("cli-tool recipe")
    steps = recipe.get("configure", {}).get("steps", [])
    assert any("${scope}" in (s.get("run") or "") for s in steps), (
        f"{rid}: mcp-server must wire with --scope ${{scope}}"
    )


@pytest.mark.parametrize("rid", RECIPE_IDS)
def test_recipe_plan_leaves_no_unexpanded_placeholder(rid):
    # After substitution the consent-surface plan must contain no literal ${...}
    # (a stray/unknown placeholder would otherwise be shelled out verbatim).
    for scope in ("user", "project", "local"):
        plan = call_tool(
            "inspect_recipe", {"recipe_id": rid, "scope": scope, "project_dir": "/tmp/proj"}
        )["will_run"]
        assert "${" not in repr(plan), f"{rid} @ {scope}: unexpanded placeholder in plan"
