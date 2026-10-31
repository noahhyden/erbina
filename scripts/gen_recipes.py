#!/usr/bin/env python3
"""Generate curated cli-tool recipes from a compact data table.

Not part of the shipped server — a maintainer helper that emits well-formed
recipes/<id>.yaml files matching the SCHEMA.md contract and the curated-registry
policy (guarded install methods, honest verify, github version shorthand). Run:

    python3 scripts/gen_recipes.py

It refuses to clobber an existing recipe file (so hand-tuned recipes are safe),
and every file it writes is designed to pass `lint_recipes.py` and the
conformance suite. Feed it more rows in TOOLS to grow the registry.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECIPES_DIR = REPO_ROOT / "recipes"

# Guard commands per package manager (curated policy: every method is guarded so
# it only fires where its manager exists — safe to list many on one recipe).
GUARDS = {
    "brew": "command -v brew",
    "winget": "winget --version",
    "cargo": "command -v cargo",
    "go": "command -v go",
    "pipx": "command -v pipx",
    "npm": "command -v npm",
    "gem": "command -v gem",
    "pip": "command -v pipx",  # prefer pipx for pip apps
    "curl": "command -v curl",
}

WINGET_TAIL = (
    "--source winget --silent --accept-package-agreements "
    "--accept-source-agreements --disable-interactivity"
)


# (key, method id, install template, update template), in preference order.
# curl|sh is the last-resort fallback (the tool's official install script): after
# every package manager -- including winget, since Windows also ships `curl` -- so
# it only fires when nothing more managed matches. Re-running it upgrades.
MANAGERS = (
    ("brew", "homebrew", "brew install {}", "brew upgrade {}"),
    ("winget", "winget", f"winget install -e --id {{}} {WINGET_TAIL}", f"winget upgrade -e --id {{}} {WINGET_TAIL}"),
    ("cargo", "cargo", "cargo install {}", "cargo install {}"),
    ("go", "go", "go install {}", "go install {}"),
    ("pipx", "pipx", "pipx install {}", "pipx upgrade {}"),
    ("npm", "npm", "npm install -g {}", "npm update -g {}"),
    ("gem", "gem", "gem install {}", "gem update {}"),
)


def _methods(t: dict, col: int) -> list[tuple[str, str, str]]:
    """(method_id, guard, run) in preference order; col 2=install, 3=update."""
    out = [(mid, GUARDS[k], row[col].format(t[k]))
           for row in MANAGERS for k, mid in [row[:2]] if t.get(k)]
    if t.get("curl"):  # `curl_shell` overrides the pipe shell (default POSIX sh)
        out.append(("curl", GUARDS["curl"], f"curl -fsSL {t['curl']} | {t.get('curl_shell', 'sh')}"))
    return out


def render(t: dict) -> str:
    rid = t["id"]
    bin_ = t.get("bin", rid)
    detect = t.get("detect", f"{bin_} --version")
    verify = t.get("verify", detect)
    version_cur = t.get("version_current", verify)

    lines: list[str] = []
    lines.append(f"id: {rid}")
    lines.append("kind: cli-tool")
    lines.append(f'title: "{t["title"]}"')
    desc = t["desc"].rstrip()
    if t.get("url"):
        desc = f"{desc} {t['url']}"
    lines.append("description: >")
    lines.append(textwrap.fill(desc, 74, initial_indent="  ", subsequent_indent="  ",
                               break_long_words=False, break_on_hyphens=False))
    lines.append("")

    lines.append("detect:")
    lines.append(f'  command: "{detect}"')
    lines.append("")

    methods = _methods(t, 2)
    assert methods, f"{rid}: no install method"
    lines.append("install:")
    lines.append("  methods:")
    for mid, guard, run in methods:
        lines.append(f"    - id: {mid}")
        lines.append(f'      when: "{guard}"')
        lines.append(f'      run: "{run}"')
    lines.append("")

    lines.append("verify:")
    lines.append(f'  - command: "{verify}"')
    lines.append("")

    if t.get("gh"):
        lines.append("version:")
        lines.append(f'  current: "{version_cur}"')
        lines.append(f"  latest: {{ github: {t['gh']} }}")
        lines.append("")

    lines.append("update:")
    lines.append("  methods:")
    for mid, guard, run in _methods(t, 3):
        lines.append(f"    - id: {mid}")
        lines.append(f'      when: "{guard}"')
        lines.append(f'      run: "{run}"')
    lines.append("")
    # optional queriability metadata (see SCHEMA.md) — only emitted when a row
    # authors it, so rows without it render byte-identically to the pre-taxonomy
    # files. `category` overrides erbina's inferred bucket.
    if t.get("category"):
        lines.append(f"category: {t['category']}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import sys

    from recipe_data import TOOLS  # local import so the table lives in its own file

    # By default the generator never clobbers an existing recipe (so hand-tuned
    # files are safe). `--rewrite` re-renders every TOOLS row and overwrites a
    # file whose content has DRIFTED from its row — the safe way to backfill a new
    # field (e.g. `category:`) into already-generated recipes: rows unchanged since
    # generation render byte-identically and are left untouched.
    rewrite = "--rewrite" in (argv if argv is not None else sys.argv[1:])

    written, updated, skipped = 0, 0, 0
    seen: set[str] = set()
    for t in TOOLS:
        rid = t["id"]
        if rid in seen:
            raise SystemExit(f"duplicate id in TOOLS: {rid}")
        seen.add(rid)
        path = RECIPES_DIR / f"{rid}.yaml"
        rendered = render(t)
        if path.exists():
            if rewrite and path.read_text() != rendered:
                path.write_text(rendered)
                updated += 1
            else:
                skipped += 1
            continue
        path.write_text(rendered)
        written += 1
    print(f"wrote {written}, updated {updated}, skipped {skipped} existing, "
          f"{len(seen)} rows total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
