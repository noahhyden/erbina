#!/usr/bin/env python3
"""Generate curated cli-tool recipes from the scripts/recipe_data.py table."""
from __future__ import annotations

import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECIPES_DIR = REPO_ROOT / "recipes"

# Guard per package manager: every method only fires where its manager exists.
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


# (key, method id, install, update) in preference order; curl|sh is the last-resort fallback.
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
    if not t.get("category"):
        raise SystemExit(f"{rid}: row has no category (required on every recipe)")
    lines.append(f"category: {t['category']}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import sys

    from _harvest import DEFAULT_RECIPE_DATA, load_tools

    TOOLS = load_tools(DEFAULT_RECIPE_DATA)

    # never clobbers an existing recipe; --rewrite overwrites only files that drifted from their row.
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
