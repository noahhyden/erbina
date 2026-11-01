# Changelog

All notable changes to erbina are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Relicensed from MIT to Apache License 2.0** (`LICENSE`), with a trademark
  reservation in a new `NOTICE` file: the name *erbina*, the name *Noah Hyden*,
  and the project's logos are not licensed under it. The code is as free to fork
  as before — a fork simply needs its own name. Sole copyright holder, so no
  third-party consent was required, and releases published before the move keep
  the MIT terms they shipped under. `TRADEMARKS.md` spells out what is fine
  without asking (nominative use, forking) and what needs permission (branding a
  product, implying endorsement).

### Removed

- `CODE_OF_CONDUCT.md` and `SECURITY.md`. The substantive half of the latter —
  that erbina runs *outside* Claude Code's Bash sandbox with your real
  privileges, that a recipe is equivalent to a shell script, and that erbina
  sends no telemetry and makes no network calls of its own — moved into the
  README's **Safety model** section. Private vulnerability reporting is
  unaffected: the issue-template config already routes it to GitHub Security
  Advisories.

### Added

- **Broad `winget` coverage — 207 recipes now install on Windows** (up from 13).
  A new harvester (`scripts/winget_candidates.py` + a `winget-ingest` CI workflow)
  downloads the winget *community source* index (the SQLite catalog the `winget`
  CLI uses) and resolves a `winget` PackageIdentifier for each `recipe_data.py` row
  that lacked one, tiered by trust — `high` (id is the row's `gh` owner/repo exactly,
  or a command/moniker match whose publisher equals the GitHub owner), `medium` (a
  unique installed-command match), `low` (moniker-only). 194 ids were applied across
  all tiers and the recipes regenerated. It installs nothing and uses stdlib only,
  so it runs anywhere; the default emits `winget_proposals.json` for review, and
  `--apply` stages the keys into `recipe_data.py` as a reviewable diff.

### Notes

- **Windows support is limited and error-prone.** The bulk-resolved winget ids are
  only spot-checked — some may be wrong, stale, or resolve to a look-alike package,
  so a `winget install` can fail or install the wrong tool. Each method's `when:`
  guard means a bad winget method fails cleanly rather than breaking a POSIX
  bootstrap, but macOS/Linux remain the first-class targets; treat Windows as
  best-effort and verify what got installed.

## [0.2.1] - 2026-07-19

### Added

- **Recipe registry grown from 28 to 503 recipes** (+475 `cli-tool`s), covering
  Rust/Go CLIs, Kubernetes & cloud, Python/Node/Ruby/PHP/Haskell/JVM/Swift tooling,
  compression, editors/shells, docs/markup, formatters, language runtimes, build
  systems, media/graphics, science/math, and API/testing tools. Every new recipe
  passes the schema, linter policy, and full conformance suite.
- **Data-driven recipe generator** (`scripts/recipe_data.py` + `scripts/gen_recipes.py`)
  for maintaining the bulk `cli-tool` registry. It renders each `recipes/<id>.yaml`
  (never clobbering a hand-written recipe) and keeps two invariants in sync: the
  README recipe gallery (between `GENERATED` markers) and the version-extraction
  red-team samples (`tests/_generated_version_samples.py`).

### Notes

- Generated recipes are POSIX-first (no `winget` methods yet) and their
  version-extraction samples use a standardized `<bin> X.Y.Z` shape, so they prove
  the extractor works but do not red-team each tool's real `--version` quirks the
  way the hand-curated samples do.

## [0.2.0] - 2026-07-19

### Added

- **Windows support via `winget`.** 13 cli-tool recipes gained a `winget` install
  + update method (ripgrep, fd, bat, jq, gh, delta, zoxide, hyperfine, uv, lazygit,
  yq, dust, bottom). Because a method's `when:` guard runs in the platform
  shell, the existing brew/cargo/go guards fail cleanly on Windows (cmd.exe) while
  the winget guard (`winget --version`) fails cleanly on POSIX — so no core change
  was needed, methods just self-select per platform. The winget package ids are
  locked in the suite and **proven for real** by a new `windows` job in the
  real-bootstrap workflow (`winget show` resolves every id; a stable subset is
  bootstrapped end-to-end).

