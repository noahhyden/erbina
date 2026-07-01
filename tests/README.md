# erbina tests

The first automated test suite for erbina (closes #1). It exercises the server
the way an agent does — through an in-memory FastMCP client — plus unit tests for
the pure helpers. **No test performs a real side effect**: nothing installs,
wires, or removes anything, nothing hits the network, and nothing reads the
host's live Claude Code config. Read-only/`dry_run` paths only; subprocess and
file reads are monkeypatched where a tool would otherwise shell out.

## Running

From the repo root:

```bash
uv run --with pytest --with fastmcp --with pyyaml pytest tests/ -v
```

No `pyproject.toml`, lockfile, or build step — matching erbina's single-file,
PEP 723 ethos. The suite deliberately depends on **no pytest plugins**: async
interactions are written as plain sync tests that call `asyncio.run(...)`
internally (see `helpers.py`), so `pytest-asyncio` is not required.

`conftest.py` puts the repo root on `sys.path` so `import server` works
regardless of the current working directory.

## What's covered

| file | covers |
|---|---|
| `test_import.py` | `import server` succeeds and does **not** start the server (`mcp.run()` stays `__main__`-guarded). |
| `test_tools.py` | Exactly the 6 expected tools register; `list_recipes` sees both real recipes; `inspect_recipe` / `bootstrap(dry_run=True)` return a plan and execute nothing; path-traversal recipe ids (`../server`, `../../etc/passwd`) are rejected as "no recipe"; a bad `scope` is rejected cleanly. |
| `test_helpers.py` | `_subst` placeholder expansion incl. the missing-`project_dir` → `.` fallback; `_load_recipe` traversal guard; `_parse_mcp_list` classifies a realistic `claude mcp list` capture (connected + failed + ANSI) — documenting the brittle parser (#3). Driven with a monkeypatched `_run`, never a live `claude`. |
| `test_validate_recipe.py` | Recipe-validation tests. **Skipped in full** unless `server.validate_recipe` exists (it lands in PR #4). When present: both real recipes validate clean; a malformed recipe reports each seeded problem; the load path refuses a malformed recipe (via a temp recipes dir, never `recipes/`). |

## Expected result on this branch

`validate_recipe` is not yet present on `launch-prep-ci`, so
`test_validate_recipe.py` reports as **SKIPPED** — that is correct and expected.
Everything else passes.
