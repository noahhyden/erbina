#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=2.0", "pyyaml>=6.0", "packaging>=23"]
# ///
"""erbina — a Claude-Code-only MCP server (reachable only via an MCP client, never by hand) that installs, wires and verifies recipe tools and audits MCP scopes."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastmcp import FastMCP
from packaging.version import InvalidVersion, Version

HERE = Path(__file__).resolve().parent
RECIPES_DIR = HERE / "recipes"
# erbina's state manifest (installs, versions, pins), its one stateful place; tests point STATE_DIR at a temp dir.
STATE_DIR = Path.home() / ".erbina"
VALID_SCOPES = ("local", "project", "user")
VALID_KINDS = ("cli-tool", "mcp-server", "profile")
# A profile installs nothing itself, only `requires` other recipes, so per-tool lifecycle keys are rejected on it.
_PROFILE_FORBIDDEN_KEYS = ("detect", "install", "configure", "verify", "version", "update", "uninstall")

# The closed set of top-level keys SCHEMA.md defines (`_path` is injected after validation, so it is excluded).
TOP_LEVEL_KEYS = frozenset(
    {"id", "kind", "title", "description", "detect", "install", "configure", "verify", "scope", "version", "update", "requires", "uninstall", "category"}
)

# recipe taxonomy: closed CATEGORIES, authored `category` wins, else `_categorize` infers it from id/title/description
CATEGORIES = (
    "search", "files", "git", "http", "network", "kubernetes", "containers",
    "cloud", "data", "database", "monitoring", "editors", "shells", "terminal",
    "docs", "languages", "build", "packaging", "media", "security", "text",
    "benchmarking", "compression", "devtools", "mcp-server", "profile", "misc",
)

# Ordered (category, keywords) rules, first hit wins; a spaced/hyphenated keyword is a substring match, a bare word a token match.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kubernetes", ("kubernetes", "k8s", "kubectl", "kubectx", "kubens",
                    "kustomize", "kubeconfig", "cluster", "clusters", "helm")),
    ("containers", ("docker", "podman", "container", "containers", "oci",
                    "buildah", "nerdctl", "containerd", "dockerfile")),
    ("cloud", ("aws", "gcp", "azure", "terraform", "terragrunt", "pulumi",
               "cloudformation", "opentofu", "serverless", "lambda", "cloud",
               "deploy", "deployment", "s3", "bucket", "cloudflare", "heroku")),
    ("security", ("secret", "secrets", "vulnerability", "vulnerabilities", "cve",
                  "encrypt", "encryption", "decrypt", "password", "passwords",
                  "credential", "credentials", "certificate", "scanner",
                  "malware", "exploit", "pentest", "leak", "leaks")),
    ("git", ("git", "commit", "commits", "rebase", "staging", "branches")),
    ("database", ("database", "databases", "sql", "postgres", "postgresql",
                  "mysql", "sqlite", "redis", "mongodb", "mongo")),
    ("compression", ("compression", "compress", "compresses", "decompress",
                     "decompresses", "gzip", "lossless", "zstd", "archive",
                     "archives", "tarball")),
    ("benchmarking", ("benchmark", "benchmarks", "benchmarking",
                      "load-testing", "load test", "stress")),
    ("security", ("fuzzer", "fuzzing", "hashing")),
    ("search", ("search", "grep", "fuzzy", "finder", "ripgrep")),
    ("http", ("http", "rest", "webhook", "http requests")),
    ("network", ("network", "networking", "dns", "ping", "tcp", "udp", "port",
                 "ports", "ssh", "vpn", "bandwidth", "netcat", "socket",
                 "latency", "traceroute", "tunnel", "download", "downloader",
                 "accelerator", "proxy")),
    ("data", ("json", "yaml", "csv", "toml", "xml", "parquet", "dataframe",
              "structured data", "html", "statistical", "stats")),
    ("media", ("image", "images", "video", "audio", "photo", "png", "jpeg",
               "gif", "ffmpeg", "exif", "graphics", "svg", "imagemagick",
               "color", "colors", "colour", "visualization", "graph", "plot")),
    ("monitoring", ("monitor", "monitoring", "htop", "processes", "metrics",
                    "observability", "disk usage", "resource usage")),
    ("editors", ("editor", "vim", "neovim", "emacs", "text editor")),
    ("shells", ("shell", "shells", "prompt", "zsh", "cross-shell")),
    ("terminal", ("terminal", "multiplexer", "tmux", "panes", "tui",
                  "terminal ui", "terminal workspace")),
    ("docs", ("documentation", "markdown", "man page", "cheatsheet",
              "cheatsheets", "tldr", "manpage")),
    ("languages", ("version manager", "runtime", "compiler", "interpreter",
                   "programming language", "language", "type checker",
                   "type-safe")),
    ("build", ("build system", "build tool", "build automation", "task runner",
               "command runner", "bundler", "bundles", "compile", "makefile")),
    ("packaging", ("package manager", "packaging", "dependency", "dependencies")),
    ("files", ("directory", "directories", "file manager", "listing", "tree",
               "du", "find", "files")),
    ("text", ("formatter", "formatting", "format", "formats", "linter",
              "linters", "linting", "lint", "style", "cut", "diff", "regex",
              "regular expression", "unicode")),
    ("devtools", ("developer", "utility", "productivity")),
)

# Single-word search terms harvested from the rules above; any found in a recipe's text become its `tags`.
_TAG_VOCAB = frozenset(
    kw for _cat, kws in _CATEGORY_RULES for kw in kws if " " not in kw and "-" not in kw
)


_URL_RE = re.compile(r"https?://\S+")


def _norm_text(recipe: dict[str, Any]) -> tuple[str, set[str]]:
    """(lowercased raw text, word-token set) from title + description, with homepage URLs stripped so "https"/"github" don't pollute category and tags."""
    parts = [str(recipe.get("title") or ""), str(recipe.get("description") or "")]
    raw = _URL_RE.sub(" ", " ".join(parts).lower())
    tokens = set(re.findall(r"[a-z0-9]+", raw))
    return raw, tokens


def _token_hit(kw: str, tokens: set[str]) -> bool:
    """Plural-tolerant word match (`certificate` matches `certificates` and vice-versa)."""
    return kw in tokens or (kw + "s") in tokens or (kw.endswith("s") and kw[:-1] in tokens)


