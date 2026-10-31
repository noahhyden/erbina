## A CI step that skips its own missing file reports green forever

`if [ -f lint_recipes.py ]` guarded the recipe lint in two ci.yml jobs long after the file was tracked, so deleting it would have passed CI silently; run a tracked guard unconditionally and let the command's own absence be the failure.
