"""Placeholder handling: `_check_placeholders` (the linter's guard) and its
consistency with `_subst` (the runtime expander).

The load-bearing invariant is: *anything the linter passes, `_subst` fully
expands* — no `${known}` token should ever reach an executed command literally.
The linter only knows two placeholders (${scope}, ${project_dir}); any other
`${...}` token is a recipe bug and must be flagged.
"""
from __future__ import annotations

import pytest

import server


# --------------------------------------------------------------------------- #
# _check_placeholders — what gets flagged
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "echo ${scope}",
    "cd ${project_dir}",
    "claude mcp add x --scope ${scope} in ${project_dir}",
    "${scope}${project_dir}",       # adjacent, no separator
    "no placeholders at all",
    "literal $scope without braces",  # not a ${...} token
])
def test_known_and_placeholderless_text_is_clean(text):
    errs: list[str] = []
    server._check_placeholders(text, "loc", errs)
    assert errs == []


@pytest.mark.parametrize("text,needle", [
    ("${scopee}", "scopee"),          # the classic typo
    ("${SCOPE}", "SCOPE"),            # wrong case
    ("${ scope }", "scope"),          # stray whitespace inside braces
    ("${}", "${}"),                   # empty token
    ("a${scope}b${bad}c", "bad"),     # one good, one bad
    ("${project_directory}", "project_directory"),
])
def test_unknown_placeholders_are_flagged(text, needle):
    errs: list[str] = []
    server._check_placeholders(text, "loc", errs)
    assert errs, f"{text!r} should be flagged"
    assert needle in " ".join(errs)


def test_check_placeholders_ignores_non_strings():
    errs: list[str] = []
    server._check_placeholders(None, "loc", errs)
    server._check_placeholders(123, "loc", errs)
    assert errs == []


# --------------------------------------------------------------------------- #
# the invariant: lint-clean known placeholders always fully expand
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "echo ${scope}",
    "cd ${project_dir} && ${scope}",
    "${scope}${project_dir}",
    "a${scope}b${project_dir}c",
])
def test_lint_clean_text_leaves_no_placeholder_after_subst(text):
    errs: list[str] = []
    server._check_placeholders(text, "loc", errs)
    assert errs == []  # precondition: the linter accepts it
    out = server._subst(text, "user", "/proj")
    assert "${scope}" not in out
    assert "${project_dir}" not in out


def test_subst_leaves_unknown_tokens_untouched():
    # _subst only expands the two known tokens; a flagged token is left literal
    # (the linter is what stops it reaching a real command, not _subst).
    assert server._subst("${SCOPE}", "user", None) == "${SCOPE}"
    assert server._subst("${ scope }", "user", None) == "${ scope }"


# --------------------------------------------------------------------------- #
# Regression for finding #2, FIXED in iteration 5: a dangling `${scope` (missing
# closing brace) survives _subst untouched (the regex needs a closing `}`), so
# the linter now flags an unterminated `${` explicitly — refusing the recipe at
# load time rather than letting a literal `${` reach an executed command.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "echo ${scope",                 # lone dangling
    "cd ${project_dir} && ${scope", # one closed, one dangling
    "${",                           # bare opener
])
def test_unterminated_placeholder_is_flagged(text):
    errs: list[str] = []
    server._check_placeholders(text, "loc", errs)
    assert errs, f"{text!r} should be flagged as unterminated"
    assert any("unterminated" in e for e in errs)


def test_dangling_brace_still_survives_subst_literally():
    # _subst is unchanged (only expands closed known tokens); the LINTER is what
    # now stops a dangling ${ from reaching a command.
    assert server._subst("echo ${scope", "user", "/p") == "echo ${scope"
