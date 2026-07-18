"""Behavioral tests for the check_updates tool, driven through the in-memory
client against prototype recipes. Version commands are `echo <version>` builtins,
so the whole check is deterministic and side-effect free.
"""
from __future__ import annotations

import pytest

from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, registry


def _versioned(rid, current="1.0.0", latest="2.0.0", detect=TRUE):
    return cli_recipe(
        rid,
        detect={"command": detect},
        version={"current": f"echo {current}", "latest": f"echo {latest}"},
    )


def _check(recipe, **kwargs):
    with registry(recipe):
        return call_tool("check_updates", {"recipe_id": recipe["id"], **kwargs})


# --------------------------------------------------------------------------- #
# core: update available / current / newer-installed
# --------------------------------------------------------------------------- #
def test_reports_available_update():
    out = _check(_versioned("t", current="1.0.0", latest="2.0.0"))
    entry = out["checked"][0]
    assert entry["installed"] is True
    assert entry["current"] == "1.0.0"
    assert entry["latest"] == "2.0.0"
    assert entry["update_available"] is True
    assert out["updates_available"] == ["t"]
    assert "1 update" in out["hint"]


def test_reports_up_to_date():
    out = _check(_versioned("t", current="1.2.3", latest="1.2.3"))
    assert out["checked"][0]["update_available"] is False
    assert out["updates_available"] == []
    assert "No updates" in out["hint"]


def test_summary_reflects_available_updates():
    out = _check(_versioned("t", current="1.0.0", latest="2.0.0"))
    assert "1 tool update(s) available" in out["summary"]
    assert "t" in out["summary"]


def test_summary_when_all_current():
    out = _check(_versioned("t", current="1.0.0", latest="1.0.0"))
    assert out["summary"] == "erbina: all tracked tools are up to date."


# --------------------------------------------------------------------------- #
# not installed -> nothing to update
# --------------------------------------------------------------------------- #
def test_not_installed_is_reported_without_version_compare():
    out = _check(_versioned("t", detect=FALSE))
    entry = out["checked"][0]
    assert entry["installed"] is False
    assert "not installed" in entry["note"]
    assert "current" not in entry  # no version comparison attempted
    assert out["updates_available"] == []


# --------------------------------------------------------------------------- #
# recipes without a version block
# --------------------------------------------------------------------------- #
def test_explicit_recipe_without_version_block_errors():
    with registry(cli_recipe("noversion")):
        out = call_tool("check_updates", {"recipe_id": "noversion"})
    assert "error" in out
    assert "version" in out["error"]


def test_bulk_scan_skips_recipes_without_version_block():
    with registry(_versioned("has_ver"), cli_recipe("no_ver")):
        out = call_tool("check_updates", {})  # no recipe_id -> scan all
    ids = {e["id"] for e in out["checked"]}
    assert ids == {"has_ver"}  # only the opted-in recipe appears


def test_bulk_scan_over_multiple_versioned_recipes():
    with registry(
        _versioned("a", current="1.0.0", latest="2.0.0"),  # update
        _versioned("b", current="3.0.0", latest="3.0.0"),  # current
    ):
        out = call_tool("check_updates", {})
    assert set(out["updates_available"]) == {"a"}
    assert {e["id"] for e in out["checked"]} == {"a", "b"}


# --------------------------------------------------------------------------- #
# unparseable version output never claims an update
# --------------------------------------------------------------------------- #
def test_unparseable_version_output_is_safe():
    out = _check(_versioned("t", current="whoknows", latest="2.0.0"))
    entry = out["checked"][0]
    assert entry["update_available"] is None
    assert out["updates_available"] == []
    # no version token at all -> the "could not parse" branch (server.py:167-172)
    assert entry["reason"] == "could not parse a version from the command output"


# --------------------------------------------------------------------------- #
# CHARACTERIZATION — the extraction regex is more permissive than packaging.
#
# `_extract_version` happily pulls tokens like "1.2.3-git20240101" /
# "2.0-SNAPSHOT" / "1.2.3-alpha.beta" out of `--version` output, but
# packaging.Version() rejects them, so `_version_status` falls into its
# `except InvalidVersion` arm (server.py:176-177) and reports update_available
# None with a DISTINCT reason ("unparseable version: ...") from the no-token
# case above. These tests pin that current behavior AND cover that branch.
#
# CANDIDATE FINDING (documented in PROTOTYPE_NOTES.md, not fixed yet): the arm
# is safe (never a false update) but LOSSY — a tool whose current version is
# "1.2.3-git20240101" and whose latest is "1.2.4" is silently NOT flagged as
# updatable, even though the release core "1.2.3" is right there and clearly
# older. See test_CURRENT_suffixed_current_misses_a_real_update.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad",
    ["1.2.3-git20240101", "2.0-SNAPSHOT", "1.2.3-alpha.beta", "10.20.30-rc.1.2.3"],
)
def test_extracted_but_unparseable_version_is_safe_with_distinct_reason(bad):
    out = _check(_versioned("t", current=bad, latest="2.0.0"))
    entry = out["checked"][0]
    # token WAS extracted (so this is the InvalidVersion arm, not the None arm)
    assert entry["current"] == bad
    assert entry["update_available"] is None
    assert entry["reason"].startswith("unparseable version:")
    assert out["updates_available"] == []


def test_CURRENT_suffixed_current_misses_a_real_update():
    """Pinned quirk: a real, newer `latest` is not surfaced when `current`
    carries a packaging-illegal suffix. If a future iteration teaches
    `_version_status` to fall back to the release core, flip this to expect
    update_available True and updates_available == ["t"]."""
    out = _check(_versioned("t", current="1.2.3-git20240101", latest="1.2.4"))
    entry = out["checked"][0]
    assert entry["update_available"] is None  # <- the lossy behavior being pinned
    assert out["updates_available"] == []
