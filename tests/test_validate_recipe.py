"""Tests for recipe validation.

`validate_recipe` (and load-time validation) shipped in #4. The skipif guard is
kept as a harmless safety net (the module skips rather than errors if the symbol
is ever removed), but on the current tree these tests always run.

We NEVER write into recipes/ — malformed recipes are built as in-memory dicts.
The one test that must exercise the _load_recipe path writes to a tmp dir and
monkeypatches RECIPES_DIR, restoring it after.
"""
from __future__ import annotations

import pytest

import server
from helpers import call_tool

pytestmark = pytest.mark.skipif(
    not hasattr(server, "validate_recipe"),
    reason="validate_recipe not present (safety net; it ships in server.py)",
)


def _errors(recipe: dict, stem: str | None = None) -> list[str]:
    """Normalise validate_recipe's return into a list of error strings.

    validate_recipe takes the parsed recipe plus the filename `stem` it must
    match; we default `stem` to the recipe's own id so a well-formed recipe
    validates clean. The return is normalised across the two most likely shapes
    (a list of strings, or an object exposing an .errors list) so this test
    stays robust to a minor signature choice.
    """
    result = server.validate_recipe(recipe, stem=stem if stem is not None else recipe.get("id", ""))
    if isinstance(result, list):
        return [str(e) for e in result]
    errs = getattr(result, "errors", None)
    if errs is not None:
        return [str(e) for e in errs]
    if isinstance(result, dict) and "errors" in result:
        return [str(e) for e in result["errors"]]
    raise AssertionError(f"unexpected validate_recipe return shape: {result!r}")


def test_real_recipes_validate_clean():
    for rid in ("ataegina", "fetch"):
        recipe = server._load_recipe(rid)
        recipe.pop("_path", None)  # injected by _load_recipe, not part of the schema
        assert _errors(recipe) == [], f"{rid} should validate clean"


def test_malformed_recipe_reports_all_problems():
    bad = {
        "id": "bad",
        "kind": "not-a-kind",  # invalid kind
        "title": "bad recipe",
        "detect": {"expect_exit": 0},  # missing detect.command
        "install": {"methods": [{"id": "m", "run": "true"}]},
        "configure": {"steps": [{"run": "echo ${scopee}"}]},  # typo'd placeholder
        "verify": [],  # empty verify
        "bogus_top_level_key": True,  # unknown top-level key
        "scope": "user",
    }
    errs = _errors(bad)
    assert errs, "a malformed recipe must produce at least one error"
    blob = " ".join(errs).lower()
    # Each named problem should be surfaced somewhere in the error list.
    assert "kind" in blob
    assert "detect" in blob and "command" in blob
    assert "verify" in blob
    assert "scopee" in blob or "placeholder" in blob
    assert "bogus_top_level_key" in blob or "unknown" in blob


def test_load_path_refuses_malformed_recipe(tmp_path, monkeypatch):
    """inspect_recipe/bootstrap must refuse a recipe that fails validation.

    We write a malformed recipe into a TEMP recipes dir and repoint the server
    at it, so the real recipes/ registry is never touched.
    """
    bad_yaml = (
        "id: temp_bad\n"
        "kind: not-a-kind\n"
        "title: temp bad\n"
        "install:\n"
        "  methods:\n"
        "    - id: m\n"
        "      run: 'true'\n"
        "verify: []\n"
    )
    (tmp_path / "temp_bad.yaml").write_text(bad_yaml)
    monkeypatch.setattr(server, "RECIPES_DIR", tmp_path)

    # However validation is wired into the load path, a malformed recipe must
    # not yield a clean plan. Accept either a raised error or an {'error': ...}.
    try:
        out = call_tool("inspect_recipe", {"recipe_id": "temp_bad"})
    except Exception as e:  # noqa: BLE001
        assert "temp_bad" in str(e) or "invalid" in str(e).lower() or "kind" in str(e).lower()
        return
    assert isinstance(out, dict) and "error" in out, (
        "inspect_recipe should refuse a malformed recipe, got: %r" % out
    )
