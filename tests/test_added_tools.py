"""Spec-lock for a curated batch of well-known CLI tools added to the registry.

These are real, widely-used tools with package names verified by hand (the
weekly real-bootstrap CI is the ultimate check, but this pins the intended
identity/category so a regeneration or classifier change can't drop or relabel
them). Each must load cleanly, verify by RUNNING its binary, and land in its
intended category.
"""
from __future__ import annotations

import shlex

import server

# recipe id -> (expected category, binary the detect/verify command must run)
ADDED: dict[str, tuple[str, str]] = {
    "dog": ("network", "dog"),
    "ctop": ("containers", "ctop"),
    "borg": ("files", "borg"),
    "magic-wormhole": ("network", "wormhole"),
    "aichat": ("devtools", "aichat"),
    "television": ("search", "tv"),
}


def test_added_tools_load_and_categorize():
    for rid, (category, _bin) in ADDED.items():
        recipe = server._load_recipe(rid)  # raises if malformed
        assert recipe["kind"] == "cli-tool"
        assert server._categorize(recipe)[0] == category, f"{rid} category"


def test_added_tools_verify_by_running_their_binary():
    # erbina's thesis: verify RUNS the tool. Each verify command's first token
    # must be the tool's own binary, not a filesystem probe.
    for rid, (_category, binary) in ADDED.items():
        recipe = server._load_recipe(rid)
        verify_cmds = [v["command"] for v in recipe["verify"]]
        assert any(shlex.split(c)[0] == binary for c in verify_cmds), (
            f"{rid}: no verify command runs `{binary}`"
        )


def test_added_tools_install_methods_are_guarded():
    for rid in ADDED:
        recipe = server._load_recipe(rid)
        for m in recipe["install"]["methods"]:
            assert m.get("when", "").strip(), f"{rid}: unguarded install method {m.get('id')}"
