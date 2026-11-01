"""Behavioral tests for check_updates via the in-memory client; versions are `echo` builtins, so it is deterministic."""
from __future__ import annotations

import pytest

import server
from helpers import call_tool
from prototype import FALSE, TRUE, cli_recipe, registry

_LATEST: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    _LATEST.clear()
    monkeypatch.setattr(server, "_github_latest", lambda spec: _LATEST.get(spec["github"]))


def _versioned(rid, current="1.0.0", latest="2.0.0", detect=TRUE):
    _LATEST[f"o/{rid}"] = latest
    return cli_recipe(
        rid,
        detect={"command": detect},
        version={"current": f"echo {current}", "latest": {"github": f"o/{rid}"}},
    )


def _check(recipe, **kwargs):
    with registry(recipe):
        return call_tool("check_updates", {"recipe_id": recipe["id"], **kwargs})


# core: update available / current / newer-installed
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


# not installed -> nothing to update
def test_not_installed_is_reported_without_version_compare():
    out = _check(_versioned("t", detect=FALSE))
    entry = out["checked"][0]
    assert entry["installed"] is False
    assert "not installed" in entry["note"]
    assert "current" not in entry  # no version comparison attempted
    assert out["updates_available"] == []


# recipes without a version block
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


# A load failure surfaces for an EXPLICIT recipe_id, but a bulk scan skips the unloadable recipe and reports the rest.
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


# unparseable version output never claims an update
def test_unparseable_version_output_is_safe():
    out = _check(_versioned("t", current="whoknows", latest="2.0.0"))
    entry = out["checked"][0]
    assert entry["update_available"] is None
    assert out["updates_available"] == []
    # no version token at all -> the "could not parse" branch (server.py:167-172)
    assert entry["reason"] == "could not parse a version from the command output"


# Finding #4: a suffixed `current` (`1.2.3-git20240101`) fails packaging.Version, so `_release_core` compares its numeric core instead of hiding an update.
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
    """Defensive branch: if even the release-core fallback yields nothing, `_version_status` reports None with a reason rather than raising."""
    import server

    monkeypatch.setattr(server, "_release_core", lambda tok: None)
    out = server._version_status("1.2.3-git20240101", "1.2.4")
    assert out["update_available"] is None
    assert out["reason"].startswith("unparseable current version:")


def test_unavailable_latest_is_not_claimed_as_an_update():
    recipe = _versioned("t", current="1.0.0")
    _LATEST.clear()  # the fetch yields None, as on any network/HTTP/JSON failure
    entry = _check(recipe)["checked"][0]
    assert entry["update_available"] is None
    assert entry["latest"] is None


def test_unparseable_latest_is_not_claimed_as_an_update():
    """`latest` stays strict: an unparseable dev build (`1.2.4-SNAPSHOT`) is never claimed as an update, which keeps the core fallback safe."""
    out = _check(_versioned("t", current="1.2.3", latest="1.2.4-SNAPSHOT"))
    entry = out["checked"][0]
    assert entry["update_available"] is None
    assert entry["reason"].startswith("unparseable latest version:")
    assert out["updates_available"] == []


# Many tools print --version to stderr (`dot -V`, JVM tools); check_updates must resolve a version there or the version: block is dead weight.
def test_version_current_read_from_stderr():
    _LATEST["o/t"] = "2.0.0"
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        version={"current": "echo 1.0.0 >&2", "latest": {"github": "o/t"}},
    )
    out = _check(recipe)
    entry = out["checked"][0]
    assert entry["current"] == "1.0.0"          # rescued from stderr
    assert entry["latest"] == "2.0.0"
    assert entry["update_available"] is True


def test_version_current_prefers_stdout_over_stderr():
    # When both streams carry a token, stdout wins so a noisy stderr warning cannot shadow the real version.
    _LATEST["o/t"] = "1.5.0"
    recipe = cli_recipe(
        "t",
        detect={"command": TRUE},
        version={"current": "echo 1.5.0; echo 9.9.9 >&2", "latest": {"github": "o/t"}},
    )
    entry = _check(recipe)["checked"][0]
    assert entry["current"] == "1.5.0"
    assert entry["update_available"] is False
