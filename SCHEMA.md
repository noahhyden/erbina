# erbina recipe schema (v0)

A **recipe** is a four-part contract that an agent executes to bring one tool
across the threshold into your environment: **detect → install → configure →
verify**. One YAML file per tool lives in `recipes/`. The four phases exist so
that an LLM-driven setup is *safe to re-run*: detection gates installation, and
verification proves the result actually works rather than that a config line was
written.

> Validate a recipe against this contract with `uv run --script lint_recipes.py`
> (the same checks run at recipe load time, so `bootstrap` refuses a malformed
> recipe rather than silently skipping a phase).

```yaml
id: <slug>                 # stable id; must match the filename (<id>.yaml)
kind: cli-tool             # cli-tool | mcp-server
title: <human title>
description: <one paragraph; what it is and why>

# 1. DETECT — the idempotency gate. Runs FIRST, every time.
#    If `command` exits with `expect_exit`, the tool is already present and the
#    install phase is skipped entirely.
detect:
  command: "<shell command>"
  expect_exit: 0           # optional, default 0
  needs_project_dir: false # optional; run the check inside project_dir (e.g. a
                           # project-scope mcp-server resolves by cwd)

# 2. INSTALL — runs only when detect failed.
#    Methods are tried in order; the FIRST whose `when:` guard exits 0 is used.
#    A guard lets a recipe prefer brew on a machine that has it and fall back to
#    curl otherwise, without ever running a package manager that isn't installed.
install:
  methods:
    - id: <method id>
      when: "<guard command>"   # optional; absent ⇒ always eligible
      run: "<install command>"

# 3. CONFIGURE — tool-specific wiring (optional).
#    For kind: mcp-server this is where you `claude mcp add` at the chosen scope.
#    `needs_project_dir: true` runs the step in the supplied project_dir and is
#    skipped (not failed) when none is given. `optional: true` means a nonzero
#    exit does not fail the bootstrap.
configure:
  steps:
    - run: "<command>"
      needs_project_dir: false   # optional
      optional: false            # optional

# 4. VERIFY — proof of success. Every command must exit `expect_exit`
#    (default 0) or the bootstrap is reported failed, unless marked optional.
verify:
  - command: "<command>"
    expect_exit: 0
    optional: false
    needs_project_dir: false   # optional; run the check inside project_dir

# VERSION — optional. Powers `check_updates`: `current` prints the installed
# version, `latest` prints the newest available (from a registry / releases API).
# erbina extracts the version token from each command's output and compares them,
# so extra text around the number is fine. Only present when a tool can be
# meaningfully version-checked.
version:
  current: "<cmd that prints the installed version>"
  latest: "<cmd that prints the latest available version>"
  needs_project_dir: false   # optional; run both commands inside project_dir

# UPDATE — optional. What the `update` tool runs to upgrade an already-installed
# tool: the same guarded/ordered method shape as install (first passing `when:`
# wins). If omitted, `update` falls back to the install methods only when
# `install.upgrade_safe: true` is set (i.e. re-running install upgrades in place).
update:
  methods:
    - id: <method id>
      when: "<guard command>"   # optional
      run: "<upgrade command>"  # e.g. brew upgrade <pkg>

# scope this recipe targets when wiring an mcp-server (local | project | user).
# Informational for cli-tool recipes.
scope: user
```

## Version checks (`check_updates`)

A recipe with a `version:` block opts into `check_updates`, which reports whether
an installed tool has a newer version available (read-only — it never installs).
For each such recipe erbina:

1. confirms the tool is installed (runs `detect`); if not, reports "not installed"
   and stops — nothing to update;
2. runs `version.current` and `version.latest` and extracts a version token from
   each (e.g. `ataegina 0.1.0` → `0.1.0`, `v1.2.3 (build 4)` → `1.2.3`);
3. compares them with [`packaging`](https://packaging.pypa.io) semantics (numeric,
   not lexical; a release outranks its pre-releases).

If either output has no parseable version, `update_available` is `null` — erbina
never claims an update it can't justify.

## Applying updates (`update`)

`update(recipe_id, dry_run)` upgrades an already-installed tool. It runs the
recipe's `update:` methods (first passing `when:` guard wins), or the install
methods when `install.upgrade_safe: true`, then **re-runs `verify`** as the
safety net — if verify fails after the upgrade, the update is reported failed and
the tool flagged as possibly broken. `dry_run: true` shows the exact command
first (consent surface, like `bootstrap`). It refuses a tool that isn't installed
yet (run `bootstrap` first).

## `needs_project_dir` when no `project_dir` is given

`needs_project_dir: true` runs a step inside the `project_dir` passed to
`bootstrap`. If that flag is set but **no `project_dir` is supplied**, the phases
behave differently on purpose:

| phase | behavior with no `project_dir` |
|---|---|
| `configure` | the step is **skipped** (not failed) — nothing is wired |
| `detect` / `verify` | the command runs in the **current directory** instead |

So a project-scoped recipe run without a `project_dir` will typically detect/
verify against the wrong directory (and fail there) while its configure step is
skipped. Always pass `project_dir` for `scope: project` recipes.

## Placeholders

Any command string (`detect`, `install.methods[].run`, `configure.steps[].run`,
`verify[].command`) may use:

| placeholder | expands to |
|---|---|
| `${scope}` | the resolved `local` \| `project` \| `user` scope passed to `bootstrap` |
| `${project_dir}` | the supplied `project_dir` (or `.` if none) |

`${scope}` is what makes a `kind: mcp-server` recipe scope-aware — its
`configure` step is typically `claude mcp add <name> --scope ${scope} -- <cmd>`,
so the same recipe wires into `local` / `project` / `user` depending on the
`scope` argument. See [`recipes/fetch.yaml`](recipes/fetch.yaml) for a worked
mcp-server example (and [`recipes/ataegina.yaml`](recipes/ataegina.yaml) for a
cli-tool). For `project` scope, set `needs_project_dir: true` on the detect /
configure / verify steps so the entry lands in (and is read back from) the
target repo's `.mcp.json`.

## Why these four phases

- **detect first** — the single most important defense against re-install
  damage from a non-deterministic agent. Mirrors `brew`'s no-op-if-installed.
- **guarded, ordered install** — express "prefer brew, else curl" declaratively
  so the agent never runs a package manager the machine lacks.
- **verify by running, not by presence** — success means the tool *runs*
  (`ataegina --version` exits 0), not that a file was written. This is the part
  every existing installer skips, and the reason they feel unreliable.
- **re-runnable** — because detect gates install and verify is side-effect-free,
  the whole recipe is safe to run again; config writes should themselves be
  check-then-write.

## Scopes (Claude Code)

| scope | stored in | shared? | precedence |
|---|---|---|---|
| `local` | `~/.claude.json` → `projects[<cwd>].mcpServers` | no (per-project, private) | highest |
| `project` | `<repo>/.mcp.json` | yes (git) | middle |
| `user` | `~/.claude.json` → top-level `mcpServers` | no (private, all projects) | lowest |

Highest scope wins outright — fields are **not** merged. `audit_scopes` reports
all three at once and flags any server name defined in more than one (the classic
"why is my config being shadowed" trap).

See [`recipes/ataegina.yaml`](recipes/ataegina.yaml) for a complete worked example.
