"""Tests for scripts/curl_candidates.py: a wrong installer runs the wrong software, so pin the `corroborate` confidence model and the gap/idempotency filters."""
from __future__ import annotations

import json

import curl_candidates as cc
from _harvest import apply_keys, parse_tools


# norm
def test_norm():
    assert cc.norm("Golangci-Lint") == "golangcilint"
    assert cc.norm("volta-cli") == "voltacli"
    assert cc.norm(None) == ""
    assert cc.norm("") == ""


# is_linux_gapped / rows_needing_curl — the gap + idempotency filters
def test_is_linux_gapped_true_for_brew_winget_only():
    assert cc.is_linux_gapped({"id": "deno", "brew": "deno", "winget": "DenoLand.Deno"}) is True


def test_is_linux_gapped_false_when_a_linux_method_exists():
    # any of cargo/go/pipx/npm/gem/curl means it already installs on Linux
    assert cc.is_linux_gapped({"id": "atuin", "brew": "atuin", "cargo": "atuin"}) is False
    assert cc.is_linux_gapped({"id": "x", "go": "example.com/x@latest"}) is False


def test_rows_needing_curl_excludes_non_gapped_and_already_curl():
    tools = [
        {"id": "deno", "brew": "deno"},                      # gapped, no curl -> included
        {"id": "atuin", "brew": "atuin", "cargo": "atuin"},  # not gapped -> excluded
        {"id": "ollama", "brew": "ollama", "curl": "x"},     # already curl -> excluded (idempotent)
        {"id": "empty", "brew": "e", "curl": ""},            # blank curl counts as missing -> included
    ]
    assert [t["id"] for t in cc.rows_needing_curl(tools)] == ["deno", "empty"]


# corroborate — the confidence tiers (security-relevant)
def test_raw_githubusercontent_matching_owner_repo_is_high():
    url = "https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh"
    assert cc.corroborate(url, "aquasecurity/trivy") == "high"


def test_raw_githubusercontent_wrong_repo_is_not_high():
    # Served from a DIFFERENT repo than the row claims, so it is not first-party and falls back to the domain check.
    url = "https://raw.githubusercontent.com/someoneelse/thing/main/install.sh"
    assert cc.corroborate(url, "aquasecurity/trivy") == "medium"


def test_vanity_domain_matching_repo_is_high():
    assert cc.corroborate("https://deno.land/install.sh", "denoland/deno") == "high"      # label deno == repo
    assert cc.corroborate("https://get.volta.sh", "volta-cli/volta") == "high"            # label volta == repo


def test_vanity_domain_matching_owner_is_high():
    assert cc.corroborate("https://tailscale.com/install.sh", "tailscale/tailscale") == "high"


def test_uncorroborated_domain_is_medium():
    # fly.io is the official installer but nothing in the URL proves it against gh superfly/flyctl, so medium for a human to eyeball.
    assert cc.corroborate("https://fly.io/install.sh", "superfly/flyctl") == "medium"


def test_corroborate_is_normalized_equality_not_substring():
    # owner "den" must NOT match domain label "deno" as a substring
    assert cc.corroborate("https://deno.land/install.sh", "den/deno-x") == "medium"


def test_corroborate_handles_missing_or_malformed_gh():
    assert cc.corroborate("https://deno.land/install.sh", None) == "medium"
    assert cc.corroborate("https://deno.land/install.sh", "noslash") == "medium"


def test_registrable_label():
    assert cc._registrable_label("https://get.pulumi.com") == "pulumi"
    assert cc._registrable_label("https://deno.land/install.sh") == "deno"
    assert cc._registrable_label("https://bun.sh/install") == "bun"
    assert cc._registrable_label("not a url") == ""


# resolve — allowlist lookup + shell passthrough
def test_resolve_unknown_id_is_none():
    assert cc.resolve({"id": "totally-unlisted", "brew": "x"}) is None


def test_resolve_sh_installer_omits_shell(monkeypatch):
    monkeypatch.setitem(cc.KNOWN_INSTALLERS, "faketool", {"url": "https://faketool.dev/install.sh"})
    p = cc.resolve({"id": "faketool", "gh": "faker/faketool"})
    assert p == {"id": "faketool", "curl": "https://faketool.dev/install.sh", "confidence": "high"}
    assert "curl_shell" not in p


def test_resolve_bash_installer_carries_shell(monkeypatch):
    monkeypatch.setitem(cc.KNOWN_INSTALLERS, "fakebash",
                        {"url": "https://fakebash.dev/install.sh", "shell": "bash"})
    p = cc.resolve({"id": "fakebash", "gh": "faker/fakebash"})
    assert p["curl_shell"] == "bash"


# the shipped allowlist is internally consistent (guards against typos)
def test_shipped_allowlist_entries_are_wellformed():
    for rid, entry in cc.KNOWN_INSTALLERS.items():
        assert entry["url"].startswith("https://"), f"{rid}: url must be https"
        assert set(entry) <= {"url", "shell"}, f"{rid}: unexpected keys {set(entry)}"


