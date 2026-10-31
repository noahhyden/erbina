#!/usr/bin/env python3
"""Propose official `curl | sh` installers for recipe rows with no Linux install.

erbina's generator renders a `curl` install/update method the moment a
scripts/recipe_data.py row carries a `curl` key (the official install-script URL;
an optional `curl_shell` overrides the pipe shell for bash-only scripts). But
most bulk-generated rows only have `brew`/`winget`, so on a plain Linux box with
no Homebrew NOTHING installs -- every guard fails and bootstrap dead-ends. This
maintainer helper closes that Linux gap for the mechanical subset: tools whose
official installer we've vetted into KNOWN_INSTALLERS below.

Unlike the winget harvester there is no authoritative catalog of install scripts,
and a wrong installer runs the WRONG software -- so this is deliberately an
allowlist, not a repo-probing guess. Each entry is a URL we've confirmed serves a
real install script, plus the shell it needs. Every proposal is then corroborated
against the row's `gh` owner and tiered:

  high    the URL is served from the tool's own GitHub repo
          (raw.githubusercontent.com/<owner>/<repo>/...), OR its registrable
          domain matches the gh owner or repo (e.g. deno.land ~ denoland/deno).
  medium  a plausible official domain that does NOT corroborate the gh row --
          a human should eyeball it before trusting it.

Only rows that are actually Linux-gapped (no cargo/go/pipx/npm/gem/curl method
already) and lack a `curl` key are proposed, so it is idempotent against rows a
previous run already backfilled. Stdlib only -- runs anywhere with python3.

    python3 scripts/curl_candidates.py                    # HIGH-confidence proposals
    python3 scripts/curl_candidates.py --min-confidence medium
    python3 scripts/curl_candidates.py --apply            # stage keys for git review

Nothing is committed -- review the diff/JSON, then commit and regenerate recipes.
"""
from __future__ import annotations

import re

from _harvest import (CONF_RANK, apply_keys, base_parser, load_tools, norm,  # noqa: F401
                      report, resolve_rows, stage)

# Install methods that already work on a plain Linux box. brew/winget do NOT count
# (Homebrew is rare on Linux; winget is Windows) -- a row carrying only those is
# the gap this tool fills.
LINUX_METHODS = ("cargo", "go", "pipx", "npm", "gem", "curl")

# Curated allowlist of official install scripts, each vetted (HTTP 200 + shell
# shebang) at seed time. `shell` is the interpreter the script requires -- it
# becomes the recipe's `curl_shell` (default sh is omitted). Add an entry only
# after confirming the URL is the project's OFFICIAL installer.
KNOWN_INSTALLERS: dict[str, dict[str, str]] = {
    "deno":          {"url": "https://deno.land/install.sh"},
    "chezmoi":       {"url": "https://get.chezmoi.io"},
    "tailscale":     {"url": "https://tailscale.com/install.sh"},
    "pulumi":        {"url": "https://get.pulumi.com"},
    "golangci-lint": {"url": "https://raw.githubusercontent.com/golangci/golangci-lint/HEAD/install.sh"},
    "trivy":         {"url": "https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh"},
    "rclone":        {"url": "https://rclone.org/install.sh", "shell": "bash"},
    "k3d":           {"url": "https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh", "shell": "bash"},
    "direnv":        {"url": "https://direnv.net/install.sh", "shell": "bash"},
    "volta":         {"url": "https://get.volta.sh", "shell": "bash"},
}


def is_linux_gapped(tool: dict) -> bool:
    """A row whose install methods would ALL fail on a plain Linux box."""
    return not any(tool.get(k) for k in LINUX_METHODS)


def rows_needing_curl(tools: list[dict]) -> list[dict]:
    """Linux-gapped rows that don't already carry a (truthy) curl key."""
    return [t for t in tools if is_linux_gapped(t) and not t.get("curl")]


def _registrable_label(url: str) -> str:
    """The second-level domain label of a URL's host (get.pulumi.com -> pulumi,
    bun.sh -> bun, sh.rustup.rs -> rustup). A rough heuristic (no public-suffix
    list), only ever used to *corroborate* -- a miss downgrades to medium, it
    never fabricates a match."""
    m = re.match(r"https?://([^/]+)", url or "")
    if not m:
        return ""
    labels = m.group(1).split(".")
    return labels[-2] if len(labels) >= 2 else labels[0]


def corroborate(url: str, gh: str | None) -> str:
    """`high` if the URL is provably first-party to the gh row, else `medium`.

    First-party means: served out of the project's own GitHub repo
    (raw.githubusercontent.com/<owner>/<repo>/...), or a vanity domain whose
    registrable label equals (normalized) the gh owner or repo. Everything else
    is medium -- plausible, but a human should confirm the domain is really the
    project's before piping it to a shell.
    """
    owner = repo = None
    if gh and "/" in gh:
        owner, repo = gh.split("/", 1)
    m = re.match(r"https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/", url or "")
    if m and owner and repo:
        if norm(m.group(1)) == norm(owner) and norm(m.group(2)) == norm(repo):
            return "high"
    label = norm(_registrable_label(url))
    if label and (label == norm(owner) or label == norm(repo)):
        return "high"
    return "medium"


def resolve(tool: dict) -> dict | None:
    """One tool row -> a curl proposal from the allowlist, or None if not listed."""
    entry = KNOWN_INSTALLERS.get(tool["id"])
    if not entry:
        return None
    url = entry["url"]
    proposal = {
        "id": tool["id"],
        "curl": url,
        "confidence": corroborate(url, tool.get("gh")),
    }
    if entry.get("shell"):
        proposal["curl_shell"] = entry["shell"]
    return proposal


def resolve_all(tools: list[dict], min_confidence: str = "high",
                ids: set[str] | None = None) -> list[dict]:
    """Resolve every Linux-gapped, curl-less row at or above `min_confidence`."""
    return resolve_rows(rows_needing_curl(tools), resolve, min_confidence, ids)


CURL_KEYS = ("curl", "curl_shell")


def apply_proposals(source_text: str, proposals: list[dict]) -> tuple[str, list[str], list[str]]:
    """Stage `curl` (+ optional `curl_shell`) after each row's id; see _harvest.apply_keys."""
    return apply_keys(source_text, proposals, CURL_KEYS)


def main(argv: list[str] | None = None) -> int:
    ap = base_parser("Propose curl installers for Linux-gapped recipe rows.", "curl_proposals.json")
    args = ap.parse_args(argv)

    tools = load_tools(args.recipe_data)
    proposals = resolve_all(tools, args.min_confidence, set(args.ids) or None)

    by_conf = report(proposals, args.out)
    gapped = len(rows_needing_curl(tools))
    print(f"resolved {len(proposals)} curl installer(s) "
          f"(high={by_conf['high']} medium={by_conf['medium']}) "
          f"of {gapped} Linux-gapped row(s) -> {args.out}")

    if args.apply:
        stage(args.recipe_data, proposals, CURL_KEYS)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
