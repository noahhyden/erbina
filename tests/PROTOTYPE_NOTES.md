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

### Iteration 11 (2026-07-18) — resumed loop; version-parse robustness
- **Log/reality gap:** this log stalled at iteration 10 (168 tests) but the suite
  had since grown to **417 passed / 16 skipped** via later PRs (more recipes, the
  linter policy, conformance + integration + readme-gallery + version tests).
  Re-baselined here; resuming disciplined logging.
- Objective gap-finding via `--cov=server`: 95% (27 stmts uncovered, mostly
  defensive arms). Targeted the one uncovered branch that is a real *behavioral*
  path, not just a guard: `_version_status`'s `except InvalidVersion` arm
  (server.py:176-177).
- **CANDIDATE FINDING #4 (documented, NOT fixed — validate next iteration):**
  `_extract_version`'s regex (`v?(\d+\.\d+(?:\.\d+)?(?:[-.]…)?)`) is strictly
  more permissive than `packaging.Version`. It extracts tokens like
  `1.2.3-git20240101`, `2.0-SNAPSHOT`, `1.2.3-alpha.beta`, `10.20.30-rc.1.2.3`
  that `Version()` then rejects, so `check_updates` reports `update_available:
  None` with reason `"unparseable version: …"`. Safe (never a false update) but
  **lossy**: current `1.2.3-git20240101` vs latest `1.2.4` is silently NOT
  flagged, though the release core `1.2.3` is clearly older. Confirmed live
  through the tool surface (not just the helper).
- Added to `test_check_updates.py` (+5 tests, 417 → 422): a parametrized safety
  test over four packaging-illegal-but-extractable strings (covers the
  InvalidVersion arm + pins the DISTINCT `"unparseable version:"` reason vs the
  no-token `"could not parse a version"` reason), a `test_CURRENT_*`
  characterization pinning the missed-update, and a reason assertion on the
  existing no-token test.
- Red-team: **M1** InvalidVersion arm → `update_available: True` (false update):
  5 RED. **M2** collapse the two reasons into one: 4 RED (proves the distinct-
  reason assertion isn't a false pass). Revert → 14/14 green. Suite stable at
  422 across 2 repeats + new-file-first ordering; ruff + recipe-lint clean.
  → **Next iteration:** re-confirm #4, then likely fix by having `_version_status`
    fall back to the numeric release core (`re.match(r"\d+(\.\d+)*", tok)`) when
    the full token fails `Version()`, so suffixed versions still compare. Flip
    `test_CURRENT_suffixed_current_misses_a_real_update` to expect the update.

### Iteration 12 (2026-07-18) — red-teamed my OWN fix; uncovered-branch sweep
- **Pushed back on iteration 11's proposed fix and rejected it (for now).**
  Iter 11 proposed "fall back to the numeric release core on BOTH sides." Bench
  test showed that's unsafe: if `latest` is an unparseable dev build (e.g.
  `1.2.4-SNAPSHOT`), reducing it to core `1.2.4` would flag an update to a
  non-release — against erbina's "never claim an update it can't justify" ethos.
  (Also learned `1.2.4-alpha.1` already parses via packaging today, so the
  prerelease worry is narrower than feared.) → Sharpened the fix plan: fall back
  to the core for **`current` only**, and **require a clean `latest`**. Pinned
  the invariant with `test_CURRENT_unparseable_latest_is_not_claimed_as_an_update`
  so the eventual fix can't regress it. Finding #4 stays UNFIXED — now validated
  twice, ready to fix next iteration with the corrected asymmetric approach.
- **Uncovered-branch sweep** (95% → **97%**, missing 27 → 19 lines), targeting
  real behavioral paths not just guards:
  - `remove_mcp` LIVE (non-dry) exit mapping (server.py:1112-1118): +2 tests via
    a monkeypatched `_run` — success → `removed`/`ok`, nonzero exit → `removed:
    None`/`failed`. Previously only dry-run/error paths ran.
  - `check_updates` load-error split (server.py:762-765): +2 tests — an explicit
    unloadable `recipe_id` surfaces the `_load_recipe` refusal; a bulk scan skips
    it and still reports the good recipes.
