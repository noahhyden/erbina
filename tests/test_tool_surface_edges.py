"""Edge behavior of the read-only tool surface: search_recipes resilience and inspect_recipe / bootstrap(dry_run) plan parity."""
from __future__ import annotations

import pytest

from helpers import call_tool
from prototype import cli_recipe, mcp_recipe, registry


# search_recipes must skip a malformed recipe in the dir and still return the valid ones.
def test_search_recipes_skips_a_malformed_recipe():
    with registry(cli_recipe("good")) as tmp:
        # a second file that fails validation (bad kind, no detect/install/verify)
        (tmp / "broken.yaml").write_text("id: broken\nkind: not-a-kind\n")
        ids = {r["id"] for r in call_tool("search_recipes", {"limit": 1000})["results"]}
    assert ids == {"good"}  # broken silently skipped, good still listed


def test_search_recipes_tolerates_unparseable_yaml():
    with registry(cli_recipe("good")) as tmp:
        (tmp / "garbage.yaml").write_text("id: [unterminated\n  : :\n")
        ids = {r["id"] for r in call_tool("search_recipes", {"limit": 1000})["results"]}
    assert "good" in ids


# Plan parity: inspect_recipe.will_run and bootstrap(dry_run).plan are both the consent surface and must be the SAME plan.
@pytest.mark.parametrize("recipe_id,scope", [
    ("ataegina", "user"),
    ("fetch", "project"),
    ("fetch", "local"),
    ("fetch", "user"),
])
def test_inspect_and_bootstrap_dryrun_plans_agree_real(recipe_id, scope):
    insp = call_tool("inspect_recipe", {"recipe_id": recipe_id, "scope": scope})["will_run"]
    boot = call_tool("bootstrap", {"recipe_id": recipe_id, "scope": scope, "dry_run": True})["plan"]
    assert insp == boot


@pytest.mark.parametrize("factory", [cli_recipe, mcp_recipe])
def test_inspect_and_bootstrap_dryrun_plans_agree_prototype(factory):
    recipe = factory("parity")
    with registry(recipe):
        insp = call_tool("inspect_recipe", {"recipe_id": "parity", "scope": "user"})["will_run"]
        boot = call_tool("bootstrap", {"recipe_id": "parity", "scope": "user", "dry_run": True})["plan"]
    assert insp == boot


def test_bootstrap_dryrun_plan_carries_project_dir():
    recipe = cli_recipe("pd")
    with registry(recipe):
        boot = call_tool("bootstrap", {"recipe_id": "pd", "dry_run": True, "project_dir": "/tmp/here"})
    assert boot["plan"]["project_dir"] == "/tmp/here"
