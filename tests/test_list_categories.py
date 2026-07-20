"""Tool-surface tests for `list_categories` — the registry's domain map.

Driven through the in-memory FastMCP client. Read-only.
"""
from __future__ import annotations

from helpers import call_tool

from server import CATEGORIES


def test_list_categories_shape():
    out = call_tool("list_categories", {})
    assert out["count"] == len(out["categories"])
    for c in out["categories"]:
        assert c["category"] in CATEGORIES
        assert c["count"] >= 1
        assert isinstance(c["examples"], list)
        assert len(c["examples"]) <= 5
        # examples are real recipe ids drawn from that category
        assert all(isinstance(e, str) for e in c["examples"])


def test_counts_sum_to_every_recipe():
    # each recipe has exactly one category, so the counts partition the registry.
    cats = call_tool("list_categories", {})
    total = sum(c["count"] for c in cats["categories"])
    assert total == len(call_tool("list_recipes", {}))


def test_only_nonempty_categories_are_listed():
    out = call_tool("list_categories", {})
    assert all(c["count"] >= 1 for c in out["categories"])
    # no duplicate category rows
    names = [c["category"] for c in out["categories"]]
    assert len(names) == len(set(names))


def test_sorted_by_count_descending():
    out = call_tool("list_categories", {})
    counts = [c["count"] for c in out["categories"]]
    assert counts == sorted(counts, reverse=True)


def test_counts_agree_with_search_recipes_filter():
    cats = {c["category"]: c["count"] for c in call_tool("list_categories", {})["categories"]}
    for cat in ("kubernetes", "search", "profile", "mcp-server"):
        filtered = call_tool("search_recipes", {"category": cat})
        assert cats[cat] == filtered["count"], cat


def test_examples_belong_to_their_category():
    all_ids = {r["id"] for r in call_tool("list_recipes", {})}
    for c in call_tool("list_categories", {})["categories"]:
        for ex in c["examples"]:
            assert ex in all_ids
        # and each example really is in that category
        got = call_tool("search_recipes", {"category": c["category"], "limit": 1000})
        ids_in_cat = {r["id"] for r in got["results"]}
        assert set(c["examples"]) <= ids_in_cat
