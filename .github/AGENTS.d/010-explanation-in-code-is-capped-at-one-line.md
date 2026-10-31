## Explanation in code is capped at ONE line; the rest belongs in AGENTS.d

check_one_line_comments.py fails any multi-line docstring or standalone comment run in .py/.yaml, with no baseline to park one in; a run carrying a pragma (noqa, PEP 723 `/// script`) and an `@mcp.tool` docstring (the model reads it) are exempt.
