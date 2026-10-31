"""Placeholder handling: anything `_check_placeholders` passes, `_subst` fully expands, and any `${...}` beyond ${scope}/${project_dir} is a flagged recipe bug."""
from __future__ import annotations

import pytest

import server


# _check_placeholders — what gets flagged
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


# the invariant: lint-clean known placeholders always fully expand
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
    # _subst expands only the two known tokens and leaves a flagged one literal; the linter, not _subst, stops it reaching a command.
    assert server._subst("${SCOPE}", "user", None) == "${SCOPE}"
    assert server._subst("${ scope }", "user", None) == "${ scope }"


# Finding #2 (fixed): a dangling `${scope` survives _subst, so the linter flags an unterminated `${` and refuses the recipe at load time.
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
    # _subst is unchanged (closed known tokens only); the LINTER now stops a dangling ${ from reaching a command.
    assert server._subst("echo ${scope", "user", "/p") == "echo ${scope"
