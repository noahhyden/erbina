#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=2.0", "pyyaml>=6.0"]
# ///
"""
erbina — a Claude-Code-only MCP server that bootstraps a dev environment.

Named after the Lusitanian goddess of boundaries and crossings: erbina is the
threshold a tool crosses to become part of your environment. It is *only*
reachable through an MCP client (an agent), by design — there is no manual
entry point, so nobody can mistake it for something they run by hand.

What it does, from one prompt:
  - install + wire + verify CLI tools and other MCP servers from curated
    recipes (detect -> install -> configure -> verify, idempotent), and
  - audit where MCP servers are configured across Claude Code's local /
    project / user scopes, so you have one place that knows what's installed
    where.

Proof-of-concept recipe #1: ataegina (a single-file bash CLI that gives each
git worktree collision-free ports/databases).
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import yaml
from fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
RECIPES_DIR = HERE / "recipes"
VALID_SCOPES = ("local", "project", "user")

mcp = FastMCP(
    "erbina",
    instructions=(
        "erbina bootstraps a developer's environment from curated recipes. Use it to "
        "INSTALL, CONFIGURE, and VERIFY CLI tools and other MCP servers for Claude Code, "
        "and to AUDIT where MCP servers live across local/project/user scopes.\n\n"
        "Always call `inspect_recipe` (or `bootstrap` with dry_run=true) FIRST and show the "
        "user exactly what will run before executing — erbina shells out to package managers "
        "with real privileges. Recipes are idempotent: `bootstrap` detects an already-present "
        "tool and skips installation. When a recipe installs a new MCP server, remind the user "
        "to reload Claude Code so the new server connects."
    ),
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _run(cmd: str, cwd: str | None = None, timeout: int = 600) -> dict[str, Any]:
    """Run a shell command, capturing a trimmed result. Never raises."""
    try:
        p = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return {
            "cmd": cmd,
            "exit": p.returncode,
            "stdout": p.stdout.strip()[-4000:],
            "stderr": p.stderr.strip()[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "exit": 124, "stdout": "", "stderr": f"timed out after {timeout}s"}
    except Exception as e:  # noqa: BLE001 - report, don't crash the tool call
        return {"cmd": cmd, "exit": 1, "stdout": "", "stderr": f"{type(e).__name__}: {e}"}


def _guard_ok(when: str | None) -> bool:
    """A method's `when:` guard passes when the guard command exits 0 (or is absent)."""
    if not when:
        return True
    return _run(when, timeout=15)["exit"] == 0


def _load_recipe(recipe_id: str) -> dict[str, Any]:
    safe = Path(recipe_id).name  # no path traversal
    path = RECIPES_DIR / f"{safe}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"no recipe '{recipe_id}'. Available: {', '.join(_recipe_ids()) or '(none)'}"
        )
    data = yaml.safe_load(path.read_text()) or {}
    data["_path"] = str(path)
    return data


def _recipe_ids() -> list[str]:
    if not RECIPES_DIR.exists():
        return []
    return sorted(p.stem for p in RECIPES_DIR.glob("*.yaml"))


def _pick_install_method(recipe: dict[str, Any]) -> dict[str, Any] | None:
    for m in recipe.get("install", {}).get("methods", []):
        if _guard_ok(m.get("when")):
            return m
    return None


def _plan(recipe: dict[str, Any], scope: str, project_dir: str | None) -> dict[str, Any]:
    """The consent surface: exactly what bootstrap would do, running nothing destructive."""
    method = _pick_install_method(recipe)
    return {
        "detect": recipe.get("detect", {}).get("command"),
        "install": {
            "chosen_method": method.get("id") if method else None,
            "command": method.get("run") if method else None,
            "all_methods": [
                {"id": m.get("id"), "when": m.get("when"), "run": m.get("run")}
                for m in recipe.get("install", {}).get("methods", [])
            ],
        },
        "configure": recipe.get("configure", {}).get("steps", []),
        "verify": [v.get("command") for v in recipe.get("verify", [])],
        "scope": scope,
        "project_dir": project_dir,
    }


def _claude_json() -> dict[str, Any]:
    p = Path.home() / ".claude.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return {}


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #
@mcp.tool
def list_recipes() -> list[dict[str, str]]:
    """List the curated recipes erbina can bootstrap (id, kind, title, description)."""
    out = []
    for rid in _recipe_ids():
        try:
            r = _load_recipe(rid)
        except Exception:  # noqa: BLE001
            continue
        out.append(
            {
                "id": rid,
                "kind": r.get("kind", "?"),
                "title": r.get("title", rid),
                "description": r.get("description", ""),
            }
        )
    return out


@mcp.tool
def inspect_recipe(recipe_id: str, scope: str = "user", project_dir: str | None = None) -> dict[str, Any]:
    """
    Show EXACTLY what bootstrapping a recipe would run, without executing anything.
    Call this and show the user before running `bootstrap`. `scope` is one of
    local|project|user (only meaningful for kind: mcp-server recipes).
    """
    if scope not in VALID_SCOPES:
        return {"error": f"scope must be one of {VALID_SCOPES}"}
    recipe = _load_recipe(recipe_id)
    return {
        "id": recipe_id,
        "kind": recipe.get("kind"),
        "title": recipe.get("title"),
        "description": recipe.get("description"),
        "will_run": _plan(recipe, scope, project_dir),
        "note": "Nothing was executed. Re-run via `bootstrap` (optionally dry_run=true) to proceed.",
    }


