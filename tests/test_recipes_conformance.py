"""Registry policy applied to EVERY recipes/*.yaml (stricter than `validate_recipe`), discovered dynamically so new recipes opt in automatically."""
from __future__ import annotations

import graphlib

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
def test_recipe_meets_registry_policy(rid):
    # Non-empty title and description plus a `when:` guard on every install method; single source is server.lint_recipe_policy.
    recipe = server._load_recipe(rid)
    problems = server.lint_recipe_policy(recipe)
    assert problems == [], f"{rid}: {problems}"


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
def test_recipe_requires_reference_existing_recipes(rid):
    # A `requires:` entry must name a shipped recipe, else bootstrap fails at runtime on a dangling prerequisite.
    recipe = server._load_recipe(rid)
    for dep in recipe.get("requires") or []:
        assert dep in RECIPE_IDS, f"{rid}: requires unknown recipe {dep!r}"


def test_requires_graph_has_no_cycles():
    # Build the whole requires DAG and assert it is acyclic; the registry must never ship a cycle.
    graph = {rid: (server._load_recipe(rid).get("requires") or []) for rid in RECIPE_IDS}
    try:
        graphlib.TopologicalSorter(graph).prepare()
    except graphlib.CycleError as e:
        pytest.fail(f"requires cycle: {' -> '.join(map(str, e.args[1]))}")


@pytest.mark.parametrize("rid", RECIPE_IDS)
def test_recipe_plan_leaves_no_unexpanded_placeholder(rid):
    # After substitution the plan must contain no literal ${...}, or a stray placeholder would be shelled out verbatim.
    for scope in ("user", "project", "local"):
        plan = call_tool(
            "bootstrap", {"recipe_id": rid, "scope": scope, "project_dir": "/tmp/proj", "dry_run": True}
        )["plan"]
        assert "${" not in repr(plan), f"{rid} @ {scope}: unexpanded placeholder in plan"
