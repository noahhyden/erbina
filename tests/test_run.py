"""Tests for `_run`, the subprocess wrapper every phase goes through.

`_run` must NEVER raise (it reports failures as data) and must bound both time
and output size, so a misbehaving recipe command can't hang or flood the agent.
Commands here are POSIX shell builtins / tiny utilities — deterministic and
side-effect free.
"""
from __future__ import annotations

import server


def test_run_captures_zero_exit_and_stdout():
    res = server._run("printf hello")
    assert res["exit"] == 0
    assert res["stdout"] == "hello"
    assert res["cmd"] == "printf hello"


def test_run_passes_through_nonzero_exit():
    assert server._run("false")["exit"] == 1
    assert server._run("exit 5")["exit"] == 5


def test_run_captures_stderr():
    res = server._run("echo oops 1>&2")
    assert res["exit"] == 0
    assert "oops" in res["stderr"]


def test_run_times_out_and_reports_124_without_raising():
    # sleep 2 with a 1s budget: still running at the deadline -> timeout branch.
    res = server._run("sleep 2", timeout=1)
    assert res["exit"] == 124
    assert "timed out" in res["stderr"]
    assert res["stdout"] == ""


def test_run_trims_stdout_to_last_4000_chars():
    # emit exactly 5000 'a' characters (no newlines); only the last 4000 kept.
    res = server._run("head -c 5000 /dev/zero | tr '\\0' a")
    assert res["exit"] == 0
    assert len(res["stdout"]) == 4000


def test_run_never_raises_on_a_broken_command():
    # An unparsable command still returns a dict (reported, not raised).
    res = server._run("(((")
    assert isinstance(res, dict)
    assert res["exit"] != 0


def test_run_respects_cwd(tmp_path):
    (tmp_path / "marker.txt").write_text("x")
    res = server._run("ls", cwd=str(tmp_path))
    assert res["exit"] == 0
    assert "marker.txt" in res["stdout"]


def test_run_never_raises_when_subprocess_itself_errors(tmp_path):
    # A nonexistent cwd makes subprocess.run RAISE (FileNotFoundError /
    # NotADirectoryError) before the shell even starts -- distinct from a
    # shell-level nonzero exit. _run must catch it and report exit 1, never raise.
    missing = str(tmp_path / "does" / "not" / "exist")
    res = server._run("true", cwd=missing)
    assert isinstance(res, dict)
    assert res["exit"] == 1
    assert res["stdout"] == ""
    assert res["stderr"]  # the exception type/message is surfaced, not swallowed
