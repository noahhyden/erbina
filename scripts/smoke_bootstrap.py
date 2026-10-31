#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=2.0", "pyyaml>=6.0", "packaging>=23"]
# ///
"""Real (non-dry) bootstrap smoke test: bootstraps each named recipe through erbina's own MCP tools."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

# make `import server` work from anywhere
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import server  # noqa: E402
from helpers import call_tool  # noqa: E402


def _bootstrap(rid: str, scope: str = "user", project_dir: str | None = None) -> dict:
    args: dict = {"recipe_id": rid, "scope": scope}
    if project_dir is not None:
        args["project_dir"] = project_dir
    return call_tool("bootstrap", args)


def _uninstall(rid: str) -> dict:
    return call_tool("uninstall", {"recipe_id": rid})


def _print_phases(report: dict) -> bool:
    """Print a bootstrap report's per-phase status; return its `ok` flag."""
    phases = report.get("phases", {})
    for name in ("detect", "install", "configure", "verify"):
        ph = phases.get(name)
        if ph is not None:
            status = ph.get("status") or ("present" if ph.get("present") else "absent") if isinstance(ph, dict) else ph
            print(f"  {name:10}: {status}", flush=True)
    ok = report.get("ok")
    print(f"  ok = {ok}", flush=True)
    if not ok:
        print(f"  REPORT: {json.dumps(report)[:1500]}", flush=True)
    return bool(ok)


USAGE = """\
usage examples:
  scripts/smoke_bootstrap.py ripgrep fd bat            # bootstrap these for real
  scripts/smoke_bootstrap.py --uninstall httpie        # bootstrap, then uninstall
                                                       # (leaves the machine clean)

Each recipe runs detect -> install -> configure -> verify and fails unless its
report is ok. Meant for CI runners with real package managers
(.github/workflows/real-bootstrap.yml), or locally.

Isolation: erbina's state manifest is redirected to a temp dir, so a smoke run
never touches ~/.erbina. Where a recipe is installed depends on the eligible
install method (brew prefix, cargo/go bin, pipx venv); pass --uninstall to have
recipes with an `uninstall:` block reverse themselves afterward.
"""


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Real bootstrap smoke test for erbina recipes.", epilog=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipes", nargs="+", help="recipe ids to bootstrap for real")
    ap.add_argument("--uninstall", action="store_true", help="uninstall each recipe afterward (if it has an uninstall block)")
    ap.add_argument("--roundtrip", action="store_true",
                    help="prove install->uninstall->reinstall: bootstrap, uninstall, then bootstrap AGAIN, "
                         "failing unless the reinstall is ok. Catches package managers whose teardown leaves "
                         "install state behind (pipx venv, cargo .crates2.json) so the reinstall silently no-ops.")
    ap.add_argument("--scope", default="user", help="scope for mcp-server wiring (local|project|user)")
    ap.add_argument("--project-dir", default=None, help="project dir for needs_project_dir phases (mcp-server recipes)")
    args = ap.parse_args()

    # isolate the state manifest so a smoke run never touches the real ~/.erbina
    server.STATE_DIR = Path(tempfile.mkdtemp(prefix="erbina-smoke-")) / ".erbina"

    failures: list[str] = []
    for rid in args.recipes:
        print(f"\n=== bootstrap {rid} ===", flush=True)
        if not _print_phases(_bootstrap(rid, scope=args.scope, project_dir=args.project_dir)):
            failures.append(rid)
            continue

        if args.roundtrip:
            print(f"--- roundtrip {rid}: uninstall ---", flush=True)
            u = _uninstall(rid)
            print(f"  uninstall ok = {u.get('ok')}", flush=True)
            if not u.get("ok"):
                print(f"  UNINSTALL FAILED: {json.dumps(u)[:1000]}", flush=True)
                failures.append(f"{rid} (uninstall)")
                continue
            print(f"--- roundtrip {rid}: REINSTALL (the assertion) ---", flush=True)
            if not _print_phases(_bootstrap(rid, scope=args.scope, project_dir=args.project_dir)):
                print(f"  BROKEN ROUND-TRIP: {rid} would not reinstall cleanly after uninstall", flush=True)
                failures.append(f"{rid} (reinstall)")
                continue
            print("  round-trip ok = True", flush=True)
        elif args.uninstall:
            u = _uninstall(rid)
            print(f"  uninstall ok = {u.get('ok')} (forgotten={u.get('forgotten')})", flush=True)

    print("\n" + ("=" * 50))
    if failures:
        print(f"FAILED to bootstrap: {', '.join(failures)}")
        return 1
    verb = "round-tripped" if args.roundtrip else "bootstrapped"
    print(f"OK: {verb} {len(args.recipes)} recipe(s) for real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
