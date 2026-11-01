"""`version.latest: {github: owner/repo}` is fetched in Python (urllib + json) and degrades to None on any failure; the network is always faked here."""
from __future__ import annotations

import pytest

import server
from helpers import call_tool
from prototype import TRUE, cli_recipe, registry


# _github_latest fetch (urlopen faked, never the network)
class _Resp:
    def __init__(self, body):
        self._b = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._b


def _urlopen_returning(body):
    return lambda url, timeout=None: _Resp(body)


def test_github_latest_reads_tag_name(monkeypatch):
    seen = []

    def fake(url, timeout=None):
        seen.append(url)
        return _Resp(b'{"tag_name": "v2.0.0"}')

    monkeypatch.setattr(server.urllib.request, "urlopen", fake)
    assert server._github_latest({"github": "BurntSushi/ripgrep"}) == "v2.0.0"
    assert seen == ["https://api.github.com/repos/BurntSushi/ripgrep/releases/latest"]


@pytest.mark.parametrize("body", [b"not json", b"{}", b'{"tag_name": 5}', b"[]"])
def test_github_latest_degrades_on_bad_payload(monkeypatch, body):
    monkeypatch.setattr(server.urllib.request, "urlopen", _urlopen_returning(body))
    assert server._github_latest({"github": "o/r"}) is None


def test_github_latest_degrades_on_network_error(monkeypatch):
    def boom(url, timeout=None):
        raise OSError("no network")

    monkeypatch.setattr(server.urllib.request, "urlopen", boom)
    assert server._github_latest({"github": "o/r"}) is None


@pytest.mark.parametrize("bad", ["rg --version", {"github": ""}, {"github": "noslash"}, {"other": "x"}, {}, 5, None])
def test_malformed_latest_never_hits_the_network(monkeypatch, bad):
    def boom(*a, **k):
        raise AssertionError("network touched")

    monkeypatch.setattr(server.urllib.request, "urlopen", boom)
    assert server._github_latest(bad) is None


# validation
def test_github_latest_validates_clean():
    r = cli_recipe("t", version={"current": "t --version", "latest": {"github": "owner/repo"}})
    assert server.validate_recipe(r, stem="t") == []


@pytest.mark.parametrize("latest,needle", [
    ({"github": ""}, "owner/repo"),
    ({"github": "noslash"}, "owner/repo"),
    ({"github": "a/b/c"}, "owner/repo"),
    ({"github": 5}, "owner/repo"),
    ({"github": "a/b", "ref": "main"}, "only the 'github' key"),
    ({"tarball": "x"}, "only the 'github' key"),
    (5, "must be a {github"),
    ({}, "only the 'github' key"),
    ("echo 1.2.3", "must be a {github"),   # the string-command form is gone
])
def test_bad_github_latest_is_reported(latest, needle):
    r = cli_recipe("t", version={"current": "t --version", "latest": latest})
    errs = server.validate_recipe(r, stem="t")
    assert any(needle in e for e in errs), (latest, errs)


def test_current_still_required_as_a_string():
    r = cli_recipe("t", version={"current": {"github": "o/r"}, "latest": {"github": "o/r"}})
    errs = server.validate_recipe(r, stem="t")
    assert any("version.current" in e for e in errs)


# check_updates end-to-end through the github source (network mocked)
def test_release_notes_url_for_github_source():
    assert server._release_notes_url({"github": "BurntSushi/ripgrep"}) == \
        "https://github.com/BurntSushi/ripgrep/releases"


@pytest.mark.parametrize("latest", ["rg --version", {"github": "noslash"}, {"other": "x"}, {}, 5, None])
def test_release_notes_url_is_none_for_non_github_latest(latest):
    assert server._release_notes_url(latest) is None


def test_check_updates_surfaces_release_notes_and_latest_for_github_source(monkeypatch):
    monkeypatch.setattr(server, "_run", lambda cmd, *a, **k: {"cmd": cmd, "exit": 0, "stdout": "1.0.0", "stderr": ""})
    monkeypatch.setattr(server, "_github_latest", lambda spec: "v2.0.0")
    r = cli_recipe("t", detect={"command": TRUE},
                   version={"current": "t --version", "latest": {"github": "o/r"}})
    with registry(r):
        out = call_tool("check_updates", {"recipe_id": "t"})
    entry = out["checked"][0]
    assert entry["current"] == "1.0.0"
    assert entry["latest"] == "2.0.0"      # leading v stripped
    assert entry["update_available"] is True
    assert entry["release_notes"] == "https://github.com/o/r/releases"
    assert out["updates_available"] == ["t"]
