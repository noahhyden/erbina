## A generated recipe never restates a reader's default

gen_recipes.py renders 483 files, so one redundant line costs 483: `expect_exit: 0` and `scope: user` were 1,540 lines restating defaults server.py already applies. Emit a key only where it differs from what the reader assumes.
