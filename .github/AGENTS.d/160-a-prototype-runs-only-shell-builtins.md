## A prototype recipe runs only shell builtins

Every command in a tests/prototype.py recipe is a builtin with a fixed exit code (true, false, exit N, echo), so a live bootstrap is deterministic and installs nothing; a prototype that shells out to brew, curl or claude breaks that.
