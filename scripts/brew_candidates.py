#!/usr/bin/env python3
"""Emit a ranked list of Homebrew formulae to feed scripts/ingest_validated.py.

Pulls Homebrew's install-analytics (popularity = a quality signal) and formula
metadata, then prints the most-installed formulae that AREN'T already recipes,
skipping keg-only libraries and obvious non-CLIs. The list is only a starting
point: the ingester still installs and probes each one, so any library that slips
through here produces no runnable binary and is dropped there.

    scripts/brew_candidates.py --limit 60 --offset 0
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

RECIPES = Path(__file__).resolve().parent.parent / "recipes"
ANALYTICS = "https://formulae.brew.sh/api/analytics/install/365d.json"
FORMULA = "https://formulae.brew.sh/api/formula.json"
LIBISH = re.compile(r"(^lib|-dev$|^glib|zlib|@\d)")
LIB_WORDS = ("library", "libraries", "bindings", "header", "font", "codec",
             "encoder", "decoder", "framework for", "c++ ", "runtime library")


def _get(url: str) -> object:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args()

    analytics = _get(ANALYTICS)
    items = analytics["items"] if isinstance(analytics, dict) else analytics
    forms = {f["name"]: f for f in _get(FORMULA)}
    existing = {p.stem for p in RECIPES.glob("*.yaml")}

    rank: dict[str, int] = {}
    for it in items:
        name = it["formula"].split()[0]
        rank[name] = max(rank.get(name, 0), int(str(it["count"]).replace(",", "")))

    def ok(name: str) -> bool:
        f = forms.get(name)
        if not f or f.get("keg_only") or name in existing or LIBISH.search(name):
            return False
        desc = (f.get("desc") or "").lower()
        return bool(desc) and not any(w in desc for w in LIB_WORDS)

    ranked = sorted((n for n in rank if ok(n)), key=lambda n: -rank[n])
    for name in ranked[args.offset:args.offset + args.limit]:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
