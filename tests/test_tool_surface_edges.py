"""Edge behavior of the read-only tool surface: list_recipes resilience and the
inspect_recipe / bootstrap(dry_run) plan-parity contract.
"""
from __future__ import annotations

import pytest

from helpers import call_tool
from prototype import cli_recipe, mcp_recipe, registry


# --------------------------------------------------------------------------- #
# list_recipes must not blow up on a malformed recipe sitting in the dir — it
# skips it and still returns the valid ones.
# --------------------------------------------------------------------------- #
def test_list_recipes_skips_a_malformed_recipe():
    with registry(cli_recipe("good")) as tmp:
        # a second file that fails validation (bad kind, no detect/install/verify)
        (tmp / "broken.yaml").write_text("id: broken\nkind: not-a-kind\n")
        ids = {r["id"] for r in call_tool("list_recipes", {})}
    assert ids == {"good"}  # broken silently skipped, good still listed


def test_list_recipes_tolerates_unparseable_yaml():
    with registry(cli_recipe("good")) as tmp:
        (tmp / "garbage.yaml").write_text("id: [unterminated\n  : :\n")
        ids = {r["id"] for r in call_tool("list_recipes", {})}
    assert "good" in ids


# --------------------------------------------------------------------------- #
# plan parity: inspect_recipe.will_run and bootstrap(dry_run).plan must be the
# SAME plan — both are the consent surface and must never diverge.
# --------------------------------------------------------------------------- #
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