def _infer_category(raw: str, tokens: set[str], rid: str) -> str:
    rid_l = rid.lower()
    for category, keywords in _CATEGORY_RULES:
        for kw in keywords:
            if " " in kw or "-" in kw:
                if kw in raw:
                    return category
            elif _token_hit(kw, tokens):
                return category
        # id-substring hints for buckets whose tools name themselves (lazygit -> git, k9s -> kubernetes).
        if category == "git" and "git" in rid_l:
            return category
        if category == "kubernetes" and any(h in rid_l for h in ("kube", "k9s", "k3s", "k3d")):
            return category
    return "misc"


def _categorize(recipe: dict[str, Any]) -> tuple[str, list[str]]:
    """Return (category, tags) for a recipe; total and crash-proof, an authored valid `category` wins for cli-tools, profile/mcp-server map to their own bucket, and the id is always a tag."""
    rid = str(recipe.get("id") or "")
    kind = recipe.get("kind")
    raw, tokens = _norm_text(recipe)

    if kind == "profile":
        category = "profile"
    elif kind == "mcp-server":
        category = "mcp-server"
    else:
        stored = recipe.get("category")
        category = stored if stored in CATEGORIES else _infer_category(raw, tokens, rid)

    tags = {rid, category}
    tags.update(t for t in tokens if t in _TAG_VOCAB)
    tags.discard("")
    return category, sorted(tags)
# First version-looking token in command output ("v1.2.3 (build 4)" -> "1.2.3"); a leading `v` is stripped by _extract_version.
_VERSION_RE = re.compile(r"v?(\d+\.\d+(?:\.\d+)?(?:[-.][0-9A-Za-z][0-9A-Za-z.-]*)?)")
# The only placeholders `_subst` expands (see AGENTS.d/101).
KNOWN_PLACEHOLDERS = frozenset({"scope", "project_dir"})
_PLACEHOLDER_RE = re.compile(r"\$\{([^}]*)\}")
# A verify starting with one of these only inspects the filesystem, so registry policy flags it (see AGENTS.d/102).
_FILE_INSPECT_CMDS = frozenset({"test", "[", "ls", "cat", "stat", "head", "tail", "find"})

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


# helpers
def _run(cmd: str, cwd: str | None = None, timeout: int = 600) -> dict[str, Any]:
    """Run a shell command, capturing a trimmed result. Never raises."""
    try:
        p = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout,
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
    """Expand `${scope}` (resolved local|project|user) and `${project_dir}` (supplied dir or '.') in a command string."""
    if not cmd:
        return ""
    return cmd.replace("${scope}", scope).replace("${project_dir}", project_dir or ".")


def _check_placeholders(text: Any, where: str, errors: list[str]) -> None:
    """Flag any `${...}` token (or unterminated `${`) that `_subst` would not expand, since it would reach an executed command literally."""
    if not isinstance(text, str):
        return
    for tok in _PLACEHOLDER_RE.findall(text):
        if tok not in KNOWN_PLACEHOLDERS:
            errors.append(
                f"{where}: unknown placeholder '${{{tok}}}' "
                f"(only {', '.join('${' + p + '}' for p in sorted(KNOWN_PLACEHOLDERS))} are substituted)"
            )
    # An unterminated `${` is neither expanded nor caught above, so more `${` than closed tokens means a missing-brace typo.
    if text.count("${") > len(_PLACEHOLDER_RE.findall(text)):
        errors.append(f"{where}: unterminated placeholder — a '${{' has no closing '}}'")


_GITHUB_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _latest_command(latest: Any) -> str:
    """Resolve a `version.latest` spec to a shell command printing the latest version: a string as-is, `{github: owner/repo}` to a releases-API curl grepped to the `"tag_name"` line, else ""."""
    if isinstance(latest, str):
        return latest
    if isinstance(latest, dict) and isinstance(latest.get("github"), str) and _GITHUB_REPO_RE.match(latest["github"]):
        repo = latest["github"]
        return f"curl -fsSL https://api.github.com/repos/{repo}/releases/latest | grep '\"tag_name\"'"
    return ""


def _release_notes_url(latest: Any) -> str | None:
    """The GitHub releases URL for a `{github: owner/repo}` version source, or None for a plain-string `latest`."""
    if isinstance(latest, dict) and isinstance(latest.get("github"), str) and _GITHUB_REPO_RE.match(latest["github"]):
        return f"https://github.com/{latest['github']}/releases"
    return None


_VERSION_LABEL_RE = re.compile(r"\bversion\b", re.IGNORECASE)


def _extract_version(text: str | None) -> str | None:
    """First version-looking token in command output (None if none), preferring the token after a "version" label so a build date printed earlier isn't mistaken for it."""
    if not isinstance(text, str):
        return None
    label = _VERSION_LABEL_RE.search(text)
    if label:
        m = _VERSION_RE.search(text, label.end())
        if m:
            return m.group(1)
    m = _VERSION_RE.search(text)
    return m.group(1) if m else None


def _release_core(token: str) -> str | None:
    """Leading numeric release segment of a version token (`1.2.3-git…` -> `1.2.3`), or None; salvages a comparable version from a dev/vcs suffix packaging rejects."""
    m = re.match(r"\d+(?:\.\d+)*", token)
    return m.group(0) if m else None


def _version_text(res: dict[str, Any]) -> str:
    """The stream of a version-command result that carries a version token: stdout, else stderr (see AGENTS.d/105)."""
    return res["stdout"] if _extract_version(res["stdout"]) else res["stderr"]


def _version_status(current_out: str | None, latest_out: str | None) -> dict[str, Any]:
    """Compare two raw command outputs with `packaging` and report update_available (None if either side is unresolvable); latest/current are treated asymmetrically (see AGENTS.d/100)."""
    cur, lat = _extract_version(current_out), _extract_version(latest_out)
    if cur is None or lat is None:
        return {
            "current": cur,
            "latest": lat,
            "update_available": None,
            "reason": "could not parse a version from the command output",
        }
    try:
        lv = Version(lat)
    except InvalidVersion as e:
        return {"current": cur, "latest": lat, "update_available": None, "reason": f"unparseable latest version: {e}"}
    try:
        cv = Version(cur)
    except InvalidVersion:
        core = _release_core(cur)
        if core is None:  # defensive: an extracted token always has a numeric core
            return {"current": cur, "latest": lat, "update_available": None, "reason": f"unparseable current version: {cur!r}"}
        cv = Version(core)
    return {"current": cur, "latest": lat, "update_available": lv > cv}


