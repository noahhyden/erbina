## What and why

What this change does, and the problem it solves. Link any related issue
(`Closes #NNN`).

## How to verify

The tool calls (or in-memory client snippet) a reviewer can run to see it work,
plus what they should observe. For anything that executes, include the
`bootstrap(dry_run=true)` plan and a real run.

## Checklist

- [ ] One logical change (small is good).
- [ ] The server stays a single `server.py` with inline (PEP 723) deps — no
      `pyproject.toml`, lockfile, or build step added.
- [ ] Consent-before-execution preserved: anything that executes is reachable
      only after a dry-run / `inspect_recipe` surface could show it; `audit_*` /
      `find_*` tools stay read-only.
- [ ] If a recipe was added/changed: `detect` is cheap and side-effect-free,
      `verify` proves the tool actually *runs*, and `id` matches the filename.
- [ ] Recipes stay declarative data handled generically — no per-recipe
      special-casing in the server.
- [ ] Smoke-tested with an in-memory FastMCP client (see CONTRIBUTING.md);
      anything wired in during testing was `claude mcp remove`d.
- [ ] README.md and SCHEMA.md updated if a tool signature, the recipe schema, or
      a placeholder changed.
- [ ] CHANGELOG.md updated under `## [Unreleased]`.

## Notes

Anything else reviewers should know (trade-offs, follow-ups, things you are
unsure about).
