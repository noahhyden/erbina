# erbina recipe schema (v0)

A **recipe** is a four-part contract that an agent executes to bring one tool
across the threshold into your environment: **detect → install → configure →
verify**. One YAML file per tool lives in `recipes/`. The four phases exist so
that an LLM-driven setup is *safe to re-run*: detection gates installation, and
verification proves the result actually works rather than that a config line was
written.

> Validate a recipe against this contract with `uv run --script lint_recipes.py`
> (the same schema checks run at recipe load time, so `bootstrap` refuses a
> malformed recipe rather than silently skipping a phase). The linter additionally
> enforces **curated-registry policy** on top of this schema — a non-empty
> `title`/`description`, a `when:` guard on every install method, and an honest
> `verify` (it must run the tool, not just inspect the filesystem) — so a recipe
> PR fails fast; that policy is linter-only, not enforced at load time.

```yaml
id: <slug>                 # stable id; must match the filename (<id>.yaml)
kind: cli-tool             # cli-tool | mcp-server | profile
title: <human title>
description: <one paragraph; what it is and why>

# REQUIRES — optional. Other recipe ids to bootstrap FIRST (idempotently), before
# this recipe's own detect/install. Prerequisites are resolved depth-first; a
# prereq shared by several recipes is bootstrapped once per `bootstrap` call, a
# cyclic prereq is skipped, and a prerequisite that fails aborts this recipe
# before it installs. Must not list the recipe itself; every id must name a recipe
# that ships in the registry (the conformance suite enforces both).
requires: [<recipe id>, ...]

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
#    Guards also make methods CROSS-PLATFORM: a `command -v brew` guard fails
#    cleanly in Windows cmd.exe, and a `winget --version` guard fails cleanly on
#    POSIX, so brew/cargo/go and winget methods can coexist and self-select per OS.
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
#
# `latest` is either a shell command string OR the structured GitHub shorthand
# `{ github: "owner/repo" }`, which erbina expands to the releases-API call that
# prints the latest tag (`curl … /releases/latest | grep '"tag_name"'`). Prefer
# the shorthand for GitHub-released tools — it's less boilerplate and can't drift.
version:
  current: "<cmd that prints the installed version>"
  latest: { github: "owner/repo" }   # or: "<cmd that prints the latest version>"
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

# ROLLBACK — optional. If an `update`'s re-verify fails, erbina runs the first
# eligible rollback method to restore the prior version, then re-verifies. The
# `run` receives the recorded previous version in $ERBINA_ROLLBACK_VERSION (a
# normal env var — use it WITHOUT ${...} braces). Omit this block if the tool has
# no safe way to reinstall a specific version; erbina then just reports a plan.
rollback:
  methods:
    - id: <method id>
      when: "<guard command>"   # optional
      run: "<reinstall a specific version, e.g. brew install <pkg>@$ERBINA_ROLLBACK_VERSION>"

# scope this recipe targets when wiring an mcp-server (local | project | user).
# Informational for cli-tool recipes.
scope: user

# CATEGORY / TAGS — optional queriability metadata surfaced by `list_recipes` and
# `search_recipes` so an agent can find a tool by keyword/category instead of
# scanning every description. `category` must be one of the fixed taxonomy
# buckets; `tags` is a list of free-form search terms. BOTH ARE OPTIONAL — when a
# recipe omits them, erbina infers a category and tags from the recipe's own
# id/title/description, so the registry is fully searchable without every file
# hand-labelling itself. An authored `category` overrides the inference.
category: search          # one of the taxonomy buckets (see below)
tags: [grep, regex, find] # extra search terms
```

## Categories (`category`) and tags (`tags`)

