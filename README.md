# erbina

> A Claude-Code-only MCP server that bootstraps your dev environment from one
> prompt — install, wire, and **verify** CLI tools and other MCP servers from
> curated recipes, and see where every MCP server lives across your scopes.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-server-blueviolet.svg)](https://modelcontextprotocol.io)
[![Claude Code](https://img.shields.io/badge/client-Claude_Code-d97757.svg)](https://code.claude.com)

Named after the Lusitanian goddess of boundaries and crossings — erbina is the
threshold a tool crosses to become part of your environment. Sibling to
[ataegina](https://github.com/noahhyden/ataegina-cli) (goddess of rebirth), which
is also erbina's proof-of-concept recipe #1.

> **Status: proof of concept.** One server, four tools, one recipe. It works
> end-to-end; the registry is deliberately tiny.

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
claude mcp add erbina --scope user -- uv run /absolute/path/to/erbina/server.py
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
| `audit_scopes` | Read-only report of which MCP servers are configured in `local` / `project` / `user` scope, where each lives, and any name shadowed across scopes. |

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

The full schema — including the `local`/`project`/`user` scope model for
MCP-server recipes — is in [SCHEMA.md](SCHEMA.md).

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

## License

MIT. See [LICENSE](LICENSE).