- Suite 422 → **427**. Red-team: **M1** remove_mcp always-`ok` → failure test
  RED; **M2** explicit-load-error swallowed → explicit test RED; both revert
  green. Stable at 427 across 2 repeats + new-files-first ordering; ruff +
  recipe-lint clean.
- Remaining uncovered (19 lines) are near-pure defensive guards (`_run`'s BLE
  catch 104-105, validate non-mapping method arms, `_plan` unbalanced-quote
  fallback, `_recipe_ids` no-dir, `audit_scopes` broken-json 1040-1041,
  `mcp.run()` 1122). Low value; will pick off only if a behavioral angle appears.

### Iteration 13 (2026-07-18) — APPLIED FIX for finding #4 (asymmetric)
- **Fixed #4** (validated twice, iters 11–12): `_version_status` now handles the
  two sides asymmetrically. `latest` must parse cleanly (an unparseable dev build
  is never offered as an update → `None` with `"unparseable latest version:"`);
  `current` falls back to its numeric **release core** via the new `_release_core`
  helper when packaging rejects it, so `1.2.3-git20240101` compares as `1.2.3`.
  The asymmetry is the whole point — it recovers real updates without ever
  over-claiming (erbina's ethos). Confirmed live: `1.2.3-git20240101` vs `1.2.4`
  → update **True** (was silently `None`); `1.2.3` vs `1.2.4-SNAPSHOT` → `None`.
- Flipped the iter-11/12 characterization tests to assert the fixed behavior:
  parametrized `test_suffixed_current_compares_on_release_core` (5 cases incl.
  equal-core → up-to-date and higher-core → no-downgrade), a strict
  `test_unparseable_latest_is_not_claimed_as_an_update`, and a monkeypatched
  `test_uncoercible_current_degrades_gracefully` covering the defensive
  core-is-None arm (unreachable for real tokens, but reports rather than crashes).
- Updated SCHEMA.md's "Version checks" section to document the asymmetric rule.
- Suite 427 → **428**, still 97% server.py coverage (new fn region fully covered).
  Red-team (3 mutations): latest-not-strict → unparseable-latest test RED;
  drop-current-fallback → 6 RED; `>`→`>=` → equal-core + bulk tests RED; all
  revert green. Stable at 428 across 2 repeats + order variation; ruff +
  recipe-lint + byte-compile clean.

### Iteration 14 (2026-07-18) — red-teamed the #4 fix; locked its edges
- **Adversarially probed the new asymmetric version fix** against edges it might
  mishandle: local `+build` segments, epoch (`1!2.0`), `v`-prefix on both sides,
  whitespace, PEP440-parseable prereleases, and both-sides-same-dev-build. The
  fix held on every common case — **no new bug** (a validating result: red-team
  found no false pass in my own fix). Notable characterizations pinned:
  - a suffixed CURRENT compares on its release core (`1.2.3-git…` → `1.2.3`);
  - `latest` stays strict (unparseable → None), including when BOTH sides are the
    same dev build — safe by design; guidance is "make `latest` print a clean
    release" (not "up to date", but never a false update);
  - a `+build` local segment is stripped by extraction, so build-metadata-only
    differences are correctly not flagged.
- Added 15 regression tests to `test_version.py` (pure-function level, the right
  home — no duplication with the tool-level flips in `test_check_updates.py`):
  `_release_core` unit table, release-core comparison table, strict-latest table,
  both-dev-build characterization, local-segment. Suite 428 → **443**.
- Confirmed `update`'s verify→rollback orchestration (867-1013, the branchiest
  tool) is already fully covered by `test_update.py`/`test_rollback.py` — no gap.
- Red-team: `_release_core`-truncated (6 RED) and latest-non-strict (4 RED)
  mutations both caught; revert green. Stable at 443 across 2 repeats + order
  variation; ruff + recipe-lint clean.
- Backlog note (NOT worth a test): epoch (`1!x`) and non-common local segments are
  dropped by `_extract_version`; astronomically rare in real `--version` output.

