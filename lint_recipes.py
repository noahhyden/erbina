#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=2.0", "pyyaml>=6.0", "packaging>=23"]
# ///
"""Lint recipes/ (or the given files) against SCHEMA.md; exits non-zero on the first problem found. See AGENTS.d/080."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from server import RECIPES_DIR, lint_recipe_policy, validate_recipe


def lint_path(path: Path) -> list[str]:
    """Problems for one recipe file, empty == valid: the schema contract plus the stricter curated-registry policy."""
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
