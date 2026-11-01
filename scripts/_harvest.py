"""Code shared by the winget and curl maintainer harvesters (stdlib only)."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECIPE_DATA = REPO_ROOT / "scripts" / "recipe_data.json"

CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def norm(s: str | None) -> str:
    """Casefold to bare alphanumerics for comparing names/publishers/owners."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def apply_keys(rows: list[dict], proposals: list[dict], keys: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """Set each proposal's `keys` on its row in place (right after `id`); idempotent, a row already carrying keys[0] is skipped."""
    by_id = {r["id"]: r for r in rows}
    applied: list[str] = []
    missing: list[str] = []
    for p in proposals:
        row = by_id.get(p["id"])
        if row is None:
            missing.append(p["id"])
        elif keys[0] not in row:
            rest = {k: v for k, v in row.items() if k != "id"}
            row.clear()
            row.update({"id": p["id"], **{k: p[k] for k in keys if p.get(k)}, **rest})
            applied.append(p["id"])
    return applied, missing


def load_tools(path: str | Path) -> list[dict]:
    """Read the TOOLS rows from a recipe_data.json file."""
    return json.loads(Path(path).read_text())


def resolve_rows(rows: list[dict], resolve: Callable[[dict], dict | None],
                 min_confidence: str = "high", ids: set[str] | None = None) -> list[dict]:
    """Resolve rows (restricted to `ids`), keep proposals at or above `min_confidence`, sorted by id."""
    threshold = CONF_RANK[min_confidence]
    out = []
    for tool in rows:
        if ids is not None and tool["id"] not in ids:
            continue
        p = resolve(tool)
        if p and CONF_RANK[p["confidence"]] >= threshold:
            out.append(p)
    out.sort(key=lambda p: p["id"])
    return out


def base_parser(description: str, default_out: str, epilog: str = "") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description, epilog=epilog,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recipe-data", default=str(DEFAULT_RECIPE_DATA),
                    help="recipe_data.json to read TOOLS from (and edit with --apply)")
    ap.add_argument("--out", default=default_out, help="proposals JSON output")
    ap.add_argument("--min-confidence", choices=list(CONF_RANK), default="high")
    ap.add_argument("--apply", action="store_true",
                    help="stage resolved keys into --recipe-data in place")
    ap.add_argument("ids", nargs="*", help="restrict to these recipe ids (default: all)")
    return ap


def report(proposals: list[dict], out: str) -> Counter:
    """Write the proposals JSON; return the per-confidence counts."""
    Path(out).write_text(json.dumps(proposals, indent=2) + "\n")
    return Counter(p["confidence"] for p in proposals)


def stage(recipe_data: str, proposals: list[dict], keys: tuple[str, ...]) -> None:
    """--apply: insert `keys` into recipe_data.json in place and print a summary."""
    rd = Path(recipe_data)
    rows = load_tools(rd)
    applied, missing = apply_keys(rows, proposals, keys)
    rd.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    note = f"; {len(missing)} id(s) not found: {missing}" if missing else ""
    print(f"applied {len(applied)} {keys[0]} key(s) into {rd}{note}")
