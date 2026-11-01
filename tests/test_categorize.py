"""`server._categorize` must always return a CATEGORIES member without crashing on sparse recipes, and a stored `category` must validate and win."""
from __future__ import annotations

import server
from server import CATEGORIES, _categorize, validate_recipe


def _cat(recipe_id: str) -> str:
    return _categorize(server._load_recipe(recipe_id))


# _categorize — always-valid, total function
def test_every_shipped_recipe_gets_a_valid_category():
    for rid in server._recipe_ids():
        recipe = server._load_recipe(rid)
        cat = _categorize(recipe)
        assert cat in CATEGORIES, f"{rid}: {cat!r} not in taxonomy"


def test_categorize_never_crashes_on_sparse_recipe():
    # a recipe missing title/description must still classify (to misc) not raise.
    cat = _categorize({"id": "x", "kind": "cli-tool"})
    assert cat in CATEGORIES


def test_categorize_handles_non_string_fields_gracefully():
    # YAML can hand us odd types; _categorize must coerce, not crash.
    cat = _categorize({"id": "y", "kind": "cli-tool", "title": 123, "description": None})
    assert cat in CATEGORIES


# _categorize — unambiguous anchors classify correctly
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


# stored category — schema validation
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


def test_valid_stored_category_accepted():
    assert validate_recipe(_base(category="search"), stem="demo") == []


def test_stored_category_must_be_in_taxonomy():
    errs = validate_recipe(_base(category="not-a-real-category"), stem="demo")
    assert any("category" in e for e in errs)


def test_category_is_optional():
    assert validate_recipe(_base(), stem="demo") == []


def test_stored_category_wins_over_computed():
    # a recipe that would compute to something else, but authored 'security'
    recipe = _base(id="ripgrepish", title="ripgrepish — recursive search",
                   description="fast recursive search", category="security")
    recipe["id"] = "ripgrepish"
    cat = _categorize(recipe)
    assert cat == "security"
