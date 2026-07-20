"""Tool-surface tests for `search_recipes` and the enriched `list_recipes`.

Driven through the in-memory FastMCP client, exactly as an agent would query the
registry. Read-only — nothing installs or wires anything.
"""
from __future__ import annotations

from helpers import call_tool

from server import CATEGORIES


# --------------------------------------------------------------------------- #
# list_recipes is now enriched with category + tags
# --------------------------------------------------------------------------- #
def test_list_recipes_includes_category_and_tags_for_every_recipe():
    recipes = call_tool("list_recipes", {})
    assert recipes
    for r in recipes:
        assert r["category"] in CATEGORIES, f"{r['id']}: bad category {r['category']!r}"
        assert isinstance(r["tags"], list)
        assert all(isinstance(t, str) for t in r["tags"])


# --------------------------------------------------------------------------- #
# search_recipes — query relevance
# --------------------------------------------------------------------------- #
def _ids(results):
    return [r["id"] for r in results["results"]]


def test_search_by_keyword_surfaces_matching_tool():
    out = call_tool("search_recipes", {"query": "recursive search"})
    assert out["count"] >= 1
    assert "ripgrep" in _ids(out)


def test_search_by_json_surfaces_json_tools():
    out = call_tool("search_recipes", {"query": "json"})
    ids = _ids(out)
    assert "jq" in ids


def test_query_match_in_id_or_title_outranks_description_only():
    # "hyperfine" appears in its own id/title; it should rank first for that query.
    out = call_tool("search_recipes", {"query": "hyperfine"})
    assert _ids(out)[0] == "hyperfine"


def test_search_results_carry_full_metadata():
    out = call_tool("search_recipes", {"query": "kubernetes"})
    assert out["results"]
    r = out["results"][0]
    for key in ("id", "kind", "title", "description", "category", "tags", "score"):
        assert key in r


# --------------------------------------------------------------------------- #
# search_recipes — filters
# --------------------------------------------------------------------------- #
def test_category_filter_returns_only_that_category():
    out = call_tool("search_recipes", {"category": "kubernetes"})
    ids = _ids(out)
    assert "kubectl" in ids
    assert all(r["category"] == "kubernetes" for r in out["results"])


def test_kind_filter_returns_only_that_kind():
    out = call_tool("search_recipes", {"kind": "profile"})
    assert out["results"]
    assert all(r["kind"] == "profile" for r in out["results"])


def test_query_and_filter_compose():
    out = call_tool("search_recipes", {"query": "search", "kind": "cli-tool"})
    assert all(r["kind"] == "cli-tool" for r in out["results"])
    assert "ripgrep" in _ids(out)


def test_empty_query_no_filter_returns_everything():
    all_recipes = call_tool("list_recipes", {})
    out = call_tool("search_recipes", {})
    assert out["count"] == len(all_recipes)


def test_limit_caps_result_count():
    out = call_tool("search_recipes", {"limit": 3})
    assert len(out["results"]) <= 3
    # count reflects total matches, not the truncated page
    assert out["count"] >= len(out["results"])


# --------------------------------------------------------------------------- #
# search_recipes — bad input
# --------------------------------------------------------------------------- #
def test_invalid_category_is_rejected():
    out = call_tool("search_recipes", {"category": "bogus"})
    assert "error" in out
    assert "category" in out["error"]


def test_invalid_kind_is_rejected():
    out = call_tool("search_recipes", {"kind": "bogus"})
    assert "error" in out
    assert "kind" in out["error"]


def test_no_match_returns_empty_not_error():
    out = call_tool("search_recipes", {"query": "zzzzz-nonexistent-tool-qqqq"})
    assert out["count"] == 0
    assert out["results"] == []
