# Changelog

All notable changes to erbina are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

erbina is a proof of concept and has not cut a tagged release yet; entries below
are reconstructed from the git history. Everything is therefore under
`[Unreleased]`.

## [Unreleased]

### Added

- **Recipes: `ripgrep` and `fd`** (`kind: cli-tool`) — Homebrew with a `cargo`
  fallback (the fd crate is `fd-find`), each with `version:` + `update:` blocks so
  they participate in `check_updates` / `update`. Plus a **recipe conformance
  test suite** that every recipe (present and future) must pass: schema-clean,
  human title + description, every install method guarded, mcp-server wiring is
  scope-aware, plans leave no unexpanded placeholder, and each versioned recipe's
  real `--version` / release-tag output is red-teamed to extract a comparable
  version.
- **Auto-updating installed tools (`check_updates`, `update`, `pin`).** A recipe
  can declare a `version:` block (installed `current` vs `latest` source) and
  optional `update:` / `rollback:` methods. `check_updates` reports what's out of
  date — comparing with [`packaging`](https://packaging.pypa.io) semantics
  (numeric / pre-release aware) and never claiming an update it can't parse.
  `update` applies the upgrade and **re-runs `verify`** as a safety net: on
  failure it rolls back to the recorded previous version (passed to a `rollback:`
  command via `$ERBINA_ROLLBACK_VERSION`) or marks the tool broken and returns a
  plan. `pin` records a pin so checks/updates skip a tool. erbina now keeps a
  small **state manifest** (`~/.erbina/state.json`) of what it manages — versions,
  install method, and pins. An **opt-in** SessionStart hook
  (`examples/erbina-session-start.sh`) or `/schedule` routine can have the agent
  run `check_updates` and surface updates for consent. See
  [AUTO_UPDATE.md](AUTO_UPDATE.md). Adds the `packaging` dependency.
- **Behavioral / red-team test harness.** `tests/prototype.py` synthesizes
  recipes from POSIX shell builtins, so a live (non-dry) `bootstrap`/`update` runs
  deterministically with no side effects — exercising the real orchestration
  engine, not just dry-run paths. Coverage now spans every tool and helper
  (version compare, `_parse_mcp_list`, scope audit, state manifest, …). Each
  behavioral test is validated by **mutation testing**. The suite grew from ~26
  to 260 tests. See [tests/README.md](tests/README.md) and
  [tests/PROTOTYPE_NOTES.md](tests/PROTOTYPE_NOTES.md).
- **Recipe schema validation + linter (`lint_recipes.py`).** A `validate_recipe`
  check (in `server.py`) enforces the [SCHEMA.md](SCHEMA.md) contract: `id` must
  equal the filename stem, `kind` is `cli-tool`|`mcp-server`, `detect.command`
  is non-empty, `install.methods` is non-empty with each method carrying `id` +
  `run`, `verify` is non-empty with each entry carrying `command`, an
  `mcp-server` recipe's configure step references `${scope}`, unknown top-level
  keys are rejected, and any unknown `${...}` placeholder (e.g. a typo'd
  `${scopee}`) is flagged before it can be shelled out literally. Recipe
  **loading** now runs the same check and raises — naming the file and listing
  every problem — so `bootstrap` / `inspect_recipe` refuse a malformed recipe
  instead of silently no-op'ing a phase under real privileges. `uv run --script
  lint_recipes.py` lints every recipe and exits non-zero on any failure.
- **Test suite + CI + release process.** A pytest suite in `tests/` drives the
  server through an in-memory FastMCP client (no network, servers, or Claude Code
  needed; subprocess/config reads are monkeypatched and live runs use shell
  builtins). A GitHub Actions workflow
  (`.github/workflows/ci.yml`) runs ruff, the suite on Linux + macOS, an import
  check on the Python 3.10 floor, and a release-verify step (recipes lint clean,
  `server.json` valid, version-tag agreement on tag builds). `RELEASE.md`
  documents cutting a versioned release and publishing to the MCP registry, and
  `main` is protected by a ruleset that requires those checks to pass on a PR.

- **Project foundation.** A single-file MCP server (`server.py`, FastMCP over
  stdio) for Claude Code that bootstraps a developer's environment from curated
  recipes. Dependencies are declared inline (PEP 723) and the server is launched
  with `uv run --script`, so registration is the entire install:
  `claude mcp add erbina --scope user -- uv run --script /abs/path/server.py`.
  It is reachable only through an MCP client (an agent) — there is no manual
  entry point — by design.
- **Recipe model: `detect → install → configure → verify`.** One declarative
  YAML per tool in `recipes/`. `detect` is the idempotency gate (skip install if
  the tool is already present); `install` tries guarded methods in order (first
  `when:` guard to pass wins); `configure` does tool-specific wiring; `verify`
  proves the tool actually *runs*, not merely that a config line was written.
  Commands support the `${scope}` and `${project_dir}` placeholders. Schema in
  [SCHEMA.md](SCHEMA.md).
- **Tools `list_recipes`, `inspect_recipe`, `bootstrap`, `audit_scopes`.**
  `inspect_recipe` and `bootstrap(dry_run=true)` are the consent surface — they
  show the exact commands that would run without executing anything.
  `audit_scopes` is a read-only report of which MCP servers are configured in
  `local` / `project` / `user` scope, where each lives, and any name shadowed
  across scopes (the "why is my config not taking effect" trap).
- **First recipe: `ataegina`** (`kind: cli-tool`) — installs the
  [ataegina](https://github.com/noahhyden/ataegina-cli) worktree launcher via
  Homebrew with a `curl | sh` fallback, then verifies it runs.
- **`kind: mcp-server` recipes with scope-aware wiring.** An `mcp-server` recipe
  wires a server into the chosen Claude Code scope via
  `claude mcp add <name> --scope ${scope} -- …`, so the same recipe targets
  `local` / `project` / `user` depending on the `scope` argument. Added the
  `fetch` recipe (the reference MCP fetch server) to exercise it end-to-end at
  project scope.
- **Tools `find_dead_mcps` + `remove_mcp`.** `find_dead_mcps` health-checks
  every configured MCP server (via `claude mcp list`), flags the ones that fail
  to connect, and annotates each with the scope it lives in. `remove_mcp`
  deletes a server by name, auto-resolving its scope (or taking an explicit one
  when a name is shadowed), with `dry_run=true` to preview the exact
  `claude mcp remove` command. Together they let an agent prune stale/dead
  servers — dogfooded by removing an abandoned, never-connecting server.
- **Release-hygiene docs:** this changelog, `SECURITY.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, and GitHub issue / pull-request templates.
