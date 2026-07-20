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

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECIPES_DIR = REPO_ROOT / "recipes"
README = REPO_ROOT / "README.md"
SAMPLES_MODULE = REPO_ROOT / "tests" / "_generated_version_samples.py"

# README gallery region managed by this script (kept in sync with recipes/).
GALLERY_BEGIN = "<!-- GENERATED:cli-tools (managed by scripts/gen_recipes.py) -->"
GALLERY_END = "<!-- /GENERATED:cli-tools -->"

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
}

WINGET_TAIL = (
    "--source winget --silent --accept-package-agreements "
    "--accept-source-agreements --disable-interactivity"
)


def _install_methods(t: dict) -> list[tuple[str, str, str]]:
    """(method_id, guard, run) install methods in preference order."""
    out: list[tuple[str, str, str]] = []
    if t.get("brew"):
        out.append(("homebrew", GUARDS["brew"], f"brew install {t['brew']}"))
    if t.get("winget"):
        out.append(("winget", GUARDS["winget"],
                    f"winget install -e --id {t['winget']} {WINGET_TAIL}"))
    if t.get("cargo"):
        out.append(("cargo", GUARDS["cargo"], f"cargo install {t['cargo']}"))
    if t.get("go"):
        out.append(("go", GUARDS["go"], f"go install {t['go']}"))
    if t.get("pipx"):
        out.append(("pipx", GUARDS["pipx"], f"pipx install {t['pipx']}"))
    if t.get("npm"):
        out.append(("npm", GUARDS["npm"], f"npm install -g {t['npm']}"))
    if t.get("gem"):
        out.append(("gem", GUARDS["gem"], f"gem install {t['gem']}"))
    return out


def _update_methods(t: dict) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if t.get("brew"):
        out.append(("homebrew", GUARDS["brew"], f"brew upgrade {t['brew']}"))
    if t.get("winget"):
        out.append(("winget", GUARDS["winget"],
                    f"winget upgrade -e --id {t['winget']} {WINGET_TAIL}"))
    if t.get("cargo"):
        out.append(("cargo", GUARDS["cargo"], f"cargo install {t['cargo']}"))
    if t.get("go"):
        out.append(("go", GUARDS["go"], f"go install {t['go']}"))
    if t.get("pipx"):
        out.append(("pipx", GUARDS["pipx"], f"pipx upgrade {t['pipx']}"))
    if t.get("npm"):
        out.append(("npm", GUARDS["npm"], f"npm update -g {t['npm']}"))
    if t.get("gem"):
        out.append(("gem", GUARDS["gem"], f"gem update {t['gem']}"))
    return out


def _wrap(text: str, width: int = 74, indent: str = "  ") -> str:
    words = text.split()
    lines: list[str] = []
    cur = indent
    for w in words:
        if len(cur) + len(w) + 1 > width and cur.strip():
            lines.append(cur.rstrip())
            cur = indent + w
        else:
            cur = (cur + " " + w) if cur.strip() else (indent + w)
    if cur.strip():
        lines.append(cur.rstrip())
    return "\n".join(lines)


