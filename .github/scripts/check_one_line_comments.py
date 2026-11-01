#!/usr/bin/env python3
"""Explanation in code is capped at ONE line; the rest belongs in .github/AGENTS.d/ - design and each exemption's rationale live in 010-explanation-in-code-is-capped-at-one-line.md, not here."""

from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCANNED_SUFFIXES = (".py", ".yml", ".yaml")

PRAGMAS: tuple[str, ...] = (
    "noqa",
    "type: ignore",
    "pragma:",
    "ruff:",
    "mypy:",
    "nosec",
    "fmt:",
    "DO NOT EDIT",
    "AUTO-GENERATED",
    "SPDX-",
    "Copyright",
    "!/usr/bin",
    "-*- coding",
    "/// script",
)

def has_pragma(lines: list[str]) -> bool:
    """True when any line in the run carries a tooling pragma."""
    return any(p in line for line in lines for p in PRAGMAS)


def python_violations(text: str) -> list[tuple[int, str]]:
    """Multi-line docstrings and multi-line standalone comment runs."""
    out: list[tuple[int, str]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            (isinstance(d, ast.Attribute) and d.attr == "tool") or (isinstance(d, ast.Name) and d.id == "tool")
            for d in node.decorator_list
        ):
            continue
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        span = first.end_lineno - first.lineno + 1
        if span > 1:
            name = getattr(node, "name", "<module>")
            out.append((first.lineno, f"docstring spans {span} lines ({name})"))

    lines = text.split("\n")
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return out
    standalone = sorted(
        t.start[0]
        for t in toks
        if t.type == tokenize.COMMENT and not lines[t.start[0] - 1][: t.start[1]].strip()
    )
    out.extend(_runs(standalone, lines))
    return out


BLOCK_SCALAR_RE = re.compile(r"^(\s*)\S.*:\s*[|>][+\-0-9]*\s*(#.*)?$")


def yaml_violations(text: str) -> list[tuple[int, str]]:
    """Multi-line standalone `#` comment runs, skipping block-scalar bodies (`run: |`, `description: >`) where `#` is literal content, not a YAML comment."""
    out: list[tuple[int, str]] = []
    lines = text.split("\n")
    standalone: list[int] = []
    in_block = False
    block_parent_indent = 0
    for i, raw in enumerate(lines, start=1):
        if in_block:
            stripped = raw.strip()
            indent = len(raw) - len(raw.lstrip(" "))
            if stripped == "" or indent > block_parent_indent:
                continue
            in_block = False
        m = BLOCK_SCALAR_RE.match(raw)
        if m:
            block_parent_indent = len(m.group(1))
            in_block = True
            continue
        if raw.strip().startswith("#"):
            standalone.append(i)
    out.extend(_runs(standalone, lines))
    return out


def _runs(linenos: list[int], lines: list[str]) -> list[tuple[int, str]]:
    """Consecutive comment lines grouped into runs longer than one line."""
    out: list[tuple[int, str]] = []
    run: list[int] = []

    def flush() -> None:
        if len(run) > 1 and not has_pragma([lines[k - 1] for k in run]):
            out.append((run[0], f"comment run spans {len(run)} lines"))

    for n in linenos:
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        flush()
        run = [n]
    flush()
    return out


def scan(paths: list[str]) -> dict[str, list[tuple[int, str]]]:
    """Violations per path, skipping non-source and missing files."""
    found: dict[str, list[tuple[int, str]]] = {}
    for rel in paths:
        if not rel.endswith(SCANNED_SUFFIXES):
            continue
        full = REPO_ROOT / rel
        if not full.is_file():
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = python_violations(text) if rel.endswith(".py") else yaml_violations(text)
        if hits:
            found[rel] = hits
    return found


def all_source_paths() -> list[str]:
    """Every tracked .py/.yml/.yaml path."""
    out = subprocess.run(
        ["git", "ls-files", "*.py", "*.yml", "*.yaml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [p for p in out.split("\n") if p]


def _report(found: dict[str, list[tuple[int, str]]]) -> list[str]:
    """Lines naming every file with a violation and its first few offenders."""
    out: list[str] = []
    for path, hits in sorted(found.items()):
        out.append(f"  {path}: {len(hits)} violation(s)")
        for lineno, why in hits[:4]:
            out.append(f"      {path}:{lineno}  {why}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()

    paths = args.files or all_source_paths()
    scanned = [p for p in paths if p.endswith(SCANNED_SUFFIXES)]
    if not scanned:
        print("one-line-comments: no scannable file matched - refusing to pass vacuously")
        return 1
    found = scan(paths)
    py_scanned = len([p for p in scanned if p.endswith(".py")])
    yaml_scanned = len(scanned) - py_scanned

    if found:
        print("one-line-comments: explanation in code is capped at ONE line.\n")
        print("\n".join(_report(found)))
        print(
            "\nA module, class or function gets a one-line docstring or none, and a run of\n"
            "standalone comments is one line. Move the rest into a .github/AGENTS.d/ rule.\n"
            "An `@mcp.tool` docstring is exempt - it is the description the model reads.\n"
            f"\nScanned {py_scanned} python file(s), {yaml_scanned} yaml file(s)."
        )
        return 1

    print(
        f"one-line-comments: OK - {py_scanned} python + {yaml_scanned} yaml file(s) scanned, "
        "zero violations."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
