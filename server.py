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
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import yaml
from fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
RECIPES_DIR = HERE / "recipes"
VALID_SCOPES = ("local", "project", "user")
VALID_KINDS = ("cli-tool", "mcp-server")

# The closed set of top-level keys SCHEMA.md defines. `_path` is injected by the
# loader AFTER validation, so it is not part of the recipe's authored contract.
TOP_LEVEL_KEYS = frozenset(
    {"id", "kind", "title", "description", "detect", "install", "configure", "verify", "scope"}
)
# The only placeholders `_subst` expands; any other ${...} token would pass through
# into an executed command literally, so it is a recipe bug.
KNOWN_PLACEHOLDERS = frozenset({"scope", "project_dir"})
_PLACEHOLDER_RE = re.compile(r"\$\{([^}]*)\}")

mcp = FastMCP(
    "erbina",
    instructions=(
        "erbina bootstraps a developer's environment from curated recipes. Use it to "
        "INSTALL, CONFIGURE, and VERIFY CLI tools and other MCP servers for Claude Code, "
        "to AUDIT where MCP servers live across local/project/user scopes, and to find "
        "and REMOVE stale/dead MCP servers that no longer connect (`find_dead_mcps` then "
        "`remove_mcp`).\n\n"
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


def _subst(cmd: str | None, scope: str, project_dir: str | None) -> str:
    """Expand recipe placeholders in a command string.

    ${scope}        -> the resolved local|project|user scope (mcp-server wiring)
    ${project_dir}  -> the supplied project dir (or '.' if none)
    """
    if not cmd:
        return ""
    return cmd.replace("${scope}", scope).replace("${project_dir}", project_dir or ".")


def _check_placeholders(text: Any, where: str, errors: list[str]) -> None:
    """Flag any ${...} token that `_subst` would NOT expand (e.g. a typo'd
    `${scopee}`), since it would otherwise pass through into an executed command
    string literally."""
    if not isinstance(text, str):
        return
    for tok in _PLACEHOLDER_RE.findall(text):
        if tok not in KNOWN_PLACEHOLDERS:
            errors.append(
                f"{where}: unknown placeholder '${{{tok}}}' "
                f"(only {', '.join('${' + p + '}' for p in sorted(KNOWN_PLACEHOLDERS))} are substituted)"
            )
    # A `${` with no matching `}` is neither expanded by _subst nor caught by the
    # loop above, so it would reach an executed command literally. Every `${`
    # must open a closed token, so more `${` than closed tokens ⇒ an unterminated
    # placeholder (a missing-brace typo).
    if text.count("${") > len(_PLACEHOLDER_RE.findall(text)):
        errors.append(f"{where}: unterminated placeholder — a '${{' has no closing '}}'")


def validate_recipe(recipe: Any, *, stem: str) -> list[str]:
    """Validate a parsed recipe dict against the SCHEMA.md contract.

    Returns a list of human-readable error strings; an empty list means the
    recipe is valid. This is the single source of truth shared by recipe LOADING
    (`_load_recipe` raises if this is non-empty, so a malformed recipe is refused
    rather than silently no-op'ing a phase) and the standalone `lint_recipes.py`.
    """
    errors: list[str] = []
    if not isinstance(recipe, dict):
        return [f"recipe must be a YAML mapping, got {type(recipe).__name__}"]

    # ignore the loader-injected internal key when checking the closed key set
    unknown = set(recipe) - TOP_LEVEL_KEYS - {"_path"}
    if unknown:
        errors.append(f"unknown top-level key(s): {', '.join(sorted(unknown))}")

    # id — present and equal to the filename stem
    rid = recipe.get("id")
    if not rid:
        errors.append("missing required key 'id'")
    elif rid != stem:
        errors.append(f"'id' ({rid!r}) must equal the filename stem ({stem!r})")

    # kind — closed enum
    kind = recipe.get("kind")
    if kind not in VALID_KINDS:
        errors.append(f"'kind' must be one of {VALID_KINDS}, got {kind!r}")

    # detect — required, with a non-empty command
    detect = recipe.get("detect")
    if not isinstance(detect, dict):
        errors.append("missing or malformed 'detect' (expected a mapping with a 'command')")
    else:
        cmd = detect.get("command")
        if not (isinstance(cmd, str) and cmd.strip()):
            errors.append("'detect.command' is required and must be a non-empty string")
        _check_placeholders(detect.get("command"), "detect.command", errors)

    # install — required, methods non-empty, each method has id + run
    install = recipe.get("install")
    if not isinstance(install, dict):
        errors.append("missing or malformed 'install' (expected a mapping with 'methods')")
    else:
        methods = install.get("methods")
        if not isinstance(methods, list) or not methods:
            errors.append("'install.methods' must be a non-empty list")
        else:
            for i, m in enumerate(methods):
                tag = f"install.methods[{i}]"
                if not isinstance(m, dict):
                    errors.append(f"{tag}: must be a mapping")
                    continue
                if not (isinstance(m.get("id"), str) and m["id"].strip()):
                    errors.append(f"{tag}: missing non-empty 'id'")
                if not (isinstance(m.get("run"), str) and m["run"].strip()):
                    errors.append(f"{tag}: missing non-empty 'run'")
                _check_placeholders(m.get("run"), f"{tag}.run", errors)
                _check_placeholders(m.get("when"), f"{tag}.when", errors)

    # configure — optional, but if present each step needs a 'run'
    configure = recipe.get("configure")
    cfg_runs: list[str] = []
    if configure is not None:
        if not isinstance(configure, dict):
            errors.append("'configure' must be a mapping with 'steps'")
        else:
            steps = configure.get("steps")
            if not isinstance(steps, list) or not steps:
                errors.append("'configure.steps' must be a non-empty list when 'configure' is present")
            else:
                for i, s in enumerate(steps):
                    tag = f"configure.steps[{i}]"
                    if not isinstance(s, dict):
                        errors.append(f"{tag}: must be a mapping")
                        continue
                    run = s.get("run")
                    if not (isinstance(run, str) and run.strip()):
                        errors.append(f"{tag}: missing non-empty 'run'")
                    elif isinstance(run, str):
                        cfg_runs.append(run)
                    _check_placeholders(run, f"{tag}.run", errors)

    # verify — required, non-empty, each entry has a command
    verify = recipe.get("verify")
    if not isinstance(verify, list) or not verify:
        errors.append("'verify' must be a non-empty list")
    else:
        for i, v in enumerate(verify):
            tag = f"verify[{i}]"
            if not isinstance(v, dict):
                errors.append(f"{tag}: must be a mapping")
                continue
            if not (isinstance(v.get("command"), str) and v["command"].strip()):
                errors.append(f"{tag}: missing non-empty 'command'")
            _check_placeholders(v.get("command"), f"{tag}.command", errors)

    # scope — optional, but if present must be a valid scope
    scope = recipe.get("scope")
    if scope is not None and scope not in VALID_SCOPES:
        errors.append(f"'scope' must be one of {VALID_SCOPES}, got {scope!r}")

    # mcp-server: the configure wiring must be scope-aware (reference ${scope}),
    # otherwise the same recipe can't target local/project/user.
    if kind == "mcp-server" and not any("${scope}" in r for r in cfg_runs):
        errors.append(
            "kind: mcp-server requires a configure step whose 'run' references ${scope} "
            "(e.g. `claude mcp add <name> --scope ${scope} -- …`) so it wires into the chosen scope"
        )

    return errors


def _load_recipe(recipe_id: str) -> dict[str, Any]:
    safe = Path(recipe_id).name  # no path traversal
    path = RECIPES_DIR / f"{safe}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"no recipe '{recipe_id}'. Available: {', '.join(_recipe_ids()) or '(none)'}"
        )
    data = yaml.safe_load(path.read_text()) or {}
    problems = validate_recipe(data, stem=safe)
    if problems:
        bullets = "\n  - ".join(problems)
        raise ValueError(
            f"recipe '{path.name}' is malformed and was refused (fix these, or run "
            f"`uv run --script lint_recipes.py`):\n  - {bullets}"
        )
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
        "detect": _subst(recipe.get("detect", {}).get("command"), scope, project_dir) or None,
        "install": {
            "chosen_method": method.get("id") if method else None,
            "command": _subst(method.get("run"), scope, project_dir) if method else None,
            "all_methods": [
                {"id": m.get("id"), "when": m.get("when"), "run": _subst(m.get("run"), scope, project_dir)}
                for m in recipe.get("install", {}).get("methods", [])
            ],
        },
        "configure": [
            {**s, "run": _subst(s.get("run"), scope, project_dir)}
            for s in recipe.get("configure", {}).get("steps", [])
        ],
        "verify": [_subst(v.get("command"), scope, project_dir) for v in recipe.get("verify", [])],
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


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _scope_map(project_dir: str | None = None) -> dict[str, list[str]]:
    """name -> the list of scopes that configure an MCP server with that name."""
    cj = _claude_json()
    proj_root = Path(project_dir).resolve() if project_dir else Path.cwd()
    out: dict[str, list[str]] = {}

    def add(names: Any, scope: str) -> None:
        for n in names:
            out.setdefault(n, []).append(scope)

    add((cj.get("mcpServers") or {}).keys(), "user")
    local_entry = (cj.get("projects") or {}).get(str(proj_root), {})
    add((local_entry.get("mcpServers") or {}).keys(), "local")
    mcp_json = proj_root / ".mcp.json"
    if mcp_json.exists():
        try:
            add((json.loads(mcp_json.read_text()).get("mcpServers") or {}).keys(), "project")
        except Exception:  # noqa: BLE001
            pass
    return out


def _parse_mcp_list(project_dir: str | None = None) -> list[dict[str, Any]]:
    """Run `claude mcp list` (the live health check) and parse per-server status.

    Lines look like:  `name: <command> - ✔ Connected`  /  `... - ✘ Failed to connect`
    """
    res = _run("claude mcp list", cwd=project_dir, timeout=120)
    servers: list[dict[str, Any]] = []
    for raw in res["stdout"].splitlines():
        line = _ANSI.sub("", raw).strip()
        if not line or ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name, rest = name.strip(), rest.strip()
        # Classify on the STATUS tail only (everything after the last ` - `), not
        # the whole line: otherwise a command that merely contains "Failed to
        # connect" (or "✘") would mislabel a healthy server as dead. See issue #3
        # / tests/test_parse_mcp_list_edges.py.
        command, sep, status = rest.rpartition(" - ")
        if not sep:  # no ` - <status>` separator → treat the whole line as status
            command, status = "", rest
        connected = ("✔" in status) or ("Connected" in status and "Failed" not in status)
        failed = ("✘" in status) or ("Failed to connect" in status)
        if not (connected or failed):
            continue  # header / summary line, not a server status
        command = command.strip()
        servers.append({"name": name, "connected": connected and not failed, "command": command})
    return servers


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
        det_cwd = project_dir if det_spec.get("needs_project_dir") else None
        det = _run(_subst(det_spec["command"], scope, project_dir), cwd=det_cwd, timeout=30)
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
        configure_failed = False
        for step in cfg_steps:
            cwd = project_dir if step.get("needs_project_dir") else None
            if step.get("needs_project_dir") and not project_dir:
                results.append(
                    {"cmd": step.get("run"), "status": "skipped", "reason": "no project_dir supplied"}
                )
                continue
            res = _run(_subst(step["run"], scope, project_dir), cwd=cwd)
            ok = res["exit"] == 0 or step.get("optional")
            results.append({"status": "ok" if ok else "failed", **res})
            if not ok:
                configure_failed = True
        report["phases"]["configure"] = {"steps": results}
        # A required (non-optional) configure step is a prerequisite for verify to
        # be meaningful — if one fails, short-circuit like a failed install rather
        # than reporting ok on the strength of an unrelated verify.
        if configure_failed:
            report["ok"] = False
            return report

    # 4. verify (must exit 0)
    verify_results = []
    all_ok = True
    for v in recipe.get("verify", []):
        v_cwd = project_dir if v.get("needs_project_dir") else None
        res = _run(_subst(v["command"], scope, project_dir), cwd=v_cwd, timeout=30)
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


@mcp.tool
def find_dead_mcps(project_dir: str | None = None) -> dict[str, Any]:
    """
    Health-check every configured MCP server (via `claude mcp list`) and report
    which ones fail to connect — stale/dead servers that are candidates for
    removal. Each result is annotated with the scope(s) it lives in, so removal
    knows where to delete it. Read-only.
    """
    servers = _parse_mcp_list(project_dir)
    smap = _scope_map(project_dir)
    for s in servers:
        s["scopes"] = smap.get(s["name"], [])
    dead = [s for s in servers if not s["connected"]]
    return {
        "checked": len(servers),
        "alive": [s["name"] for s in servers if s["connected"]],
        "dead": dead,
        "hint": (
            "Show the user the dead servers and confirm before deleting, then call "
            "remove_mcp(name) for each one to delete."
            if dead
            else "No dead servers — everything connects."
        ),
    }


@mcp.tool
def remove_mcp(name: str, scope: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """
    Remove a configured MCP server by name (e.g. a dead one surfaced by
    `find_dead_mcps`). If `scope` is omitted, erbina resolves which scope holds
    it; pass it explicitly if the same name exists in more than one scope.

    Destructive — run `find_dead_mcps` and confirm with the user first. Set
    dry_run=true to see the exact `claude mcp remove` command without running it.
    """
    if scope is None:
        scopes = _scope_map().get(name, [])
        if not scopes:
            return {"error": f"no MCP server named '{name}' found in any scope"}
        if len(scopes) > 1:
            return {"error": f"'{name}' exists in multiple scopes {scopes}; pass `scope` explicitly"}
        scope = scopes[0]
    if scope not in VALID_SCOPES:
        return {"error": f"scope must be one of {VALID_SCOPES}"}

    cmd = f"claude mcp remove {shlex.quote(name)} -s {scope}"
    if dry_run:
        return {"would_run": cmd, "scope": scope, "note": "Dry run — nothing was removed."}
    res = _run(cmd)
    return {
        "removed": name if res["exit"] == 0 else None,
        "scope": scope,
        "status": "ok" if res["exit"] == 0 else "failed",
        **res,
    }


if __name__ == "__main__":
    mcp.run()  # stdio transport (the only way in: an MCP client / agent)
