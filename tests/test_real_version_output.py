"""Extend the version surface to REAL tools: feed `_extract_version` authentic
`--version` output from the kinds of CLIs erbina's recipes install, and assert it
pulls the right token. This is the "extend to real tools" arm of the behavioral
loop — it guards the extraction regex against a regression that would silently
break `check_updates` for a whole class of tools.

It also pins a KNOWN limitation (candidate finding #5): "first version-looking
token wins", so a dotted date/number appearing BEFORE the real version is
misextracted. No current recipe triggers it (their outputs are single clean
lines), so it's characterized here, not fixed — see PROTOTYPE_NOTES.md.
"""
from __future__ import annotations

import pytest

import server

# Authentic (or authentically-shaped) `--version` / `--help` version lines for
# real tools erbina installs, plus a few common runtimes. The value is the token
# a human reads as "the version".
REAL_OUTPUTS = [
    ("git version 2.43.0", "2.43.0"),
    ("jq-1.7.1", "1.7.1"),                                  # jq: dash, no space
    ("ripgrep 14.1.0", "14.1.0"),
    ("rg 14.1.0 (rev e50df40a01)", "14.1.0"),              # trailing vcs rev
    ("go version go1.22.0 linux/amd64", "1.22.0"),         # go's "go1.22.0"
    ("uv 0.5.11 (0c8b0a8f2 2024-12-06)", "0.5.11"),        # hash + ISO date after
    ("fd 10.1.0", "10.1.0"),
    ("bat 0.24.0", "0.24.0"),
    ("eza - A modern ls\nv0.20.5 [+git]", "0.20.5"),       # blurb line, then vX
    ("zoxide 0.9.6", "0.9.6"),
    ("delta 0.18.2", "0.18.2"),
    ("dust 1.1.1", "1.1.1"),
    ("btm 0.10.2", "0.10.2"),                              # bottom
    ("hyperfine 1.18.0", "1.18.0"),
    ("tokei 12.1.2", "12.1.2"),
    ("sd 1.0.0", "1.0.0"),
    ("procs 0.14.6", "0.14.6"),
    ("tldr 1.7.1", "1.7.1"),                               # tealdeer
    ("ataegina 0.1.0", "0.1.0"),                           # erbina's PoC recipe #1
    # common runtimes / system tools of the same shape
    ("Python 3.13.1", "3.13.1"),
    ("node v20.11.0", "20.11.0"),
    ("GNU bash, version 5.2.21(1)-release", "5.2.21"),
    ("curl 8.5.0 (x86_64-pc-linux-gnu) libcurl/8.5.0", "8.5.0"),
    ("OpenSSL 3.0.13 30 Jan 2024", "3.0.13"),
]


@pytest.mark.parametrize("output,expected", REAL_OUTPUTS)
def test_extract_version_handles_real_tool_output(output, expected):
    assert server._extract_version(output) == expected


def test_real_corpus_is_broad_enough_to_matter():
    # guardrail: don't let this corpus quietly shrink below a meaningful size
    assert len(REAL_OUTPUTS) >= 20


# --------------------------------------------------------------------------- #
# FINDING #5 (mostly fixed): "first version-looking token wins" used to let a
# dotted build-date BEFORE the version be grabbed. `_extract_version` now prefers
# the token AFTER an explicit "version" label, which covers the common case.
# --------------------------------------------------------------------------- #
def test_labeled_version_beats_a_leading_dotted_date():
    # the fix: a "version" label pulls extraction past the build date
    assert server._extract_version("Built 2024.01.15, tool version 2.3.4") == "2.3.4"


@pytest.mark.parametrize("output,extracted", [
    ("gh version 2.62.0 (2024-11-27)", "2.62.0"),        # label + parenthetical date
    ("GNU bash, version 5.2.21(1)-release", "5.2.21"),
    ("commit=abc, version=0.44.1, os=linux", "0.44.1"),  # lazygit-style label=value
])
def test_labeled_version_extraction(output, extracted):
    assert server._extract_version(output) == extracted


# RESIDUAL of #5 (documented, still ambiguous): output with NO "version" label —
# a bare `v1.2.3` or `10.0` printed after a dotted date — is genuinely
# indistinguishable from a calver (`2024.01.05` IS a real version), so extraction
# still takes the first token. No recipe's real output triggers this (dates in
# real `--version` output use '-', not '.'; confirmed by the live real-bootstrap
# run), so it stays a pinned characterization rather than a risky heuristic.
@pytest.mark.parametrize("output,extracted", [
    ("compiled 2023.12.31 v1.0.0", "2023.12.31"),   # unlabeled -> first token
    ("release 10.0 build 2.3.4", "10.0"),
])
def test_CURRENT_unlabeled_leading_dotted_number_still_shadows(output, extracted):
    assert server._extract_version(output) == extracted