def _state_file() -> Path:
    return STATE_DIR / "state.json"


def _read_state() -> dict[str, Any]:
    """Read the state manifest as a well-shaped {"version": 1, "tools": {...}} dict, degrading a missing/corrupt file to empty."""
    p = _state_file()
    if not p.exists():
        return {"version": 1, "tools": {}}
    try:
        data = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return {"version": 1, "tools": {}}
    if not isinstance(data, dict) or not isinstance(data.get("tools"), dict):
        return {"version": 1, "tools": {}}
    return data


def _write_state(state: dict[str, Any]) -> None:
    """Atomically persist the state manifest (temp file + replace) so a crash mid-write can't corrupt it."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = _state_file()
    tmp = p.parent / (p.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(p)


def _record_tool(recipe_id: str, **fields: Any) -> dict[str, Any]:
    """Merge non-None fields into a tool's state record and persist it, refreshing 'updated_at' and preserving any pin."""
    state = _read_state()
    rec = state["tools"].get(recipe_id, {})
    now = datetime.now(timezone.utc).isoformat()
    rec.setdefault("installed_at", now)
    rec["updated_at"] = now
    for k, v in fields.items():
        if v is not None:
            rec[k] = v
    state["tools"][recipe_id] = rec
    _write_state(state)
    return rec


def _forget_tool(recipe_id: str) -> bool:
    """Drop a tool's state record after uninstall; True if one was removed, idempotent no-op otherwise."""
    state = _read_state()
    if recipe_id not in state["tools"]:
        return False
    del state["tools"][recipe_id]
    _write_state(state)
    return True


def _is_pinned(recipe_id: str) -> bool:
    """True if the tool is pinned in the state manifest (pins block updates)."""
    return bool(_read_state()["tools"].get(recipe_id, {}).get("pinned"))


def _validate_methods(block: Any, name: str, *, required: bool, errors: list[str]) -> None:
    """Validate a guarded-method block {methods: [{id, run, when?}]} shared by `install` (required) and `update`/`uninstall` (optional)."""
    if not isinstance(block, dict):
        # None or wrong type: required means missing/malformed, optional only needs to be a mapping.
        if required:
            errors.append(f"missing or malformed '{name}' (expected a mapping with 'methods')")
        elif block is not None:
            errors.append(f"'{name}' must be a mapping with 'methods'")
        return
    methods = block.get("methods")
    if not isinstance(methods, list) or not methods:
        suffix = "" if required else f" when '{name}' is present"
        errors.append(f"'{name}.methods' must be a non-empty list{suffix}")
        return
    for i, m in enumerate(methods):
        tag = f"{name}.methods[{i}]"
        if not isinstance(m, dict):
            errors.append(f"{tag}: must be a mapping")
            continue
        if not (isinstance(m.get("id"), str) and m["id"].strip()):
            errors.append(f"{tag}: missing non-empty 'id'")
        if not (isinstance(m.get("run"), str) and m["run"].strip()):
            errors.append(f"{tag}: missing non-empty 'run'")
        _check_placeholders(m.get("run"), f"{tag}.run", errors)
        _check_placeholders(m.get("when"), f"{tag}.when", errors)


def validate_recipe(recipe: Any, *, stem: str) -> list[str]:
    """Validate a parsed recipe against the SCHEMA.md contract and return error strings (empty means valid); the single source of truth for `_load_recipe` and lint_recipes.py."""
    errors: list[str] = []
    if not isinstance(recipe, dict):
        return [f"recipe must be a YAML mapping, got {type(recipe).__name__}"]

    # ignore the loader-injected `_path`; keys go through str() because YAML allows non-string keys and this must return errors, never crash.
    unknown = set(recipe) - TOP_LEVEL_KEYS - {"_path"}
    if unknown:
        errors.append(f"unknown top-level key(s): {', '.join(sorted(str(k) for k in unknown))}")

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
    is_profile = kind == "profile"

    # a profile MUST declare a non-empty `requires` and MUST NOT carry any per-tool lifecycle key.
    if is_profile:
        if not recipe.get("requires"):
            errors.append("kind: profile must declare a non-empty 'requires' list (the recipes it bundles)")
        present_forbidden = [k for k in _PROFILE_FORBIDDEN_KEYS if k in recipe]
        if present_forbidden:
            errors.append(
                f"kind: profile installs nothing itself, so it must not have: {', '.join(present_forbidden)}"
            )

    # detect is required (non-empty command) for an installing recipe; a profile has none.
    if not is_profile:
        detect = recipe.get("detect")
        if not isinstance(detect, dict):
            errors.append("missing or malformed 'detect' (expected a mapping with a 'command')")
        else:
            cmd = detect.get("command")
            if not (isinstance(cmd, str) and cmd.strip()):
                errors.append("'detect.command' is required and must be a non-empty string")
            _check_placeholders(detect.get("command"), "detect.command", errors)

        # install — required, methods non-empty, each method has id + run
        _validate_methods(recipe.get("install"), "install", required=True, errors=errors)

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

    # verify — required for an installing recipe; a profile has none.
    if not is_profile:
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

    # version is optional, but needs `current` + `latest` commands so check_updates can compare them.
    version = recipe.get("version")
    if version is not None:
        if not isinstance(version, dict):
            errors.append("'version' must be a mapping with 'current' and 'latest' commands")
        else:
            # current is always a shell command string
            cur = version.get("current")
            if not (isinstance(cur, str) and cur.strip()):
                errors.append("'version.current' is required and must be a non-empty string")
            _check_placeholders(cur, "version.current", errors)
    # latest is a shell command string or the structured {github: "owner/repo"} form.
            lat = version.get("latest")
            if isinstance(lat, dict):
                repo = lat.get("github")
                if set(lat) != {"github"}:
                    errors.append("'version.latest' mapping supports only the 'github' key")
                elif not (isinstance(repo, str) and _GITHUB_REPO_RE.match(repo)):
                    errors.append("'version.latest.github' must be an \"owner/repo\" string")
            elif isinstance(lat, str):
                if not lat.strip():
                    errors.append("'version.latest' is required and must be a non-empty string")
                _check_placeholders(lat, "version.latest", errors)
            else:
                errors.append("'version.latest' must be a non-empty string or a {github: \"owner/repo\"} mapping")

    # update is optional, same guarded-method shape as install; what the `update` tool runs.
    _validate_methods(recipe.get("update"), "update", required=False, errors=errors)

    # uninstall is optional, same guarded-method shape; what the `uninstall` tool runs to reverse an install.
    _validate_methods(recipe.get("uninstall"), "uninstall", required=False, errors=errors)

    # requires: only its shape and self-reference are checked here; existence and cycles are a registry-wide conformance check.
    requires = recipe.get("requires")
    if requires is not None:
        if not isinstance(requires, list) or not requires:
            errors.append("'requires' must be a non-empty list of recipe ids")
        else:
            for i, dep in enumerate(requires):
                if not (isinstance(dep, str) and dep.strip()):
                    errors.append(f"requires[{i}]: must be a non-empty recipe id string")
                elif dep == rid:
                    errors.append("'requires' must not list the recipe itself")

    # scope — optional, but if present must be a valid scope
    scope = recipe.get("scope")
    if scope is not None and scope not in VALID_SCOPES:
        errors.append(f"'scope' must be one of {VALID_SCOPES}, got {scope!r}")

    # category is optional; if present it must be a taxonomy member (else it is inferred).
    category = recipe.get("category")
    if category is not None and category not in CATEGORIES:
        errors.append(f"'category' must be one of {CATEGORIES}, got {category!r}")

    # mcp-server wiring must reference ${scope} (see AGENTS.d/101).
    if kind == "mcp-server" and not any("${scope}" in r for r in cfg_runs):
        errors.append(
            "kind: mcp-server requires a configure step whose 'run' references ${scope} "
            "(e.g. `claude mcp add <name> --scope ${scope} -- …`) so it wires into the chosen scope"
        )

    return errors


