## A recipe_data row sets `gh` and package names only when verified

Attach `gh` only when the version command prints a clean version token to stdout, and set `brew`/`winget`/etc. only to package names known to be correct; a wrong name installs the wrong software.
