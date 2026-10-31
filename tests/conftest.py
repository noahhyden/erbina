"""Puts the repo root and scripts/ on sys.path so `import server` and maintainer helpers work from any cwd."""
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
    """Redirect STATE_DIR to a temp dir for every test so bootstrap/update never touch the real ~/.erbina."""
    import server

    monkeypatch.setattr(server, "STATE_DIR", tmp_path / ".erbina")