def lint_recipe_policy(recipe: Any) -> list[str]:
    """Curated-registry policy stricter than the schema (run by lint_recipes.py, not at load time); returns problem strings, empty means the recipe meets policy."""
    problems: list[str] = []
    if not isinstance(recipe, dict):
        return problems  # structural errors are validate_recipe's job
    # a curated recipe must explain itself
    for key in ("title", "description"):
        val = recipe.get(key)
        if not (isinstance(val, str) and val.strip()):
            problems.append(f"{key}: a curated recipe needs a non-empty '{key}'")
    # every install method must be guarded so it only runs where its package manager exists.
    install = recipe.get("install")
    if isinstance(install, dict) and isinstance(install.get("methods"), list):
        for i, m in enumerate(install["methods"]):
            if isinstance(m, dict) and not (isinstance(m.get("when"), str) and m["when"].strip()):
                problems.append(
                    f"install.methods[{i}] ({m.get('id')!r}): needs a `when:` guard "
                    "(curated policy — gate each method on its package manager)"
                )
    # verify honesty: a verify must RUN the tool, not just inspect the filesystem (see AGENTS.d/102).
    verify = recipe.get("verify")
    if isinstance(verify, list):
        for i, v in enumerate(verify):
            cmd = (v.get("command") or "").strip() if isinstance(v, dict) else ""
            if not cmd:
                continue
            try:
                first = shlex.split(cmd)[0]
            except ValueError:  # unbalanced quotes etc. — fall back to a rough split
                parts = cmd.split()
                first = parts[0] if parts else ""
            if first in _FILE_INSPECT_CMDS:
                problems.append(
                    f"verify[{i}]: '{first}' only inspects the filesystem — a verify should RUN "
                    "the tool (e.g. `<tool> --version`) to prove it works, not check for a file"
                )
    return problems


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


