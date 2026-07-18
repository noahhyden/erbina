"""Tests for the curated-registry policy layer (server.lint_recipe_policy) and
its wiring into lint_recipes.py.

The design under test: `validate_recipe` is the schema (also enforced at load
time, so the test harness can build minimal recipes), while `lint_recipe_policy`
is a stricter contributor-facing layer the LINTER runs — non-empty title +
description, and a `when:` guard on every install method.
"""
from __future__ import annotations

import pytest

import server
from lint_recipes import lint_path
from prototype import cli_recipe


def _valid_policy_recipe():
    # cli_recipe already has title/description; give its install method a guard so
    # it satisfies policy too (the factory default is intentionally unguarded).
    return cli_recipe("t", install={"methods": [{"id": "m", "when": "command -v brew", "run": "true"}]})


def test_clean_recipe_has_no_policy_problems():
    assert server.lint_recipe_policy(_valid_policy_recipe()) == []


@pytest.mark.parametrize("drop", ["title", "description"])
def test_missing_title_or_description_flagged(drop):
    r = _valid_policy_recipe()
    r.pop(drop)
    problems = server.lint_recipe_policy(r)
    assert any(drop in p for p in problems)


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_title_flagged(blank):
    r = _valid_policy_recipe()
    r["title"] = blank
    assert any("title" in p for p in server.lint_recipe_policy(r))


def test_unguarded_install_method_flagged():
    r = cli_recipe("t", install={"methods": [{"id": "m", "run": "true"}]})  # no `when`
    problems = server.lint_recipe_policy(r)
    assert any("guard" in p for p in problems)


def test_policy_ignores_non_mapping():
    assert server.lint_recipe_policy("not a dict") == []


# --------------------------------------------------------------------------- #
# verify honesty
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("verify_cmd", [
    "test -f /usr/local/bin/foo",
    "[ -x /usr/local/bin/foo ]",
    "ls /usr/local/bin/foo",
    "cat /etc/foo.conf",
    "stat /usr/local/bin/foo",
    "find / -name foo",
])
def test_file_inspection_verify_is_flagged(verify_cmd):
    r = _valid_policy_recipe()
    r["verify"] = [{"command": verify_cmd}]
    problems = server.lint_recipe_policy(r)
    assert any("verify" in p and "filesystem" in p for p in problems), problems


@pytest.mark.parametrize("verify_cmd", [
    "foo --version",
    "foo doctor",
    "claude mcp get foo",       # the honest mcp-server check
    "python -c 'import foo'",
])
def test_real_invocation_verify_is_not_flagged(verify_cmd):
    r = _valid_policy_recipe()
    r["verify"] = [{"command": verify_cmd}]
    assert not any("filesystem" in p for p in server.lint_recipe_policy(r))


def test_verify_honesty_flags_the_right_index():
    r = _valid_policy_recipe()
    r["verify"] = [{"command": "foo --version"}, {"command": "test -f /bin/foo"}]
    problems = [p for p in server.lint_recipe_policy(r) if "filesystem" in p]
    assert len(problems) == 1
    assert "verify[1]" in problems[0]


def test_verify_honesty_survives_unbalanced_quotes_and_still_flags():
    # a verify command with an unbalanced quote makes shlex.split raise; the check
    # must NOT crash — it falls back to a rough split and still catches the
    # file-inspecting first word (`find`).
    r = _valid_policy_recipe()
    r["verify"] = [{"command": 'find "unterminated /usr/bin/foo'}]
    problems = server.lint_recipe_policy(r)
    assert any("verify" in p and "filesystem" in p for p in problems), problems


def test_verify_honesty_survives_unbalanced_quotes_on_an_honest_cmd():
    # same broken-quote path, but the first word runs the tool -> not flagged
    r = _valid_policy_recipe()
    r["verify"] = [{"command": 'foo --json "unterminated'}]
    assert not any("filesystem" in p for p in server.lint_recipe_policy(r))


@pytest.mark.parametrize("bad_entry", [{"command": "   "}, {"command": ""}, {}, "notadict", None])
def test_verify_honesty_skips_empty_or_non_dict_entries(bad_entry):
    # an empty/blank command or a non-mapping verify entry contributes no
    # filesystem-honesty problem (and never raises) — that's a schema concern,
    # handled elsewhere.
    r = _valid_policy_recipe()
    r["verify"] = [bad_entry]
    assert not any("filesystem" in p for p in server.lint_recipe_policy(r))


# --------------------------------------------------------------------------- #
# the separation: a recipe can be schema-valid (load-time OK) yet fail policy,
# and the LINTER (lint_path) must catch it.
# --------------------------------------------------------------------------- #
def test_schema_valid_but_policyless_recipe_loads_but_fails_linter(tmp_path):
    # schema-valid: has detect/install/verify/kind/id — but NO title/description
    # and an unguarded install method.
    (tmp_path / "policyless.yaml").write_text(
        "id: policyless\n"
        "kind: cli-tool\n"
        "detect: {command: 'true'}\n"
        "install: {methods: [{id: m, run: 'true'}]}\n"
        "verify: [{command: 'true'}]\n"
    )
    data = __import__("yaml").safe_load((tmp_path / "policyless.yaml").read_text())

    # schema layer accepts it (so programmatic/test use still works)...
    assert server.validate_recipe(data, stem="policyless") == []
    # ...but the linter (schema + policy) rejects it
    problems = lint_path(tmp_path / "policyless.yaml")
    assert problems
    assert any("title" in p for p in problems)
    assert any("guard" in p for p in problems)
