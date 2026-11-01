"""Feed `_extract_version` real `--version` output so a regex regression cannot silently break check_updates; pins the known "first token wins" limit (finding #5)."""
from __future__ import annotations

import pytest

import server

# Authentic (or authentically-shaped) version lines for tools erbina installs; the value is the token a human reads as the version.
REAL_OUTPUTS = [
    ("git version 2.43.0", "2.43.0"),
    ("jq-1.7.1", "1.7.1"),                                  # jq: dash, no space
    ("ripgrep 14.1.0", "14.1.0"),
    ("rg 14.1.0 (rev e50df40a01)", "14.1.0"),              # trailing vcs rev
    ("go version go1.22.0 linux/amd64", "1.22.0"),         # go's "go1.22.0"
    ("uv 0.5.11 (0c8b0a8f2 2024-12-06)", "0.5.11"),        # hash + ISO date after
    ("fd 10.1.0", "10.1.0"),
    ("bat 0.24.0", "0.24.0"),
    ("eza - A modern ls\nv0.20.5 [+git]", "0.20.5"),       # blurb line, then vX
    ("zoxide 0.9.6", "0.9.6"),
    ("delta 0.18.2", "0.18.2"),
    ("dust 1.1.1", "1.1.1"),
    ("btm 0.10.2", "0.10.2"),                              # bottom
    ("hyperfine 1.18.0", "1.18.0"),
    ("tokei 12.1.2", "12.1.2"),
    ("sd 1.0.0", "1.0.0"),
    ("procs 0.14.6", "0.14.6"),
    ("tldr 1.7.1", "1.7.1"),                               # tealdeer
    ("ataegina 0.1.0", "0.1.0"),                           # erbina's PoC recipe #1
    # common runtimes / system tools of the same shape
    ("Python 3.13.1", "3.13.1"),
    ("node v20.11.0", "20.11.0"),
    ("GNU bash, version 5.2.21(1)-release", "5.2.21"),
    ("curl 8.5.0 (x86_64-pc-linux-gnu) libcurl/8.5.0", "8.5.0"),
    ("OpenSSL 3.0.13 30 Jan 2024", "3.0.13"),
    # Go/cobra `<bin> version` output (helm, consul, vault, nomad, caddy, k6, ...) is multi-line with a Revision/BuildDate/GoVersion tail; take the leading release token.
    ("Consul v1.17.0\nRevision e6d0525c\nBuild Date 2023-11-03", "1.17.0"),
    ("Vault v1.15.4 ('4c5e5c3'), built 2024-01-01", "1.15.4"),
    ("Nomad v1.7.2\nBuildDate 2023-12-13", "1.7.2"),
    ("k6 v0.48.0 (go1.21.6, linux/amd64)", "0.48.0"),
    ("v3.100.0", "3.100.0"),                                # pulumi: bare vX.Y.Z
    ("OpenTofu v1.6.1\non linux_amd64", "1.6.1"),           # opentofu (tofu)
    ("v2.7.6 h1:abcd", "2.7.6"),                            # caddy: vX.Y.Z + h1: hash
    ("0.11.0", "0.11.0"),                                   # zig: bare version, no prefix
    # helm dumps a Go struct where "version" (version.BuildInfo) precedes the token, so the label rule must pick v3.14.0 not GoVersion go1.21.5.
    ('version.BuildInfo{Version:"v3.14.0", GitCommit:"e8858f8", GoVersion:"go1.21.5"}', "3.14.0"),
    # kubectl/argocd `version --client`: "Client Version:" label, then vX.Y.Z.
    ("Client Version: v1.29.2\nKustomize Version: v5.0.4", "1.29.2"),
    # azure-cli `az version` prints JSON; no "version" word, first token wins.
    ('{\n  "azure-cli": "2.57.0",\n  "azure-cli-core": "2.57.0"\n}', "2.57.0"),
    # tool strings folded in from the recipe version samples, plus release-tag lines
    ("ripgrep 14.1.1\nfeatures:+pcre2\nsimd(compile):+SSE2", "14.1.1"),
    ("Dust 1.1.1", "1.1.1"),
    ("tealdeer 1.7.0", "1.7.0"),
    ("gh version 2.62.0 (2024-11-27)\nhttps://github.com/cli/cli/releases/tag/v2.62.0", "2.62.0"),
    ("commit=abcdef0, build date=2024-11-20, build source=binaryRelease, version=0.44.1, os=darwin, arch=arm64", "0.44.1"),
    ("yq (https://github.com/mikefarah/yq/) version v4.44.3", "4.44.3"),
    ("Difftastic 0.61.0", "0.61.0"),
    ("3.2.4", "3.2.4"),                                     # httpie: bare version
    ('  "tag_name": "v10.1.0",', "10.1.0"),
    ('  "tag_name": "jq-1.7.1",', "1.7.1"),
    ('  "tag_name": "14.1.1",', "14.1.1"),
]


@pytest.mark.parametrize("output,expected", REAL_OUTPUTS)
def test_extract_version_handles_real_tool_output(output, expected):
    assert server._extract_version(output) == expected


# Finding #5 (mostly fixed): a dotted build date BEFORE the version used to win; `_extract_version` now prefers the token after an explicit "version" label.
def test_labeled_version_beats_a_leading_dotted_date():
    # the fix: a "version" label pulls extraction past the build date
    assert server._extract_version("Built 2024.01.15, tool version 2.3.4") == "2.3.4"


@pytest.mark.parametrize("output,extracted", [
    ("gh version 2.62.0 (2024-11-27)", "2.62.0"),        # label + parenthetical date
    ("GNU bash, version 5.2.21(1)-release", "5.2.21"),
    ("commit=abc, version=0.44.1, os=linux", "0.44.1"),  # lazygit-style label=value
])
def test_labeled_version_extraction(output, extracted):
    assert server._extract_version(output) == extracted


# Residual of #5: with NO "version" label a bare token after a dotted date is indistinguishable from calver (`2024.01.05` IS a version), and real output dates use '-' not '.', so it stays pinned.
@pytest.mark.parametrize("output,extracted", [
    ("compiled 2023.12.31 v1.0.0", "2023.12.31"),   # unlabeled -> first token
    ("release 10.0 build 2.3.4", "10.0"),
])
def test_CURRENT_unlabeled_leading_dotted_number_still_shadows(output, extracted):
    assert server._extract_version(output) == extracted