- **Real-bootstrap smoke (`scripts/smoke_bootstrap.py` + a weekly/dispatch CI
  workflow).** A second, non-offline validation tier that bootstraps recipes *for
  real* (detect → install → verify) on runners that actually have the package
  managers, catching recipe rot — a renamed formula, a dead URL, a wrong `go
  install` path, a bad MCP-server package name — that the deterministic offline
  suite can't. Four jobs: **every cli-tool** via brew (macOS, validates all
  formula names); the go/cargo/pipx **fallbacks** (Ubuntu); **gh's webi** fallback
  (forced by removing the preinstalled gh); and **mcp-servers** (wired against a
  stub `claude`, with every server package resolved for real against PyPI/npm).
  Not wired to PRs (real installs are slow/flaky); runs weekly and on manual
  dispatch, and fails loudly. The driver's wiring and every real mcp-server
  recipe's `claude mcp add` command are additionally covered offline
  (`tests/test_smoke_bootstrap.py`, `tests/test_real_mcp_recipes.py`).

- **Update digest — release-notes link.** For a recipe whose `version.latest` is a
  `{github: owner/repo}` source, `check_updates` now includes a `release_notes`
  URL (`https://github.com/owner/repo/releases`) in the checked entry, so the
  consent decision to apply an update can be made with the changelog one click
  away. Omitted for plain-command `latest` sources (erbina can't know where their
  notes live).

- **Profiles (`kind: profile`).** A meta-recipe that installs nothing itself and
  just `requires:` a curated set of other recipes, so bootstrapping one sets up a
  whole bundle in a single prompt (reusing the `requires` machinery: idempotent,
  member failure aborts the profile). Validation requires a non-empty `requires`
  and forbids every per-tool lifecycle key. Ships a first profile,
  [`modern-unix`](recipes/modern-unix.yaml) (ripgrep, fd, bat, eza, dust, zoxide).

- **Five new cli-tool recipes** (registry 22 → 27): `gh` (GitHub CLI), `lazygit`,
  `yq`, `difftastic` (`difft`), and `httpie` (`http`). Each ships the full contract
  — brew plus a native-ecosystem fallback (webi / `go install` / `cargo install` /
  `pipx`), an honest `verify`, the `{github: …}` version source, and `update` +
  `uninstall` blocks — and each has a real `--version` sample in the version-format
  suite (gh's two-line banner, lazygit's field soup, and yq's repo-URL line all
  verified to extract cleanly). Added to the README gallery.

- **`uninstall` tool — reverse a cli-tool install.** Runs the recipe's new
  `uninstall:` block (guarded methods, same shape as install/update), confirms the
  tool is actually gone by re-running `detect`, and forgets it in the state
  manifest. Destructive → consent-first with a `dry_run`. erbina never guesses how
  to remove a tool: a recipe without an `uninstall:` block is refused; an
  mcp-server is pointed at `remove_mcp`; an already-absent tool reports so and its
  stale record is cleaned up. Brings the tool surface to eleven.

