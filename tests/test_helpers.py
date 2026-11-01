"""Unit tests for `_subst`, the `_load_recipe` traversal guard."""
from __future__ import annotations

import pytest

import server


# _subst
def test_subst_expands_scope():
    out = server._subst("claude mcp add x --scope ${scope}", "project", None)
    assert out == "claude mcp add x --scope project"


def test_subst_expands_project_dir():
    out = server._subst("cd ${project_dir} && go", "user", "/repos/thing")
    assert out == "cd /repos/thing && go"


def test_subst_missing_project_dir_falls_back_to_dot():
    # The documented fallback (per the code) is '.' when project_dir is None.
    out = server._subst("run in ${project_dir}", "user", None)
    assert out == "run in ."


def test_subst_expands_both_placeholders_together():
    out = server._subst(
        "claude mcp add f --scope ${scope} in ${project_dir}", "local", "/tmp/p"
    )
    assert out == "claude mcp add f --scope local in /tmp/p"


def test_subst_none_command_returns_empty_string():
    assert server._subst(None, "user", None) == ""


# _load_recipe path-traversal guard (helper level)
@pytest.mark.parametrize("bad_id", ["../server", "../../etc/passwd", "/etc/passwd", "..%2f..%2fetc"])
def test_load_recipe_rejects_traversal(bad_id):
    # Path(recipe_id).name drops directory parts, so a traversal id becomes a basename with no <name>.yaml -> FileNotFoundError.
    with pytest.raises(FileNotFoundError) as exc:
        server._load_recipe(bad_id)
    # The error names the missing recipe, not a system file's contents.
    assert "no recipe" in str(exc.value).lower()


def test_load_recipe_loads_real_recipe():
    r = server._load_recipe("ataegina")
    assert r["id"] == "ataegina"
    assert r["kind"] == "cli-tool"
