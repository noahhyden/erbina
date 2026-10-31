"""Prototype fake-tool factory: recipes of shell builtins with fixed exit codes, so a live bootstrap through the REAL code paths installs nothing."""
from __future__ import annotations

import contextlib
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


def cli_recipe(rid: str = "proto", **overrides: Any) -> dict[str, Any]:
    """A minimal VALID kind: cli-tool recipe; override any top-level key (e.g. detect={"command": FALSE} forces the install path)."""
    recipe: dict[str, Any] = {
        "id": rid,
        "kind": "cli-tool",
        "title": f"{rid} — prototype cli tool",
        "description": "A synthetic prototype recipe for behavioral testing.",
        "detect": {"command": TRUE},
        "install": {"methods": [{"id": "always", "run": TRUE}]},
        "verify": [{"command": TRUE}],
        "scope": "user",
    }
    recipe.update(overrides)
    return recipe


def mcp_recipe(rid: str = "proto_mcp", **overrides: Any) -> dict[str, Any]:
    """A minimal VALID kind: mcp-server recipe whose configure step is a harmless echo of ${scope}."""
    recipe: dict[str, Any] = {
        "id": rid,
        "kind": "mcp-server",
        "title": f"{rid} — prototype mcp server",
        "description": "A synthetic prototype mcp-server recipe.",
        "detect": {"command": TRUE},
        "install": {"methods": [{"id": "always", "run": TRUE}]},
        "configure": {"steps": [{"run": "echo scope=${scope}"}]},
        "verify": [{"command": TRUE}],
        "scope": "user",
    }
    recipe.update(overrides)
    return recipe


def profile_recipe(rid: str = "proto_profile", requires: list[str] | None = None, **overrides: Any) -> dict[str, Any]:
    """A minimal VALID kind: profile recipe, a meta-recipe that only bundles others via `requires`."""
    recipe: dict[str, Any] = {
        "id": rid,
        "kind": "profile",
        "title": f"{rid} — prototype profile",
        "description": "A synthetic prototype profile bundling other recipes.",
        "requires": list(requires) if requires is not None else ["proto"],
    }
    recipe.update(overrides)
    return recipe


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
