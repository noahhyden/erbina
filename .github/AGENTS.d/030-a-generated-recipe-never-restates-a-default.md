## A generated recipe never restates a reader's default

gen_recipes.py renders 483 files, so one redundant line costs 483: the former `scope: user` lines restated a default server.py already applies. Emit a key only where it differs from what the reader assumes.
