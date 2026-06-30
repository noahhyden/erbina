---
name: Bug report
about: Something in erbina does not behave as documented
title: "[bug] "
labels: ["type: bug", "status: needs triage"]
assignees: ''
---

## What happened

A clear description of the bug.

## What you expected

What you expected to happen instead.

## Which tool / recipe

The erbina tool involved (`list_recipes` / `inspect_recipe` / `bootstrap` /
`audit_scopes` / `find_dead_mcps` / `remove_mcp`) and, if a recipe was involved,
which one and at what `scope`.

## Steps to reproduce

The exact prompt or tool call. For anything that executes, please first capture
the read-only plan:

```
# in Claude Code, ask the agent to run:
inspect_recipe(recipe_id="<id>", scope="<local|project|user>")
# or
bootstrap(recipe_id="<id>", dry_run=true)
```

## Plan / dry-run output

The output of `inspect_recipe` or `bootstrap(dry_run=true)` for the recipe (it
executes nothing — safe to paste):

```
paste here
```

## Environment

- erbina commit (`git -C <erbina> rev-parse --short HEAD`):
- OS / distro:
- `uv --version`:
- Claude Code version:
- `claude mcp list` (redact anything sensitive):

```
paste here
```

## Anything else

Logs, the failing command's stderr, or notes that might help.
