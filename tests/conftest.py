"""Test configuration for the erbina suite.

Ensures `import server` works regardless of the current working directory by
putting the repository root (the parent of this tests/ dir) on sys.path, and the
scripts/ dir too so maintainer helpers (e.g. winget_candidates) are importable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(autouse=True)
def _isolate_erbina_state(tmp_path, monkeypatch):
    """Redirect erbina's state manifest to a fresh temp dir for EVERY test.

    bootstrap/update now write to STATE_DIR (~/.erbina) as a side effect; this
    autouse fixture guarantees no test ever touches the real home directory.
    """
    import server

    monkeypatch.setattr(server, "STATE_DIR", tmp_path / ".erbina")
