"""Self-tests for the prototype factory (tests/prototype.py).

A test harness that lies about its own fixtures is worse than none: these guard
the factory itself. They prove the synthetic recipes are genuinely VALID (so a
later behavioral test can't 'pass' merely because erbina rejected a malformed
prototype), that `registry()` actually swaps the recipe registry, and that it
restores it afterward (no leakage into other tests).
"""
from __future__ import annotations

import server
from helpers import call_tool, list_tool_names
from prototype import cli_recipe, mcp_recipe, registry


def test_factory_recipes_validate_clean():
    # If a prototype didn't validate, _load_recipe would refuse it and every
    # behavioral test built on it would be exercising the error path by accident.
    assert server.validate_recipe(cli_recipe(), stem="proto") == []
    assert server.validate_recipe(mcp_recipe(), stem="proto_mcp") == []


def test_registry_exposes_only_the_prototypes():
    with registry(cli_recipe("alpha"), mcp_recipe("beta")):
        ids = {r["id"] for r in call_tool("list_recipes", {})}
        assert ids == {"alpha", "beta"}
        # and the real registry entries are NOT visible while swapped
        assert "ataegina" not in ids
        assert "fetch" not in ids


def test_registry_recipes_load_through_the_real_tool_surface():
    with registry(cli_recipe("gamma")):
        out = call_tool("inspect_recipe", {"recipe_id": "gamma"})
    assert "error" not in out
    assert out["id"] == "gamma"
    assert out["kind"] == "cli-tool"
    # the plan reflects the prototype's (builtin) commands verbatim
    assert out["will_run"]["detect"] == "true"


def test_registry_restores_recipes_dir_afterward():
    before = server.RECIPES_DIR
    with registry(cli_recipe("delta")):
        assert server.RECIPES_DIR != before
    assert server.RECIPES_DIR == before
    # sanity: the real recipes are visible again once the block exits
    ids = {r["id"] for r in call_tool("list_recipes", {})}
    assert "ataegina" in ids


def test_registry_restores_even_on_exception():
    before = server.RECIPES_DIR
    try:
        with registry(cli_recipe("epsilon")):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert server.RECIPES_DIR == before


def test_prototypes_do_not_disturb_the_tool_registry():
    # Swapping RECIPES_DIR must not change which tools are registered.
    with registry(cli_recipe("zeta")):
        assert "bootstrap" in list_tool_names()


def test_registry_nesting_restores_each_layer():
    original = server.RECIPES_DIR
    with registry(cli_recipe("outer")):
        outer_dir = server.RECIPES_DIR
        assert {r["id"] for r in call_tool("list_recipes", {})} == {"outer"}
        with registry(cli_recipe("inner")):
            assert {r["id"] for r in call_tool("list_recipes", {})} == {"inner"}
        # inner exit restores the OUTER registry, not the original
        assert server.RECIPES_DIR == outer_dir
        assert {r["id"] for r in call_tool("list_recipes", {})} == {"outer"}
    assert server.RECIPES_DIR == original


def test_registry_with_no_recipes_is_empty():
    with registry():
        assert call_tool("list_recipes", {}) == []


def test_registry_with_many_recipes_lists_all():
    protos = [cli_recipe(f"r{i}") for i in range(5)]
    with registry(*protos):
        ids = {r["id"] for r in call_tool("list_recipes", {})}
    assert ids == {f"r{i}" for i in range(5)}
