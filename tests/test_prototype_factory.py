"""Self-tests for tests/prototype.py: prototypes validate clean and `registry()` restores the real registry."""
from __future__ import annotations

import server
from helpers import call_tool
from prototype import cli_recipe, mcp_recipe, registry


def test_factory_recipes_validate_clean():
    assert server.validate_recipe(cli_recipe(), stem="proto") == []
    assert server.validate_recipe(mcp_recipe(), stem="proto_mcp") == []


def test_registry_restores_recipes_dir_afterward():
    before = server.RECIPES_DIR
    with registry(cli_recipe("delta")):
        assert server.RECIPES_DIR != before
    assert server.RECIPES_DIR == before
    ids = {r["id"] for r in call_tool("search_recipes", {"limit": 1000})["results"]}
    assert "ataegina" in ids
