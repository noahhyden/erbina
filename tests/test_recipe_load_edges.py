"""Edge cases in recipe loading and validation input types.

A recipe file that parses to something other than a populated mapping (empty
file, comment-only, a top-level list) must be refused with a clear message —
never loaded as a half-recipe that silently no-ops a phase.
"""
from __future__ import annotations

import pytest

import server


def _write(tmp_path, monkeypatch, name, text):
    (tmp_path / f"{name}.yaml").write_text(text)
    monkeypatch.setattr(server, "RECIPES_DIR", tmp_path)


def test_empty_recipe_file_is_refused(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, "empty", "")
    with pytest.raises(ValueError) as exc:
        server._load_recipe("empty")
    assert "malformed" in str(exc.value).lower()


def test_comment_only_recipe_file_is_refused(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, "c", "# just a comment, no content\n")
    with pytest.raises(ValueError):
        server._load_recipe("c")


def test_top_level_list_recipe_is_refused(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, "lst", "- a\n- b\n")
    with pytest.raises(ValueError):
        server._load_recipe("lst")


# --------------------------------------------------------------------------- #
# validate_recipe input-type guards (the very first check)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [None, [1, 2], "a string", 42])
def test_validate_recipe_rejects_non_mapping(bad):
    errs = server.validate_recipe(bad, stem="x")
    assert errs
    assert "mapping" in errs[0].lower()


def test_validate_recipe_non_mapping_short_circuits_to_single_error():
    # a non-dict can't have fields checked, so exactly one (clear) error is best
    assert len(server.validate_recipe(None, stem="x")) == 1


# --------------------------------------------------------------------------- #
# _recipe_ids over a nonexistent RECIPES_DIR
# --------------------------------------------------------------------------- #
def test_recipe_ids_is_empty_when_recipes_dir_is_missing(tmp_path, monkeypatch):
    # contract: a missing RECIPES_DIR yields [] (drives list_recipes/check_updates
    # bulk scans off an empty set). NB: the explicit `if not exists` guard in
    # _recipe_ids is belt-and-suspenders — Path.glob already returns empty on a
    # missing dir — so this test pins the CONTRACT, not that specific guard.
    monkeypatch.setattr(server, "RECIPES_DIR", tmp_path / "no_such_dir")
    assert server._recipe_ids() == []


def test_list_recipes_is_empty_when_recipes_dir_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RECIPES_DIR", tmp_path / "gone")
    from helpers import call_tool
    assert call_tool("list_recipes", {}) == []
