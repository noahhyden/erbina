"""Real end-to-end tests: a genuinely absent fixture tool `erbtool` is installed by a real script into a temp $ERB_BIN on PATH and verified by execution, offline."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

import server
from helpers import call_tool
from prototype import registry
from stubs import write_claude_stub


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
    """A shell command that installs the `erbtool` script into $ERB_BIN; ok=False makes the installed tool exit nonzero."""
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
        "category": "devtools",
    }
    if update_to is not None:
        r["version"] = {"current": "erbtool --version", "latest": {"github": "o/erbtool"}}
        r["update"] = {"methods": [{"id": "script", "when": "command -v chmod", "run": _write_script(update_to)}]}
    return r


# bootstrap: real detect -> install -> verify
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
    # Install succeeds but the installed tool exits 1, so the real verify must fail the bootstrap.
    with registry(_recipe(ok=False)):
        out = call_tool("bootstrap", {"recipe_id": "erbtool"})
    assert out["phases"]["install"]["status"] == "ok"      # the install command ran fine
    assert out["phases"]["verify"][0]["status"] == "failed"  # but the tool doesn't work
    assert out["ok"] is False
    assert (erb_bin / "erbtool").exists()  # the (broken) file was written


# update: real install v1 -> update to v2 -> re-verify -> state records both
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


# mcp-server wiring: real bootstrap against a STUB `claude` binary
@pytest.fixture
def stub_claude(erb_bin, tmp_path, monkeypatch):
    """A fake `claude` on PATH: `mcp add <name>` records to a store dir and `mcp get <name>` exits 0 iff added; returns the store."""
    store = tmp_path / "mcp_store"
    store.mkdir()
    write_claude_stub(erb_bin)
    monkeypatch.setenv("CLAUDE_STUB_STORE", str(store))
    return store


def _mcp_recipe(name="fixsrv", runner="npx -y fixsrv-server"):
    return {
        "id": name,
        "kind": "mcp-server",
        "category": "mcp-server",
        "title": f"{name} — mcp-server fixture",
        "description": "a stub mcp-server recipe for end-to-end wiring tests",
        "detect": {"command": f"claude mcp get {name}", "needs_project_dir": True},
        "install": {"methods": [{"id": "rt", "when": "command -v claude", "run": "command -v claude"}]},
        "configure": {"steps": [{"run": f"claude mcp add {name} --scope ${{scope}} -- {runner}", "needs_project_dir": True}]},
        "verify": [{"command": f"claude mcp get {name}", "needs_project_dir": True}],
        "scope": "project",
    }


def test_mcp_server_bootstrap_wires_and_verifies_e2e(stub_claude, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with registry(_mcp_recipe()):
        out = call_tool("bootstrap", {"recipe_id": "fixsrv", "scope": "project", "project_dir": str(proj)})
    assert out["ok"] is True
    assert out["phases"]["detect"]["present"] is False              # genuinely not yet registered
    assert out["phases"]["configure"]["steps"][0]["status"] == "ok"  # claude mcp add ran
    assert out["phases"]["verify"][0]["status"] == "ok"             # claude mcp get now succeeds
    # the stub received the exact wiring command, with ${scope} substituted
    assert (stub_claude / "fixsrv").read_text().strip() == "mcp add fixsrv --scope project -- npx -y fixsrv-server"


def test_mcp_server_scope_substitution_e2e(stub_claude, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with registry(_mcp_recipe()):
        call_tool("bootstrap", {"recipe_id": "fixsrv", "scope": "user", "project_dir": str(proj)})
    assert "--scope user --" in (stub_claude / "fixsrv").read_text()


def test_mcp_server_bootstrap_is_idempotent_e2e(stub_claude, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with registry(_mcp_recipe()):
        call_tool("bootstrap", {"recipe_id": "fixsrv", "scope": "project", "project_dir": str(proj)})
        second = call_tool("bootstrap", {"recipe_id": "fixsrv", "scope": "project", "project_dir": str(proj)})
    # already registered -> detect present -> install + configure skipped
    assert second["phases"]["detect"]["present"] is True
    assert second["phases"]["configure"]["status"] == "skipped"
