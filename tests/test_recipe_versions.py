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
    ("bat", "bat 0.24.0", '  "tag_name": "v0.24.0",', "0.24.0", "0.24.0"),
    ("delta", "delta 0.18.2", '  "tag_name": "0.18.2",', "0.18.2", "0.18.2"),
    ("zoxide", "zoxide 0.9.6", '  "tag_name": "v0.9.6",', "0.9.6", "0.9.6"),
    # eza prints a banner line (no version) then "v0.20.4 [+git]" — extraction
    # must skip the banner and find the token on the second line.
    ("eza", "eza - A modern, maintained replacement for ls\nv0.20.4 [+git]", '  "tag_name": "v0.20.4",', "0.20.4", "0.20.4"),
    ("uv", "uv 0.5.11 (abc1234 2024-11-27)", '  "tag_name": "0.5.11",', "0.5.11", "0.5.11"),
    ("hyperfine", "hyperfine 1.18.0", '  "tag_name": "v1.18.0",', "1.18.0", "1.18.0"),
    ("dust", "Dust 1.1.1", '  "tag_name": "v1.1.1",', "1.1.1", "1.1.1"),
    ("bottom", "btm 0.10.2", '  "tag_name": "0.10.2",', "0.10.2", "0.10.2"),
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
    ("bat", "bat --version", {"homebrew": "brew install bat", "cargo": "cargo install bat"}, "bat --version"),
    # delta: binary is `delta`, but the brew formula AND cargo crate are `git-delta`
    ("delta", "delta --version", {"homebrew": "brew install git-delta", "cargo": "cargo install git-delta"}, "delta --version"),
    ("zoxide", "zoxide --version", {"homebrew": "brew install zoxide", "cargo": "cargo install zoxide --locked"}, "zoxide --version"),
    ("eza", "eza --version", {"homebrew": "brew install eza", "cargo": "cargo install eza"}, "eza --version"),
    ("uv", "uv --version", {"homebrew": "brew install uv", "standalone": "curl -LsSf https://astral.sh/uv/install.sh | sh"}, "uv --version"),
    ("hyperfine", "hyperfine --version", {"homebrew": "brew install hyperfine", "cargo": "cargo install hyperfine"}, "hyperfine --version"),
    # dust: binary/formula are `dust`, but the cargo crate is `du-dust`
    ("dust", "dust --version", {"homebrew": "brew install dust", "cargo": "cargo install du-dust"}, "dust --version"),
    # bottom: formula/crate are `bottom`, but the binary is `btm`
    ("bottom", "btm --version", {"homebrew": "brew install bottom", "cargo": "cargo install bottom --locked"}, "btm --version"),
])
def test_cli_recipe_plan_commands(rid, detect_cmd, methods, verify_cmd):
    plan = call_tool("inspect_recipe", {"recipe_id": rid})["will_run"]
    assert plan["detect"] == detect_cmd
    got = {m["id"]: m["run"] for m in plan["install"]["all_methods"]}
    assert got == methods
    assert verify_cmd in plan["verify"]


# --------------------------------------------------------------------------- #
# mcp-server wiring: lock the exact `claude mcp add` command per recipe + scope
# so a wrong runner/package or missing scope substitution is caught. `runner` is
# everything after `-- ` (uvx for Python servers, npx for Node ones).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rid,runner", [
    ("fetch", "uvx mcp-server-fetch"),
    ("git", "uvx mcp-server-git"),
    ("time", "uvx mcp-server-time"),
    ("sequentialthinking", "npx -y @modelcontextprotocol/server-sequential-thinking"),
    ("memory", "npx -y @modelcontextprotocol/server-memory"),
    ("everything", "npx -y @modelcontextprotocol/server-everything"),
])
def test_mcp_server_wiring_command(rid, runner):
    for scope in ("user", "project", "local"):
        plan = call_tool("bootstrap", {"recipe_id": rid, "scope": scope, "dry_run": True})["plan"]
        runs = " ".join(s["run"] for s in plan["configure"])
        assert f"claude mcp add {rid} --scope {scope} -- {runner}" in runs