### Iteration 15 (2026-07-18) — extend to REAL tools: version-output corpus
- **New surface: `_extract_version` vs authentic `--version` output.** Built a
  24-line corpus of real formats from the tools erbina installs (git, jq, ripgrep,
  go's `go1.22.0`, uv's `0.5.11 (hash date)`, eza's blurb+`v0.20.5`, bottom's
  `btm`, tealdeer's `tldr`, …) plus common runtimes. **All 24 extract correctly** —
  the regex is robust on the happy path. Captured as `test_real_version_output.py`
  (regression guard that would catch a regex change silently breaking
  `check_updates` for a whole class of tools). Suite 443 → **471**.
- **CANDIDATE FINDING #5 (characterized, NOT fixed):** "first version-looking
  token wins", so a dotted date/number appearing BEFORE the real version is
  misextracted — `Built 2024.01.15, version 2.3.4` → `2024.01.15`;
  `release 10.0 build 2.3.4` → `10.0`. Pinned with `test_CURRENT_leading_dotted_
  number_shadows_the_real_version`. **None of the 16 versioned recipes trigger it**
  (their outputs are single clean lines), so it's a latent limitation, not an
  active bug → validate 1-2 iters before deciding. A fix (prefer the token after
  "version"/"v", or skip a leading 4-digit year) is a real design call.
- Red-team of the CORPUS itself (guard against a false pass): `search`→`match`
  mutation → 27 RED (proves non-anchored extraction is exercised); a naive
  drop-patch-segment mutation PASSED but is semantically equivalent (the suffix
  group re-absorbs `.0`) — so I used a real truncation (major.minor only) → 26 RED,
  proving patch-level sensitivity. Stable at 471 across 2 repeats + ordering; ruff
  + recipe-lint clean.

### Iteration 16 (2026-07-18) — fuzzed validate_recipe; found a real crash (#6)
- **Fuzzed `validate_recipe` with a hostile-type matrix** (per-field value
  corruption + non-mapping + nested members): 576 inputs. It's the shared
  never-raise validator behind `_load_recipe` AND `lint_recipes.py`, documented to
  RETURN an error list for any input.
- **CONFIRMED FINDING #6 (pinned, fix next iteration):** a non-string TOP-LEVEL
  key — valid YAML, e.g. a recipe file starting `2024: hi` → `{2024: "hi"}` —
  crashes `validate_recipe` at `", ".join(sorted(unknown))` over the unknown-key
  set (`TypeError: sequence item 0: expected str`). Reproduced END-TO-END through
  the tool surface: `inspect_recipe`/`bootstrap`/`check_updates` (explicit load)
  surface a cryptic `ToolError` instead of a clean "unknown top-level key" refusal,
  and `lint_recipes.py` would crash in CI. `list_recipes` (bulk) survives (per-
  recipe catch). Pinned with a **strict xfail** (3 cases: int/tuple keys); the fix
  (`sorted(str(k) for k in unknown)`) will XPASS→fail and prompt marker removal.
- Added never-raise regression guards (green today): hostile field values (12
  fields), non-mapping recipe (9 types), hostile nested members (21 types) — 42
  passing assertions locking the contract for everything EXCEPT the #6 key path.
- Suite 471 → **513 passed, 3 xfailed**. Red-team: dropping a verify non-dict
  guard → 18 never-raise cases RED (proves the fuzz is sensitive, not a false
  pass); revert green. Stable across 2 repeats + ordering; ruff + recipe-lint clean.
- **Finding #5 decision (deferred as documented limitation, like #3(1)):** the
  leading-dotted-number misextraction is validated (1 iter) and NOT worth fixing —
  a heuristic (prefer token after "version"/skip a leading year) risks regressing
  the clean 24-format real corpus, and no recipe triggers it. Kept as a pinned
  `test_CURRENT_*` characterization.

### Iteration 17 (2026-07-18) — APPLIED FIX for finding #6
- **Fixed #6** (validated iter 16): `validate_recipe` coerces top-level keys
  through `str()` before `sorted(...)`/`join` (`sorted(str(k) for k in unknown)`),
  so a non-string YAML key (`2024: hi` → `{2024: "hi"}`) is reported as an
  "unknown top-level key(s): 2024" error instead of crashing with a `TypeError`.
  Note the bare form could crash TWO ways (join on non-str, and `sorted` on
  mixed-type keys) — the `str()` map fixes both.
- Verified END-TO-END: a `2024: hi` recipe file now flows through
  `inspect_recipe`/`_load_recipe` as a clean `ValueError` ("malformed and was
  refused", listing the unknown key) — the intended refusal — not a cryptic
  internal `TypeError`. The linter (`lint_recipes.py`) is likewise safe now.
- Flipped the 3 strict-xfail cases to a passing regression test (+ a mixed
  key case, + a name-appears-in-error assertion), and added a 7-case hostile
  top-level KEY fuzz guard (int/float/bool/None/tuple). Suite 513 → **525**,
  0 xfailed.
- Red-team: reverting the fix → 12 RED (the non-string/hostile-key tests);
  restore → green. Stable at 525 across 2 repeats + ordering; ruff + recipe-lint
  + byte-compile clean.

### Iteration 18 (2026-07-18) — fuzzed the TOOL entry points; found #7
- **Fuzzed every MCP tool's args** (recipe_id / scope / project_dir / name +
  pin's `pinned`) with adversarial strings — the tools should return an error
  dict, never let an exception escape to the client.
- **Two observations:**
  - `inspect_recipe`/`bootstrap`/`update` propagate a `_load_recipe` error as a
    ToolError on a bad `recipe_id` (whereas `check_updates` catches it and returns
    `{"error": …}`). Judged intentional, not a bug: fastmcp surfaces the clean,
    helpful `ValueError` message ("no recipe 'x'. Available: …") to the client.
    Documented, not flagged.
  - **CONFIRMED FINDING #7 (pinned, fix next iteration):** a pathological
    `project_dir` crashes the scope surface with a RAW exception instead of
    degrading to the user-scope map — despite that code going out of its way to
    tolerate a missing/malformed `.mcp.json`. Two vectors: an over-long path
    component → `OSError` (ENAMETOOLONG) at `mcp_json.exists()` (the `.exists()`
    sits OUTSIDE the guarding try), and an embedded NUL byte → `ValueError` at
    `Path(project_dir).resolve()`. The gap is DUPLICATED in **both** `_scope_map`
    AND `audit_scopes` (they hand-roll the same config read), so it hits
    audit_scopes/bootstrap/check_updates/remove_mcp. (A project_dir routed
    through a regular file → ENOTDIR already degrades fine; pinned as a passing
    test.)
- Pinned with strict xfails (long-path + NUL for `_scope_map`; long-path for
  `audit_scopes`). Validated by applying the candidate fix (guard `resolve()` and
  `exists()`/read with `(OSError, ValueError)`): the two `_scope_map` xfails XPASS,
  while `audit_scopes` stays red — proving the fix must touch BOTH sites, not just
  the helper. Reverted. (Note: a stale `.pyc` briefly masked the XPASS — cleared.)
- Suite 525 → **526 passed, 3 xfailed**. Stable across 2 repeats + ordering; ruff
  + recipe-lint clean.

## Status: steady state + opportunistic hardening
Comprehensive coverage reached — all 6 tools + all helpers + load/validate/run
edges, **526 tests, 97% server.py coverage**, **5 bugs/robustness findings fixed**
(all validated ≥1 iteration before fixing: #1 parse misclassification, #2
unterminated `${`, #3(2) non-optional configure gate, #4 permissive version
regex, #6 non-string top-level key crashes validate_recipe), and 2 limitations
documented/deferred (#3(1) configure-skip asymmetry, #5 leading-dotted-number
shadows the version). The loop continues opportunistically, one validated finding
at a time.

## Backlog (low value)
- A tiny CI smoke that imports the harness modules (guards against renames).
- Fuzz recipe YAML with random types per field (broader than the curated corruptions).
