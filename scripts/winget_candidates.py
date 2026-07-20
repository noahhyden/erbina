#!/usr/bin/env python3
"""Resolve winget PackageIdentifiers for recipe rows that lack Windows coverage.

erbina's generator already renders a `winget` install/update method the moment a
scripts/recipe_data.py row carries a `winget` key -- but almost no rows do, so the
bulk-generated recipes are brew/cargo/go-only and install nothing on Windows.
This maintainer helper closes that gap: it downloads the winget *community source*
index (the same pre-built SQLite catalog the `winget` CLI itself uses), and for
each row missing a `winget` key it resolves a PackageIdentifier, tiered by how
much the match can be trusted:

  high    the id is the row's `gh` owner/repo exactly, OR a command/moniker match
          whose publisher equals the GitHub owner (strong corroboration).
  medium  a UNIQUE command (installed-executable) match, but no gh corroboration.
  low     a moniker-only match (weakest -- monikers collide across unrelated apps).

Only stdlib is used, so it runs anywhere with plain python3 (no winget, no
Windows, no uv needed). The default emits winget_proposals.json for review -- the
same "propose, a human merges" idiom as the brew ingester. `--apply` additionally
stages the resolved keys into scripts/recipe_data.py in place, so a maintainer
reviews the change as a git diff before committing.

    python3 scripts/winget_candidates.py                    # HIGH-confidence proposals
    python3 scripts/winget_candidates.py --min-confidence medium
    python3 scripts/winget_candidates.py --apply            # stage keys for git review
    python3 scripts/winget_candidates.py --msix ./source.msix   # offline, cached index

Nothing is committed -- review the diff/JSON, then commit and regenerate recipes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sqlite3
import tempfile
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECIPE_DATA = REPO_ROOT / "scripts" / "recipe_data.py"

# The winget community source ships as a signed MSIX (a zip) whose Public/index.db
# is a SQLite catalog of every package. This is the CDN URL `winget` fetches.
WINGET_SOURCE_URL = "https://cdn.winget.microsoft.com/cache/source2.msix"
INDEX_MEMBER = "Public/index.db"

CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def norm(s: str | None) -> str:
    """Casefold to bare alphanumerics for comparing names/publishers/owners."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def rows_missing_winget(tools: list[dict]) -> list[dict]:
    """Rows without a *truthy* winget key (blank/None count as missing)."""
    return [t for t in tools if not t.get("winget")]


