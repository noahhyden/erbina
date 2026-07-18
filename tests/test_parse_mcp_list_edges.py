"""Adversarial / edge-case coverage for `_parse_mcp_list` (the brittle parser,
issue #3). We drive it by monkeypatching `server._run` so no real subprocess or
`claude` CLI is ever invoked.

`claude mcp list` prints one line per server:
    <name>: <command> - ✔ Connected     (or  ✘ Failed to connect)
The parser strips ANSI, splits name off the first colon, classifies by marker,
and takes the command as everything before the trailing ` - <status>`.
"""
from __future__ import annotations

import pytest

import server


def _parse(stdout: str, monkeypatch):
    monkeypatch.setattr(
        server, "_run", lambda cmd, cwd=None, timeout=600: {"cmd": cmd, "exit": 0, "stdout": stdout, "stderr": ""}
    )
    return {s["name"]: s for s in server._parse_mcp_list()}


# --------------------------------------------------------------------------- #
# commands that themselves contain the delimiters the parser splits on
# --------------------------------------------------------------------------- #
def test_command_containing_a_colon_is_preserved(monkeypatch):
    # partition(':') splits on the FIRST colon (the name/command boundary), so a
    # colon inside the command must survive.
    got = _parse("srv: uvx pkg:subcmd - \x1b[32m✔ Connected\x1b[0m", monkeypatch)
    assert got["srv"]["connected"] is True
    assert got["srv"]["command"] == "uvx pkg:subcmd"


def test_command_containing_dash_delimiter_keeps_only_status_off_the_end(monkeypatch):
    # rsplit(' - ', 1) strips ONLY the trailing ` - <status>`, so a ` - ` inside
    # the command is kept.
    got = _parse("srv: run --a - --b - \x1b[31m✘ Failed to connect\x1b[0m", monkeypatch)
    assert got["srv"]["connected"] is False
    assert got["srv"]["command"] == "run --a - --b"


# --------------------------------------------------------------------------- #
# whitespace / line-ending robustness
# --------------------------------------------------------------------------- #
def test_crlf_line_endings_parse(monkeypatch):
    got = _parse("a: x - ✔ Connected\r\nb: y - ✘ Failed to connect\r\n", monkeypatch)
    assert set(got) == {"a", "b"}
    assert got["a"]["connected"] is True
    assert got["b"]["connected"] is False


def test_leading_trailing_whitespace_and_blank_lines_ignored(monkeypatch):
    got = _parse("\n\n   a: x - ✔ Connected   \n\n", monkeypatch)
    assert set(got) == {"a"}
    assert got["a"]["command"] == "x"


def test_empty_output_yields_no_servers(monkeypatch):
    assert _parse("", monkeypatch) == {}


# --------------------------------------------------------------------------- #
# non-status lines must be dropped (headers, summaries, prose with a colon)
# --------------------------------------------------------------------------- #
def test_header_and_summary_lines_dropped(monkeypatch):
    out = (
        "Checking MCP server health...\n"
        "Configured servers: 2\n"           # has a colon but no ✔/✘ marker
        "real: cmd - ✔ Connected\n"
    )
    got = _parse(out, monkeypatch)
    assert set(got) == {"real"}


def test_line_without_colon_dropped(monkeypatch):
    assert _parse("no colon here ✔ Connected", monkeypatch) == {}


# --------------------------------------------------------------------------- #
# both markers on one line: ✔ present but ✘ also present -> treated as NOT
# connected (a defensible fail-safe; documents current behavior).
# --------------------------------------------------------------------------- #
def test_ambiguous_double_marker_treated_as_not_connected(monkeypatch):
    got = _parse("srv: z - ✔ ✘ weird", monkeypatch)
    assert got["srv"]["connected"] is False


# --------------------------------------------------------------------------- #
# CANDIDATE BUG (issue #3): a HEALTHY server (✔ marker present) whose command
# text merely contains the substring "Failed to connect" is misclassified as
# dead, because `failed` is matched against the whole line including the command.
# xfail(strict) so this documents the bug now AND fails loudly once it is fixed
# (prompting removal of the marker). Confirmed real via a probe on 2026-07-18.
# --------------------------------------------------------------------------- #
@pytest.mark.xfail(strict=True, reason="issue #3: 'Failed to connect' inside a command misclassifies a healthy server")
def test_healthy_server_whose_command_mentions_failed_to_connect(monkeypatch):
    got = _parse("foo: echo Failed to connect - \x1b[32m✔ Connected\x1b[0m", monkeypatch)
    assert got["foo"]["connected"] is True
