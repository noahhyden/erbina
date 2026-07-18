"""Red-team the shipped recipes' version blocks and install plans.

The risk with a `version:` block is that a tool's real `--version` / release-tag
output doesn't yield a parseable token — then check_updates silently returns
update_available=null and the feature is dead weight. These tests feed
REPRESENTATIVE real-world outputs through erbina's extraction/compare and assert
a definite result, and lock the install/verify commands so a recipe typo is
caught.
"""
from __future__ import annotations

import pytest

import server
from helpers import call_tool

# (recipe, sample `current` output, sample `latest`/tag output, expected current, expected latest)
VERSION_SAMPLES = [
    ("ripgrep", "ripgrep 14.1.1\nfeatures:+pcre2\nsimd(compile):+SSE2", '  "tag_name": "14.1.1",', "14.1.1", "14.1.1"),
    ("fd", "fd 10.1.0", '  "tag_name": "v10.1.0",', "10.1.0", "10.1.0"),
    # jq prints "jq-1.7.1" and tags "jq-1.7.1" — the leading "jq-" must not fool
    # extraction (there's no digit in "jq", so the first token is the version).
    ("jq", "jq-1.7.1", '  "tag_name": "jq-1.7.1",', "1.7.1", "1.7.1"),
    ("ataegina", "ataegina 0.1.0", '  "tag_name": "v0.2.0",', "0.1.0", "0.2.0"),
]


@pytest.mark.parametrize("rid,cur_out,lat_out,exp_cur,exp_lat", VERSION_SAMPLES)
def test_recipe_version_output_extracts_a_token(rid, cur_out, lat_out, exp_cur, exp_lat):
    assert server._extract_version(cur_out) == exp_cur, f"{rid}: current"
    assert server._extract_version(lat_out) == exp_lat, f"{rid}: latest"


@pytest.mark.parametrize("rid,cur_out,lat_out,exp_cur,exp_lat", VERSION_SAMPLES)
def test_recipe_version_comparison_is_definite(rid, cur_out, lat_out, exp_cur, exp_lat):
    # a real comparison must resolve to True/False, never None (unparseable)
    status = server._version_status(cur_out, lat_out)
    assert status["update_available"] is not None, f"{rid}: version compare came back null"
    assert status["update_available"] == (exp_cur != exp_lat)


def test_every_versioned_recipe_is_covered_by_a_sample():
    # guard: if a recipe declares a version: block, it must have a sample here, so
    # nobody adds a versioned recipe without red-teaming its output format.
    covered = {s[0] for s in VERSION_SAMPLES}
    for rid in server._recipe_ids():
        if server._load_recipe(rid).get("version"):
            assert rid in covered, f"{rid} has a version: block but no version sample in VERSION_SAMPLES"


# --------------------------------------------------------------------------- #
# install/verify plan shape for the new cli-tool recipes (catch command typos)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rid,detect_cmd,methods,verify_cmd", [
    ("ripgrep", "rg --version", {"homebrew": "brew install ripgrep", "cargo": "cargo install ripgrep"}, "rg --version"),
    ("fd", "fd --version", {"homebrew": "brew install fd", "cargo": "cargo install fd-find"}, "fd --version"),
])
def test_cli_recipe_plan_commands(rid, detect_cmd, methods, verify_cmd):
    plan = call_tool("inspect_recipe", {"recipe_id": rid})["will_run"]
    assert plan["detect"] == detect_cmd
    got = {m["id"]: m["run"] for m in plan["install"]["all_methods"]}
    assert got == methods
    assert verify_cmd in plan["verify"]


# --------------------------------------------------------------------------- #
# mcp-server wiring: lock the exact `claude mcp add` command per recipe + scope
# so a wrong package name (mcp-server-<x>) or missing scope substitution is caught
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rid,pkg", [
    ("fetch", "mcp-server-fetch"),
    ("git", "mcp-server-git"),
    ("time", "mcp-server-time"),
])
def test_mcp_server_wiring_command(rid, pkg):
    for scope in ("user", "project", "local"):
        plan = call_tool("bootstrap", {"recipe_id": rid, "scope": scope, "dry_run": True})["plan"]
        runs = " ".join(s["run"] for s in plan["configure"])
        assert f"claude mcp add {rid} --scope {scope} -- uvx {pkg}" in runs
