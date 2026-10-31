## A test recipe runs only POSIX shell builtins

Prototype recipes (tests/prototype.py) use true/false/exit N/echo, never brew, curl or the claude CLI, so a live bootstrap or uninstall is deterministic and side-effect-free; a real package manager in a test recipe installs on the dev box.