# resolve_all — threshold filtering, gap filter, ordering
def test_resolve_all_respects_gap_and_min_confidence(monkeypatch):
    monkeypatch.setattr(cc, "KNOWN_INSTALLERS", {
        "hi":   {"url": "https://hi.dev/install.sh"},          # domain label hi == repo -> high
        "med":  {"url": "https://vanity.example/install.sh"},  # no corroboration -> medium
    })
    tools = [
        {"id": "hi", "brew": "hi", "gh": "acme/hi"},           # gapped, high
        {"id": "med", "brew": "med", "gh": "acme/med"},        # gapped, medium
        {"id": "hi-butlinux", "cargo": "hi", "gh": "acme/hi"}, # NOT gapped -> excluded even if listed
    ]
    # only 'hi-butlinux' is non-gapped; but it's a different id anyway. Add a gapped clone:
    tools.append({"id": "hi", "cargo": "hi", "gh": "acme/hi"})  # duplicate id, but not gapped form filtered per-row
    high = cc.resolve_all(tools, min_confidence="high")
    assert [p["id"] for p in high] == ["hi"]
    med = cc.resolve_all(tools, min_confidence="medium")
    assert [p["id"] for p in med] == ["hi", "med"]  # sorted by id


def test_resolve_all_id_filter(monkeypatch):
    monkeypatch.setattr(cc, "KNOWN_INSTALLERS", {
        "a": {"url": "https://a.dev/install.sh"},
        "b": {"url": "https://b.dev/install.sh"},
    })
    tools = [{"id": "a", "brew": "a", "gh": "x/a"}, {"id": "b", "brew": "b", "gh": "x/b"}]
    got = cc.resolve_all(tools, min_confidence="high", ids={"b"})
    assert [p["id"] for p in got] == ["b"]


# apply_keys — staging into recipe_data.py source text (pure)
SRC = """TOOLS = [
    {"id": "deno", "bin": "deno", "brew": "deno", "gh": "denoland/deno"},
    {"id": "denox", "bin": "denox", "brew": "denox"},
    {"id": "rclone", "bin": "rclone", "brew": "rclone", "curl": "https://x"},
]
"""


def test_apply_inserts_after_id_and_is_anchored_to_exact_id():
    new, applied, missing = apply_keys(SRC, [{"id": "deno", "curl": "https://deno.land/install.sh"}], cc.CURL_KEYS)
    assert applied == ["deno"] and missing == []
    assert '"id": "deno", "curl": "https://deno.land/install.sh"' in new
    assert '"id": "denox", "curl"' not in new  # exact-id anchoring, not prefix


def test_apply_writes_curl_shell_when_present():
    new, _, _ = apply_keys(SRC, [{"id": "deno", "curl": "https://x/install.sh", "curl_shell": "bash"}], cc.CURL_KEYS)
    assert '"curl": "https://x/install.sh", "curl_shell": "bash"' in new


def test_apply_is_idempotent_on_rows_that_already_have_curl():
    new, applied, _ = apply_keys(SRC, [{"id": "rclone", "curl": "https://other"}], cc.CURL_KEYS)
    assert applied == [] and new == SRC


def test_apply_reports_missing_ids():
    new, applied, missing = apply_keys(SRC, [{"id": "ghost", "curl": "https://x"}], cc.CURL_KEYS)
    assert applied == [] and missing == ["ghost"] and new == SRC


def test_apply_leaves_the_rest_of_the_file_byte_identical():
    commented = "# a section header the table leans on\n" + SRC
    new, applied, _ = apply_keys(commented, [{"id": "deno", "curl": "https://deno.land/install.sh"}], cc.CURL_KEYS)
    assert applied == ["deno"]
    assert new.startswith("# a section header the table leans on\n")
    assert new.count("\n") == commented.count("\n")


# main — end-to-end against a fixture recipe_data.py
def _fixture_recipe_data(tmp_path):
    p = tmp_path / "recipe_data.py"
    p.write_text(
        'TOOLS = [\n'
        '    {"id": "deno", "bin": "deno", "brew": "deno", "gh": "denoland/deno"},\n'
        '    {"id": "atuin", "bin": "atuin", "brew": "atuin", "cargo": "atuin", "gh": "atuinsh/atuin"},\n'
        ']\n'
    )
    return p


def test_main_writes_proposals_json(tmp_path):
    out = tmp_path / "p.json"
    rc = cc.main(["--recipe-data", str(_fixture_recipe_data(tmp_path)), "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    # deno is gapped + listed -> proposed; atuin has cargo (not gapped) -> skipped
    assert [p["id"] for p in data] == ["deno"]
    assert data[0]["curl"] == "https://deno.land/install.sh"


def test_main_apply_writes_curl_key_into_recipe_data(tmp_path):
    rd = _fixture_recipe_data(tmp_path)
    rc = cc.main(["--recipe-data", str(rd), "--out", str(tmp_path / "p.json"), "--apply"])
    assert rc == 0
    curl = {t["id"]: t.get("curl") for t in parse_tools(rd.read_text())}
    assert curl["deno"] == "https://deno.land/install.sh"
    assert curl["atuin"] is None  # not gapped -> never touched
