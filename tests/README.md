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

See `PROTOTYPE_NOTES.md` for the design, the iteration log, the loop discipline
(mutation testing to catch false passes), and the running list of findings.

## What's covered

| file | covers |
|---|---|
| `test_import.py` | `import server` succeeds and does **not** start the server (`mcp.run()` stays `__main__`-guarded). |
| `test_tools.py` | The 11 expected tools register; `list_recipes` sees both real recipes; `inspect_recipe` / `bootstrap(dry_run)` return a plan and execute nothing; path-traversal ids rejected; bad `scope` rejected. |
| `test_helpers.py` | `_subst` expansion (incl. missing-`project_dir` → `.`); `_load_recipe` traversal guard; `_parse_mcp_list` on a realistic capture (monkeypatched `_run`). |
| `test_validate_recipe.py` | Both real recipes validate clean; a malformed recipe reports each seeded problem; the load path refuses a malformed recipe (temp recipes dir, never `recipes/`). |
| `test_prototype_factory.py` | Self-tests for the harness: prototypes validate clean, `registry()` swaps + restores (incl. nesting and on-exception), tool registry undisturbed. |
| `test_bootstrap_engine.py` | LIVE bootstrap orchestration: detect-gates-install, guarded/ordered install selection, configure skip + `force_configure`, verify pass/fail + `optional` + `expect_exit`, mcp-server reload hint. |
| `test_parse_mcp_list_edges.py` | Adversarial `_parse_mcp_list` inputs (commands containing `:` or ` - `, CRLF, blank/header lines, double markers) + regressions for the status-tail fix. |
| `test_real_recipes.py` | Real ataegina / fetch recipes through the dry-run plan surface, incl. `${scope}` across all scopes and `needs_project_dir` propagation. |
| `test_scopes.py` | `_scope_map`, `audit_scopes` (bucketing, shadowing, precedence/where), `remove_mcp` guardrails, `_claude_json` tolerance. |
| `test_placeholders.py` | `_check_placeholders` flagging + the lint↔subst invariant + unterminated-`${` regression. |
| `test_validate_recipe_props.py` | Property fuzzing: valid → 0 errors; single-defect corruptions each → ≥1 matching error. |
| `test_run.py` | `_run` exit passthrough, stderr, timeout→124 (no raise), stdout 4000-char trim, cwd, never-raises. |
| `test_project_dir_and_phases.py` | `needs_project_dir` actually changes the cwd a phase runs in (marker technique); phase-gating incl. non-optional configure failure. |
| `test_tool_surface_edges.py` | `list_recipes` skips malformed recipes; `inspect_recipe` ↔ `bootstrap(dry_run)` plan parity. |
| `test_find_dead_mcps.py` | Alive/dead split, scope annotation, orphan handling, hints (monkeypatched `_parse_mcp_list` + `_scope_map`). |
| `test_integration.py` | **Real end-to-end** (deterministic + offline): bootstraps a fixture tool genuinely absent → installed (a real script in a temp `$ERB_BIN` on PATH) → verified by execution; idempotent re-run; verify catches a broken install; real update v1→v2 with state recorded; **rollback recovery** of a broken update; and **mcp-server wiring** against a stub `claude` binary (`mcp add`/`get`, `${scope}`, `needs_project_dir`, idempotency). |

(Auto-update, recipe, and quality suites — `test_version`, `test_check_updates`,
`test_update`, `test_state`, `test_pin`, `test_rollback`, `test_recipes_conformance`,
`test_recipe_versions`, `test_lint_policy`, `test_readme_gallery` — round out the
coverage; run `pytest tests/ -q` for the full picture.)
