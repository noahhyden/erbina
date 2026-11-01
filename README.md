# erbina

> A Claude-Code-only MCP server that bootstraps your dev environment from one
> prompt — install, wire, and **verify** CLI tools and other MCP servers from
> curated recipes, and see where every MCP server lives across your scopes.

[![CI](https://github.com/noahhyden/erbina/actions/workflows/ci.yml/badge.svg)](https://github.com/noahhyden/erbina/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/noahhyden/erbina?sort=semver)](https://github.com/noahhyden/erbina/releases)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-server-blueviolet.svg)](https://modelcontextprotocol.io)

![An interactive Claude Code session driving erbina: one prompt inspects the httpie recipe to show the plan, then bootstraps it — installing via pipx and verifying http --version for real](docs/demo.gif)

Claude Code scatters MCP config across up to four files in two apps, with no
single place that knows what's installed where
([#27458](https://github.com/anthropics/claude-code/issues/27458),
[#8288](https://github.com/anthropics/claude-code/issues/8288),
[#5963](https://github.com/anthropics/claude-code/issues/5963)). erbina is an MCP
server an *agent* drives — there is no human entry point. Every recipe is a
contract: **detect → install → configure → verify**, idempotent by construction,
where success means the tool actually *runs*. Recipes compose (`requires:`,
`profile`s), cover the full lifecycle (`update`, `uninstall`, `doctor`), and a
weekly CI job installs a subset *for real* on macOS, Linux and Windows.

## Install

A single Python file run by [`uv`](https://docs.astral.sh/uv/) — it declares its
dependencies inline, so there's no venv to manage.

```bash
git clone https://github.com/noahhyden/erbina
# --scope user makes it available everywhere
claude mcp add erbina --scope user -- uv run --script /absolute/path/to/erbina/server.py
```

Then just ask: *"use erbina to set up ataegina"* — the agent inspects the recipe,
shows you exactly what it will run, then bootstraps and verifies it.

Needs `uv` and Claude Code, plus whatever a recipe's install method uses (`brew`,
`winget`, `cargo` / `go` / `pipx`, or a `curl` fallback). Every method is guarded,
so only one that exists on your machine ever runs.

## Safety model

erbina runs as an ordinary sibling process of Claude Code — **not** inside its
Bash sandbox — so a recipe's commands execute with your real privileges. The
safety model is **consent before execution**: `inspect_recipe` and
`bootstrap(dry_run=true)` show you the exact commands first, and the server
instructs the agent to surface that plan before any real run.

A recipe's `install.methods[].run` is a shell command string, so a malicious or
compromised recipe file is equivalent to a malicious shell script, and erbina
does not — and cannot — sandbox it. **Only bootstrap recipes you have read, from
a checkout you trust.**

erbina reads `~/.claude.json` and any project `.mcp.json` to answer "what MCP
servers are installed, and where", and shells out to `claude mcp list`. It sends
**no telemetry** and makes **no network calls of its own** — the only outbound
activity is whatever a recipe's own commands do when you bootstrap it.

Found a vulnerability? Report it privately through
[GitHub Security Advisories](https://github.com/noahhyden/erbina/security/advisories/new),
not a public issue.

## Tools

- **Discover** — `list_recipes`, `search_recipes`, `list_categories`,
  `inspect_recipe` (the consent surface: shows what would run, executes nothing)
- **Act** — `bootstrap`, `update`, `uninstall`, `pin`
- **Audit** — `check_updates`, `audit_scopes`, `find_dead_mcps`, `remove_mcp`,
  `doctor`

Each tool's own description is its documentation — the agent reads it at call
time. Everything that executes takes `dry_run=true`.

## How a recipe works

Four phases an agent executes. From
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

A `kind: mcp-server` recipe instead wires a server into a chosen scope via
`claude mcp add <name> --scope ${scope} -- …` (see
[`recipes/fetch.yaml`](recipes/fetch.yaml)); a `kind: profile` installs nothing
itself and just `requires:` a curated set. Because each `when:` guard runs in the
host shell, methods self-select per OS. Optional blocks (`requires:`, `version:`,
`update:`, `uninstall:`) and the full contract are in [SCHEMA.md](SCHEMA.md).

> [!WARNING]
> **Windows support is best-effort.** Most `winget` ids were resolved in bulk
> against the winget catalog and are only spot-checked, so one may be wrong or
> resolve to a look-alike package — verify what got installed. A bad winget
> method fails cleanly rather than breaking a POSIX bootstrap.

## Auto-updating tools

A recipe opting in with a `version:` block gets `check_updates` (compares
installed vs latest via `packaging`, never claims an update it can't parse, skips
**pinned** tools) and `update` (upgrades, then **re-runs `verify`**; on failure it
marks the tool `broken` and returns a `rollback_plan` — there is no automatic
rollback). erbina records what it manages in `~/.erbina/state.json`.

<details>
<summary>Checking automatically (opt-in)</summary>

erbina has no CLI, so nothing calls `check_updates` on a timer — the *agent* has
to. Both options below only nudge the agent; neither updates anything without
your confirmation.

**SessionStart hook.** Point one at
[`examples/erbina-session-start.sh`](examples/erbina-session-start.sh), which
prints a payload whose `additionalContext` asks the agent to run `check_updates`.
In `.claude/settings.json` (or `~/.claude/settings.json` for all projects):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          { "type": "command", "command": "bash /ABSOLUTE/PATH/TO/erbina/examples/erbina-session-start.sh" }
        ]
      }
    ]
  }
}
```

**Scheduled routine.** Or create a `/schedule` routine whose prompt asks the
agent to run `check_updates` and report the `summary` before applying anything.

</details>

## Headless / CI usage

A non-interactive `claude -p` run has no trust prompt, so load the server with
`--mcp-config` and **pre-approve** its tools with `--allowedTools` — without that
a headless call can call nothing, which is the one thing CI users trip on.

```bash
# erbina.mcp.json: { "mcpServers": { "erbina": {
#   "command": "uv", "args": ["run", "--script", "/absolute/path/to/erbina/server.py"] } } }
claude -p "use erbina to list recipes, then inspect ripgrep" \
  --mcp-config erbina.mcp.json --strict-mcp-config \
  --allowedTools mcp__erbina__list_recipes mcp__erbina__inspect_recipe
```

Add `mcp__erbina__bootstrap` to install for real. `--strict-mcp-config` makes the
run use *only* that file, never your global config.

## What this is *not*

Not a package manager you run by hand (`mcpm` / `brew` / `aqua`), not a discovery
registry (Smithery), and not reproducible provisioning (Nix / chezmoi / a
Brewfile — an LLM-driven setup is the wrong tool for that). erbina's niche is the
intersection: **agent-run, verify-on-install recipes spanning CLI tools *and* MCP
servers, aware of Claude Code's scopes.**

## Recipes

500+ live in [`recipes/`](recipes/); agents find them with `search_recipes` and
`list_categories`. Adding one — a single YAML file following
[SCHEMA.md](SCHEMA.md), with a cheap `detect` and an honest `verify` — is the most
useful contribution. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache 2.0](LICENSE). The names **erbina** and **Noah Hyden** and the project's
logos are trademarks, *not* covered by that licence — see
[TRADEMARKS.md](TRADEMARKS.md). Fork the code freely; just give your fork its own
name.
