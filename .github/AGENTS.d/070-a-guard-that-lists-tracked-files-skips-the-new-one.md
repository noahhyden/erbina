## A guard that enumerates with `git ls-files` never sees the file you just added

check_agents_rule_length reported "scanned 6, OK" while a brand-new 300-char rule sat untracked beside it; a guard that discovers its own inputs must add `--others --exclude-standard`, or it passes on exactly the file a contributor is about to get wrong.
