## Config and state readers degrade, never raise

Reading ~/.claude.json, .mcp.json, the state file or project_dir (NUL byte, ENAMETOOLONG, malformed JSON) must return empty/None, and validate_recipe must return errors rather than crash, so read-only tools stay usable.
