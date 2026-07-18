# Auto-updating installed tools — design & roadmap

erbina installs tools; this feature lets it keep them current. It builds on two
pieces erbina already has — the `verify` phase (proof a tool actually runs) and
the consent-first execution model — and adds the two it lacked: **version
awareness** and (later) **state**.

## Phases

| phase | deliverable | status |
|---|---|---|
| **0** | `version:` recipe block + version compare core | ✅ done (iter 1) |
| **1** | `check_updates` tool — read-only current-vs-latest report | ✅ done (iter 1) |
| **2** | `update(recipe_id, dry_run)` — apply update, re-run `verify` | ✅ done (iter 2); `pin`/`unpin` deferred to phase 3 |
| **3** | state manifest (`~/.erbina/state.json`): what was installed, versions, pins, last-checked | ✅ 3a manifest+recording, 3b pins, 3c rollback |
| **4** | automatic trigger — SessionStart hook or `/schedule` routine that runs `check_updates` and offers to apply | planned |

## How it works today (phases 0–1)

- A recipe opts in with a `version:` block (`current` + `latest` commands). See
  `recipes/ataegina.yaml` for a real example (installed `--version` vs GitHub
  releases API).
- `check_updates(recipe_id?, project_dir?)` runs `detect` (skip if not installed),
  then `current`/`latest`, extracts a version token from each, and compares with
  `packaging` semantics. `update_available` is `True`/`False`, or `null` when a
  version can't be parsed (never a false positive).
- Core helpers: `_extract_version`, `_version_status` in `server.py`.

## Design decisions

- **`packaging` dependency** added (was: fastmcp, pyyaml). Correct version
  ordering (numeric, pre-release, calver) is subtle enough that hand-rolling it
  is a liability. Rippled into the CI/test run commands and the two PEP 723
  headers (`server.py`, `lint_recipes.py`).
- **Extraction, not strict parsing.** `--version` output is arbitrary text, so we
  pull the first version-looking token rather than require a bare version. Safe
  because an unparseable token yields `update_available: null`.
- **Read-only by default.** `check_updates` changes nothing, matching erbina's
  consent model. Applying updates (phase 2) will go through a dry-run/consent
  surface like `bootstrap`, and re-run `verify` as the update's safety net.

## Open questions for later phases

- **Rollback**: easy for brew/pip (reinstall prior), hard for curl-script
  installs (no version history). The state manifest (phase 3) is what makes
  rollback possible.
- **Floating installs**: MCP servers run via `uvx <pkg>` already fetch latest on
  launch unless pinned — need to detect pinned vs floating before "updating."
- **Rate limits** on `latest` queries (GitHub/PyPI). Consider caching in the
  state manifest with a last-checked timestamp.

## Iteration log

### Iteration 1 (2026-07-18) — phases 0 + 1
- Prototyped version extraction + `packaging` comparison against messy real-world
  strings (calver, prereleases, `1.10` vs `1.9`, trailing junk) before building.
- Built: `version:` schema block + validation; `_extract_version` /
  `_version_status`; the `check_updates` tool; a real `version:` block on
  ataegina. Updated SCHEMA.md, CI (+`--with packaging`, tool count 6→7), and the
  6→7 tool-count test.
- Tests: +36 (168 → 204). `test_version.py` (extraction + compare, incl.
  never-false-positive), `test_check_updates.py` (update/current/not-installed/
  no-version-block/bulk/unparseable), version-block validation cases.
- End-to-end: `check_updates(ataegina)` on the real recipe correctly reports
  "not installed" here (ataegina absent) without a bogus compare.
- Red-team: mutations caught — comparison inverted (7), always-installed (1),
  extract-returns-whole-text (4); no flakiness across repeats.

### Iteration 2 (2026-07-18) — phase 2 (`update` tool)
- Built the `update(recipe_id, scope, dry_run, project_dir)` tool: resolves an
  update method (explicit `update:` block, else install methods when
  `install.upgrade_safe: true`), requires the tool to be installed (runs
  `detect`), runs the chosen method, then **re-runs `verify` as the safety net**
  (verify failure → ok=False + a "may be broken" warning). Reports version
  before/after and flags a no-op when unchanged. Dry-run returns the plan only.
- Schema: optional `update:` block (guarded methods, like install) +
  `install.upgrade_safe`; validated; documented in SCHEMA.md. Real `update:`
  block added to the ataegina recipe (brew upgrade / re-run install script).
