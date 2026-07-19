"""Tests for the structured `version.latest: {github: "owner/repo"}` source.

erbina resolves the mapping into the same releases-API `curl | grep '"tag_name"'`
command recipes used to hand-roll, so `check_updates` extraction/comparison is
unchanged — this just removes boilerplate and a class of copy-paste typos.
"""
from __future__ import annotations

import pytest

import server
from helpers import call_tool
from prototype import TRUE, cli_recipe, registry


# --------------------------------------------------------------------------- #
# _latest_command resolver
# --------------------------------------------------------------------------- #
def test_string_latest_is_returned_unchanged():
    assert server._latest_command("rg --version") == "rg --version"


def test_github_form_expands_to_releases_api_with_tag_grep():
    cmd = server._latest_command({"github": "BurntSushi/ripgrep"})
    assert "api.github.com/repos/BurntSushi/ripgrep/releases/latest" in cmd
    assert "curl -fsSL" in cmd
    assert 'grep \'"tag_name"\'' in cmd  # the grep isolates the tag line


def test_github_form_matches_the_legacy_handrolled_string():
    # migrating a recipe from the raw string to {github: …} must be a no-op
    legacy = (
        "curl -fsSL https://api.github.com/repos/o/r/releases/latest | grep '\"tag_name\"'"
    )
    assert server._latest_command({"github": "o/r"}) == legacy


@pytest.mark.parametrize("bad", [{"github": ""}, {"github": "noslash"}, {"other": "x"}, {}, 5, None])
def test_malformed_latest_resolves_to_empty(bad):
    # anything the validator rejects must not produce a runnable command
    assert server._latest_command(bad) == ""


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def test_github_latest_validates_clean():
    r = cli_recipe("t", version={"current": "t --version", "latest": {"github": "owner/repo"}})
    assert server.validate_recipe(r, stem="t") == []


def test_string_latest_still_validates_clean():
    r = cli_recipe("t", version={"current": "t --version", "latest": "echo 1.2.3"})
    assert server.validate_recipe(r, stem="t") == []


@pytest.mark.parametrize("latest,needle", [
    ({"github": ""}, "owner/repo"),
    ({"github": "noslash"}, "owner/repo"),
    ({"github": "a/b/c"}, "owner/repo"),
    ({"github": 5}, "owner/repo"),
    ({"github": "a/b", "ref": "main"}, "only the 'github' key"),
    ({"tarball": "x"}, "only the 'github' key"),
    (5, "must be a non-empty string or"),
    ({}, "only the 'github' key"),
    ("   ", "non-empty string"),   # a blank string latest is rejected like any command
])
def test_bad_github_latest_is_reported(latest, needle):
    r = cli_recipe("t", version={"current": "t --version", "latest": latest})
    errs = server.validate_recipe(r, stem="t")
    assert any(needle in e for e in errs), (latest, errs)


def test_current_still_required_as_a_string():
    r = cli_recipe("t", version={"current": {"github": "o/r"}, "latest": "echo 1"})
    errs = server.validate_recipe(r, stem="t")
    assert any("version.current" in e for e in errs)


# --------------------------------------------------------------------------- #
# check_updates end-to-end through the github source (network mocked)
# --------------------------------------------------------------------------- #
def test_release_notes_url_for_github_source():
    assert server._release_notes_url({"github": "BurntSushi/ripgrep"}) == \
        "https://github.com/BurntSushi/ripgrep/releases"


@pytest.mark.parametrize("latest", ["rg --version", {"github": "noslash"}, {"other": "x"}, {}, 5, None])
def test_release_notes_url_is_none_for_non_github_latest(latest):
    assert server._release_notes_url(latest) is None


def test_check_updates_surfaces_release_notes_for_github_source(monkeypatch):
    def fake_run(cmd, *a, **k):
        out = '  "tag_name": "2.0.0",' if "api.github.com" in cmd else "1.0.0"
        return {"cmd": cmd, "exit": 0, "stdout": out, "stderr": ""}

    monkeypatch.setattr(server, "_run", fake_run)
    r = cli_recipe("t", detect={"command": TRUE},
                   version={"current": "t --version", "latest": {"github": "o/r"}})
    with registry(r):
        entry = call_tool("check_updates", {"recipe_id": "t"})["checked"][0]
    assert entry["update_available"] is True
    assert entry["release_notes"] == "https://github.com/o/r/releases"


def test_check_updates_omits_release_notes_for_a_string_latest(monkeypatch):
    monkeypatch.setattr(server, "_run", lambda cmd, *a, **k: {"cmd": cmd, "exit": 0, "stdout": "1.0.0", "stderr": ""})
    r = cli_recipe("t", detect={"command": TRUE},
                   version={"current": "t --version", "latest": "echo 2.0.0"})
    with registry(r):
        entry = call_tool("check_updates", {"recipe_id": "t"})["checked"][0]
    assert "release_notes" not in entry  # a plain command has no known notes URL


def test_check_updates_resolves_github_source(monkeypatch):
    # intercept the resolved curl command and return a canned releases-API line
    def fake_run(cmd, *a, **k):
        if "api.github.com" in cmd:
            out = '  "tag_name": "2.0.0",'
        else:
            out = "1.0.0"  # the `current` command
        return {"cmd": cmd, "exit": 0, "stdout": out, "stderr": ""}

    monkeypatch.setattr(server, "_run", fake_run)
    r = cli_recipe("t", detect={"command": TRUE},
                   version={"current": "t --version", "latest": {"github": "o/r"}})
    with registry(r):
        out = call_tool("check_updates", {"recipe_id": "t"})
    entry = out["checked"][0]
    assert entry["current"] == "1.0.0"
    assert entry["latest"] == "2.0.0"      # extracted from the tag_name line
    assert entry["update_available"] is True
    assert out["updates_available"] == ["t"]
