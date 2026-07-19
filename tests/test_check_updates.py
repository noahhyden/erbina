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
# load failures: an EXPLICIT recipe_id surfaces the error; a bulk scan skips the
# unloadable recipe and still reports the good ones (server.py:762-765).
# --------------------------------------------------------------------------- #
def test_explicit_unloadable_recipe_surfaces_error():
    with registry(_versioned("good")) as tmp:
        (tmp / "broken.yaml").write_text("id: broken\nkind: not-a-kind\n")  # fails validate
        out = call_tool("check_updates", {"recipe_id": "broken"})
    assert "error" in out
    assert "malformed" in out["error"]  # the _load_recipe refusal is surfaced verbatim


def test_bulk_scan_skips_an_unloadable_recipe():
    with registry(_versioned("good", current="1.0.0", latest="2.0.0")) as tmp:
        (tmp / "broken.yaml").write_text("id: broken\nkind: not-a-kind\n")
        out = call_tool("check_updates", {})  # no recipe_id -> scan all
    # broken is silently skipped; the good versioned recipe is still checked
    assert {e["id"] for e in out["checked"]} == {"good"}
    assert out["updates_available"] == ["good"]


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
# FINDING #4 (fixed): the extraction regex is more permissive than packaging, so
# a `current` version with a dev/vcs suffix (`1.2.3-git20240101`, `2.0-SNAPSHOT`,
# `1.2.3-alpha.beta`) fails packaging.Version(). `_version_status` now falls back
# to the numeric release CORE for `current` (server.py `_release_core`), so a
# suffixed current still compares against a clean `latest` instead of hiding a
# real update. `latest` stays strict (see the unparseable-latest test below).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "current,latest,expected",
    [
        ("1.2.3-git20240101", "1.2.4", True),   # core 1.2.3 < 1.2.4 -> update
        ("2.0-SNAPSHOT", "2.1.0", True),        # core 2.0   < 2.1.0 -> update
        ("1.2.3-alpha.beta", "1.3.0", True),    # core 1.2.3 < 1.3.0 -> update
        ("1.2.3-git20240101", "1.2.3", False),  # core 1.2.3 == 1.2.3 -> up to date
        ("2.0.0-rc1build", "1.9.0", False),     # core 2.0.0 > 1.9.0  -> no downgrade
    ],
)
def test_suffixed_current_compares_on_release_core(current, latest, expected):
    out = _check(_versioned("t", current=current, latest=latest))
    entry = out["checked"][0]
    assert entry["current"] == current  # the raw token is still reported to the user
    assert entry["update_available"] is expected
    assert out["updates_available"] == (["t"] if expected else [])


def test_uncoercible_current_degrades_gracefully(monkeypatch):
    """Defensive branch: if even the release-core fallback yields nothing (an
    extracted token always has a numeric core, so this can't happen for real
    input), `_version_status` must report None with a clear reason rather than
    crash — erbina reports, never raises."""
    import server

    monkeypatch.setattr(server, "_release_core", lambda tok: None)
    out = server._version_status("1.2.3-git20240101", "1.2.4")
    assert out["update_available"] is None
    assert out["reason"].startswith("unparseable current version:")


def test_unparseable_latest_is_not_claimed_as_an_update():
    """`latest` stays strict: an unparseable dev build (e.g. `1.2.4-SNAPSHOT`) is
    NOT a release erbina will claim as an update, even though its core is 1.2.4 —
    that would violate 'never claim an update it can't justify'. This is the
    asymmetry that makes the release-core fallback safe."""
    out = _check(_versioned("t", current="1.2.3", latest="1.2.4-SNAPSHOT"))
    entry = out["checked"][0]
    assert entry["update_available"] is None
    assert entry["reason"].startswith("unparseable latest version:")
    assert out["updates_available"] == []


# --------------------------------------------------------------------------- #
# stderr version output: many real tools print --version/-V to stderr (graphviz's
# `dot -V`, anything JVM-based, some GNU tools). check_updates must still resolve
# a version from there, or their version: block is silently dead weight.
# --------------------------------------------------------------------------- #
def test_version_current_read_from_stderr():
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        version={"current": "echo 1.0.0 >&2", "latest": "echo 2.0.0"},
    )
    out = _check(recipe)
    entry = out["checked"][0]
    assert entry["current"] == "1.0.0"          # rescued from stderr
    assert entry["latest"] == "2.0.0"
    assert entry["update_available"] is True


def test_version_current_prefers_stdout_over_stderr():
    # when both streams carry a token, stdout (the convention) wins so a noisy
    # stderr warning can't shadow the real version on stdout.
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        version={"current": "echo 1.5.0; echo 9.9.9 >&2", "latest": "echo 1.5.0"},
    )
    entry = _check(recipe)["checked"][0]
    assert entry["current"] == "1.5.0"
    assert entry["update_available"] is False
