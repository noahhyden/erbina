"""Importing `server` must succeed and must NOT start the MCP server.

`mcp.run()` is guarded behind `if __name__ == "__main__":`, so importing the
module as `server` should be a pure, side-effect-free definition of tools and
helpers. If someone ever moves `mcp.run()` out from under that guard, importing
the module would block forever (stdio transport) and this test would hang —
which is exactly the regression we want to catch.
"""
from __future__ import annotations

import server


def test_import_succeeds_and_exposes_mcp():
    # If import had started the server (blocking stdio loop), we'd never get here.
    assert server.mcp is not None
    assert server.mcp.name == "erbina"


def test_run_is_main_guarded():
    # The only call to mcp.run() lives under the __main__ guard, not at import.
    src = (server.HERE / "server.py").read_text()
    assert "if __name__ ==" in src
    guard_idx = src.index("if __name__ ==")
    before_guard = src[:guard_idx]
    # No bare mcp.run() should execute at import time.
    assert "mcp.run()" not in before_guard
    assert "mcp.run()" in src[guard_idx:]
