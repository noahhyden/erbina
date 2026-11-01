"""`category` is authored data: validate_recipe requires it as a string in CATEGORIES, and the registry reads it back verbatim."""
from __future__ import annotations

import pytest

import server
from server import CATEGORIES, validate_recipe


def _base(**extra):
    r = {
        "id": "demo",
        "kind": "cli-tool",
        "title": "demo",
        "description": "d",
        "category": "devtools",
        "detect": {"command": "demo --version"},
        "install": {"methods": [{"id": "m", "when": "true", "run": "true"}]},
        "verify": [{"command": "demo --version"}],
    }
    r.update(extra)
    return r


def test_every_shipped_recipe_carries_a_valid_category():
    for rid in server._recipe_ids():
        assert server._load_recipe(rid)["category"] in CATEGORIES, rid


def test_valid_category_accepted():
    assert validate_recipe(_base(category="search"), stem="demo") == []


@pytest.mark.parametrize("bad", ["not-a-real-category", 5, None, ["search"], ""])
def test_category_must_be_in_taxonomy(bad):
    errs = validate_recipe(_base(category=bad), stem="demo")
    assert any("category" in e for e in errs)


def test_category_is_required():
    r = _base()
    del r["category"]
    assert any("category" in e for e in validate_recipe(r, stem="demo"))


def test_profile_and_mcp_recipes_author_their_own_category():
    assert server._load_recipe("modern-unix")["category"] == "profile"
    assert server._load_recipe("fetch")["category"] == "mcp-server"
