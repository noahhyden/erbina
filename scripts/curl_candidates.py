#!/usr/bin/env python3
"""Propose official `curl | sh` installers for recipe rows with no Linux install."""
from __future__ import annotations

import re

from _harvest import base_parser, load_tools, norm, report, resolve_rows, stage

# Install methods that work on plain Linux; brew/winget do NOT count, that gap is what this fills.
LINUX_METHODS = ("cargo", "go", "pipx", "npm", "gem", "curl")

# Allowlist of vetted official install scripts; `shell` becomes the recipe `curl_shell` (sh omitted).
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
    """The second-level domain label of a URL host (get.pulumi.com -> pulumi); corroboration only."""
    m = re.match(r"https?://([^/]+)", url or "")
    if not m:
        return ""
    labels = m.group(1).split(".")
    return labels[-2] if len(labels) >= 2 else labels[0]


def corroborate(url: str, gh: str | None) -> str:
    """`high` if the URL is first-party to the gh row (own repo or matching vanity domain), else `medium`."""
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
USAGE = """\
usage examples:
  python3 scripts/curl_candidates.py                    # HIGH-confidence proposals
  python3 scripts/curl_candidates.py --min-confidence medium
  python3 scripts/curl_candidates.py --apply            # stage keys for git review

confidence tiers:
  high    URL served from the tool's own GitHub repo, or its registrable domain matches the gh owner/repo
  medium  plausible official domain that does not corroborate the gh row; eyeball it first

Nothing is committed -- review the diff/JSON, then commit and regenerate recipes.
"""


def main(argv: list[str] | None = None) -> int:
    ap = base_parser("Propose curl installers for Linux-gapped recipe rows.", "curl_proposals.json", epilog=USAGE)
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
