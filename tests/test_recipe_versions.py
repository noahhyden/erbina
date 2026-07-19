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
    ("sd", "sd 1.0.0", '  "tag_name": "v1.0.0",', "1.0.0", "1.0.0"),
    ("tokei", "tokei 12.1.2", '  "tag_name": "v12.1.2",', "12.1.2", "12.1.2"),
    # tealdeer's binary is `tldr`; `tldr --version` prints "tealdeer 1.7.0".
    ("tealdeer", "tealdeer 1.7.0", '  "tag_name": "v1.7.0",', "1.7.0", "1.7.0"),
    ("procs", "procs 0.14.5", '  "tag_name": "v0.14.5",', "0.14.5", "0.14.5"),
    ("ataegina", "ataegina 0.1.0", '  "tag_name": "v0.2.0",', "0.1.0", "0.2.0"),
    # gh prints a two-line banner with a trailing URL + an ISO date; extraction
    # must take the version and ignore both (dates use '-', so no dotted token).
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
    ("sd", "sd --version", {"homebrew": "brew install sd", "cargo": "cargo install sd"}, "sd --version"),
    ("tokei", "tokei --version", {"homebrew": "brew install tokei", "cargo": "cargo install tokei"}, "tokei --version"),
    # tealdeer: formula/crate are `tealdeer`, but the binary is `tldr`
    ("tealdeer", "tldr --version", {"homebrew": "brew install tealdeer", "cargo": "cargo install tealdeer"}, "tldr --version"),
    ("procs", "procs --version", {"homebrew": "brew install procs", "cargo": "cargo install procs"}, "procs --version"),
])
def test_cli_recipe_plan_commands(rid, detect_cmd, methods, verify_cmd):
    plan = call_tool("inspect_recipe", {"recipe_id": rid})["will_run"]
    assert plan["detect"] == detect_cmd
    got = {m["id"]: m["run"] for m in plan["install"]["all_methods"]}
    # the brew/cargo commands must match exactly (catch a typo); a cross-platform
    # `winget` method may additionally be present (its id is locked separately).
    for mid, run in methods.items():
        assert got.get(mid) == run, f"{rid}.{mid}: {got.get(mid)!r}"
    assert set(got) - set(methods) <= {"winget"}, f"{rid}: unexpected methods {set(got) - set(methods)}"
    assert verify_cmd in plan["verify"]


# --------------------------------------------------------------------------- #
# Windows: the winget package IDs (typo-prone) are locked here and proven for
# real by the `windows` job in the real-bootstrap workflow.
# --------------------------------------------------------------------------- #
WINGET_IDS = {
    "ripgrep": "BurntSushi.ripgrep.MSVC", "fd": "sharkdp.fd", "bat": "sharkdp.bat",
    "jq": "jqlang.jq", "gh": "GitHub.cli", "delta": "dandavison.delta",
    "zoxide": "ajeetdsouza.zoxide", "hyperfine": "sharkdp.hyperfine", "uv": "astral-sh.uv",
    "lazygit": "JesseDuffield.lazygit", "yq": "MikeFarah.yq",
    "dust": "bootandy.dust", "bottom": "Clement.bottom",
}


@pytest.mark.parametrize("rid,wid", sorted(WINGET_IDS.items()))
def test_winget_method_is_guarded_and_carries_the_id(rid, wid):
    plan = call_tool("inspect_recipe", {"recipe_id": rid})["will_run"]
    methods = {m["id"]: m for m in plan["install"]["all_methods"]}
    assert "winget" in methods, f"{rid}: no winget install method"
    win = methods["winget"]
    assert win["when"] == "winget --version"       # Windows-only guard (degrades on POSIX)
    assert f"--id {wid} " in win["run"]             # the exact package id
    assert "winget install" in win["run"]


def test_every_winget_recipe_is_covered():
    # a recipe that grows a winget method must be listed above (so its id is locked)
    with_winget = {rid for rid in server._recipe_ids()
                   if any(m.get("id") == "winget"
                          for m in (server._load_recipe(rid).get("install", {}).get("methods") or []))}
    assert with_winget == set(WINGET_IDS), (
        f"uncovered: {with_winget - set(WINGET_IDS)}; stale: {set(WINGET_IDS) - with_winget}"
    )


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
