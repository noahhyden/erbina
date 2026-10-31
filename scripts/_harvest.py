"""Code shared by the winget and curl maintainer harvesters (stdlib only)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECIPE_DATA = REPO_ROOT / "scripts" / "recipe_data.py"

CONF_RANK = {"high": 3, "medium": 2, "low": 1}

_ROW = re.compile(r"\{[^{}]*\}")  # a TOOLS row is a brace-balanced dict with no nesting


def norm(s: str | None) -> str:
    """Casefold to bare alphanumerics for comparing names/publishers/owners."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _id_token(rid: str) -> re.Pattern[str]:
    # anchored on the exact id so `fd` never matches the `fdupes` row.
    return re.compile(r'"id":\s*"' + re.escape(rid) + r'"')


def apply_keys(source_text: str, proposals: list[dict],
               keys: tuple[str, ...]) -> tuple[str, list[str], list[str]]:
    """Insert `, "<key>": "<value>"` after each row's id; idempotent, a row already carrying keys[0] is skipped."""
    text = source_text
    applied: list[str] = []
    missing: list[str] = []
    for p in proposals:
        rid = p["id"]
        token = _id_token(rid)
        row_match = next((m for m in _ROW.finditer(text) if token.search(m.group())), None)
        if row_match is None:
            missing.append(rid)
            continue
        row = row_match.group()
        if f'"{keys[0]}"' in row:  # already staged -> idempotent
            continue
        insert = "".join(f', "{k}": "{p[k]}"' for k in keys if p.get(k))
        at = token.search(row).end()
        text = text[:row_match.start()] + row[:at] + insert + row[at:] + text[row_match.end():]
        applied.append(rid)
    return text, applied, missing


def load_tools(recipe_data_path: str | Path) -> list[dict]:
    """Import TOOLS from a recipe_data.py file at an arbitrary path."""
    spec = importlib.util.spec_from_file_location("_erbina_recipe_data", recipe_data_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TOOLS


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
                    help="recipe_data.py to read TOOLS from (and edit with --apply)")
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
    """--apply: insert `keys` into recipe_data.py in place and print a summary."""
    rd = Path(recipe_data)
    new_text, applied, missing = apply_keys(rd.read_text(), proposals, keys)
    rd.write_text(new_text)
    note = f"; {len(missing)} id(s) not found: {missing}" if missing else ""
    print(f"applied {len(applied)} {keys[0]} key(s) into {rd}{note}")
