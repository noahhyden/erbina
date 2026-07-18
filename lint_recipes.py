#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=2.0", "pyyaml>=6.0", "packaging>=23"]
# ///
"""Lint every recipe in recipes/ against the SCHEMA.md contract.

Run it before opening a recipe PR:

    uv run --script lint_recipes.py            # lint recipes/
    uv run --script lint_recipes.py path.yaml  # lint specific file(s)

Exits 0 when every recipe is valid, non-zero (and prints each problem) otherwise.

Two layers, both from server.py: `validate_recipe` is the schema contract, also
enforced at recipe LOAD time (so anything that lints clean here, `bootstrap` will
also accept), plus `lint_recipe_policy` — stricter curated-registry policy
(non-empty title/description, guarded install methods) that runs only here, so a
contributor's recipe PR fails fast without blocking programmatic/test recipes.
(We depend on fastmcp only because importing server.py pulls it in at module top;
importing does not start the server — `mcp.run()` is guarded by `__main__`.)
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from server import RECIPES_DIR, lint_recipe_policy, validate_recipe


def lint_path(path: Path) -> list[str]:
    """Return the list of problems for one recipe file (empty == valid).

    Combines the schema contract (`validate_recipe`, also enforced at load time)
    with the stricter curated-registry policy (`lint_recipe_policy`, linter-only:
    non-empty title/description, guarded install methods).
    """
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        return [f"YAML parse error: {e}"]
    if data is None:
        return ["file is empty"]
    return validate_recipe(data, stem=path.stem) + lint_recipe_policy(data)


def main(argv: list[str]) -> int:
    if argv:
        paths = [Path(a) for a in argv]
    else:
        paths = sorted(RECIPES_DIR.glob("*.yaml"))

    if not paths:
        print(f"no recipes found in {RECIPES_DIR}")
        return 0

    failed = 0
    for path in paths:
        problems = lint_path(path)
        if problems:
            failed += 1
            print(f"FAIL {path}")
            for p in problems:
                print(f"  - {p}")
        else:
            print(f"ok   {path}")

    total = len(paths)
    if failed:
        print(f"\n{failed}/{total} recipe(s) failed validation.")
        return 1
    print(f"\nAll {total} recipe(s) valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