- **`doctor` tool — health-check installed CLI tools.** Re-runs each recorded
  tool's `detect` (still present?) and, when present, `verify` (still runs?),
  classifying every entry in the state manifest as healthy / missing / broken.
  Read-only (only the recipe's own non-destructive checks); the CLI-tool
  counterpart to `find_dead_mcps`, which stays responsible for MCP servers. Brings
  the tool surface to ten.

- **Structured GitHub version source (`version.latest: { github: "owner/repo" }`).**
  `version.latest` may now be the GitHub shorthand instead of a hand-rolled
  command; erbina expands it to the releases-API call that isolates the latest tag
  (`curl … /releases/latest | grep '"tag_name"'`) — the grep matters so version
  extraction reads the tag, not another number in the JSON. All 16 GitHub-released
  recipes were migrated to the shorthand (each verified byte-identical to its old
  command, so no behavior change). Validation accepts a string or a `{github}`
  mapping and rejects a malformed `owner/repo` or any extra key.

- **Recipe prerequisites (`requires:`).** A recipe may declare `requires: [<id>,
  …]` — other recipes that `bootstrap` installs first, idempotently and
  depth-first, before the recipe's own detect/install. A prerequisite shared by
  several recipes is bootstrapped once per call, a cyclic prerequisite is skipped
  (no infinite recursion), and a failed prerequisite aborts the dependent before
  it installs. `dry_run` lists prerequisites in the plan. Enforced end to end:
  schema validation (shape + no self-reference), a registry-wide conformance
  check (every `requires` names a real recipe; the graph is acyclic), and
  behavioral tests for ordering / idempotency / transitive + diamond deps / cycle
  safety / failure short-circuiting.

### Fixed

- **Version extraction prefers a labeled version.** When `--version` output labels
  its version (contains the word "version"), `_extract_version` now takes the
  token *after* the label, so a dotted build date printed before it
  (`Built 2024.01.15, tool version 2.3.4`) is no longer mistaken for the version.
  Verified to not regress the whole version corpus (incl. the real outputs proven
  by the real-bootstrap run). Unlabeled output (a bare `v1.2.3`/`10.0` after a
  date) stays first-token — genuinely ambiguous vs. a calver, and no recipe hits it.

## [0.1.0] - 2026-07-18

First tagged release: a single-file `server.py` (FastMCP, run by `uv run --script`)
plus a curated recipe registry. Published to the
[MCP registry](https://registry.modelcontextprotocol.io) as
`io.github.noahhyden/erbina`.

### Added

- **Recipe model and schema** ([SCHEMA.md](SCHEMA.md)): one YAML per tool in
  `recipes/`, run as `detect → install → configure → verify`. `detect` gates
  install for idempotency, `install` methods are tried in order (first passing
  `when:` guard wins), and `verify` must prove the tool actually *runs*. Commands
  support `${scope}` and `${project_dir}`. `kind: mcp-server` recipes wire a
  server into the chosen scope via `claude mcp add <name> --scope ${scope}`.
- **Schema validation and linter.** `validate_recipe` enforces the contract (`id`
  equals the filename stem, valid `kind`, non-empty `detect` / `install.methods` /
  `verify`, `${scope}` in mcp-server configure steps, no unknown top-level keys,
  no unknown `${...}` placeholders). Recipe loading raises on any violation, so
  `bootstrap` / `inspect_recipe` refuse a malformed recipe. `lint_recipes.py`
  lints every recipe and adds registry policy: title and description present, a
  `when:` guard on every install method, and a `verify` that runs the tool.
- **Tools:** `list_recipes`, `inspect_recipe`, `bootstrap`, `audit_scopes`,
  `find_dead_mcps`, `remove_mcp`, `check_updates`, `update`, `pin`.
  `inspect_recipe` and `bootstrap(dry_run=true)` are the consent surface;
  `audit_scopes` reports MCP servers per `local` / `project` / `user` scope and
  shadowed names; `find_dead_mcps` flags servers that fail to connect and
  `remove_mcp` deletes one (scope auto-resolved, `dry_run` supported).
- **Auto-updates** ([AUTO_UPDATE.md](AUTO_UPDATE.md)). Recipes can declare
  `version:` and `update:` blocks. `check_updates` compares versions with
  [`packaging`](https://packaging.pypa.io) semantics and never claims an update it
  cannot parse; `update` re-runs `verify` afterwards and, on failure, rolls back
  or marks the tool broken; `pin` skips a tool. A state manifest
  (`~/.erbina/state.json`) records versions, install method and pins. An opt-in
  SessionStart hook (`examples/erbina-session-start.sh`) or `/schedule` routine
  can surface updates for consent. Adds the `packaging` dependency.
- **Recipes:** `ataegina`, `ripgrep`, `fd`, `jq`, `bat`, `delta`, `zoxide`, `eza`,
  `uv`, `hyperfine`, `dust`, `bottom`, `sd`, `tokei`, `tealdeer`, `procs`
  (`cli-tool`; Homebrew with guarded cargo/apt fallbacks, `version:` + `update:`)
  and `fetch`, `git`, `time`, `sequentialthinking`, `memory`, `everything`
  (`mcp-server`; the last three run via `npx`). Binary/crate/version-output name
  gotchas (`git-delta`, `du-dust`, `btm`, `tldr`, `fd-find`, `jq-1.7.1`) are
  locked by tests.
- **Test suite** (260 tests, up from ~26): drives the server through an in-memory
  FastMCP client; `tests/prototype.py` builds recipes from shell builtins so live
  `bootstrap` / `update` runs are deterministic; `tests/test_integration.py` runs
  real install, verify, idempotent re-run, update and rollback against a fixture
  tool and a stub `claude`; a conformance suite every recipe must pass; a README
  recipe-gallery drift guard. Behavioral tests were mutation-tested. See
  [tests/README.md](tests/README.md).
- **CI and release.** `.github/workflows/ci.yml` runs ruff, the suite on Linux +
  macOS, an import check on the Python 3.10 floor, and release verification
  (recipes lint, `server.json` valid, tag/version agreement); `main` is protected
  by a ruleset requiring those checks. `RELEASE.md` documents cutting a release.
- **Docs:** this changelog, `SECURITY.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, and issue / pull-request templates.

[Unreleased]: https://github.com/noahhyden/erbina/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/noahhyden/erbina/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/noahhyden/erbina/releases/tag/v0.1.0
