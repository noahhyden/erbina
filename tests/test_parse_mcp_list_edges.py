"""Edge cases for `_parse_mcp_list` (issue #3): it strips ANSI, splits the name at the first colon, classifies by marker, and takes the command before the trailing ` - <status>`."""
from __future__ import annotations

import server


def _parse(stdout: str, monkeypatch):
    monkeypatch.setattr(
        server, "_run", lambda cmd, cwd=None, timeout=600: {"cmd": cmd, "exit": 0, "stdout": stdout, "stderr": ""}
    )
    return {s["name"]: s for s in server._parse_mcp_list()}


# commands that themselves contain the delimiters the parser splits on
def test_command_containing_a_colon_is_preserved(monkeypatch):
    # partition(':') splits on the FIRST colon, so a colon inside the command must survive.
    got = _parse("srv: uvx pkg:subcmd - \x1b[32m✔ Connected\x1b[0m", monkeypatch)
    assert got["srv"]["connected"] is True
    assert got["srv"]["command"] == "uvx pkg:subcmd"


def test_command_containing_dash_delimiter_keeps_only_status_off_the_end(monkeypatch):
    # rsplit(' - ', 1) strips only the trailing status, so a ` - ` inside the command is kept.
    got = _parse("srv: run --a - --b - \x1b[31m✘ Failed to connect\x1b[0m", monkeypatch)
    assert got["srv"]["connected"] is False
    assert got["srv"]["command"] == "run --a - --b"


# whitespace / line-ending robustness
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


# non-status lines must be dropped (headers, summaries, prose with a colon)
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


# Both markers on one line count as NOT connected (a defensible fail-safe).
def test_ambiguous_double_marker_treated_as_not_connected(monkeypatch):
    got = _parse("srv: z - ✔ ✘ weird", monkeypatch)
    assert got["srv"]["connected"] is False


# Issue #3 regression: a HEALTHY server whose command contains "Failed to connect" was misread as dead, so classify on the status tail only.
def test_healthy_server_whose_command_mentions_failed_to_connect(monkeypatch):
    got = _parse("foo: echo Failed to connect - \x1b[32m✔ Connected\x1b[0m", monkeypatch)
    assert got["foo"]["connected"] is True
    assert got["foo"]["command"] == "echo Failed to connect"


def test_dead_server_whose_command_mentions_connected(monkeypatch):
    # Mirror case: a FAILED server whose command contains "Connected" must still be dead (tail says ✘).
    got = _parse("bar: run --Connected-flag - \x1b[31m✘ Failed to connect\x1b[0m", monkeypatch)
    assert got["bar"]["connected"] is False
    assert got["bar"]["command"] == "run --Connected-flag"
