#!/usr/bin/env python3
"""Resolve winget PackageIdentifiers for recipe rows that lack Windows coverage."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from _harvest import (CONF_RANK, apply_keys, base_parser, load_tools, norm,  # noqa: F401
                      report, resolve_rows, stage)

# The winget community source is a signed MSIX (zip) holding a SQLite catalog; this is its CDN URL.
WINGET_SOURCE_URL = "https://cdn.winget.microsoft.com/cache/source2.msix"
INDEX_MEMBER = "Public/index.db"

def rows_missing_winget(tools: list[dict]) -> list[dict]:
    """Rows without a *truthy* winget key (blank/None count as missing)."""
    return [t for t in tools if not t.get("winget")]


# the winget community-source index (SQLite inside the MSIX)
class WingetIndex:
    """Case-insensitive query layer over the winget SQLite catalog; rows are (id, name, moniker)."""

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
        """Packages that install an executable named `command` (the strongest CLI signal)."""
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


# resolver: tool row + index -> a confidence-tiered proposal (pure)
def _publisher(package_id: str) -> str:
    """The publisher portion of a PackageIdentifier (`BurntSushi.ripgrep` -> BurntSushi)."""
    return package_id.split(".", 1)[0]


def _uniq_by_id(rows: list[tuple]) -> list[tuple]:
    seen: dict[str, tuple] = {}
    for row in rows:
        seen.setdefault(row[0], row)
    return list(seen.values())


def _pick(rows: list[tuple], owner: str | None) -> tuple[tuple, bool] | None:
    """Pick (row, publisher_corroborated); several hits resolve only if the gh owner picks exactly one, else None."""
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
    """Resolve one row to a winget proposal (gh exact id > command > moniker), or None."""
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
    return resolve_rows(rows_missing_winget(tools), lambda t: resolve(t, index),
                        min_confidence, ids)


def apply_proposals(source_text: str, proposals: list[dict]) -> tuple[str, list[str], list[str]]:
    """Stage `winget` after each row's id; see _harvest.apply_keys."""
    return apply_keys(source_text, proposals, ("winget",))


# I/O + CLI
def fetch_source_msix(url: str, dest_dir: str | Path) -> Path:  # pragma: no cover - network I/O
    dest = Path(dest_dir) / "winget-source.msix"
    with urllib.request.urlopen(url, timeout=180) as r, open(dest, "wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f)
    return dest


USAGE = """\
usage examples:
  python3 scripts/winget_candidates.py                    # HIGH-confidence proposals
  python3 scripts/winget_candidates.py --min-confidence medium
  python3 scripts/winget_candidates.py --apply            # stage keys for git review
  python3 scripts/winget_candidates.py --msix ./source.msix   # offline, cached index

confidence tiers:
  high    id is the row's gh owner/repo exactly, or a command/moniker match whose publisher equals the gh owner
  medium  a UNIQUE command (installed-executable) match, but no gh corroboration
  low     a moniker-only match (weakest; monikers collide across unrelated apps)

Reads the winget community-source index (the SQLite catalog the winget CLI uses); stdlib only.
Nothing is committed -- review the diff/JSON, then commit and regenerate recipes.
"""


def main(argv: list[str] | None = None) -> int:
    ap = base_parser("Resolve winget PackageIdentifiers for recipe rows.", "winget_proposals.json", epilog=USAGE)
    ap.add_argument("--msix", help="use this local source MSIX instead of downloading")
    ap.add_argument("--source-url", default=WINGET_SOURCE_URL)
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

    by_conf = report(proposals, args.out)
    print(f"resolved {len(proposals)} winget id(s) "
          f"(high={by_conf['high']} medium={by_conf['medium']} low={by_conf['low']}) "
          f"-> {args.out}")

    if args.apply:
        stage(args.recipe_data, proposals, ("winget",))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
