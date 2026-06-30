# Changelog

All notable changes to erbina are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

erbina is a proof of concept and has not cut a tagged release yet; entries below
are reconstructed from the git history. Everything is therefore under
`[Unreleased]`.

## [Unreleased]

### Added

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
