"""Keep the README "Recipe gallery" in sync with recipes/.

A gallery that silently goes stale is worse than none. This asserts the gallery
lists exactly the recipe ids present in recipes/ — catching both a new recipe
that wasn't added and a removed recipe still listed.
"""
from __future__ import annotations

import re
from pathlib import Path

import server

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

# a gallery list item: `- [`<id>`](recipes/<id>.yaml) — ...`
_GALLERY_ITEM = re.compile(r"^- \[`([a-z0-9_-]+)`\]\(recipes/", re.MULTILINE)


def _gallery_section() -> str:
    text = README.read_text()
    start = text.index("## Recipe gallery")
    rest = text[start + len("## Recipe gallery"):]
    end = rest.find("\n## ")  # next top-level section
    return rest if end == -1 else rest[:end]


def test_readme_has_a_gallery_section():
    assert "## Recipe gallery" in README.read_text()


def test_gallery_lists_exactly_the_recipes_on_disk():
    listed = set(_GALLERY_ITEM.findall(_gallery_section()))
    on_disk = set(server._recipe_ids())
    assert listed == on_disk, (
        f"README gallery out of sync — missing: {sorted(on_disk - listed)}; "
        f"stale: {sorted(listed - on_disk)}"
    )


def test_gallery_links_point_at_real_recipe_files():
    for rid in _GALLERY_ITEM.findall(_gallery_section()):
        assert (REPO_ROOT / "recipes" / f"{rid}.yaml").exists(), f"gallery links to missing {rid}.yaml"
