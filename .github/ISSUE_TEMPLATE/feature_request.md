---
name: Feature request
about: Suggest an idea or improvement for erbina
title: "[feature] "
labels: ["type: feature", "status: needs triage"]
assignees: ''
---

> Adding a new **recipe** does not need an issue — just open a PR with a
> `recipes/<id>.yaml` (see [SCHEMA.md](../../SCHEMA.md) and
> [CONTRIBUTING.md](../../CONTRIBUTING.md)). Use this template for changes to the
> server, the tools, or the recipe schema.

## The problem

What are you trying to do that erbina makes hard or impossible today?

## Proposed solution

What you would like to see. If it touches a tool, sketch the signature and the
returned shape. If it touches the recipe schema, sketch the new field.

## Alternatives considered

Other approaches, including expressing it as a recipe (data) rather than a server
change.

## Fit with the project ethos

erbina is deliberately a single, inline-dependency `server.py` run by `uv`, with
**consent before execution** as its safety model, scoped to Claude Code only.
Please note how your request fits within that:

- [ ] No build step / packaging / lockfile — stays a single `uv run --script`
      file
- [ ] Anything that executes is reachable only after a dry-run / inspect surface
      could show it; `audit_*` / `find_*` tools stay read-only
- [ ] Recipes stay declarative data, handled generically — no per-recipe
      special-casing in the server
- [ ] Stays Claude-Code-specific (its `local`/`project`/`user` scopes and
      `claude mcp` CLI); no other-client abstraction

## Anything else

Context, links, or prior art.
