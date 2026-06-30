# Contributing

Thanks for taking a look. erbina is deliberately small: a single Python file
(`server.py`) that is an MCP server, plus a folder of declarative recipes. It
declares its own dependencies inline (PEP 723) and runs under [`uv`](https://docs.astral.sh/uv/) —
there is no venv to manage and no build step. Keep it that way.

The most useful contribution is almost always **a new recipe**, not a change to
the server. Adding a recipe is just dropping one YAML file in `recipes/`.

## Ground rules

- **The server stays a single file with inline deps.** `server.py` carries its
  dependencies in its PEP 723 header (`# /// script ... # ///`) and is launched
  with `uv run --script`. Don't introduce a `pyproject.toml`, a lockfile, or a
  packaging step — the whole point is that `claude mcp add erbina -- uv run …`
  is the entire install.
- **Consent before execution is the safety model — don't erode it.** erbina runs
  as a sibling process with real privileges, *not* inside Claude Code's Bash
  sandbox. Every code path that executes something must be reachable only after
  `inspect_recipe` / `bootstrap(dry_run=true)` could show it. Never add a tool
  that runs an install side-effect without a dry-run surface, and keep `audit_*`
  / `find_*` tools strictly read-only.
- **Recipes are declarative, not code.** A recipe is data an agent executes; it
  must not require server changes to work. If a recipe needs a new field, that
  field goes in [SCHEMA.md](SCHEMA.md) and is handled generically in the server,
  never special-cased per recipe.
- **Keep `detect` cheap and `verify` honest.** `detect` is the idempotency gate —
  it must be fast and side-effect-free. `verify` must prove the tool *runs*
  (exit 0 from actually invoking it), not merely that a config line was written.
  That honesty is erbina's entire differentiation; don't weaken it.
- **Claude Code only.** erbina targets Claude Code's `local` / `project` / `user`
  scope model and its `claude mcp` CLI. Don't add other-client abstractions —
  the narrow scope is intentional.

## Adding a recipe

1. Create `recipes/<id>.yaml` following [SCHEMA.md](SCHEMA.md). `id` must match
   the filename. Pick `kind: cli-tool` (installs a binary) or `kind: mcp-server`
   (additionally wires the server into a chosen scope via `claude mcp add
   --scope ${scope}`).
2. Make `detect` a real presence check and `verify` a real run check.
3. For a `mcp-server` recipe, set `needs_project_dir: true` on the
   detect/configure/verify steps if it targets `project` scope, so the entry
   lands in (and is read back from) the right `.mcp.json`.
4. Test it end-to-end (below) before opening a PR. Include the
   `bootstrap(dry_run=true)` plan and a real run in the PR description.

## Workflow

1. Open an issue describing the change before large PRs. New recipes don't need
   one.
2. One logical change per PR. Small is good.
3. Update [README.md](README.md) and [SCHEMA.md](SCHEMA.md) if you change a tool
   signature, the recipe schema, or the placeholder set.
4. Update [CHANGELOG.md](CHANGELOG.md) under `## [Unreleased]`.

## Testing

erbina has no network test harness — you exercise it the way an agent does, with
an in-memory FastMCP client. A minimal smoke test (no Claude Code or servers
required) looks like:

```python
# smoke.py — run with: uv run --with 'fastmcp>=2.0' --with 'pyyaml>=6.0' smoke.py
import asyncio
from fastmcp import Client
from server import mcp

async def main():
    async with Client(mcp) as c:
        print(await c.call_tool("list_recipes", {}))
        # dry_run never executes anything — safe to run anywhere
        print(await c.call_tool("bootstrap", {"recipe_id": "ataegina", "dry_run": True}))

asyncio.run(main())
```

Because `dry_run=true` and `inspect_recipe` execute nothing, they're safe to run
on any machine. For a real `bootstrap`, use a throwaway recipe target and a
`project`-scope wiring (it lives in a temp `.mcp.json` you can delete) so you
don't pollute your user-scope config. Always `claude mcp remove` anything a test
wired in.

> Scratch files matching `scratch_*.py` are git-ignored — use that prefix for
> throwaway test scripts.
