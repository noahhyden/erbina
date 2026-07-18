"""Real end-to-end integration tests for the bootstrap/update pipeline.

Unlike the rest of the suite (shell builtins / monkeypatched subprocess), these
drive the ACTUAL pipeline against a throwaway fixture tool that is genuinely
absent, gets genuinely installed (a real script written into a temp dir on PATH),
and is genuinely verified by execution. Real subprocesses, real filesystem state
transitions — but fully deterministic and offline (no package managers, no
network), so they're safe in CI.

The fixture tool `erbtool` is installed into $ERB_BIN (a temp dir prepended to
PATH), so nothing touches the real system.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

import server
from helpers import call_tool
from prototype import registry


@pytest.fixture
def erb_bin(tmp_path, monkeypatch):
    """A temp bin dir on PATH; the fixture recipe installs `erbtool` here."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("ERB_BIN", str(bindir))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    assert shutil.which("erbtool") is None, "precondition: erbtool must not pre-exist"
    return bindir


def _write_script(version: str = "1.0.0", ok: bool = True) -> str:
    """A shell command that installs the `erbtool` script into $ERB_BIN. When
    ok=False the installed tool exits nonzero (a broken install verify must catch)."""
    body = f"echo erbtool {version}" if ok else "exit 1"
    return (
        "echo '#!/bin/sh' > \"$ERB_BIN/erbtool\"; "
        f"echo '{body}' >> \"$ERB_BIN/erbtool\"; "
        "chmod +x \"$ERB_BIN/erbtool\""
    )


def _recipe(*, version="1.0.0", ok=True, update_to=None):
    r = {
        "id": "erbtool",
        "kind": "cli-tool",
        "title": "erbtool — integration-test fixture tool",
        "description": "A throwaway tool installed into a temp PATH dir to exercise the real pipeline.",
        "detect": {"command": "command -v erbtool"},
        "install": {"methods": [{"id": "script", "when": "command -v chmod", "run": _write_script(version, ok)}]},
        "verify": [{"command": "erbtool --version"}],
        "scope": "user",
    }
    if update_to is not None:
        r["version"] = {"current": "erbtool --version", "latest": f"echo {update_to}"}
        r["update"] = {"methods": [{"id": "script", "when": "command -v chmod", "run": _write_script(update_to)}]}
    return r


# --------------------------------------------------------------------------- #
# bootstrap: real detect -> install -> verify
# --------------------------------------------------------------------------- #
def test_bootstrap_installs_and_verifies_a_real_tool(erb_bin):
    with registry(_recipe()):
        out = call_tool("bootstrap", {"recipe_id": "erbtool"})
    assert out["ok"] is True
    assert out["phases"]["detect"]["present"] is False  # was genuinely absent
    assert out["phases"]["install"]["status"] == "ok"
    assert out["phases"]["verify"][0]["status"] == "ok"
    # the tool really exists and really runs now
    exe = erb_bin / "erbtool"
    assert exe.exists() and os.access(exe, os.X_OK)
    res = subprocess.run(["erbtool", "--version"], capture_output=True, text=True)
    assert res.returncode == 0 and "erbtool 1.0.0" in res.stdout


def test_bootstrap_is_idempotent_on_second_run(erb_bin):
    with registry(_recipe()):
        first = call_tool("bootstrap", {"recipe_id": "erbtool"})
        assert first["phases"]["install"]["status"] == "ok"
        second = call_tool("bootstrap", {"recipe_id": "erbtool"})
    # the tool is now genuinely present, so detect gates install off
    assert second["phases"]["detect"]["present"] is True
    assert second["phases"]["install"]["status"] == "skipped"
    assert second["ok"] is True


def test_verify_catches_a_broken_install(erb_bin):
    # install succeeds (writes a file) but the installed tool is broken (exits 1),
    # so the real verify must fail the bootstrap.
    with registry(_recipe(ok=False)):
        out = call_tool("bootstrap", {"recipe_id": "erbtool"})
    assert out["phases"]["install"]["status"] == "ok"      # the install command ran fine
    assert out["phases"]["verify"][0]["status"] == "failed"  # but the tool doesn't work
    assert out["ok"] is False
    assert (erb_bin / "erbtool").exists()  # the (broken) file was written


# --------------------------------------------------------------------------- #
# update: real install v1 -> update to v2 -> re-verify -> state records both
# --------------------------------------------------------------------------- #
def test_update_upgrades_a_real_tool_end_to_end(erb_bin):
    with registry(_recipe(version="1.0.0", update_to="2.0.0")):
        boot = call_tool("bootstrap", {"recipe_id": "erbtool"})
        assert boot["ok"] is True
        assert subprocess.run(["erbtool", "--version"], capture_output=True, text=True).stdout.strip() == "erbtool 1.0.0"

        out = call_tool("update", {"recipe_id": "erbtool"})
    assert out["ok"] is True
    assert out["version"] == {"before": "1.0.0", "after": "2.0.0"}
    # the on-disk tool was genuinely upgraded
    assert subprocess.run(["erbtool", "--version"], capture_output=True, text=True).stdout.strip() == "erbtool 2.0.0"
    # and erbina recorded the transition in its state manifest
    rec = server._read_state()["tools"]["erbtool"]
    assert rec["installed_version"] == "2.0.0"
    assert rec["previous_version"] == "1.0.0"
