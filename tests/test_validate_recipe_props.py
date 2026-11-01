"""Property-style `validate_recipe` coverage on prototype factory recipes (valid by construction, so clean is a real assertion); each corruption adds ONE defect and must surface an error."""
from __future__ import annotations

import copy

import pytest

import server
from prototype import cli_recipe, mcp_recipe


def _errs(recipe, stem=None):
    # Default the stem to the recipe id when present; a corruption that drops 'id' must still validate (stem falls back to "").
    return server.validate_recipe(recipe, stem=stem if stem is not None else recipe.get("id", ""))


# the clean direction — factory recipes validate with zero errors
def test_factory_cli_and_mcp_validate_clean():
    assert _errs(cli_recipe("t")) == []
    assert _errs(mcp_recipe("t")) == []


def test_configure_absent_is_valid_for_cli_tool():
    # configure is optional; a cli-tool without it must still validate.
    r = cli_recipe("t")
    r.pop("configure", None)
    assert _errs(r) == []


# single-defect corruptions — each must produce >=1 error naming the problem
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


# WHITESPACE-only fields must be rejected like empty ones: dropping any `.strip()` in the non-empty checks survived mutation testing without this coverage.
@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r.__setitem__("install", {"methods": [{"id": "  ", "run": "true"}]}), "id"),
    (lambda r: r.__setitem__("install", {"methods": [{"id": "m", "run": "   "}]}), "run"),
    (lambda r: r.__setitem__("configure", {"steps": [{"run": "\t"}]}), "run"),
    (lambda r: r.__setitem__("verify", [{"command": "  "}]), "command"),
    (lambda r: r.__setitem__("detect", {"command": "\n "}), "command"),
])
def test_whitespace_only_field_is_rejected_like_empty(mutate, needle):
    r = cli_recipe("t")
    mutate(r)
    errs = _errs(r)
    assert errs, "whitespace-only value should be rejected"
    assert needle in " ".join(errs)


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


# version block (optional; powers check_updates)
def test_valid_version_block_validates_clean():
    r = cli_recipe("t", version={"current": "t --version", "latest": {"github": "o/t"}})
    assert _errs(r) == []


@pytest.mark.parametrize("version,needle", [
    ("not-a-mapping", "version"),
    ({"latest": {"github": "o/t"}}, "current"),          # missing current
    ({"current": "t --version"}, "latest"),     # missing latest
    ({"current": "  ", "latest": {"github": "o/t"}}, "current"),  # blank current
    ({"current": "echo ${scopee}", "latest": {"github": "o/t"}}, "scopee"),  # bad placeholder
])
def test_bad_version_block_is_reported(version, needle):
    r = cli_recipe("t", version=version)
    errs = _errs(r)
    assert errs, f"version={version!r} should error"
    assert needle in " ".join(errs)


# update block (optional; powers the update tool)
def test_valid_update_block_validates_clean():
    r = cli_recipe("t", update={"methods": [{"id": "u", "run": "brew upgrade t"}]})
    assert _errs(r) == []


@pytest.mark.parametrize("update,needle", [
    ("not-a-mapping", "update"),
    ({"methods": []}, "methods"),                          # empty methods
    ({"methods": [{"run": "x"}]}, "id"),                   # method missing id
    ({"methods": [{"id": "u"}]}, "run"),                   # method missing run
    ({"methods": [{"id": "u", "run": "echo ${scopee}"}]}, "scopee"),  # bad placeholder
])
def test_bad_update_block_is_reported(update, needle):
    r = cli_recipe("t", update=update)
    errs = _errs(r)
    assert errs, f"update={update!r} should error"
    assert needle in " ".join(errs)


def test_corruptions_are_independent():
    # sanity: the pristine copy each test mutates really was valid to begin with
    base = cli_recipe("t")
    assert _errs(copy.deepcopy(base)) == []


# Never-raise contract: validate_recipe returns error strings for ANY input (shared by _load_recipe and lint_recipes.py), so hostile field VALUES must give errors not exceptions (non-string KEYS: finding #6).
_HOSTILE_VALUES = [
    None, 0, 1, -1, True, False, 1.5, "", "  ", "x", [], {}, [1, 2], {"a": 1},
    {"nested": {"deep": [None]}}, ["a", "b"], (1, 2), b"bytes", [[[]]], {"": ""},
    float("inf"),
]


@pytest.mark.parametrize("field", [
    "id", "kind", "title", "description", "detect", "install", "configure",
    "verify", "version", "update", "scope",
])
def test_validate_never_raises_on_a_hostile_field_value(field):
    base = cli_recipe("t")
    for val in _HOSTILE_VALUES:
        r = copy.deepcopy(base)
        r[field] = val
        out = server.validate_recipe(r, stem="t")
        assert isinstance(out, list), f"{field}={val!r}: expected list, got {type(out)}"


@pytest.mark.parametrize("bad", [None, 0, 1.5, True, "str", [], [1, 2], (1,), b"x"])
def test_validate_never_raises_on_a_non_mapping_recipe(bad):
    out = server.validate_recipe(bad, stem="t")
    assert isinstance(out, list) and out  # a non-mapping is reported, not crashed


@pytest.mark.parametrize("hostile_step", _HOSTILE_VALUES)
def test_validate_never_raises_on_a_hostile_nested_member(hostile_step):
    # a hostile element inside install.methods / verify / configure.steps
    for setter in (
        lambda r: r["install"].__setitem__("methods", [hostile_step]),
        lambda r: r.__setitem__("verify", [hostile_step]),
        lambda r: r.__setitem__("configure", {"steps": [hostile_step]}),
    ):
        r = cli_recipe("t")
        setter(r)
        out = server.validate_recipe(r, stem="t")
        assert isinstance(out, list)


# Finding #6 (FIXED): a non-string top-level key (YAML `2024: hi`) crashed validate_recipe at `sorted(unknown)` with TypeError; keys now go through str() and report as unknown.
@pytest.mark.parametrize("bad_recipe", [
    {2024: "hi", "id": "t", "kind": "cli-tool"},
    {1: 2},
    {("tuple",): "k"},
    {1: 1, "also_bad": 2, 3.5: "x"},   # several non-string + a string unknown key
])
def test_non_string_top_level_key_is_reported_not_crashed(bad_recipe):
    out = server.validate_recipe(bad_recipe, stem="t")
    assert isinstance(out, list)
    # the offending key is surfaced as an unknown top-level key, not a crash
    assert any("unknown top-level key" in e for e in out)


def test_non_string_key_name_appears_in_the_error():
    out = server.validate_recipe({2024: "hi", "id": "t", "kind": "cli-tool"}, stem="t")
    joined = " ".join(out)
    assert "unknown top-level key" in joined and "2024" in joined


@pytest.mark.parametrize("key", [2024, 1, -1, 3.5, True, None, ("a", "b")])
def test_validate_never_raises_on_a_hostile_top_level_key(key):
    base = cli_recipe("t")
    base[key] = "whatever"
    out = server.validate_recipe(base, stem="t")
    assert isinstance(out, list)
