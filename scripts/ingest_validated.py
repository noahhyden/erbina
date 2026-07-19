#!/usr/bin/env python3
"""Install-and-probe recipe ingester — the honest way to grow the registry.

erbina's contract is "prove the tool RUNS", and recipe metadata alone can't tell
a CLI from a library (Homebrew's most-installed formulae are ~60% codecs/libs),
nor a tool's real binary name or version flag. So this does the only reliable
thing: for each candidate it INSTALLS via the given manager, discovers the actual
binary the install produced, probes which version/help flag exits 0, and emits a
recipe row ONLY for candidates that genuinely run. Libraries (no runnable binary)
are skipped automatically.

Emits rows in the scripts/recipe_data.py TOOLS shape (id/bin/title/desc/url +
manager key + validated detect/verify). Run on macOS to mine `brew` at scale;
runs anywhere for cargo/go/pipx/npm.

    scripts/ingest_validated.py --manager pipx --out rows.json ruff black mypy
    scripts/ingest_validated.py --manager npm  --out rows.json turbo madge depcheck
    scripts/ingest_validated.py --manager brew --out rows.json --keep <formula>...

Nothing is committed — review rows.json, then merge into scripts/recipe_data.py.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310
            return json.load(r)
    except Exception:  # noqa: BLE001
        return {}


def enrich(manager: str, spec: str) -> dict:
    """Pull a real description + homepage from the ecosystem's registry API, so
    ingested recipes get a meaningful gallery blurb (not '<bin> command-line tool')."""
    if manager == "pipx":
        info = _fetch_json(f"https://pypi.org/pypi/{spec}/json").get("info", {})
        urls = info.get("project_urls") or {}
        return {"desc": info.get("summary") or "",
                "url": info.get("home_page") or next(iter(urls.values()), "") or ""}
    if manager == "cargo":
        c = _fetch_json(f"https://crates.io/api/v1/crates/{spec}").get("crate", {})
        return {"desc": c.get("description") or "", "url": c.get("repository") or c.get("homepage") or ""}
    return {}

REPO = Path(__file__).resolve().parent.parent
RECIPES = REPO / "recipes"
# flag probe order: the first that exits 0 becomes the recipe's detect/verify.
FLAGS = ["--version", "version", "-V", "-v", "--help"]


def run(cmd: list[str] | str, timeout: int = 300, shell: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)


def existing_ids() -> set[str]:
    return {p.stem for p in RECIPES.glob("*.yaml")}


def existing_bins() -> set[str]:
    """Binaries already covered — the first token of each recipe's detect command
    (so a tool present under a different id, like trippy's `trip`, is still caught)."""
    bins: set[str] = set()
    for p in RECIPES.glob("*.yaml"):
        for line in p.read_text().splitlines():
            s = line.strip()
            if s.startswith("command:"):
                cmd = s.split(":", 1)[1].strip().strip('"').strip()
                if cmd:
                    bins.add(cmd.split()[0])
                break
    return bins


def slug(name: str) -> str:
    return name.lstrip("@").replace("/", "-").replace("_", "-").lower()


# --------------------------------------------------------------------------- #
# per-manager: install, then report the binary name(s) the install produced.
# --------------------------------------------------------------------------- #
def _bins_in(dir_: Path) -> set[str]:
    return {p.name for p in dir_.iterdir() if p.is_file() and os.access(p, os.X_OK)} if dir_.is_dir() else set()


def install_and_find_bins(manager: str, spec: str) -> tuple[list[str], dict]:
    """Install `spec` via `manager`; return (binary names produced, metadata)."""
    meta: dict = {}
    if manager == "npm":
        view = run(["npm", "view", spec, "--json"], timeout=60)
        info = json.loads(view.stdout or "{}") if view.returncode == 0 else {}
        meta = {"desc": info.get("description", ""), "url": info.get("homepage", "")}
        binf = info.get("bin") or {}
        bins = list(binf.keys()) if isinstance(binf, dict) else [spec.split("/")[-1]]
        if run(["npm", "install", "-g", spec], timeout=300).returncode != 0:
            return [], meta
        return bins, meta
    if manager == "pipx":
        before = json.loads(run(["pipx", "list", "--json"], timeout=60).stdout or "{}").get("venvs", {})
        if run(["pipx", "install", spec], timeout=300).returncode != 0:
            return [], meta
        data = json.loads(run(["pipx", "list", "--json"], timeout=60).stdout or "{}").get("venvs", {})
        venv = data.get(spec) or data.get(spec.lower(), {})
        md = (venv.get("metadata", {}) or {}).get("main_package", {})
        meta = {"desc": md.get("summary") or "", "url": md.get("website") or "", "ver": md.get("package_version", "")}
        return list(md.get("apps") or []), meta
    if manager == "cargo":
        if run(["cargo", "install", spec], timeout=900).returncode != 0:
            return [], meta
        # authoritative: `cargo install --list` groups each crate with its bins,
        # e.g. "trippy v0.12.0:\n    trip". A bindir diff is racy and mis-attributes.
        crate = spec.rsplit("@", 1)[0]
        out, cur, bins = run(["cargo", "install", "--list"], timeout=60).stdout, None, []
        for line in out.splitlines():
            if line and not line[0].isspace():
                cur = line.split()[0]
            elif cur == crate and line.strip():
                bins.append(line.strip())
        return bins, meta
    if manager == "go":
        # go installs a main package's binary as the last path element into GOBIN;
        # verify it actually landed (don't guess a name that wasn't produced).
        gobin = Path(os.environ.get("GOBIN") or (Path.home() / "go/bin"))
        before = _bins_in(gobin)
        if run(["go", "install", f"{spec}@latest"], timeout=900).returncode != 0:
            return [], meta
        return sorted(_bins_in(gobin) - before), meta
    if manager == "brew":  # authoritative: the formula's own bin/ entries
        if run(["brew", "install", spec], timeout=900).returncode != 0:
            return [], meta
        ls = run(["brew", "ls", spec], timeout=60).stdout.splitlines()
        return [Path(x).name for x in ls if "/bin/" in x], meta
    raise SystemExit(f"unknown manager {manager}")


def probe_flag(binary: str) -> str | None:
    """First flag on which `binary <flag>` exits 0 (the tool RUNS), else None."""
    if not shutil.which(binary):
        return None
    for flag in FLAGS:
        try:
            if run([binary, flag], timeout=20).returncode == 0:
                return flag
        except subprocess.TimeoutExpired:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Install-and-probe recipe ingester.")
    ap.add_argument("--manager", required=True, choices=["brew", "cargo", "go", "pipx", "npm"])
    ap.add_argument("--out", required=True, help="JSON file to write validated rows to")
    ap.add_argument("--keep", action="store_true", help="don't uninstall after validating")
    ap.add_argument("specs", nargs="+", help="install identifiers (formula/crate/import-path/package)")
    args = ap.parse_args()

    have, have_bins = existing_ids(), existing_bins()
    rows, skipped = [], []
    for spec in args.specs:
        print(f"\n=== {args.manager}: {spec} ===", flush=True)
        try:
            bins, meta = install_and_find_bins(args.manager, spec)
        except Exception as e:  # noqa: BLE001
            print(f"  install error: {e}")
            skipped.append((spec, "install-error"))
            continue
        if not bins:
            print("  no runnable binary produced — skip (library or install failed)")
            skipped.append((spec, "no-binary"))
            continue
        # a package can ship several binaries (mprocs installs `dekit` + `mprocs`);
        # prefer the one whose name matches the package, else the first.
        base = slug(spec.rsplit("@", 1)[0].split("/")[-1])
        binary = next((b for b in bins if slug(b) == base), bins[0])
        flag = probe_flag(binary)
        if flag is None:
            print(f"  binary '{binary}' has no version/help flag that exits 0 — skip")
            skipped.append((spec, "no-verify"))
            continue
        rid = slug(binary)
        # dedup by BOTH id and binary — a tool can already exist under a different
        # id (trippy's recipe id is `trippy` but its binary is `trip`).
        if rid in have or binary in have_bins:
            print(f"  '{binary}' already covered by an existing recipe — skip")
            skipped.append((spec, "dup"))
            continue
        cmd = f"{binary} {flag}"
        extra = enrich(args.manager, spec)  # real desc/url from the registry API
        desc = (extra.get("desc") or meta.get("desc") or f"{binary} command-line tool").strip()
        meta["url"] = meta.get("url") or extra.get("url", "")
        row = {"id": rid, "bin": binary, "title": f"{binary} — {desc[:70]}",
               "short": desc[:60], "desc": desc, "url": meta.get("url", ""),
               args.manager: spec, "detect": cmd, "verify": cmd}
        rows.append(row)
        have.add(rid)
        have_bins.add(binary)
        print(f"  OK -> id={rid} bin={binary} verify='{cmd}'")
        if not args.keep:
            uninstall = {"npm": ["npm", "uninstall", "-g", spec], "pipx": ["pipx", "uninstall", spec],
                         "cargo": ["cargo", "uninstall", spec], "brew": ["brew", "uninstall", spec],
                         "go": None}[args.manager]
            if uninstall:
                run(uninstall, timeout=120)

    Path(args.out).write_text(json.dumps(rows, indent=2))
    print(f"\n{'='*50}\nvalidated {len(rows)} recipe(s); skipped {len(skipped)}: {skipped}")
    print(f"rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
