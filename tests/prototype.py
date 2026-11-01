"""Prototype fake-tool factory: recipes of shell builtins with fixed exit codes, so a live bootstrap through the REAL code paths installs nothing."""
from __future__ import annotations

import contextlib
import copy
import tempfile
from pathlib import Path
from typing import Any, Iterator

import yaml

import server

# Handy deterministic command strings for building special properties.
TRUE = "true"    # exits 0
FALSE = "false"  # exits 1


def exit_code(n: int) -> str:
    """A command string that deterministically exits with code `n`."""
    return f"exit {n}"


_BODIES: dict[str, dict[str, Any]] = {
    "cli-tool": {
        "category": "devtools",
        "description": "A synthetic prototype recipe for behavioral testing.",
        "detect": {"command": TRUE},
        "install": {"methods": [{"id": "always", "run": TRUE}]},
        "verify": [{"command": TRUE}],
        "scope": "user",
    },
    "mcp-server": {
        "category": "mcp-server",
        "description": "A synthetic prototype mcp-server recipe.",
        "detect": {"command": TRUE},
        "install": {"methods": [{"id": "always", "run": TRUE}]},
        "configure": {"steps": [{"run": "echo scope=${scope}"}]},
        "verify": [{"command": TRUE}],
        "scope": "user",
    },
    "profile": {
        "category": "profile",
        "description": "A synthetic prototype profile bundling other recipes.",
        "requires": ["proto"],
    },
}


def recipe(kind: str, rid: str, **overrides: Any) -> dict[str, Any]:
    """A minimal VALID recipe of `kind`; override any top-level key (e.g. detect={"command": FALSE} forces the install path)."""
    body = copy.deepcopy(_BODIES[kind])
    return {"id": rid, "kind": kind, "title": f"{rid} — prototype {kind}", **body, **overrides}


def cli_recipe(rid: str = "proto", **overrides: Any) -> dict[str, Any]:
    return recipe("cli-tool", rid, **overrides)


def mcp_recipe(rid: str = "proto_mcp", **overrides: Any) -> dict[str, Any]:
    return recipe("mcp-server", rid, **overrides)


def profile_recipe(rid: str = "proto_profile", requires: list[str] | None = None, **overrides: Any) -> dict[str, Any]:
    return recipe("profile", rid, **({} if requires is None else {"requires": list(requires)}), **overrides)


@contextlib.contextmanager
def registry(*recipes: dict[str, Any]) -> Iterator[Path]:
    """Write prototype recipes into a temp RECIPES_DIR, point server at it, and restore the real one on exit."""
    original = server.RECIPES_DIR
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for r in recipes:
            rid = r["id"]
            (tmp / f"{rid}.yaml").write_text(yaml.safe_dump(r, sort_keys=False))
        server.RECIPES_DIR = tmp
        try:
            yield tmp
        finally:
            server.RECIPES_DIR = original
