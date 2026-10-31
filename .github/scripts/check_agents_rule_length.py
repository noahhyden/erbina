#!/usr/bin/env python3
"""An AGENTS.d rule body is ONE line of at most 255 characters, because markdown is never scanned by the one-line-comment guard and is the hole unbounded rule prose grows through."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RULE_RE = re.compile(r"AGENTS\.d/\d{3}-[a-z0-9-]+\.md$")
FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.S)
HEADING_RE = re.compile(r"^#+ .*\n")
MAX_LINES = 1
MAX_CHARS = 255


def rule_files(argv: list[str]) -> list[str]:
    """Rule paths from argv, else every rule file git knows about, tracked or not."""
    if argv:
        return [a for a in argv if RULE_RE.search(a)]
    # --others --exclude-standard too: a rule added but not yet `git add`ed is exactly the one a contributor is about to get wrong, and scanning only tracked files reports OK on a file it never read.
    out = _git("ls-files") + _git("ls-files", "--others", "--exclude-standard")
    return sorted({f for f in out if RULE_RE.search(f)})


def _git(*args: str) -> list[str]:
    """Whitespace-split stdout of a git command run at the repo root."""
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()


def body_of(text: str) -> str:
    """The rule text with its optional frontmatter and its single heading removed."""
    # lstrip() first: a blank line after the frontmatter leaves the heading un-anchored, so `^#+` misses it and counts it as a body line.
    return HEADING_RE.sub("", FRONTMATTER_RE.sub("", text).lstrip(), count=1).strip()


def violations(paths: list[str]) -> list[tuple[str, int, int]]:
    """(path, body line count, longest line) for every rule over the cap."""
    bad = []
    for rel in paths:
        p = REPO / rel
        if not p.is_file():
            continue
        lines = [ln for ln in body_of(p.read_text(encoding="utf-8")).split("\n") if ln.strip()]
        longest = max((len(ln) for ln in lines), default=0)
        if len(lines) > MAX_LINES or longest > MAX_CHARS:
            bad.append((rel, len(lines), longest))
    return bad


def main(argv: list[str]) -> int:
    paths = rule_files(argv)
    if not paths:
        print("check_agents_rule_length: no rule file matched - refusing to pass vacuously")
        return 1
    bad = violations(paths)
    print(f"check_agents_rule_length: scanned {len(paths)} rule file(s)")
    if not bad:
        print(f"  OK - every body is <= {MAX_LINES} line and <= {MAX_CHARS} chars")
        return 0
    for rel, n, longest in sorted(bad, key=lambda r: -r[2]):
        print(f"  FAIL {rel}: {n} line(s), longest {longest} chars")
    print(
        f"\n{len(bad)} rule(s) over the cap. A rule is one line of at most {MAX_CHARS} chars: "
        "keep the trap and its consequence, drop the measurements and the rationale essay."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
