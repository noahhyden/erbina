"""Prototype "fake tool" factory for erbina behavioral testing.

erbina's whole extensibility surface is the *recipe* — a detect -> install ->
configure -> verify contract (see SCHEMA.md). This module lets a test synthesize
a prototype recipe (a fake tool), give it *special properties* (controllable
exit codes, install guards, placeholders, optional / needs_project_dir flags),
and push it through erbina's REAL code paths: `validate_recipe`, `_load_recipe`,
`_plan`, and a live (non-dry) `bootstrap`.

Determinism is the whole point. Every command a prototype runs is a POSIX shell
builtin with a fixed exit code (`true`, `false`, `exit N`, `echo`), so a live
bootstrap is fully reproducible and machine-independent: no brew/curl, no
network, no `claude` CLI, nothing installed. That lets these tests exercise the
bootstrap *orchestration* (detect gating, guarded install selection, configure
skipping, verify pass/fail) — the logic where real bugs live — without side
effects.

Nothing here writes into the real recipes/ directory: `registry()` builds a
throwaway temp dir and repoints `server.RECIPES_DIR` at it, restoring it after.
"""
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
    """A minimal VALID kind: cli-tool recipe. Override any top-level key.

    Defaults are all shell builtins, so the recipe both validates clean AND runs
    deterministically under a live bootstrap. Override e.g. detect={"command":
    FALSE} to force the install path, or verify=[{"command": FALSE}] to force a
    verify failure.
    """
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
    """A minimal VALID kind: mcp-server recipe.

    Its configure step references ${scope}, which `validate_recipe` requires for
    an mcp-server. The configure command is a harmless `echo`, so a live
    bootstrap wires nothing real.
    """
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
    """A minimal VALID kind: profile recipe — a meta-recipe that only bundles
    other recipes via `requires` and carries no per-tool lifecycle keys."""
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
    """Write prototype recipes into a temp RECIPES_DIR and point server at it.

    Restores `server.RECIPES_DIR` afterward, so the real recipes/ registry is
    never touched and the tools (`list_recipes` / `inspect_recipe` / `bootstrap`)
    resolve ONLY these prototypes for the duration of the `with` block.
    """
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
