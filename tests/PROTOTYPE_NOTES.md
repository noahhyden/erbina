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

### Iteration 4 (2026-07-18)
- Added `test_placeholders.py` (`_check_placeholders` flagging + the lint↔subst
  invariant: lint-clean known tokens always fully expand), `test_validate_recipe_props.py`
  (property fuzzing: factory recipe → 0 errors; 13 single-defect corruptions each
  → ≥1 matching error; id≠stem; mcp-server needs ${scope}), and `test_run.py`
  (exit passthrough, stderr, timeout→124 no-raise, stdout 4000-char trim, cwd,
  never-raises-on-broken-cmd). Plus mcp-server-failed-bootstrap omits reload hint.
- Suite: 77 → 122 passed.
- **CANDIDATE FINDING #2 (low priority):** a dangling `${scope` (missing closing
  brace) passes the linter AND survives `_subst` untouched, so it reaches an
  executed command literally. Captured as a characterization test
  (`test_dangling_brace_is_currently_neither_flagged_nor_expanded`). Not fixed —
  revisit; if fixed, flag both an unclosed `${` in the linter.
- Red-team: two of my OWN new tests failed first (KeyError on dropped-id helper;
  a trim-test command that only emitted 2500 chars) — fixed before commit (this
  is exactly the false-negative red-teaming is meant to catch). Mutations:
  validate-always-clean (15 caught), no-stdout-trim (caught), never-flag-
  placeholder (caught). Stable across repeats incl. the wall-clock timeout test.

### Iteration 5 (2026-07-18)
- **APPLIED FIX for finding #2:** `_check_placeholders` now flags an unterminated
  `${` (missing closing brace) via `text.count("${") > len(closed tokens)`, so a
  missing-brace typo is refused at load time instead of reaching a command. Real
  recipes still lint clean (no false positives). Characterization test replaced
  with a parametrized regression test.
- Added `test_tool_surface_edges.py`: `list_recipes` skips a malformed / an
  unparseable-YAML recipe (still lists the good ones); inspect_recipe.will_run ==
  bootstrap(dry_run).plan parity across ataegina/fetch×scopes AND both prototype
  kinds; dry-run plan carries project_dir.
- Added `_claude_json` tolerance tests (missing / malformed / valid) to
  test_scopes.py.
- Suite: 122 → 137 passed. Red-team: unterminated-check-off (3 caught),
  list_recipes-no-skip (caught), _claude_json-no-tolerance (caught); stable x3.

### Iteration 6 (2026-07-18)
- Added `test_project_dir_and_phases.py`: proves `needs_project_dir` actually
  changes the cwd a phase runs in, using a marker file present only in
  project_dir (`test -f <marker>` passes iff it ran there). Covers detect /
  configure / verify running in project_dir; detect ignoring project_dir when not
  flagged; optional configure failure → ok.
- Added `audit_scopes` precedence/where-string + empty-config tests, and
  `_claude_json` tolerance (iter 5) — all in test_scopes.py.
- Suite: 137 → 147 passed. Red-team: detect-ignores-project_dir and
  verify-ignores-project_dir mutations both caught (validates the marker
  technique genuinely detects cwd — not a false pass); stable x3.
- **CANDIDATE FINDING #3 (documented, NOT fixed):** two related phase-handling
  quirks, pinned as `test_CURRENT_*` characterization tests:
  1. Asymmetry: `configure` step with `needs_project_dir` + no `project_dir` is
     SKIPPED, but `verify`/`detect` in the same situation run in CWD instead.
  2. A NON-optional (`optional: false`, the default) `configure` step that FAILS
     is recorded `"failed"` but does NOT gate `report["ok"]` — bootstrap reports
     ok=True if verify passes. Since the `optional` flag exists, a required step
     failing silently is surprising.
  → Decide next iteration. Likely fix for (2): a failed non-optional configure
     step sets `report["ok"]=False` (and probably short-circuits before verify,
     mirroring install). (1) is more of a design call — may just document it.

