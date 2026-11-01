"""Self-check for the one-line-comment guard: a guard that cannot fail is not a guard."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_one_line_comments as guard  # noqa: E402


def test_multi_line_docstring_is_flagged():
    hits = guard.python_violations('def f():\n    """one\n    two"""\n    return 1\n')
    assert [why for _n, why in hits] == ["docstring spans 2 lines (f)"]


def test_mcp_tool_docstring_is_exempt_but_plain_is_not():
    body = '    """one\n    two"""\n    return 1\n'
    assert guard.python_violations("@mcp.tool\ndef f():\n" + body) == []
    assert guard.python_violations("@tool\ndef f():\n" + body) == []
    assert len(guard.python_violations("def f():\n" + body)) == 1


def test_one_line_docstring_is_clean():
    assert guard.python_violations('def f():\n    """one"""\n    return 1\n') == []


def test_standalone_comment_run_is_flagged():
    hits = guard.python_violations("# one\n# two\nx = 1\n")
    assert hits == [(1, "comment run spans 2 lines")]


def test_trailing_comments_are_not_a_run():
    assert guard.python_violations("x = 1  # one\ny = 2  # two\n") == []


def test_pragma_run_is_exempt():
    assert guard.python_violations("# ruff: noqa\n# second line\nx = 1\n") == []


def test_pep723_script_header_is_exempt():
    header = '#!/usr/bin/env -S uv run --script\n# /// script\n# dependencies = ["x"]\n# ///\nx = 1\n'
    assert guard.python_violations(header) == []


def test_yaml_comment_run_is_flagged():
    assert guard.yaml_violations("# one\n# two\nid: x\n") == [(1, "comment run spans 2 lines")]


def test_yaml_block_scalar_body_is_not_a_comment():
    assert guard.yaml_violations("run: |\n  # one\n  # two\nid: x\n") == []


def test_empty_scan_refuses_to_pass_vacuously(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_one_line_comments.py", "README.md"])
    assert guard.main() == 1
    assert "refusing to pass vacuously" in capsys.readouterr().out