@mcp.tool
def bootstrap(
    recipe_id: str,
    scope: str = "user",
    dry_run: bool = False,
    project_dir: str | None = None,
    force_configure: bool = False,
) -> dict[str, Any]:
    """
    Install + configure + verify a recipe, idempotently.

    Phases: detect (skip install if already present) -> install (first method whose
    `when:` guard passes) -> configure (tool-specific wiring; skipped if already
    present unless force_configure) -> verify (commands that must exit 0).

    Set dry_run=true to get the full plan without executing. `scope` (local|project|
    user) targets where an mcp-server recipe is wired. `project_dir` is the working
    dir for configure steps (e.g. where `ataegina init` runs).
    """
    if scope not in VALID_SCOPES:
        return {"error": f"scope must be one of {VALID_SCOPES}"}
    recipe = _load_recipe(recipe_id)
    report: dict[str, Any] = {
        "recipe": recipe_id,
        "kind": recipe.get("kind"),
        "scope": scope,
        "dry_run": dry_run,
        "plan": _plan(recipe, scope, project_dir),
        "phases": {},
    }

    if dry_run:
        report["note"] = "Dry run — nothing executed. Review `plan`, then re-run with dry_run=false."
        return report

    # 1. detect (idempotency gate)
    det_spec = recipe.get("detect", {})
    detected = False
    if det_spec.get("command"):
        det = _run(det_spec["command"], timeout=30)
        detected = det["exit"] == det_spec.get("expect_exit", 0)
        report["phases"]["detect"] = {"present": detected, **det}

    # 2. install (only if not already present)
    if detected:
        report["phases"]["install"] = {"status": "skipped", "reason": "already present"}
    else:
        method = _pick_install_method(recipe)
        if not method:
            report["phases"]["install"] = {
                "status": "failed",
                "reason": "no install method's `when:` guard passed on this machine",
            }
            report["ok"] = False
            return report
        res = _run(method["run"])
        report["phases"]["install"] = {
            "status": "ok" if res["exit"] == 0 else "failed",
            "method": method.get("id"),
            **res,
        }
        if res["exit"] != 0:
            report["ok"] = False
            return report

    # 3. configure (tool-specific wiring)
    cfg_steps = recipe.get("configure", {}).get("steps", [])
    if detected and not force_configure:
        report["phases"]["configure"] = {
            "status": "skipped",
            "reason": "tool already present; pass force_configure=true to re-run",
        }
    elif not cfg_steps:
        report["phases"]["configure"] = {"status": "none"}
    else:
        results = []
        for step in cfg_steps:
            cwd = project_dir if step.get("needs_project_dir") else None
            if step.get("needs_project_dir") and not project_dir:
                results.append(
                    {"cmd": step.get("run"), "status": "skipped", "reason": "no project_dir supplied"}
                )
                continue
            res = _run(step["run"], cwd=cwd)
            ok = res["exit"] == 0 or step.get("optional")
            results.append({"status": "ok" if ok else "failed", **res})
        report["phases"]["configure"] = {"steps": results}

    # 4. verify (must exit 0)
    verify_results = []
    all_ok = True
    for v in recipe.get("verify", []):
        res = _run(v["command"], timeout=30)
        ok = res["exit"] == v.get("expect_exit", 0)
        if not ok and not v.get("optional"):
            all_ok = False
        verify_results.append({"status": "ok" if ok else "failed", **res})
    report["phases"]["verify"] = verify_results
    report["ok"] = all_ok

    if recipe.get("kind") == "mcp-server" and all_ok:
        report["next"] = "A new MCP server was wired — reload Claude Code so it connects."
    return report


@mcp.tool
def audit_scopes(project_dir: str | None = None) -> dict[str, Any]:
    """
    Show where MCP servers are configured across Claude Code's scopes — one place
    that knows what's installed where. Reads user scope (~/.claude.json top-level),
    local scope (~/.claude.json per-project), and project scope (.mcp.json in
    project_dir or CWD). Read-only.
    """
    cj = _claude_json()
    proj_root = Path(project_dir).resolve() if project_dir else Path.cwd()

    user = sorted((cj.get("mcpServers") or {}).keys())

    local_entry = (cj.get("projects") or {}).get(str(proj_root), {})
    local = sorted((local_entry.get("mcpServers") or {}).keys())

    project: list[str] = []
    mcp_json = proj_root / ".mcp.json"
    if mcp_json.exists():
        try:
            project = sorted((json.loads(mcp_json.read_text()).get("mcpServers") or {}).keys())
        except Exception:  # noqa: BLE001
            project = []

    # surface the classic confusion: same server name living in more than one scope
    by_name: dict[str, list[str]] = {}
    for s, names in (("user", user), ("project", project), ("local", local)):
        for n in names:
            by_name.setdefault(n, []).append(s)
    shadowed = {n: s for n, s in by_name.items() if len(s) > 1}

    return {
        "project_root": str(proj_root),
        "precedence": "local > project > user (highest wins; fields are not merged)",
        "scopes": {
            "user": {"where": str(Path.home() / ".claude.json") + " (top-level mcpServers)", "servers": user},
            "project": {"where": str(mcp_json) + " (shared via git)", "servers": project},
            "local": {"where": str(Path.home() / ".claude.json") + f" (projects['{proj_root}'].mcpServers)", "servers": local},
        },
        "shadowed": shadowed or "none — no server name is defined in more than one scope",
        "total_distinct": len(by_name),
    }


if __name__ == "__main__":
    mcp.run()  # stdio transport (the only way in: an MCP client / agent)