- Refactor: shared `_pick_method(methods)` used by both install and update.
- Tool count 7 → 8 (test + python-floor updated).
- Tests: +18 (204 → 222). test_update.py (dry-run/plan, no-update-path,
  upgrade_safe fallback, not-installed refusal, happy path + verify safety net,
  verify-fail-flags-broken, command-failure short-circuit, method selection,
  version before/after via a tmp version file, no-op note) + update-block
  validation cases.
- End-to-end: dry-run shows the plan; a live update bumped a fake tool 1.0.0 →
  1.1.0 with verify passing.
- Red-team: mutations caught — verify-no-longer-gates-ok, always-fallback-to-
  install; no flakiness across repeats.

### Iteration 3a (2026-07-18) — state manifest core + recording
- erbina is now stateful: `~/.erbina/state.json` (overridable via `server.STATE_DIR`).
  Schema `{"version": 1, "tools": {<id>: {kind, installed_version, install_method,
  update_method, previous_version, installed_at, updated_at, pinned?}}}`.
- Helpers: `_read_state` (tolerates missing/malformed/wrong-shape → default),
  `_write_state` (atomic: temp file + `os.replace`), `_record_tool` (merges
  non-None fields, sets timestamps, keeps first `installed_at`, PRESERVES unrelated
  fields like a future pin).
- Wiring: `bootstrap` records on success (kind, install_method, version if the
  recipe has a version block); `update` records before/after + update_method.
  Both add `recorded: true` to their report. Failures and dry-runs never record.
- **Test isolation**: an autouse `_isolate_erbina_state` fixture (conftest.py)
  redirects STATE_DIR to a temp dir for EVERY test — no test touches real ~/.erbina.
- Tests: +15 (222 → 237). Red-team: mutations caught — record-None (1),
  drop-existing-record (2), bootstrap-skip-recording (2); no flakiness or
  cross-test state pollution (verified reverse-order too).
- Deferred to 3b/3c: a `pin` tool + honoring pins in check_updates/update;
  rollback using `previous_version`. `_record_tool` already preserves pins, so 3b
  is a small addition.

### Iteration 3b (2026-07-18) — pinning
- New `pin(recipe_id, pinned=True)` tool: sets the pinned flag in the state
  manifest (direct write, no timestamps — pinning isn't an install event), errors
  on an unknown recipe. `_is_pinned` helper reads it.
- `check_updates` now annotates each entry with `pinned` and EXCLUDES pinned tools
  from `updates_available` (still shows their version status for transparency; the
  hint calls out "Pinned (skipped despite an update)").
- `update` gained `force: bool = False`; it refuses a pinned tool (returns
  skipped + note) unless force=true.
- Tool count 8 → 9 (test + python-floor updated).
- Tests: +10 (237 → 246). test_pin.py covers set/clear, unknown-recipe error,
  pin-doesn't-clobber-record, check_updates exclude/include, update refuse/force/
  unpinned. Red-team: mutations caught — check_updates-ignores-pins (1), update-
  pin-logic-inverted (2); no flakiness.

### Iteration 3c (2026-07-18) — rollback
- On a post-update verify failure, `update` now tries to recover: it runs the
  recipe's `rollback:` method (first eligible), passing the recorded previous
  version via the `$ERBINA_ROLLBACK_VERSION` env var, then re-verifies. If that
  restores a working tool → `rolled_back_to` + state records the restored version;
  otherwise → the tool is marked `broken: true` in state. With no `rollback:`
  block → a `rollback_plan` (previous version + manual instructions) is returned
  and the tool marked broken. A failed update *command* (upgrade never ran) is
  NOT marked broken.
- Env injection (not a placeholder): `_run` gained an `env` param; the rollback
  command reads `$ERBINA_ROLLBACK_VERSION`. Prototyped first — confirmed the
  inline `VAR=x cmd` form does NOT work (parent shell expands before setting), so
  it's passed via the child process environment.
- Schema: optional `rollback:` block (guarded methods) + validation; documented
  in SCHEMA.md. Shared `_run_verify` helper now backs update's verify + re-verify.
- Tests: +11 (246 → 258). test_rollback.py (no-rollback plan+broken, auto-rollback
  recovers, env-var delivery, rollback-command-fails→broken, AND
  rollback-command-succeeds-but-verify-still-fails→broken) + rollback validation.
- **Red-team found a real test gap**: the mutation `recovered = rb_res exit==0`
  (dropping the `and rb_ok` re-verify check) initially SURVIVED — no test covered
  "rollback command exits 0 but doesn't fix the tool." Added that test; mutation
  now caught. Also caught: drop-env-injection (2). No flakiness.
- Note: ataegina has no safe versioned reinstall (brew/curl install latest), so it
  ships WITHOUT a rollback block — it uses the plan+broken path by design.