Every recipe is exposed through `list_recipes` / `search_recipes` with a
`category` (exactly one of the closed taxonomy below) and a bag of `tags`
(search terms). These are **optional authored fields** — when absent, erbina
computes them from the recipe's id/title/description, so an omitted `category`
still yields a sensible bucket and an omitted `tags` still yields useful search
terms. An authored `category` (validated against the taxonomy) wins over the
computed one; `kind: profile` and `kind: mcp-server` always map to the `profile`
and `mcp-server` buckets respectively.

The taxonomy:

`search` · `files` · `git` · `http` · `network` · `kubernetes` · `containers` ·
`cloud` · `data` · `database` · `monitoring` · `editors` · `shells` ·
`terminal` · `docs` · `languages` · `build` · `packaging` · `media` ·
`security` · `text` · `benchmarking` · `compression` · `devtools` ·
`mcp-server` · `profile` · `misc`.

`search_recipes(query, category, kind, limit)` matches `query`
(case-insensitively) against id/title/description/tags and ranks results
(id/title hits outrank description hits outrank tag hits); `category`/`kind`
narrow the set; an empty query with no filters returns everything (like
`list_recipes`) in id order.

## Profiles (`kind: profile`)

A **profile** is a meta-recipe that installs nothing itself — it just declares a
`requires:` list of other recipes and lets `bootstrap` resolve the whole bundle in
one prompt. A profile has **only** `id` / `kind: profile` / `title` /
`description` / `requires` (and an optional informational `scope`); any per-tool
lifecycle key (`detect`, `install`, `configure`, `verify`, `version`, `update`,
`rollback`, `uninstall`) is rejected, and `requires` must be non-empty.

```yaml
id: modern-unix
kind: profile
title: "modern-unix — a curated set of modern CLI replacements"
description: >
  Fast, friendly replacements for the classic Unix tools.
requires: [ripgrep, fd, bat, eza, dust, zoxide]
```

Bootstrapping it bootstraps each member idempotently (a member already present is
skipped); a failing member aborts the profile.

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

The two sides are treated **asymmetrically** so that real-world `--version` output
still yields a useful answer without ever over-claiming:

- **`current`** may carry a dev/vcs suffix that `packaging` can't parse
  (`1.2.3-git20240101`, `2.0-SNAPSHOT`, `1.2.3-alpha.beta`). When it does, erbina
  falls back to the numeric **release core** (`1.2.3`, `2.0`, …) for the
  comparison, so a suffixed installed version still surfaces a genuinely newer
  release instead of hiding it.
- **`latest`** must parse cleanly. A dev/vcs-suffixed `latest` is not a release
  erbina will offer as an update, so it yields `update_available: null`.

If either side has no version token at all — or `latest` won't parse —
`update_available` is `null`, with a `reason`. erbina never claims an update it
can't justify.

## Applying updates (`update`)

`update(recipe_id, dry_run)` upgrades an already-installed tool. It runs the
recipe's `update:` methods (first passing `when:` guard wins), or the install
methods when `install.upgrade_safe: true`, then **re-runs `verify`** as the
safety net — if verify fails after the upgrade, the update is reported failed and
the tool flagged as possibly broken. `dry_run: true` shows the exact command
first (consent surface, like `bootstrap`). It refuses a tool that isn't installed
yet (run `bootstrap` first), and refuses a **pinned** tool unless `force: true`.

If the re-verify FAILS after an upgrade, erbina tries to recover: it runs the
recipe's `rollback:` method (passing the recorded previous version in
`$ERBINA_ROLLBACK_VERSION`) and re-verifies. If that restores a working tool, the
result reports `rolled_back_to`; otherwise — or when no `rollback:` is declared —
the tool is marked `broken` in the state manifest and a `rollback_plan` (the
previous version + manual instructions) is returned.

## Pinning (`pin`)

`pin(recipe_id, pinned=True)` records a pin in the state manifest.
`check_updates` still shows a pinned tool's version status but excludes it from
`updates_available`, and `update` refuses it unless `force: true`. Unpin with
`pin(recipe_id, pinned=false)`.

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
