# erbina

> A Claude-Code-only MCP server that bootstraps your dev environment from one
> prompt — install, wire, and **verify** CLI tools and other MCP servers from
> curated recipes, and see where every MCP server lives across your scopes.

[![CI](https://github.com/noahhyden/erbina/actions/workflows/ci.yml/badge.svg)](https://github.com/noahhyden/erbina/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/noahhyden/erbina?sort=semver)](https://github.com/noahhyden/erbina/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-server-blueviolet.svg)](https://modelcontextprotocol.io)
[![Claude Code](https://img.shields.io/badge/client-Claude_Code-d97757.svg)](https://code.claude.com)

Named after the Lusitanian goddess of boundaries and crossings — erbina is the
threshold a tool crosses to become part of your environment. Sibling to
[ataegina](https://github.com/noahhyden/ataegina-cli) (goddess of rebirth), which
is also erbina's proof-of-concept recipe #1.

> **The recipe contract is the core idea.** One server, nine tools, and a curated
> set of recipes spanning `cli-tool`s and scope-wiring `mcp-server`s (see the
> [Recipe gallery](#recipe-gallery)). Each is one YAML file held to a conformance
> bar (schema + linter policy + tests), and adding one is the point.

## Why this exists

Setting up a coding-agent environment is death by a thousand cuts: you install a
CLI, hand-edit a config, add an MCP server — then find out it's in the wrong
*scope* and isn't showing up. Claude Code spreads MCP config across **up to four
files in two apps**, with no single place that knows what's installed where
([anthropics/claude-code#27458](https://github.com/anthropics/claude-code/issues/27458),
[#8288](https://github.com/anthropics/claude-code/issues/8288),
[#5963](https://github.com/anthropics/claude-code/issues/5963)).

erbina makes setup a thing an **agent does for you, and proves worked**:

- **It's an MCP server, so an agent must drive it.** There is no human entry
  point — run it by hand and you get nothing. Nobody mistakes it for a manual
  installer that "should just work."
- **Recipes, not one-shot installs.** Each entry is a contract:
  **detect → install → configure → verify**. Idempotent by construction — it
  detects what's already there and skips it, and success means the tool *runs*,
  not that a line was written to a file.
- **Scope-aware.** It knows about Claude Code's `local` / `project` / `user`
  scopes, wires MCP-server recipes into the right one, and audits all three so
  you finally have one place that answers "what's installed, and where?"

## Install

erbina is a single Python file run by [`uv`](https://docs.astral.sh/uv/) (it
declares its own dependencies inline — no venv to manage).

```bash
git clone https://github.com/noahhyden/erbina
# register it with Claude Code (use --scope user to make it available everywhere)
claude mcp add erbina --scope user -- uv run --script /absolute/path/to/erbina/server.py
```

Then, in Claude Code, just ask: *"use erbina to set up ataegina"* — the agent
inspects the recipe, shows you exactly what it will run, then bootstraps and
verifies it.

Requirements: `uv` and Claude Code. `git` and a package manager (`brew`, or
`curl` for the fallback) for whatever a recipe installs.

## Tools

| Tool | What it does |
|---|---|
| `list_recipes` | List the curated recipes erbina can bootstrap. |
| `inspect_recipe` | Show **exactly** what bootstrapping a recipe would run — the consent surface. Nothing executes. |
| `bootstrap` | Run a recipe: detect → install → configure → verify, idempotently. `dry_run=true` returns the full plan without executing. |
| `check_updates` | Read-only report of whether installed tools have newer versions available, for recipes that declare a `version:` block. Pinned tools are flagged and excluded. |
| `update` | Upgrade an installed tool, then **re-run `verify`** as a safety net — on failure it rolls back (if the recipe supports it) or marks the tool broken. `dry_run=true` shows the command first. |
| `pin` | Pin (or unpin) a tool so automatic updates skip it. `update` refuses a pinned tool unless `force=true`. |
| `audit_scopes` | Read-only report of which MCP servers are configured in `local` / `project` / `user` scope, where each lives, and any name shadowed across scopes. |
| `find_dead_mcps` | Health-check every configured MCP server and flag the ones that fail to connect — stale/dead servers, annotated with the scope to remove them from. Read-only. |
| `remove_mcp` | Remove an MCP server by name (e.g. a dead one), auto-resolving its scope. `dry_run=true` shows the `claude mcp remove` command without running it. |

The server's instructions tell the agent to **always inspect (or dry-run) and
show you the commands before executing** — erbina shells out to package managers
with real privileges (it runs as a sibling process, not under Claude Code's Bash
sandbox), so consent before execution is the safety model.

## How a recipe works

A recipe is four phases an agent executes. The proof-of-concept entry,
[`recipes/ataegina.yaml`](recipes/ataegina.yaml):

```yaml
detect:   { command: "ataegina --version", expect_exit: 0 }   # skip install if present
install:                                                       # first guard to pass wins
  methods:
    - { id: homebrew, when: "command -v brew", run: "brew install noahhyden/tap/ataegina" }
    - { id: curl,     when: "command -v curl", run: "curl -fsSL .../install.sh | sh" }
configure: { steps: [ { run: "ataegina init --yes", needs_project_dir: true, optional: true } ] }
verify:   [ { command: "ataegina --version", expect_exit: 0 } ]
```

A `kind: mcp-server` recipe instead wires a server into a chosen scope — its
configure step is `claude mcp add <name> --scope ${scope} -- …`, where `${scope}`
is substituted from the `scope` you pass to `bootstrap`. See
[`recipes/fetch.yaml`](recipes/fetch.yaml). The full schema — including the
`local`/`project`/`user` scope model and command placeholders — is in
[SCHEMA.md](SCHEMA.md).

## Auto-updating tools

A recipe can opt into update checks by declaring a `version:` block (an installed
`current` command and a `latest` source) and, optionally, `update:` / `rollback:`
methods. Then:

- **`check_updates`** compares installed vs latest (numeric/pre-release aware, via
  `packaging`) and reports what's out of date — it never claims an update it can't
  parse, and skips **pinned** tools.
- **`update`** applies the upgrade and **re-runs `verify`**; if verify fails it
  rolls back to the recorded previous version (when the recipe declares a
  `rollback:` command) or marks the tool broken and returns a plan.
- erbina records what it manages in a small state manifest (`~/.erbina/state.json`)
  — versions, install method, and pins.

Checks are agent-driven; you can also enable an **opt-in** SessionStart hook or a
`/schedule` routine so the agent checks for you and asks before applying anything.
See [AUTO_UPDATE.md](AUTO_UPDATE.md) for the design, the `version:`/`update:`/
`rollback:` schema, and the trigger setup.

## Recipe gallery

The curated registry today. Each links to its YAML; `cli-tool`s install a binary,
`mcp-server`s wire a server into a chosen Claude Code scope. (This list is kept in
sync with `recipes/` by a test.)

**CLI tools**

- [`ataegina`](recipes/ataegina.yaml) — collision-free dev environments per git worktree
- [`bat`](recipes/bat.yaml) — a cat clone with syntax highlighting and Git integration
- [`bottom`](recipes/bottom.yaml) — a cross-platform graphical process/system monitor
- [`delta`](recipes/delta.yaml) — a syntax-highlighting pager for git, diff, and grep output
- [`dust`](recipes/dust.yaml) — a more intuitive version of du
- [`eza`](recipes/eza.yaml) — a modern, maintained replacement for ls
- [`fd`](recipes/fd.yaml) — a fast, friendly alternative to find
- [`hyperfine`](recipes/hyperfine.yaml) — a command-line benchmarking tool
- [`jq`](recipes/jq.yaml) — command-line JSON processor
- [`procs`](recipes/procs.yaml) — a modern replacement for ps
- [`ripgrep`](recipes/ripgrep.yaml) — blazing-fast recursive search
- [`sd`](recipes/sd.yaml) — intuitive find & replace (a friendlier sed)
- [`tealdeer`](recipes/tealdeer.yaml) — a very fast tldr client (simplified man pages)
- [`tokei`](recipes/tokei.yaml) — count your code, quickly
- [`uv`](recipes/uv.yaml) — an extremely fast Python package and project manager
- [`zoxide`](recipes/zoxide.yaml) — a smarter cd command that learns your habits

**MCP servers**

- [`everything`](recipes/everything.yaml) — official MCP reference/test server exercising the full protocol
- [`fetch`](recipes/fetch.yaml) — official MCP server for retrieving web content
- [`git`](recipes/git.yaml) — official MCP server for Git repository operations
- [`memory`](recipes/memory.yaml) — official MCP server for a persistent knowledge graph
- [`sequentialthinking`](recipes/sequentialthinking.yaml) — official MCP server for structured step-by-step reasoning
- [`time`](recipes/time.yaml) — official MCP server for time & timezone conversions

## Adding a recipe

Drop a `<id>.yaml` in `recipes/` following [SCHEMA.md](SCHEMA.md). `kind:
cli-tool` installs a binary; `kind: mcp-server` additionally wires it into the
chosen Claude Code scope. Keep `detect` cheap and `verify` honest (prove it
runs).

## What this is *not*

Not a package manager you run by hand (that's `mcpm` / `brew` / `aqua`), not a
discovery registry (that's Smithery), and not a way to "rebuild my laptop
deterministically" (use Nix / chezmoi / a Brewfile — an LLM-driven setup is the
wrong tool for reproducible provisioning). erbina's niche is the unclaimed
intersection: **agent-run, verify-on-install recipes that span CLI tools *and*
MCP servers, aware of Claude Code's scopes.**

## Safety model

erbina runs as an ordinary sibling process of Claude Code — **not** inside its
Bash sandbox — so a recipe's commands execute with your real privileges. The
safety model is **consent before execution**: `inspect_recipe` and
`bootstrap(dry_run=true)` show you the exact commands first, and the server
instructs the agent to surface that plan before any real run. Only bootstrap
recipes you've read. See [SECURITY.md](SECURITY.md) for the full trust model and
how to report a vulnerability.

## Contributing

The most useful contribution is usually a **new recipe** — one YAML file in
`recipes/`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the ground rules and how
to smoke-test with an in-memory FastMCP client, [SCHEMA.md](SCHEMA.md) for the
recipe contract, and [CHANGELOG.md](CHANGELOG.md) for what's landed. By
participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT. See [LICENSE](LICENSE).
