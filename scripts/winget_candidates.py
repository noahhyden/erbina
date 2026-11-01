#!/usr/bin/env python3
"""Resolve winget PackageIdentifiers for recipe rows that lack Windows coverage."""
from __future__ import annotations

import contextlib
import shutil
import sqlite3
import tempfile
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path

from _harvest import base_parser, load_tools, norm, report, resolve_rows, stage

# The winget community source is a signed MSIX (zip) holding a SQLite catalog; this is its CDN URL.
WINGET_SOURCE_URL = "https://cdn.winget.microsoft.com/cache/source2.msix"
INDEX_MEMBER = "Public/index.db"

def rows_missing_winget(tools: list[dict]) -> list[dict]:
    """Rows without a *truthy* winget key (blank/None count as missing)."""
    return [t for t in tools if not t.get("winget")]


# the winget community-source index (SQLite inside the MSIX); query rows are (id, name, moniker)
@contextlib.contextmanager
def open_msix(msix_path: str | Path) -> Iterator[sqlite3.Connection]:
    # deserialize() is 3.11+, but erbina supports 3.10 -> extract to a temp file.
    with tempfile.TemporaryDirectory(prefix="winget-idx-") as tmpdir:
        with zipfile.ZipFile(msix_path) as z:
            raw = z.read(INDEX_MEMBER)
        dbpath = Path(tmpdir) / "index.db"
        dbpath.write_bytes(raw)
        conn = sqlite3.connect(dbpath)
        try:
            yield conn
        finally:
            conn.close()


def by_command(conn: sqlite3.Connection, command: str) -> list[tuple]:
    """Packages that install an executable named `command` (the strongest CLI signal)."""
    return conn.execute(
        "SELECT p.id, p.name, p.moniker FROM commands2 c "
        "JOIN commands2_map m ON m.command = c.rowid "
        "JOIN packages p ON p.rowid = m.package "
        "WHERE c.command = ? COLLATE NOCASE",
        (command,),
    ).fetchall()


def by_moniker(conn: sqlite3.Connection, moniker: str) -> list[tuple]:
    return conn.execute(
        "SELECT id, name, moniker FROM packages WHERE moniker = ? COLLATE NOCASE",
        (moniker,),
    ).fetchall()


def by_id(conn: sqlite3.Connection, package_id: str) -> list[tuple]:
    return conn.execute(
        "SELECT id, name, moniker FROM packages WHERE id = ? COLLATE NOCASE",
        (package_id,),
    ).fetchall()


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


def resolve(tool: dict, conn: sqlite3.Connection) -> dict | None:
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
        hit = by_id(conn, f"{owner}.{repo}")
        if hit:
            return proposal(hit[0], "high", "gh-id-exact")

    # 2. command (installed-executable) match.
    cmd_rows = _uniq_by_id(by_command(conn, binary)
                           + (by_command(conn, rid) if rid != binary else []))
    picked = _pick(cmd_rows, owner)
    if picked is not None:
        row, corroborated = picked
        return proposal(row, "high", "cmd+publisher") if corroborated \
            else proposal(row, "medium", "cmd-unique")

    # 3. moniker match (weakest -- monikers collide across unrelated apps).
    mon_rows = _uniq_by_id(by_moniker(conn, binary)
                           + (by_moniker(conn, rid) if rid != binary else []))
    picked = _pick(mon_rows, owner)
    if picked is not None:
        row, corroborated = picked
        return proposal(row, "high", "moniker+publisher") if corroborated \
            else proposal(row, "low", "moniker-only")

    return None


def resolve_all(tools: list[dict], conn: sqlite3.Connection, min_confidence: str = "high",
                ids: set[str] | None = None) -> list[dict]:
    """Resolve every winget-less row at or above `min_confidence`, sorted by id."""
    return resolve_rows(rows_missing_winget(tools), lambda t: resolve(t, conn),
                        min_confidence, ids)


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
        msix = args.msix
    else:  # pragma: no cover - network path, exercised by the ingest workflow
        msix = fetch_source_msix(args.source_url, tempfile.mkdtemp(prefix="winget-src-"))
    with open_msix(msix) as conn:
        proposals = resolve_all(tools, conn, args.min_confidence, set(args.ids) or None)

    by_conf = report(proposals, args.out)
    print(f"resolved {len(proposals)} winget id(s) "
          f"(high={by_conf['high']} medium={by_conf['medium']} low={by_conf['low']}) "
          f"-> {args.out}")

    if args.apply:
        stage(args.recipe_data, proposals, ("winget",))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
