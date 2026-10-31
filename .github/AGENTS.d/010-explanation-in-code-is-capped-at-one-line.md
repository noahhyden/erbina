## Explanation in code is capped at ONE line; the rest belongs in AGENTS.d

check_one_line_comments.py flags multi-line docstrings and comment runs in .py/.yaml against a baseline that may only SHRINK; a run carrying a pragma (noqa, PEP 723 `/// script`) is exempt, and the burn-down ends by deleting the baseline.
