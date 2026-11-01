"""Red-team shipped version blocks: real-world `--version`/tag output must yield a parseable token or check_updates silently returns update_available=null."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import server
from helpers import call_tool

# (recipe, sample `current` output, sample `latest`/tag output, expected current, expected latest)
VERSION_SAMPLES = [
    ("ripgrep", "ripgrep 14.1.1\nfeatures:+pcre2\nsimd(compile):+SSE2", '  "tag_name": "14.1.1",', "14.1.1", "14.1.1"),
    ("fd", "fd 10.1.0", '  "tag_name": "v10.1.0",', "10.1.0", "10.1.0"),
    # jq prints and tags "jq-1.7.1"; the leading "jq-" has no digit, so the first token is the version.
    ("jq", "jq-1.7.1", '  "tag_name": "jq-1.7.1",', "1.7.1", "1.7.1"),
    ("bat", "bat 0.24.0", '  "tag_name": "v0.24.0",', "0.24.0", "0.24.0"),
    ("delta", "delta 0.18.2", '  "tag_name": "0.18.2",', "0.18.2", "0.18.2"),
    ("zoxide", "zoxide 0.9.6", '  "tag_name": "v0.9.6",', "0.9.6", "0.9.6"),
    # eza prints a version-less banner then "v0.20.4 [+git]"; extraction must skip the banner line.
    ("eza", "eza - A modern, maintained replacement for ls\nv0.20.4 [+git]", '  "tag_name": "v0.20.4",', "0.20.4", "0.20.4"),
    ("uv", "uv 0.5.11 (abc1234 2024-11-27)", '  "tag_name": "0.5.11",', "0.5.11", "0.5.11"),
    ("hyperfine", "hyperfine 1.18.0", '  "tag_name": "v1.18.0",', "1.18.0", "1.18.0"),
    ("dust", "Dust 1.1.1", '  "tag_name": "v1.1.1",', "1.1.1", "1.1.1"),
    ("bottom", "btm 0.10.2", '  "tag_name": "0.10.2",', "0.10.2", "0.10.2"),
    ("sd", "sd 1.0.0", '  "tag_name": "v1.0.0",', "1.0.0", "1.0.0"),
    ("tokei", "tokei 12.1.2", '  "tag_name": "v12.1.2",', "12.1.2", "12.1.2"),
    # tealdeer's binary is `tldr`; `tldr --version` prints "tealdeer 1.7.0".
    ("tealdeer", "tealdeer 1.7.0", '  "tag_name": "v1.7.0",', "1.7.0", "1.7.0"),
    ("procs", "procs 0.14.5", '  "tag_name": "v0.14.5",', "0.14.5", "0.14.5"),
    ("ataegina", "ataegina 0.1.0", '  "tag_name": "v0.2.0",', "0.1.0", "0.2.0"),
    # gh prints a two-line banner with a URL and an ISO date; dates use '-', so no dotted token competes with the version.
    ("gh", "gh version 2.62.0 (2024-11-27)\nhttps://github.com/cli/cli/releases/tag/v2.62.0",
     '  "tag_name": "v2.63.0",', "2.62.0", "2.63.0"),
    # lazygit embeds the version among commit=/build date=/os= fields.
    ("lazygit", "commit=abcdef0, build date=2024-11-20, build source=binaryRelease, version=0.44.1, os=darwin, arch=arm64",
     '  "tag_name": "v0.44.1",', "0.44.1", "0.44.1"),
    # yq prints its repo URL before "version v4.44.3".
    ("yq", "yq (https://github.com/mikefarah/yq/) version v4.44.3", '  "tag_name": "v4.44.3",', "4.44.3", "4.44.3"),
    ("difftastic", "Difftastic 0.61.0", '  "tag_name": "0.61.0",', "0.61.0", "0.61.0"),
    # httpie's `http --version` prints just the bare version number.
    ("httpie", "3.2.4", '  "tag_name": "3.2.4",', "3.2.4", "3.2.4"),
]

@pytest.mark.parametrize("rid,cur_out,lat_out,exp_cur,exp_lat", VERSION_SAMPLES)
def test_recipe_version_comparison_is_definite(rid, cur_out, lat_out, exp_cur, exp_lat):
    # a real comparison must resolve to True/False, never None (unparseable)
    status = server._version_status(cur_out, lat_out)
    assert status["update_available"] is not None, f"{rid}: version compare came back null"
    assert status["update_available"] == (exp_cur != exp_lat)


def test_every_versioned_recipe_extracts_a_version():
    # A version: block must yield a token from its binary's `<bin> X.Y.Z` output (the binary is the first token of version.current).
    for rid in server._recipe_ids():
        v = server._load_recipe(rid).get("version")
        if v:
            binary = v["current"].split()[0]
            assert server._extract_version(f"{binary} 1.0.0") == "1.0.0", f"{rid}: {binary}"


def test_every_winget_recipe_is_covered():
    TOOLS = json.loads((Path(__file__).parent.parent / "scripts" / "recipe_data.json").read_text())

    generated = {t["id"] for t in TOOLS if t.get("winget")}
    with_winget = {rid for rid in server._recipe_ids()
                   if any(m.get("id") == "winget"
                          for m in (server._load_recipe(rid).get("install", {}).get("methods") or []))}
    assert generated <= with_winget, f"recipe_data.json winget recipe lost its method: {generated - with_winget}"


# mcp-server wiring: lock the exact `claude mcp add` command per recipe and scope; `runner` is everything after `-- ` (uvx for Python, npx for Node).
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
