"""Unit tests for the recipe taxonomy: `server._categorize` and the optional
stored `category`/`tags` schema fields.

`_categorize` is the computed FALLBACK that gives every recipe a category and a
set of search tags even when the YAML doesn't author them. It must:
  * always return a category from the closed `CATEGORIES` taxonomy,
  * never crash on a sparse/odd recipe dict (it feeds list_recipes/search_recipes,
    which must not blow up on one weird file),
  * classify obvious, unambiguous tools correctly.

The schema half asserts that stored `category`/`tags` are validated (closed
taxonomy, list-of-strings) and that a stored value WINS over the computed one.
"""
from __future__ import annotations

import server
from server import CATEGORIES, _categorize, validate_recipe


def _cat(recipe_id: str) -> str:
    return _categorize(server._load_recipe(recipe_id))[0]


# --------------------------------------------------------------------------- #
# _categorize — always-valid, total function
# --------------------------------------------------------------------------- #
def test_every_shipped_recipe_gets_a_valid_category_and_tag_list():
    for rid in server._recipe_ids():
        recipe = server._load_recipe(rid)
        cat, tags = _categorize(recipe)
        assert cat in CATEGORIES, f"{rid}: {cat!r} not in taxonomy"
        assert isinstance(tags, list)
        assert all(isinstance(t, str) and t for t in tags)
        # the recipe's own id is always a searchable tag
        assert rid in tags


def test_categorize_never_crashes_on_sparse_recipe():
    # a recipe missing title/description must still classify (to misc) not raise.
    cat, tags = _categorize({"id": "x", "kind": "cli-tool"})
    assert cat in CATEGORIES
    assert isinstance(tags, list)


def test_categorize_handles_non_string_fields_gracefully():
    # YAML can hand us odd types; _categorize must coerce, not crash.
    cat, tags = _categorize({"id": "y", "kind": "cli-tool", "title": 123, "description": None})
    assert cat in CATEGORIES


# --------------------------------------------------------------------------- #
# _categorize — unambiguous anchors classify correctly
# --------------------------------------------------------------------------- #
def test_kind_drives_profile_and_mcp_categories():
    assert _cat("modern-unix") == "profile"
    assert _cat("fetch") == "mcp-server"


def test_anchor_classifications():
    expected = {
        "ripgrep": "search",
        "fzf": "search",
        "kubectl": "kubernetes",
        "k9s": "kubernetes",
        "helm": "kubernetes",
        "gitui": "git",
        "lazygit": "git",
        "jq": "data",
        "yq": "data",
        "httpie": "http",
        "xh": "http",
        "hyperfine": "benchmarking",
        "ffmpeg": "media",
    }
    for rid, cat in expected.items():
        assert _cat(rid) == cat, f"{rid} should categorize as {cat}, got {_cat(rid)}"


def test_tags_include_replaced_classic_tool():
    # ripgrep's blurb calls out grep-style recursive search; a user searching
    # "grep" should be able to find it via tags.
    _, tags = _categorize(server._load_recipe("ripgrep"))
    assert "search" in tags


# --------------------------------------------------------------------------- #
# stored category/tags — schema validation
# --------------------------------------------------------------------------- #
def _base(**extra):
    r = {
        "id": "demo",
        "kind": "cli-tool",
        "title": "demo",
        "description": "d",
        "detect": {"command": "demo --version"},
        "install": {"methods": [{"id": "m", "when": "true", "run": "true"}]},
        "verify": [{"command": "demo --version"}],
    }
    r.update(extra)
    return r


def test_valid_stored_category_and_tags_accepted():
    assert validate_recipe(_base(category="search", tags=["grep", "find"]), stem="demo") == []


def test_stored_category_must_be_in_taxonomy():
    errs = validate_recipe(_base(category="not-a-real-category"), stem="demo")
    assert any("category" in e for e in errs)


def test_stored_tags_must_be_a_list_of_nonempty_strings():
    assert any("tags" in e for e in validate_recipe(_base(tags="grep"), stem="demo"))
    assert any("tags" in e for e in validate_recipe(_base(tags=[1, 2]), stem="demo"))
    assert any("tags" in e for e in validate_recipe(_base(tags=[""]), stem="demo"))


def test_category_and_tags_are_optional():
    assert validate_recipe(_base(), stem="demo") == []


def test_stored_category_wins_over_computed():
    # a recipe that would compute to something else, but authored 'security'
    recipe = _base(id="ripgrepish", title="ripgrepish — recursive search",
                   description="fast recursive search", category="security")
    recipe["id"] = "ripgrepish"
    cat, _ = _categorize(recipe)
    assert cat == "security"
