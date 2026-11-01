"""Edge behavior of the read-only tool surface: search_recipes resilience and the bootstrap(dry_run) plan."""
from __future__ import annotations

from helpers import call_tool
from prototype import cli_recipe, registry


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


def test_bootstrap_dryrun_plan_carries_project_dir():
    recipe = cli_recipe("pd")
    with registry(recipe):
        boot = call_tool("bootstrap", {"recipe_id": "pd", "dry_run": True, "project_dir": "/tmp/here"})
    assert boot["plan"]["project_dir"] == "/tmp/here"