# --------------------------------------------------------------------------- #
# the winget community-source index (SQLite inside the MSIX)
# --------------------------------------------------------------------------- #
class WingetIndex:
    """Thin query layer over the winget source SQLite catalog.

    Rows are returned as (PackageIdentifier, PackageName, Moniker) tuples. Lookups
    are case-insensitive because winget identifiers are matched case-insensitively.
    """

    def __init__(self, conn: sqlite3.Connection, _tmpdir: str | None = None) -> None:
        self.conn = conn
        self._tmpdir = _tmpdir

    @classmethod
    def from_msix(cls, msix_path: str | Path) -> WingetIndex:
        # deserialize() is 3.11+, but erbina supports 3.10 -> extract to a temp file.
        tmpdir = tempfile.mkdtemp(prefix="winget-idx-")
        with zipfile.ZipFile(msix_path) as z:
            raw = z.read(INDEX_MEMBER)
        dbpath = Path(tmpdir) / "index.db"
        dbpath.write_bytes(raw)
        return cls(sqlite3.connect(dbpath), _tmpdir=tmpdir)

    def by_command(self, command: str) -> list[tuple]:
        """Packages that install an executable named `command` (the strongest CLI
        signal -- winget indexes the actual commands a package provides)."""
        return self.conn.execute(
            "SELECT p.id, p.name, p.moniker FROM commands2 c "
            "JOIN commands2_map m ON m.command = c.rowid "
            "JOIN packages p ON p.rowid = m.package "
            "WHERE c.command = ? COLLATE NOCASE",
            (command,),
        ).fetchall()

    def by_moniker(self, moniker: str) -> list[tuple]:
        return self.conn.execute(
            "SELECT id, name, moniker FROM packages WHERE moniker = ? COLLATE NOCASE",
            (moniker,),
        ).fetchall()

    def by_id(self, package_id: str) -> list[tuple]:
        return self.conn.execute(
            "SELECT id, name, moniker FROM packages WHERE id = ? COLLATE NOCASE",
            (package_id,),
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# resolver: tool row + index -> a confidence-tiered proposal (pure)
# --------------------------------------------------------------------------- #
def _publisher(package_id: str) -> str:
    """The publisher portion of a PackageIdentifier (`BurntSushi.ripgrep` -> BurntSushi)."""
    return package_id.split(".", 1)[0]


def _uniq_by_id(rows: list[tuple]) -> list[tuple]:
    seen: dict[str, tuple] = {}
    for row in rows:
        seen.setdefault(row[0], row)
    return list(seen.values())


def _pick(rows: list[tuple], owner: str | None) -> tuple[tuple, bool] | None:
    """Pick one row from a query result. Returns (row, publisher_corroborated) or
    None when the match is absent or ambiguously unresolvable.

    A single hit resolves (corroborated iff its publisher == the gh owner). Several
    hits resolve only if the gh owner disambiguates to exactly one -- otherwise the
    tie is left for a human (None)."""
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0], bool(owner and norm(_publisher(rows[0][0])) == norm(owner))
    if owner:
        matches = [r for r in rows if norm(_publisher(r[0])) == norm(owner)]
        if len(matches) == 1:
            return matches[0], True
    return None


def resolve(tool: dict, index: WingetIndex) -> dict | None:
    """Resolve one tool row to a winget proposal, or None if nothing trustworthy.

    Precedence: gh-derived exact id > command match > moniker match. A wrong id
    installs the WRONG software, so each weaker tier only fires when the stronger
    ones miss, and publisher corroboration promotes a match to `high`.
    """
    rid = tool["id"]
    binary = tool.get("bin", rid)
    gh = tool.get("gh")
    owner = repo = None
    if gh and "/" in gh:
        owner, repo = gh.split("/", 1)

    def proposal(row: tuple, confidence: str, matched_by: str) -> dict:
        return {"id": rid, "winget": row[0], "package_name": row[1],
                "confidence": confidence, "matched_by": matched_by}

    # 1. gh-derived exact id (e.g. gh "sharkdp/pastel" -> id "sharkdp.pastel").
    if owner and repo:
        hit = index.by_id(f"{owner}.{repo}")
        if hit:
            return proposal(hit[0], "high", "gh-id-exact")

    # 2. command (installed-executable) match.
    cmd_rows = _uniq_by_id(index.by_command(binary)
                           + (index.by_command(rid) if rid != binary else []))
    picked = _pick(cmd_rows, owner)
    if picked is not None:
        row, corroborated = picked
        return proposal(row, "high", "cmd+publisher") if corroborated \
            else proposal(row, "medium", "cmd-unique")

    # 3. moniker match (weakest -- monikers collide across unrelated apps).
    mon_rows = _uniq_by_id(index.by_moniker(binary)
                           + (index.by_moniker(rid) if rid != binary else []))
    picked = _pick(mon_rows, owner)
    if picked is not None:
        row, corroborated = picked
        return proposal(row, "high", "moniker+publisher") if corroborated \
            else proposal(row, "low", "moniker-only")

    return None


def resolve_all(tools: list[dict], index: WingetIndex, min_confidence: str = "high",
                ids: set[str] | None = None) -> list[dict]:
    """Resolve every winget-less row at or above `min_confidence`, sorted by id."""
    threshold = CONF_RANK[min_confidence]
    out: list[dict] = []
    for tool in rows_missing_winget(tools):
        if ids is not None and tool["id"] not in ids:
            continue
        p = resolve(tool, index)
        if p and CONF_RANK[p["confidence"]] >= threshold:
            out.append(p)
    out.sort(key=lambda p: p["id"])
    return out


