"""Property-style coverage of validate_recipe using the prototype factory.

The base recipes from tests/prototype.py are valid by construction, so the
'clean' direction is a real assertion (not a tautology). Each corruption then
introduces exactly ONE defect and asserts it is surfaced — this is the round-trip
property: valid -> no errors; single-defect -> at least one matching error.

Complements tests/test_validate_recipe.py (which uses hand-built dicts).
"""
from __future__ import annotations

import copy

import pytest

import server
from prototype import cli_recipe, mcp_recipe


def _errs(recipe, stem=None):
    # default the stem to the recipe's own id when present; a corruption that
    # drops 'id' must still be validatable (stem falls back to "").
    return server.validate_recipe(recipe, stem=stem if stem is not None else recipe.get("id", ""))


# --------------------------------------------------------------------------- #
# the clean direction — factory recipes validate with zero errors
# --------------------------------------------------------------------------- #
def test_factory_cli_and_mcp_validate_clean():
    assert _errs(cli_recipe("t")) == []
    assert _errs(mcp_recipe("t")) == []


def test_configure_absent_is_valid_for_cli_tool():
    # configure is optional; a cli-tool without it must still validate.
    r = cli_recipe("t")
    r.pop("configure", None)
    assert _errs(r) == []


# --------------------------------------------------------------------------- #
# single-defect corruptions — each must produce >=1 error naming the problem
# --------------------------------------------------------------------------- #
def _drop(key):
    def f(r):
        r.pop(key, None)
    return f


def _set(path_key, value):
    def f(r):
        r[path_key] = value
    return f


CORRUPTIONS = [
    ("missing id",            _drop("id"),                                   "id"),
    ("bad kind",              _set("kind", "not-a-kind"),                    "kind"),
    ("missing detect",        _drop("detect"),                               "detect"),
    ("empty detect.command",  _set("detect", {"command": "  "}),             "command"),
    ("missing install",       _drop("install"),                              "install"),
    ("empty install.methods", _set("install", {"methods": []}),             "methods"),
    ("method missing run",    _set("install", {"methods": [{"id": "m"}]}),  "run"),
    ("method missing id",     _set("install", {"methods": [{"run": "x"}]}), "id"),
    ("empty verify",          _set("verify", []),                            "verify"),
    ("bad scope",             _set("scope", "nope"),                         "scope"),
    ("unknown top key",       _set("bogus_key", 1),                          "unknown"),
    ("placeholder typo",      _set("verify", [{"command": "x ${scopee}"}]),  "scopee"),
    ("configure empty steps", _set("configure", {"steps": []}),              "steps"),
]


@pytest.mark.parametrize("label,mutate,needle", CORRUPTIONS, ids=[c[0] for c in CORRUPTIONS])
def test_single_defect_is_reported(label, mutate, needle):
    r = cli_recipe("t")
    mutate(r)
    errs = _errs(r)
    assert errs, f"{label}: expected an error, got none"
    assert needle in " ".join(errs).lower() or needle in " ".join(errs), (
        f"{label}: no error mentioned {needle!r}; got {errs}"
    )


def test_id_must_equal_filename_stem():
    r = cli_recipe("realid")
    errs = _errs(r, stem="different_stem")
    assert any("stem" in e for e in errs)


def test_mcp_server_requires_scope_aware_configure():
    # an mcp-server whose configure never references ${scope} is rejected
    r = mcp_recipe("t")
    r["configure"] = {"steps": [{"run": "claude mcp add t -- uvx t"}]}  # no ${scope}
    errs = _errs(r)
    assert any("${scope}" in e for e in errs)


def test_corruptions_are_independent():
    # sanity: the pristine copy each test mutates really was valid to begin with
    base = cli_recipe("t")
    assert _errs(copy.deepcopy(base)) == []
