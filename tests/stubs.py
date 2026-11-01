"""The single stub `claude` script: `mcp add|get|list` backed by a store dir."""
from __future__ import annotations

from pathlib import Path

CLAUDE_STUB = """#!/usr/bin/env bash
STORE="${CLAUDE_STUB_STORE:-$HOME/claude-stub-store}"
mkdir -p "$STORE"
if [ "$1" = "mcp" ] && [ "$2" = "add" ]; then echo "$*" > "$STORE/$3"; exit 0; fi
if [ "$1" = "mcp" ] && [ "$2" = "get" ]; then [ -f "$STORE/$3" ] && exit 0 || exit 1; fi
if [ "$1" = "mcp" ] && [ "$2" = "list" ]; then ls "$STORE" 2>/dev/null; exit 0; fi
exit 0
"""


def write_claude_stub(bindir):
    path = Path(bindir) / "claude"
    path.write_text(CLAUDE_STUB)
    path.chmod(0o755)
    return path


