# Cutting a release

erbina ships as source: a single `server.py` run by `uv run --script`, plus the
recipes and the `server.json` manifest that lists it in the
[MCP registry](https://registry.modelcontextprotocol.io). There is no compiled
artifact and no checksum to publish — a release is a **tag**, a **GitHub
release**, a **`server.json` version bump**, and a **registry publish**. The one
thing a maintainer must keep in agreement is the version: `server.json`'s
`version`, the git tag, and the `CHANGELOG.md` heading must all name the same
`X.Y.Z`. CI's `release-verify` job enforces the `server.json`↔tag part on every
tag build.

Versioning is [SemVer](https://semver.org/). While erbina is pre-1.0, breaking
changes to the recipe schema or a tool signature bump the **minor**; additive
recipes/tools and fixes bump the **patch**.

## Checklist

Run from the repo root, working tree clean, on `main`.

1. **Land the work through PRs.** `main` is protected — everything merges via a
   green PR (see [CONTRIBUTING.md](CONTRIBUTING.md)). Nothing below is done by
   pushing straight to `main`.

2. **Roll the changelog.** In [CHANGELOG.md](CHANGELOG.md), rename the
   `## [Unreleased]` section to `## [X.Y.Z] - YYYY-MM-DD` and open a fresh empty
   `## [Unreleased]` above it.

3. **Bump the manifest.** Set `"version": "X.Y.Z"` in
   [`server.json`](server.json). This is what the registry publishes and what
   `release-verify` compares against the tag.

4. **Open the release PR** with steps 2–3, let CI go green, and merge it.

5. **Tag and push the tag.**

   ```sh
   git checkout main && git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

   The tag build re-runs CI, and `release-verify` fails the build if
   `server.json`'s version isn't `X.Y.Z` — a guardrail against a forgotten bump.

6. **Create the GitHub release** on tag `vX.Y.Z` with notes drawn from the
   changelog section:

   ```sh
   gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."
   ```

7. **Publish to the MCP registry.** The manifest is already committed; publish
   the new version:

   ```sh
   mcp-publisher login github   # grants the io.github.noahhyden/* namespace
   mcp-publisher publish        # validates server.json, then pushes
   ```

   Downstream directories (PulseMCP, Glama) ingest the official registry
   automatically; no per-directory edit is needed.

## Verify before announcing

From a clean checkout of the tag:

```sh
# the version that ships is the one you bumped
python3 -c 'import json; print(json.load(open("server.json"))["version"])'

# recipes still lint clean and the server still comes up with all its tools
uv run --script lint_recipes.py
uv run --with pytest --with fastmcp --with pyyaml pytest tests/ -v

# a real user's install line actually works
claude mcp add erbina-relcheck --scope local -- \
  uv run --script "$PWD/server.py"
# ...ask Claude to `list_recipes`, then:
claude mcp remove erbina-relcheck
```

## Notes

- **Keep the three versions in lockstep.** `server.json`, the git tag, and the
  `CHANGELOG.md` heading must match. CI hard-fails a tag build on a
  `server.json`↔tag mismatch; the changelog is on you.
- **The registry entry is metadata-only by design.** erbina has no published
  npm/PyPI package (that would mean a build step, against the project ethos), so
  `server.json` carries `repository` + `websiteUrl` and points users at the
  README for the `uv run --script` install. A release does not produce a package
  to upload.
- **Never hand-edit a tagged revision in place.** Cut a new patch release
  instead.