def render(t: dict) -> str:
    rid = t["id"]
    bin_ = t.get("bin", rid)
    detect = t.get("detect", f"{bin_} --version")
    verify = t.get("verify", detect)
    version_cur = t.get("version_current", verify)
    short = t.get("short", t["title"])

    lines: list[str] = []
    lines.append(f"# erbina recipe — {rid}, a cli-tool. {short}")
    lines.append(f"id: {rid}")
    lines.append("kind: cli-tool")
    lines.append(f'title: "{t["title"]}"')
    desc = t["desc"].rstrip()
    if t.get("url"):
        desc = f"{desc} {t['url']}"
    lines.append("description: >")
    lines.append(_wrap(desc))
    lines.append("")

    lines.append("# 1. DETECT — already installed? Exits 0 when present.")
    lines.append("detect:")
    lines.append(f'  command: "{detect}"')
    lines.append("  expect_exit: 0")
    lines.append("")

    methods = _install_methods(t)
    assert methods, f"{rid}: no install method"
    lines.append("# 2. INSTALL — first passing guard wins.")
    lines.append("install:")
    lines.append("  methods:")
    for mid, guard, run in methods:
        lines.append(f"    - id: {mid}")
        lines.append(f'      when: "{guard}"')
        lines.append(f'      run: "{run}"')
    lines.append("")

    lines.append("# 3. VERIFY — prove it actually runs.")
    lines.append("verify:")
    lines.append(f'  - command: "{verify}"')
    lines.append("    expect_exit: 0")
    lines.append("")

    if t.get("gh"):
        lines.append("# 4. VERSION — powers check_updates (installed vs latest GitHub tag).")
        lines.append("version:")
        lines.append(f'  current: "{version_cur}"')
        lines.append(f"  latest: {{ github: {t['gh']} }}")
        lines.append("")

    lines.append("# 5. UPDATE — how `update` upgrades an installed copy.")
    lines.append("update:")
    lines.append("  methods:")
    for mid, guard, run in _update_methods(t):
        lines.append(f"    - id: {mid}")
        lines.append(f'      when: "{guard}"')
        lines.append(f'      run: "{run}"')
    lines.append("")
    lines.append("scope: user")
    # optional queriability metadata (see SCHEMA.md) — only emitted when a row
    # authors it, so rows without it render byte-identically to the pre-taxonomy
    # files. `category` overrides erbina's inferred bucket; `tags` add search terms.
    if t.get("category"):
        lines.append(f"category: {t['category']}")
    if t.get("tags"):
        lines.append(f"tags: [{', '.join(t['tags'])}]")
    lines.append("")
    return "\n".join(lines)


def _gallery_desc(t: dict) -> str:
    """Gallery blurb: the phrase after the em dash in the title, else the title."""
    title = t["title"]
    if "— " in title:
        return title.split("— ", 1)[1].strip()
    return title.strip()


def render_gallery_lines(tools: list[dict]) -> str:
    return "\n".join(
        f"- [`{t['id']}`](recipes/{t['id']}.yaml) — {_gallery_desc(t)}"
        for t in sorted(tools, key=lambda t: t["id"])
    )


def update_readme_gallery(tools: list[dict]) -> bool:
    text = README.read_text()
    if GALLERY_BEGIN not in text or GALLERY_END not in text:
        raise SystemExit(
            f"README is missing the gallery markers {GALLERY_BEGIN!r}/{GALLERY_END!r}"
        )
    pre, rest = text.split(GALLERY_BEGIN, 1)
    _, post = rest.split(GALLERY_END, 1)
    block = f"{GALLERY_BEGIN}\n{render_gallery_lines(tools)}\n{GALLERY_END}"
    new = pre + block + post
    if new != text:
        README.write_text(new)
        return True
    return False


def _version_sample(t: dict) -> tuple[str, str, str, str, str]:
    """(recipe_id, current_output, latest_tag_line, expected_current, expected_latest).

    Standardized representative output — `<bin> X.Y.Z` for current and a GitHub
    releases `tag_name` line for latest — chosen so `server._extract_version`
    yields the expected token (tool names carry no dotted-digit that could fool
    the version regex). `ver` on the row overrides the default sample version.
    """
    bin_ = t.get("bin", t["id"])
    ver = t.get("ver", "1.0.0")
    return (t["id"], f"{bin_} {ver}", f'  "tag_name": "v{ver}",', ver, ver)


def write_samples_module(tools: list[dict]) -> None:
    versioned = [t for t in tools if t.get("gh")]
    rows = ",\n".join("    " + repr(_version_sample(t)) for t in
                      sorted(versioned, key=lambda t: t["id"]))
    body = (
        '"""GENERATED by scripts/gen_recipes.py — do not edit by hand.\n\n'
        "Version-extraction red-team samples for the bulk-generated cli-tool\n"
        "recipes, consumed by tests/test_recipe_versions.py. Each tuple is\n"
        "(recipe_id, current_output, latest_tag_line, expected_current, expected_latest).\n"
        '"""\n'
        "GENERATED_SAMPLES = [\n"
        f"{rows},\n"
        "]\n"
    )
    SAMPLES_MODULE.write_text(body)


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
    gallery_changed = update_readme_gallery(TOOLS)
    write_samples_module(TOOLS)
    print(f"wrote {written}, updated {updated}, skipped {skipped} existing, "
          f"{len(seen)} rows total; README gallery "
          f"{'updated' if gallery_changed else 'unchanged'}; "
          f"{sum(1 for t in TOOLS if t.get('gh'))} version samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
