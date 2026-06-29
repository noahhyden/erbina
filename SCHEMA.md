# erbina recipe schema (v0)

A **recipe** is a four-part contract that an agent executes to bring one tool
across the threshold into your environment: **detect → install → configure →
verify**. One YAML file per tool lives in `recipes/`. The four phases exist so
that an LLM-driven setup is *safe to re-run*: detection gates installation, and
verification proves the result actually works rather than that a config line was
written.

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

# scope this recipe targets when wiring an mcp-server (local | project | user).
# Informational for cli-tool recipes.
scope: user
```

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