def _pick_method(methods: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The first method whose `when:` guard passes (or has none), shared by install and update."""
    for m in methods or []:
        if _guard_ok(m.get("when")):
            return m
    return None


def _pick_install_method(recipe: dict[str, Any]) -> dict[str, Any] | None:
    return _pick_method(recipe.get("install", {}).get("methods", []))


def _update_methods(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """The methods `update` will try: the recipe's `update:` block, or [] if none."""
    upd = recipe.get("update")
    return upd["methods"] if isinstance(upd, dict) and upd.get("methods") else []


def _plan(recipe: dict[str, Any], scope: str, project_dir: str | None) -> dict[str, Any]:
    """The consent surface: exactly what bootstrap would do, running nothing destructive."""
    method = _pick_install_method(recipe)
    return {
        "requires": list(recipe.get("requires") or []),
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


def _resolve_project_root(project_dir: str | None) -> Path | None:
    """Resolve `project_dir` to an absolute path, or None if unusable (NUL byte, over-long component) so read-only scope tools degrade instead of crashing."""
    try:
        return Path(project_dir).resolve() if project_dir else Path.cwd()
    except (OSError, ValueError):
        return None


def _project_mcp_names(proj_root: Path | None) -> list[str]:
    """Sorted MCP server names from `<proj_root>/.mcp.json`, returning [] on any failure (reading config is never fatal)."""
    if proj_root is None:
        return []
    mcp_json = proj_root / ".mcp.json"
    try:
        if not mcp_json.exists():
            return []
        return sorted((json.loads(mcp_json.read_text()).get("mcpServers") or {}).keys())
    except Exception:  # noqa: BLE001 - any read/parse error degrades to no project entries
        return []


def _scope_map(project_dir: str | None = None) -> dict[str, list[str]]:
    """name -> the list of scopes that configure an MCP server with that name."""
    cj = _claude_json()
    proj_root = _resolve_project_root(project_dir)
    out: dict[str, list[str]] = {}

    def add(names: Any, scope: str) -> None:
        for n in names:
            out.setdefault(n, []).append(scope)

    add((cj.get("mcpServers") or {}).keys(), "user")
    if proj_root is not None:
        local_entry = (cj.get("projects") or {}).get(str(proj_root), {})
        add((local_entry.get("mcpServers") or {}).keys(), "local")
    add(_project_mcp_names(proj_root), "project")
    return out


def _parse_mcp_list(project_dir: str | None = None) -> list[dict[str, Any]]:
    """Run `claude mcp list` (the live health check) and parse per-server status from lines like `name: <command> - ✔ Connected`."""
    res = _run("claude mcp list", cwd=project_dir, timeout=120)
    servers: list[dict[str, Any]] = []
    for raw in res["stdout"].splitlines():
        line = _ANSI.sub("", raw).strip()
        if not line or ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name, rest = name.strip(), rest.strip()
        # Classify on the status tail after the last ` - `, not the whole line (see AGENTS.d/103, issue #3).
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


# tools
def _recipe_summary(rid: str, r: dict[str, Any]) -> dict[str, Any]:
    """Compact queriable view of a recipe: identity plus authored-or-inferred `category` and `tags`."""
    category, tags = _categorize(r)
    return {
        "id": rid,
        "kind": r.get("kind", "?"),
        "title": r.get("title", rid),
        "description": r.get("description", ""),
        "category": category,
        "tags": tags,
    }


@mcp.tool
def list_recipes() -> list[dict[str, Any]]:
    """List the curated recipes erbina can bootstrap.

    Each entry carries id, kind, title, description, plus a `category` (one of the
    fixed taxonomy buckets) and `tags` (search terms) so you can tell at a glance
    what each recipe is for. To find a tool by keyword/category instead of scanning
    the whole list, use `search_recipes`.
    """
    out = []
    for rid in _recipe_ids():
        try:
            r = _load_recipe(rid)
        except Exception:  # noqa: BLE001
            continue
        out.append(_recipe_summary(rid, r))
    return out


def _search_score(query: str, summary: dict[str, Any]) -> int:
    """Relevance of a recipe to a lowercased query (id/title hit > description hit > tag hit; 0 = no match; an empty query scores every recipe 1)."""
    if not query:
        return 1
    score = 0
    rid = summary["id"].lower()
    title = str(summary["title"]).lower()
    desc = str(summary["description"]).lower()
    tags = [t.lower() for t in summary["tags"]]
    if query == rid:
        score += 100
    if query in rid:
        score += 40
    if query in title:
        score += 20
    if query in desc:
        score += 8
    if any(query == t for t in tags):
        score += 10
    elif any(query in t for t in tags):
        score += 4
    return score


@mcp.tool
def search_recipes(
    query: str = "",
    category: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Find recipes by keyword and/or filter, so you don't have to scan `list_recipes`.

    `query` is matched (case-insensitively) against each recipe's id, title,
    description and tags, and results are ranked by relevance (id/title hits beat
    description hits beat tag hits). `category` restricts to one taxonomy bucket
    (e.g. "kubernetes", "search", "http" — see `CATEGORIES`); `kind` restricts to
    cli-tool|mcp-server|profile. With no query and no filters this returns every
    recipe (like `list_recipes`) in id order. `limit` caps the returned page;
    `count` is the total number of matches before truncation.
    """
    if category is not None and category not in CATEGORIES:
        return {"error": f"category must be one of {list(CATEGORIES)}"}
    if kind is not None and kind not in VALID_KINDS:
        return {"error": f"kind must be one of {list(VALID_KINDS)}"}

    q = query.strip().lower()
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for rid in _recipe_ids():
        try:
            r = _load_recipe(rid)
        except Exception:  # noqa: BLE001
            continue
        summary = _recipe_summary(rid, r)
        if category is not None and summary["category"] != category:
            continue
        if kind is not None and summary["kind"] != kind:
            continue
        score = _search_score(q, summary)
        if score <= 0:
            continue
        summary = {**summary, "score": score}
        scored.append((score, rid, summary))

    # rank by score desc, then id asc for a stable, deterministic order
    scored.sort(key=lambda t: (-t[0], t[1]))
    results = [s for _score, _rid, s in scored]
    capped = results[: max(0, limit)] if limit is not None else results
    return {
        "query": query,
        "category": category,
        "kind": kind,
        "count": len(results),
        "results": capped,
    }


@mcp.tool
def list_categories() -> dict[str, Any]:
    """A domain map of the registry: every category that has recipes, with how
    many and a few example ids. Call this to see what erbina COVERS at a glance
    (e.g. "kubernetes: 26, languages: 40, git: 29"), then drill into one with
    `search_recipes(category=...)`. Categories partition the registry — each
    recipe has exactly one — so the counts sum to the total recipe count. Sorted
    by count (descending), then category name.
    """
    buckets: dict[str, list[str]] = {}
    for rid in _recipe_ids():
        try:
            r = _load_recipe(rid)
        except Exception:  # noqa: BLE001
            continue
        category, _tags = _categorize(r)
        buckets.setdefault(category, []).append(rid)

    rows = [
        {"category": cat, "count": len(ids), "examples": sorted(ids)[:5]}
        for cat, ids in buckets.items()
    ]
    rows.sort(key=lambda c: (-c["count"], c["category"]))
    return {"count": len(rows), "categories": rows}


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

    If the recipe declares `requires: [<id>, …]`, each prerequisite is bootstrapped
    first (idempotently, depth-first; a shared prereq runs once; a cyclic one is
    skipped) and a failed prerequisite aborts before this recipe installs. Then
    phases: detect (skip install if already present) -> install (first method whose
    `when:` guard passes) -> configure (tool-specific wiring; skipped if already
    present unless force_configure) -> verify (commands that must exit 0).

    Set dry_run=true to get the full plan (including `requires`) without executing.
    `scope` (local|project|user) targets where an mcp-server recipe is wired.
    `project_dir` is the working dir for configure steps (e.g. where
    `ataegina init` runs).
    """
    return _bootstrap_recipe(recipe_id, scope, dry_run, project_dir, force_configure, set(), ())


def _bootstrap_recipe(
    recipe_id: str,
    scope: str,
    dry_run: bool,
    project_dir: str | None,
    force_configure: bool,
    seen: set[str],
    path: tuple[str, ...],
) -> dict[str, Any]:
    """Core of `bootstrap`, recursive over `requires`: `path` is the ancestor chain (a back-edge is a cycle), `seen` is every recipe handled this call (a cross-edge is a diamond, bootstrapped once)."""
    if scope not in VALID_SCOPES:
        return {"error": f"scope must be one of {VALID_SCOPES}"}
    try:
        recipe = _load_recipe(recipe_id)
    except Exception as e:  # noqa: BLE001 - a missing/malformed prereq is a clean failure, not a crash
        return {"recipe": recipe_id, "ok": False, "error": str(e)}

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

    seen.add(recipe_id)
    here = path + (recipe_id,)

    # 0. requires — bootstrap each prerequisite (idempotently) before this recipe.
    requires = recipe.get("requires") or []
    if requires:
        req_reports: list[dict[str, Any]] = []
        for dep in requires:
            if dep in here:  # back-edge to an ancestor → cycle; stop, don't recurse
                req_reports.append({"recipe": dep, "status": "cycle", "reason": "cyclic prerequisite — skipped"})
                continue
            if dep in seen:  # already handled elsewhere in this run (diamond) → don't repeat
                req_reports.append({"recipe": dep, "status": "already-handled", "reason": "bootstrapped earlier in this run"})
                continue
            sub = _bootstrap_recipe(dep, scope, dry_run, project_dir, force_configure, seen, here)
            req_reports.append(sub)
            if not sub.get("ok", True):
                report["requires"] = req_reports
                report["ok"] = False
                report["error"] = f"prerequisite '{dep}' failed to bootstrap"
                return report
        report["requires"] = req_reports

    # A profile installs nothing itself; its `requires` (all resolved OK above) ARE the work.
    if recipe.get("kind") == "profile":
        report["ok"] = True
        report["note"] = f"Profile '{recipe_id}' bootstrapped its {len(requires)} bundled recipe(s)."
        return report

    # 1. detect (idempotency gate)
    det_spec = recipe.get("detect", {})
    detected = False
    if det_spec.get("command"):
        det, detected = _run_detect(recipe, scope, project_dir)
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
        # A failed required configure step makes verify meaningless, so short-circuit like a failed install.
        if configure_failed:
            report["ok"] = False
            return report

    # 4. verify (must exit 0)
    verify_results, all_ok = _run_verify(recipe, scope, project_dir)
    report["phases"]["verify"] = verify_results
    report["ok"] = all_ok

    # record what erbina now manages, so check_updates/update know about it later
    if all_ok:
        install_phase = report["phases"].get("install", {})
        method_id = install_phase.get("method") or ("already-present" if detected else None)
        _record_tool(
            recipe_id,
            kind=recipe.get("kind"),
            installed_version=_current_version(recipe, scope, project_dir),
            install_method=method_id,
        )
        report["recorded"] = True

    if recipe.get("kind") == "mcp-server" and all_ok:
        report["next"] = "A new MCP server was wired — reload Claude Code so it connects."
    return report


@mcp.tool
def check_updates(recipe_id: str | None = None, project_dir: str | None = None) -> dict[str, Any]:
    """
    Report whether installed tools have newer versions available — read-only.

    For each recipe that declares a `version:` block (with `current` + `latest`
    commands), erbina confirms the tool is installed (via `detect`), then runs the
    two version commands and compares them. Pass a `recipe_id` to check one tool,
    or omit it to check every recipe that supports update checks. Nothing is
    installed or changed; to apply an update, re-run `bootstrap`.
    """
    ids = [recipe_id] if recipe_id else _recipe_ids()
    checked: list[dict[str, Any]] = []
    for rid in ids:
        try:
            recipe = _load_recipe(rid)
        except Exception as e:  # noqa: BLE001
            if recipe_id:  # an explicit request should surface the load error
                return {"error": str(e)}
            continue  # bulk scan skips a recipe it can't load
        ver = recipe.get("version")
        if not ver:
            if recipe_id:
                return {"error": f"recipe '{rid}' declares no `version:` block, so updates can't be checked"}
            continue  # bulk scan only reports recipes that opted in
        scope = recipe.get("scope", "user")

        # is it installed? nothing to update if it isn't.
        det = recipe.get("detect", {})
        installed = False
        if det.get("command"):
            _d, installed = _run_detect(recipe, scope, project_dir)
        entry: dict[str, Any] = {
            "id": rid,
            "kind": recipe.get("kind"),
            "installed": installed,
            "pinned": _is_pinned(rid),
        }
        if not installed:
            entry["note"] = "not installed — run bootstrap first"
            checked.append(entry)
            continue

        v_cwd = project_dir if ver.get("needs_project_dir") else None
        cur = _run(_subst(ver["current"], scope, project_dir), cwd=v_cwd, timeout=30)
        lat = _run(_subst(_latest_command(ver["latest"]), scope, project_dir), cwd=v_cwd, timeout=60)
        entry.update(_version_status(_version_text(cur), lat["stdout"]))
        # for a github-sourced recipe, link the release notes so the update decision is informed.
        notes = _release_notes_url(ver["latest"])
        if notes:
            entry["release_notes"] = notes
        checked.append(entry)

    # a pinned tool is never offered for (automatic) update, even if newer exists
    updates = [e["id"] for e in checked if e.get("update_available") and not e.get("pinned")]
    pinned_with_update = [e["id"] for e in checked if e.get("update_available") and e.get("pinned")]
    hint = (
        f"{len(updates)} update(s) available: {', '.join(updates)}. Review, then run `update` to apply."
        if updates
        else "No updates found (tools are current, pinned, not installed, or version info unavailable)."
    )
    if pinned_with_update:
        hint += f" Pinned (skipped despite an update): {', '.join(pinned_with_update)}."
    # a terse one-liner suitable for a session banner / automatic-check surface
    summary = (
        f"erbina: {len(updates)} tool update(s) available — {', '.join(updates)}."
        if updates
        else "erbina: all tracked tools are up to date."
    )
    return {"checked": checked, "updates_available": updates, "summary": summary, "hint": hint}


def _current_version(recipe: dict[str, Any], scope: str, project_dir: str | None) -> str | None:
    """Run the recipe's version.current command and extract the token (or None)."""
    ver = recipe.get("version") or {}
    cmd = ver.get("current")
    if not cmd:
        return None
    cwd = project_dir if ver.get("needs_project_dir") else None
    res = _run(_subst(cmd, scope, project_dir), cwd=cwd, timeout=30)
    return _extract_version(_version_text(res))


def _run_detect(recipe: dict[str, Any], scope: str, project_dir: str | None) -> tuple[dict[str, Any], bool]:
    """Run the recipe's detect command; return (result, present)."""
    det = recipe.get("detect", {})
    cwd = project_dir if det.get("needs_project_dir") else None
    res = _run(_subst(det.get("command"), scope, project_dir), cwd=cwd, timeout=30)
    return res, res["exit"] == det.get("expect_exit", 0)


def _run_verify(recipe: dict[str, Any], scope: str, project_dir: str | None) -> tuple[list[dict[str, Any]], bool]:
    """Run every verify command; return (per-command results, all_required_passed)."""
    results: list[dict[str, Any]] = []
    all_ok = True
    for v in recipe.get("verify", []):
        v_cwd = project_dir if v.get("needs_project_dir") else None
        vres = _run(_subst(v["command"], scope, project_dir), cwd=v_cwd, timeout=30)
        ok = vres["exit"] == v.get("expect_exit", 0)
        if not ok and not v.get("optional"):
            all_ok = False
        results.append({"status": "ok" if ok else "failed", **vres})
    return results, all_ok


@mcp.tool
def update(
    recipe_id: str,
    scope: str = "user",
    dry_run: bool = False,
    project_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Update an already-installed tool, then re-run its `verify` as a safety net.

    Runs the recipe's `update:` methods — the first whose `when:` guard
    passes — then re-runs `verify`. If verify fails, the update is reported failed
    and flagged (the tool may be broken). Set dry_run=true to see the exact
    command without executing. Only updates a tool that is already installed; run
    `bootstrap` first otherwise. A pinned tool is refused unless force=true.
    """
    if scope not in VALID_SCOPES:
        return {"error": f"scope must be one of {VALID_SCOPES}"}
    recipe = _load_recipe(recipe_id)
    if _is_pinned(recipe_id) and not force:
        return {
            "recipe": recipe_id,
            "pinned": True,
            "skipped": True,
            "note": f"'{recipe_id}' is pinned; unpin it (pin('{recipe_id}', pinned=false)) or pass force=true to update anyway.",
        }
    methods = _update_methods(recipe)
    method = _pick_method(methods)

    if not methods:
        return {"error": f"recipe '{recipe_id}' declares no `update:` block, so erbina has no safe way to update it"}

    report: dict[str, Any] = {
        "recipe": recipe_id,
        "scope": scope,
        "dry_run": dry_run,
        "plan": {
            "update_source": "update",
            "chosen_method": method.get("id") if method else None,
            "command": _subst(method.get("run"), scope, project_dir) if method else None,
            "verify": [_subst(v.get("command"), scope, project_dir) for v in recipe.get("verify", [])],
        },
        "phases": {},
    }
    if dry_run:
        report["note"] = "Dry run — nothing executed. Review `plan`, then re-run with dry_run=false."
        return report

    # only update something that is actually installed
    det = recipe.get("detect", {})
    if det.get("command"):
        d, present = _run_detect(recipe, scope, project_dir)
        if not present:
            report["phases"]["detect"] = {"present": False, **d}
            report["ok"] = False
            report["error"] = "not installed — run bootstrap first"
            return report

    before = _current_version(recipe, scope, project_dir)

    if not method:
        report["phases"]["update"] = {
            "status": "failed",
            "reason": "no update method's `when:` guard passed on this machine",
        }
        report["ok"] = False
        return report
    res = _run(method["run"])
    report["phases"]["update"] = {"status": "ok" if res["exit"] == 0 else "failed", "method": method.get("id"), **res}
    if res["exit"] != 0:
        report["ok"] = False
        return report

    # re-run verify — the safety net that proves the updated tool still runs
    verify_results, all_ok = _run_verify(recipe, scope, project_dir)
    report["phases"]["verify"] = verify_results
    after = _current_version(recipe, scope, project_dir)
    report["version"] = {"before": before, "after": after}

    if all_ok:
        report["ok"] = True
        _record_tool(
            recipe_id,
            kind=recipe.get("kind"),
            installed_version=after,
            previous_version=before,
            update_method=method.get("id"),
        )
        report["recorded"] = True
        if before and after and before == after:
            report["note"] = f"Already at {after} — update was a no-op."
        return report

    # verify FAILED after the upgrade — mark broken and surface a manual plan.
    report["ok"] = False
    _record_tool(recipe_id, broken=True)
    report["rollback_plan"] = {
        "previous_version": before,
        "instructions": (
            f"The tool was at {before} before this update; "
            "reinstall that version manually, or run bootstrap to reinstall the latest."
            if before
            else "No recorded previous version; run bootstrap to reinstall."
        ),
    }
    report["warning"] = (
        "verify FAILED after update — the tool may be broken and is marked so in state. "
        "See rollback_plan."
    )
    return report


@mcp.tool
def uninstall(
    recipe_id: str,
    scope: str = "user",
    dry_run: bool = False,
    project_dir: str | None = None,
) -> dict[str, Any]:
    """
    Reverse a cli-tool install: run the recipe's `uninstall:` methods, confirm the
    tool is actually gone (re-run detect), and forget it in the state manifest.

    Destructive — like bootstrap, show the user the command and confirm first; set
    dry_run=true to see the exact command without running it. Only recipes that
    declare an `uninstall:` block can be removed (erbina never guesses how to delete
    a tool). For mcp-server recipes use `remove_mcp` instead. A tool that is already
    absent is reported so (and any stale state record is cleaned up).
    """
    if scope not in VALID_SCOPES:
        return {"error": f"scope must be one of {VALID_SCOPES}"}
    recipe = _load_recipe(recipe_id)
    if recipe.get("kind") == "mcp-server":
        return {"error": f"'{recipe_id}' is an mcp-server — use remove_mcp to unwire it, not uninstall"}

    methods = (recipe.get("uninstall") or {}).get("methods", [])
    if not methods:
        return {"error": f"recipe '{recipe_id}' declares no `uninstall:` block, so erbina has no safe way to remove it"}
    method = _pick_method(methods)

    report: dict[str, Any] = {
        "recipe": recipe_id,
        "scope": scope,
        "dry_run": dry_run,
        "plan": {
            "chosen_method": method.get("id") if method else None,
            "command": _subst(method.get("run"), scope, project_dir) if method else None,
        },
        "phases": {},
    }
    if dry_run:
        report["note"] = "Dry run — nothing executed. Review `plan`, then re-run with dry_run=false."
        return report

    # is it actually installed? if not, there's nothing to remove — just forget it.
    d, present = _run_detect(recipe, scope, project_dir)
    if not present:
        report["phases"]["detect"] = {"present": False, **d}
        report["ok"] = True
        report["already_absent"] = True
        report["forgotten"] = _forget_tool(recipe_id)
        report["note"] = "Not installed — nothing to remove."
        return report
    report["phases"]["detect"] = {"present": True, **d}

    if not method:
        report["phases"]["uninstall"] = {
            "status": "failed",
            "reason": "no uninstall method's `when:` guard passed on this machine",
        }
        report["ok"] = False
        return report

    res = _run(_subst(method["run"], scope, project_dir))
    report["phases"]["uninstall"] = {"status": "ok" if res["exit"] == 0 else "failed", "method": method.get("id"), **res}
    if res["exit"] != 0:
        report["ok"] = False
        return report

    # confirm removal — re-run detect; the tool should now be ABSENT.
    c, still_present = _run_detect(recipe, scope, project_dir)
    report["phases"]["confirm"] = {"present": still_present, **c}
    if still_present:
        report["ok"] = False
        report["warning"] = "uninstall ran but the tool still resolves — it may not have been fully removed."
        return report

    report["ok"] = True
    report["forgotten"] = _forget_tool(recipe_id)
    return report


@mcp.tool
def pin(recipe_id: str, pinned: bool = True) -> dict[str, Any]:
    """
    Pin (or unpin) a tool so automatic updates skip it.

    A pinned tool is flagged by `check_updates` and excluded from its
    `updates_available` list, and `update` refuses it unless called with
    force=true. Call `pin(recipe_id, pinned=false)` to unpin. Pinning is recorded
    in the state manifest and does not install or change the tool.
    """
    if recipe_id not in _recipe_ids():
        return {"error": f"no recipe '{recipe_id}'. Available: {', '.join(_recipe_ids()) or '(none)'}"}
    state = _read_state()
    rec = state["tools"].get(recipe_id, {})
    rec["pinned"] = pinned
    state["tools"][recipe_id] = rec
    _write_state(state)
    return {
        "recipe": recipe_id,
        "pinned": pinned,
        "note": (
            f"'{recipe_id}' is pinned — check_updates will flag it and update will refuse it "
            "until you unpin (pin(recipe_id, pinned=false)) or pass force=true."
            if pinned
            else f"'{recipe_id}' is unpinned — updates apply normally again."
        ),
    }


@mcp.tool
def audit_scopes(project_dir: str | None = None) -> dict[str, Any]:
    """
    Show where MCP servers are configured across Claude Code's scopes — one place
    that knows what's installed where. Reads user scope (~/.claude.json top-level),
    local scope (~/.claude.json per-project), and project scope (.mcp.json in
    project_dir or CWD). Read-only.
    """
    cj = _claude_json()
    proj_root = _resolve_project_root(project_dir)
    root_str = str(proj_root) if proj_root is not None else f"{project_dir!r} (could not be resolved)"

    user = sorted((cj.get("mcpServers") or {}).keys())

    local_entry = (cj.get("projects") or {}).get(str(proj_root), {}) if proj_root is not None else {}
    local = sorted((local_entry.get("mcpServers") or {}).keys())

    project = _project_mcp_names(proj_root)
    mcp_json_where = str(proj_root / ".mcp.json") if proj_root is not None else "(no resolvable project dir)"

    # surface the classic confusion: same server name living in more than one scope
    by_name: dict[str, list[str]] = {}
    for s, names in (("user", user), ("project", project), ("local", local)):
        for n in names:
            by_name.setdefault(n, []).append(s)
    shadowed = {n: s for n, s in by_name.items() if len(s) > 1}

    return {
        "project_root": root_str,
        "precedence": "local > project > user (highest wins; fields are not merged)",
        "scopes": {
            "user": {"where": str(Path.home() / ".claude.json") + " (top-level mcpServers)", "servers": user},
            "project": {"where": mcp_json_where + " (shared via git)", "servers": project},
            "local": {"where": str(Path.home() / ".claude.json") + f" (projects['{root_str}'].mcpServers)", "servers": local},
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
def doctor(project_dir: str | None = None) -> dict[str, Any]:
    """
    Health-check the CLI tools erbina has installed (from its state manifest):
    re-run each recorded tool's `detect` (is it still present?) and, when present,
    its `verify` (does it still run?), classifying each as healthy / missing /
    broken. Read-only — it runs only the recipe's own non-destructive
    detect/verify commands. This is the CLI-tool counterpart to `find_dead_mcps`
    (which health-checks MCP servers); mcp-server records are deferred to it.
    """
    recorded = _read_state()["tools"]
    healthy: list[str] = []
    problems: list[dict[str, Any]] = []
    checked = 0
    for rid in sorted(recorded):
        try:
            recipe = _load_recipe(rid)
        except Exception:  # noqa: BLE001 - recorded but the recipe is gone from the registry
            checked += 1
            problems.append({
                "recipe": rid, "status": "recipe-missing",
                "detail": "recorded in state but no longer in the registry — can't health-check",
            })
            continue
        if recipe.get("kind") == "mcp-server":
            continue  # an mcp-server's health is find_dead_mcps' job, not a CLI detect/verify
        checked += 1
        scope = recipe.get("scope", "user")
        _d, present = _run_detect(recipe, scope, project_dir)
        if not present:
            problems.append({
                "recipe": rid, "status": "missing",
                "detail": "recorded as installed but detect now fails — reinstall via bootstrap",
            })
            continue
        _results, ok = _run_verify(recipe, scope, project_dir)
        if ok:
            healthy.append(rid)
        else:
            problems.append({
                "recipe": rid, "status": "broken",
                "detail": "present but verify failed — the tool may be corrupted; re-run bootstrap",
            })
    hint = (
        f"{len(problems)} recorded tool(s) need attention — re-run `bootstrap` for each. "
        "For MCP servers, use find_dead_mcps."
        if problems
        else "All recorded tools are healthy."
    )
    return {"checked": checked, "healthy": healthy, "problems": problems, "hint": hint}


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


if __name__ == "__main__":  # pragma: no cover - blocking stdio entry point, not unit-testable
    mcp.run()  # stdio transport (the only way in: an MCP client / agent)