### Iteration 7 (2026-07-18)
- **APPLIED FIX for finding #3(2):** a failed non-optional `configure` step now
  gates `report["ok"]=False` and short-circuits before verify (mirroring a failed
  install). This aligns the code with SCHEMA.md, which already states
  "`optional: true` means a nonzero exit does not fail the bootstrap" — implying a
  non-optional step DOES. Characterization test flipped to a regression test;
  added a test that an optional failure alongside a passing required step still
  passes through to verify.
- Suite: 147 → 148 passed. Red-team: gate-reverted mutation caught; stable x2.
- Finding #3(1) (configure-skips vs verify/detect-run-in-CWD asymmetry) left as a
  documented `test_CURRENT_*` — it's a design call, not a clear bug; deferring.

### Iteration 8 (2026-07-18)
- Added `test_find_dead_mcps.py`: the last untested tool. Driven by monkeypatched
  `_parse_mcp_list` + `_scope_map` — alive/dead split, dead entries annotated with
  scope(s), orphan (not in scope map) → empty scopes, all-alive reassurance,
  dead-present hint points at remove_mcp, empty list. No product bug found (tool
  is correct).
- Added `registry()` isolation tests: nested registries restore each layer (inner
  → outer → original), empty registry, many recipes.
- Suite: 148 → 157 passed. **All 6 MCP tools now have behavioral coverage**
  (list_recipes, inspect_recipe, bootstrap, audit_scopes, find_dead_mcps,
  remove_mcp), plus every helper. Red-team: dead-filter-inverted (5 caught) and
  scope-annotation-dropped (caught); stable x2.

## Coverage summary (after iteration 8)
- Tools: all 6 (read-only + dry-run + live-bootstrap orchestration).
- Helpers: _run, _subst, _check_placeholders, validate_recipe, _load_recipe,
  _pick_install_method, _plan, _claude_json, _scope_map, _parse_mcp_list.
- 3 product bugs found & fixed (all validated ≥1 iteration first):
  #1 _parse_mcp_list whole-line status misclassification;
  #2 unterminated `${` not linted; #3(2) non-optional configure failure not gating ok.
- 1 documented design quirk deferred: #3(1) configure-skip vs verify/detect-CWD asymmetry.

### Iteration 9 (2026-07-18) — consolidation
- **Resolved #3(1) by documenting it** (design call, not a code change): added a
  `needs_project_dir`-when-no-`project_dir` table to SCHEMA.md (configure skips;
  detect/verify run in CWD). Kept the `test_CURRENT_*` characterization tests.
- Rewrote the stale `tests/README.md`: it claimed "read-only / dry_run only"
  (no longer true — live builtin bootstraps run) and that validate_recipe "lands
  in PR #4 / test SKIPS" (shipped long ago). Now lists all 15 test files + the
  prototype harness. Fixed the same stale "PR #4" wording in
  test_validate_recipe.py's docstring/skipif reason (guard kept as a safety net).
- No product logic change; 157 passed, ruff + recipe-lint clean. No mutation
  testing this round (docs/docstring only — nothing behavioral changed).

### Iteration 10 (2026-07-18) — edge hardening
- Added `test_recipe_load_edges.py`: empty / comment-only / top-level-list recipe
  files are refused (ValueError, "malformed"); `validate_recipe` rejects a
  non-mapping (None/list/str/int) with a single clear error.
- `test_bootstrap_engine.py`: an install `when:` guard pointing at a MISSING
  binary (exit 127) is treated as ineligible → falls through to the next method;
  a method with no `when` is always eligible.
- `test_scopes.py`: a name shadowed across ALL three scopes is flagged with all
  three and counted once (total_distinct == 1).
- Suite: 157 → 168 passed. No product bug found (all edges already robust).
  Red-team: guard-always-eligible (3 caught), non-mapping-swallowed (5 caught);
  stable x2.

## Status: steady state
Comprehensive coverage reached — all 6 tools + all helpers + load/validate/run
edges, 168 tests, 3 bugs fixed (all validated before fixing), 1 design quirk
documented. Remaining ideas are low-value; the loop can wind down or continue
opportunistically.

## Backlog (low value)
- A tiny CI smoke that imports the harness modules (guards against renames).
- Fuzz recipe YAML with random types per field (broader than the curated corruptions).
