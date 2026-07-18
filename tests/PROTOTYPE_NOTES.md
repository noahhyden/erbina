# Prototype testing harness — design & iteration log

A behavioral / red-team test harness for erbina. The idea: erbina's whole
extensibility surface is the **recipe** (`detect → install → configure →
verify`), so the "fake tool you can modify or give special properties to" is a
**prototype recipe**. We synthesize recipes with special properties (controllable
exit codes, install guards, placeholders, `optional` / `needs_project_dir`
flags), then push them through erbina's REAL code paths to surface behavioral
changes, bugs, and development possibilities.

## Pieces

- `prototype.py` — the factory. `cli_recipe()` / `mcp_recipe()` build minimal
  VALID recipes made entirely of POSIX shell builtins (`true`/`false`/`exit N`/
  `echo`), so a **live (non-dry) `bootstrap` is deterministic and side-effect
  free** — nothing installed, no network, no `claude` CLI. `registry(*recipes)`
  is a context manager that swaps `server.RECIPES_DIR` to a temp dir and restores
  it, so synthetic recipes resolve through the real MCP tool surface.
- `test_prototype_factory.py` — self-tests for the harness itself (prototypes
  validate clean; `registry()` swaps and restores; no tool-registry disturbance).
- `test_bootstrap_engine.py` — behavioral tests for the LIVE bootstrap
  orchestration (detect-gates-install, guarded/ordered install selection,
  configure skipping + `force_configure`, verify pass/fail + `optional` +
  `expect_exit`, mcp-server reload hint). This is the branchiest code in
  `server.py` and was previously only covered on dry-run paths.

## Loop discipline

- **Red-team every iteration.** Validate tests via (a) repeated + reverse-order
  runs for flakiness/pollution, and (b) **mutation testing**: temporarily break a
  product behavior, confirm the targeted test goes RED, revert. A test that stays
  green under its own mutation is a false pass and must be strengthened.
- **Fix product findings only after 1–2 validating iterations**, so we don't
  "fix" a bug that's really a bad test.

## Iteration log

### Iteration 1 (2026-07-18)
- Built the factory + registry + factory self-tests + live bootstrap-engine
  tests. +21 tests (26 → 47).
- Red-team results:
  - Flakiness/pollution: 46→47 tests, stable across 3 repeats + reverse order.
  - Mutation `detected = False` → 3 detect/configure tests RED. ✓
  - Mutation `_pick_install_method` reversed → caught only after strengthening
    `test_install_picks_earliest_among_multiple_eligible_methods` (original test
    had a single eligible method and could NOT distinguish first-vs-last; fixed).
  - Mutation verify `if not ok` (ignore `optional`) → optional-verify test RED. ✓
- Candidate findings (NOT yet fixed — pending validation next iteration): none
  confirmed yet. Stale-docs observation to revisit: `test_validate_recipe.py`
  docstring + `tests/README.md` still say `validate_recipe` "lands in PR #4 / will
  SKIP", but it's present now, so those tests run. Doc-only; low priority.

### Iteration 2 (2026-07-18)
- Added `test_parse_mcp_list_edges.py` (adversarial parser inputs) and
  `test_real_recipes.py` (real ataegina/fetch plan coverage across all scopes).
  +17 tests (47 → 63 passed, +1 xfailed).
- **CONFIRMED FINDING #1 (issue #3):** `_parse_mcp_list` misclassifies a HEALTHY
  server (✔ marker present) as dead when its command text contains the substring
  `"Failed to connect"`, because `failed` is matched against the whole line
  (command + status) instead of just the status tail. Validated three ways:
  direct probe; strict `xfail` (fails today as expected); and by applying the
  candidate fix (`status = rest.rsplit(" - ", 1)[-1]`; classify on `status`),
  which flips the xfail to XPASS **and keeps all 8 other parse tests green** —
  so the fix is correct and non-regressing.
  → **Apply this fix in iteration 3** and remove the xfail marker (the strict
  xfail will then XPASS→fail, which is the reminder to unmark).
- Red-team: stable across 3 repeats; scope-subst mutation caught by 4 real-recipe
  tests; install-order + detect + verify-optional mutations still caught.

### Iteration 3 (2026-07-18)
- **APPLIED FIX for finding #1** (issue #3): `_parse_mcp_list` now classifies on
  the status tail (`rest.rpartition(" - ")`) instead of the whole line, so a
  command containing "Failed to connect"/"✘" no longer mislabels a healthy
  server. Removed the strict xfail; replaced with two regression tests (the
  healthy-command-mentions-failed case AND the mirror dead-command-mentions-
  connected case). Existing test_helpers parser tests still green (no regression).
- Added `test_scopes.py`: `_scope_map` (3-scope aggregation, multi-scope, broken
  `.mcp.json` tolerance), `audit_scopes` (bucketing, shadowing flagged, clean
  message), `remove_mcp` (single-scope resolution + dry-run, multi-scope error,
  absent error, bad-scope error, explicit-scope-skips-resolution, shlex quoting).
  All driven by monkeypatched `_claude_json`/`_scope_map` + temp `.mcp.json`.
- Suite: 63 → 77 passed (0 xfailed now). Red-team: parse revert-to-whole-line
  caught by regression test; shlex-quote drop caught; stable across repeats.

## Backlog (future iterations)
- Placeholder/validation edge cases: `${scopee}` typos, adjacent/nested tokens,
  empty `${}`, `${scope}` used in detect/verify (not just configure).
- Property-based fuzzing of `validate_recipe` (round-trip: a mutated-invalid
  recipe must produce ≥1 error; a valid one must produce none).
- `_run` behavior: timeout path (exit 124), non-zero exit capture, output
  trimming to last 4000 chars, stderr capture.
- `bootstrap` detect `needs_project_dir` propagation (detect runs in project_dir).
- Probe: does an mcp-server recipe whose bootstrap FAILS still omit the reload
  `next` hint? (currently gated on `all_ok` — worth a test.)
