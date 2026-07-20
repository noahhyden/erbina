"""Curated-category regression lock.

`_categorize` infers a category from a recipe's text, but the heuristic can't get
every tool right — some tools describe themselves in terms that pull them into
the wrong bucket (e.g. a DigitalOcean CLI that mentions "Kubernetes clusters", a
linter that mentions "many languages"). For those we author an explicit
`category:` in the recipe, which wins over the inference.

This test pins the intended category of every curated recipe, so a future change
to the description or the classifier can't silently regress it. Each entry here
must have an authored `category:` in its YAML (that's the whole point — the
inference alone got them wrong or dumped them in `misc`).
"""
from __future__ import annotations

import server

# recipe id -> the category it MUST resolve to (authored, not inferred)
CURATED: dict[str, str] = {
    # code linters / analyzers / text tools the inference left in misc
    "cppcheck": "text",
    "hlint": "text",
    "pylint": "text",
    "shellharden": "text",
    "nbdime": "text",
    "gawk": "text",
    "cspell": "text",
    # python packaging / env managers
    "hatch": "packaging",
    "pipx": "packaging",
    "uv": "packaging",
    "virtualenv": "packaging",
    # data / database
    "papermill": "data",
    "fq": "data",
    "thrift": "data",
    "pspg": "database",
    "prisma": "database",
    # dev/testing utilities
    "pa11y": "devtools",
    "playwright": "devtools",
    "scc": "devtools",
    "tokei": "devtools",
    # process/watch monitors
    "pm2": "monitoring",
    "viddy": "monitoring",
    # build / bundlers / compilers
    "sass": "build",
    "wasm-pack": "build",
    "parcel": "build",
    "pyinstaller": "build",
    # security
    "subfinder": "security",
    "semgrep": "security",
    "opa": "security",
    "checkov": "security",
    "conftest": "security",
    # misc-bucket rescues
    "thefuck": "shells",
    "typst": "docs",
    "zola": "docs",
    "volta": "languages",
    "ghostscript": "media",
    # kubernetes over-capture corrections
    "colima": "containers",
    "doctl": "cloud",
    # round 2 — flagship tools the git/media buckets over-captured because their
    # blurbs mention "Git integration" / "color" / "graph" in passing.
    "bat": "files",
    "eza": "files",
    "lsd": "files",
    "yazi": "files",
    "typos": "text",
    "icdiff": "text",
    "htop": "monitoring",
    "concurrently": "devtools",
    "webpack": "build",
    "mdcat": "docs",
}


def test_curated_recipes_resolve_to_expected_category():
    for rid, expected in CURATED.items():
        recipe = server._load_recipe(rid)
        got = server._categorize(recipe)[0]
        assert got == expected, f"{rid}: expected {expected!r}, got {got!r}"


def test_curated_recipes_actually_author_the_category():
    # guard that these are STORED (the inference is deliberately overridden), not
    # coincidentally inferred — otherwise the lock above would be vacuous.
    for rid, expected in CURATED.items():
        recipe = server._load_recipe(rid)
        assert recipe.get("category") == expected, (
            f"{rid}: should carry an authored `category: {expected}` in its YAML"
        )
