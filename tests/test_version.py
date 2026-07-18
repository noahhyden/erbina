"""Unit tests for the version-comparison core used by check_updates:
`_extract_version` (pull a version token out of arbitrary command output) and
`_version_status` (compare two outputs, never claiming an unjustified update).
"""
from __future__ import annotations

import pytest

import server


# --------------------------------------------------------------------------- #
# _extract_version
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("0.1.0", "0.1.0"),
    ("ataegina 0.1.0", "0.1.0"),
    ("ataegina version 1.2.3\n", "1.2.3"),
    ("v1.2.3", "1.2.3"),                 # leading v stripped
    ("1.2.3 (build 456)", "1.2.3"),      # trailing junk ignored
    ("2024.01.05", "2024.01.05"),        # calver
    ("1.2.3-rc1", "1.2.3-rc1"),          # prerelease kept
    ("1.2", "1.2"),                      # two-part
])
def test_extract_pulls_the_version_token(text, expected):
    assert server._extract_version(text) == expected


@pytest.mark.parametrize("text", ["unknown", "", "no digits here", "git-a1b2c3d", None, 123])
def test_extract_returns_none_when_no_version(text):
    assert server._extract_version(text) is None


# --------------------------------------------------------------------------- #
# _version_status
# --------------------------------------------------------------------------- #
def test_status_detects_available_update():
    s = server._version_status("tool 1.2.3", "1.2.4")
    assert s["current"] == "1.2.3"
    assert s["latest"] == "1.2.4"
    assert s["update_available"] is True


def test_status_equal_versions_no_update():
    assert server._version_status("v1.2.3", "1.2.3")["update_available"] is False


def test_status_installed_newer_than_latest_no_update():
    # e.g. a locally built newer build; never report a downgrade as an update
    assert server._version_status("2.0.0", "1.9.9")["update_available"] is False


def test_status_numeric_not_lexical_ordering():
    # 1.10.0 > 1.9.0 numerically (a lexical compare would get this wrong)
    assert server._version_status("1.9.0", "1.10.0")["update_available"] is True


def test_status_release_beats_prerelease():
    # installed release 1.0.0 is NEWER than latest 1.0.0-rc1 -> no update
    assert server._version_status("1.0.0", "1.0.0-rc1")["update_available"] is False


def test_status_prerelease_to_release_is_an_update():
    assert server._version_status("1.0.0-rc1", "1.0.0")["update_available"] is True


@pytest.mark.parametrize("cur,lat", [("unknown", "1.0.0"), ("1.0.0", "n/a"), ("x", "y")])
def test_status_unparseable_never_claims_an_update(cur, lat):
    s = server._version_status(cur, lat)
    assert s["update_available"] is None
    assert "reason" in s