# --------------------------------------------------------------------------- #
# staging: insert `winget` keys into recipe_data.py source text (pure)
# --------------------------------------------------------------------------- #
_ROW = re.compile(r"\{[^{}]*\}")  # a TOOLS row is a brace-balanced dict with no nesting


def _id_token(rid: str) -> re.Pattern[str]:
    # anchored on the exact id so `fd` never matches the `fdupes` row.
    return re.compile(r'"id":\s*"' + re.escape(rid) + r'"')


def apply_proposals(source_text: str, proposals: list[dict]) -> tuple[str, list[str], list[str]]:
    """Insert `"winget": "<id>"` after each row's id. Returns (new_text, applied
    ids, missing ids). Idempotent: a row that already has a winget key is left
    untouched."""
    text = source_text
    applied: list[str] = []
    missing: list[str] = []
    for p in proposals:
        rid, wid = p["id"], p["winget"]
        token = _id_token(rid)
        row_match = next((m for m in _ROW.finditer(text) if token.search(m.group())), None)
        if row_match is None:
            missing.append(rid)
            continue
        row = row_match.group()
        if '"winget"' in row:  # already staged -> idempotent
            continue
        at = token.search(row).end()
        new_row = row[:at] + f', "winget": "{wid}"' + row[at:]
        text = text[:row_match.start()] + new_row + text[row_match.end():]
        applied.append(rid)
    return text, applied, missing


# --------------------------------------------------------------------------- #
# I/O + CLI
# --------------------------------------------------------------------------- #
def load_tools(recipe_data_path: str | Path) -> list[dict]:
    """Import TOOLS from a recipe_data.py file at an arbitrary path."""
    spec = importlib.util.spec_from_file_location("_erbina_recipe_data", recipe_data_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TOOLS


def fetch_source_msix(url: str, dest_dir: str | Path) -> Path:  # pragma: no cover - network I/O
    dest = Path(dest_dir) / "winget-source.msix"
    with urllib.request.urlopen(url, timeout=180) as r, open(dest, "wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f)
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Resolve winget PackageIdentifiers for recipe rows.")
    ap.add_argument("--recipe-data", default=str(DEFAULT_RECIPE_DATA),
                    help="recipe_data.py to read TOOLS from (and edit with --apply)")
    ap.add_argument("--out", default="winget_proposals.json", help="proposals JSON output")
    ap.add_argument("--min-confidence", choices=list(CONF_RANK), default="high")
    ap.add_argument("--msix", help="use this local source MSIX instead of downloading")
    ap.add_argument("--source-url", default=WINGET_SOURCE_URL)
    ap.add_argument("--apply", action="store_true",
                    help="stage resolved winget keys into --recipe-data in place")
    ap.add_argument("ids", nargs="*", help="restrict to these recipe ids (default: all)")
    args = ap.parse_args(argv)

    tools = load_tools(args.recipe_data)
    if args.msix:
        index = WingetIndex.from_msix(args.msix)
    else:  # pragma: no cover - network path, exercised by the ingest workflow
        msix = fetch_source_msix(args.source_url, tempfile.mkdtemp(prefix="winget-src-"))
        index = WingetIndex.from_msix(msix)
    try:
        proposals = resolve_all(tools, index, args.min_confidence, set(args.ids) or None)
    finally:
        index.close()

    Path(args.out).write_text(json.dumps(proposals, indent=2) + "\n")
    by_conf = Counter(p["confidence"] for p in proposals)
    print(f"resolved {len(proposals)} winget id(s) "
          f"(high={by_conf['high']} medium={by_conf['medium']} low={by_conf['low']}) "
          f"-> {args.out}")

    if args.apply:
        rd = Path(args.recipe_data)
        new_text, applied, missing = apply_proposals(rd.read_text(), proposals)
        rd.write_text(new_text)
        note = f"; {len(missing)} id(s) not found: {missing}" if missing else ""
        print(f"applied {len(applied)} winget key(s) into {rd}{note}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
