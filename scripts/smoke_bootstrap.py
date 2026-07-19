#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=2.0", "pyyaml>=6.0", "packaging>=23"]
# ///
"""Real (non-dry) bootstrap smoke test — the counterpart to the offline suite.

The pytest suite is deterministic and OFFLINE: it never runs a real package
manager, so it can prove the ORCHESTRATION is correct but not that a recipe's
actual install command works (a renamed brew formula, a dead URL, a wrong
`go install` path would all pass offline and only break on a real bootstrap).

This driver closes that gap: it bootstraps each named recipe FOR REAL through
erbina's own MCP tool surface (detect -> install -> configure -> verify) and
fails if any recipe's report isn't ok. Meant to run on CI runners that actually
have the package managers (see .github/workflows/real-bootstrap.yml), or locally.

Usage:
    scripts/smoke_bootstrap.py ripgrep fd bat            # bootstrap these for real
    scripts/smoke_bootstrap.py --uninstall httpie        # bootstrap, then uninstall
                                                         # (leaves the machine clean)

Isolation: erbina's state manifest is redirected to a temp dir, so a smoke run
never touches ~/.erbina. Where a recipe is installed depends on the eligible
install method (brew prefix, cargo/go bin, pipx venv) — pass --uninstall to have
recipes with an `uninstall:` block reverse themselves afterward.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

# make `import server` work from anywhere (repo root is this file's parent's parent)
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402
from fastmcp import Client  # noqa: E402


async def _call(name: str, args: dict) -> dict:
    async with Client(server.mcp) as client:
        res = await client.call_tool(name, args)
        for attr in ("data", "structured_content"):
            val = getattr(res, attr, None)
            if val is not None:
                return val
        return {}


def _bootstrap(rid: str, scope: str = "user", project_dir: str | None = None) -> dict:
    args: dict = {"recipe_id": rid, "scope": scope}
    if project_dir is not None:
        args["project_dir"] = project_dir
    return asyncio.run(_call("bootstrap", args))


def _uninstall(rid: str) -> dict:
    return asyncio.run(_call("uninstall", {"recipe_id": rid}))


def main() -> int:
    ap = argparse.ArgumentParser(description="Real bootstrap smoke test for erbina recipes.")
    ap.add_argument("recipes", nargs="+", help="recipe ids to bootstrap for real")
    ap.add_argument("--uninstall", action="store_true", help="uninstall each recipe afterward (if it has an uninstall block)")
    ap.add_argument("--scope", default="user", help="scope for mcp-server wiring (local|project|user)")
    ap.add_argument("--project-dir", default=None, help="project dir for needs_project_dir phases (mcp-server recipes)")
    args = ap.parse_args()

    # isolate the state manifest so a smoke run never touches the real ~/.erbina
    server.STATE_DIR = Path(tempfile.mkdtemp(prefix="erbina-smoke-")) / ".erbina"

    failures: list[str] = []
    for rid in args.recipes:
        print(f"\n=== bootstrap {rid} ===", flush=True)
        report = _bootstrap(rid, scope=args.scope, project_dir=args.project_dir)
        ok = report.get("ok")
        phases = report.get("phases", {})
        for name in ("detect", "install", "configure", "verify"):
            ph = phases.get(name)
            if ph is not None:
                status = ph.get("status") or ("present" if ph.get("present") else "absent") if isinstance(ph, dict) else ph
                print(f"  {name:10}: {status}", flush=True)
        print(f"  ok = {ok}", flush=True)
        if not ok:
            print(f"  REPORT: {json.dumps(report)[:1500]}", flush=True)
            failures.append(rid)
        elif args.uninstall:
            u = _uninstall(rid)
            print(f"  uninstall ok = {u.get('ok')} (forgotten={u.get('forgotten')})", flush=True)

    print("\n" + ("=" * 50))
    if failures:
        print(f"FAILED to bootstrap: {', '.join(failures)}")
        return 1
    print(f"OK: bootstrapped {len(args.recipes)} recipe(s) for real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
