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
| **3** | state manifest (`~/.erbina/state.json`): what was installed, versions, pins, last-checked | planned |
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
