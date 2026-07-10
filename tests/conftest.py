"""Test configuration for the erbina suite.

Ensures `import server` works regardless of the current working directory by
putting the repository root (the parent of this tests/ dir) on sys.path.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
