# erbina tests

The automated test suite for erbina (closes #1). It exercises the server the way
an agent does — through an in-memory FastMCP client — plus unit tests for the
pure helpers and a **prototype-recipe harness** for behavioral / red-team testing.

**No test performs a real side effect.** Nothing installs, wires, or removes
anything for real, nothing hits the network, and nothing reads or writes the
host's live Claude Code config. Where a tool would shell out (`claude`, package
managers) the subprocess or config read is monkeypatched. Live `bootstrap` runs
*are* exercised, but only against prototype recipes whose every command is a
POSIX shell builtin (`true` / `false` / `exit N` / `echo`), so they are
deterministic and produce no side effects.

## Running

From the repo root:

```bash
uv run --with pytest --with fastmcp --with pyyaml --with packaging pytest tests/ -v
```

No `pyproject.toml`, lockfile, or build step — matching erbina's single-file,
PEP 723 ethos. The suite deliberately depends on **no pytest plugins**: async
interactions are written as plain sync tests that call `asyncio.run(...)`
internally (see `helpers.py`), so `pytest-asyncio` is not required.

`conftest.py` puts the repo root on `sys.path` so `import server` works
regardless of the current working directory.

## The prototype harness

`prototype.py` is the core of the behavioral suite. It treats an erbina recipe
as a "fake tool" you can give special properties to, then pushes it through the
server's real code paths:

- `cli_recipe()` / `mcp_recipe()` — build minimal VALID recipes (all shell
  builtins) that you override to introduce edge cases.
- `registry(*recipes)` — a context manager that swaps `server.RECIPES_DIR` to a
  temp dir holding the given prototypes and restores it afterward, so synthetic
  recipes resolve through the real MCP tool surface without touching `recipes/`.

Run `pytest tests/ -q --collect-only` (or read the filenames) for what is covered.
