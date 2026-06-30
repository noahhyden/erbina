# Security Policy

## Supported versions

erbina is a single-file MCP server with no released-version branches. Security
fixes land on `main`; please reproduce on the latest `server.py` before
reporting.

## Reporting a vulnerability

Please report security issues privately, not in a public issue:

- Preferred: open a private vulnerability report through GitHub Security
  Advisories on this repository (the "Report a vulnerability" button under the
  Security tab).
- Alternatively, email the maintainer (see the GitHub profile of the repository
  owner, `noahhyden`) with `[erbina security]` in the subject.

Please include the commit you reproduced on, your OS, your `uv` and Claude Code
versions, the recipe (or tool call) involved, and what you expected versus what
happened. We aim to acknowledge a report within a few days. Please give us a
reasonable window to ship a fix before any public disclosure.

## Trust model

erbina is a developer tool you run on your own machine. Understanding two
properties is essential before you rely on it.

### erbina executes shell commands with your real privileges

This is the single most important thing to understand. erbina is an MCP server
launched as an ordinary sibling process of Claude Code — it is **not** confined
by Claude Code's Bash tool sandbox or its permission prompts. When `bootstrap`
runs a recipe, the `detect`, `install`, `configure`, and `verify` commands run
through your shell with the same privileges as the process that launched erbina.
A recipe can therefore run arbitrary code.

The safety model is **consent before execution**, and it depends on the agent
honoring it:

- `list_recipes`, `inspect_recipe`, `audit_scopes`, and `find_dead_mcps` are
  read-only. `inspect_recipe` and `bootstrap(dry_run=true)` show you the *exact*
  commands a recipe would run, substituting placeholders, **without executing
  anything**. The server's own instructions tell the agent to surface this plan
  and get your confirmation before a real `bootstrap`.
- A real `bootstrap` (and `remove_mcp` without `dry_run`) executes. Treat the
  plan it would run the way you'd treat any `curl | sh`, `Makefile` target, or
  `package.json` script: **read it first.**

Consequently: **only bootstrap recipes you have read, from a checkout you
trust.** A recipe's `install.methods[].run` is a shell command string; a
malicious or compromised recipe file is equivalent to a malicious shell script.
erbina does not, and cannot, sandbox the commands a recipe asks it to run.

### erbina reads — but does not transmit — your Claude Code config

`audit_scopes`, `find_dead_mcps`, and `remove_mcp` read `~/.claude.json` and any
`.mcp.json` in the working project, and `find_dead_mcps` shells out to `claude
mcp list`. This is to answer "what MCP servers are installed, and where." erbina
sends **no telemetry** and makes **no network calls of its own** — the only
outbound activity is whatever a recipe's commands do (e.g. `brew install`,
`curl …`, `uvx …`) when you bootstrap it. `remove_mcp` is destructive (it runs
`claude mcp remove`); it is gated behind `find_dead_mcps` and an explicit
confirmation in the documented flow, and supports `dry_run=true` to preview the
exact command first.
