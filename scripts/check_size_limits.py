"""Enforce the size limits CONTRIBUTING.md states, so they stay true.

A style rule nobody checks is a style rule the codebase quietly stops
following. This is deliberately crude: line counts, not complexity metrics.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MAX_FILE_LINES = 400
MAX_FUNCTION_LINES = 50
ROOTS = (Path("src"), Path("scripts"))


def _function_lengths(path: Path) -> list[tuple[str, int, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lengths = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        span = (node.end_lineno or node.lineno) - node.lineno + 1
        if span > MAX_FUNCTION_LINES:
            lengths.append((node.name, node.lineno, span))
    return lengths


def main() -> int:
    failures: list[str] = []
    checked = 0

    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            checked += 1
            lines = len(path.read_text(encoding="utf-8").splitlines())
            if lines > MAX_FILE_LINES:
                failures.append(f"{path}: {lines} lines (limit {MAX_FILE_LINES})")
            failures.extend(
                f"{path}:{line}: {name} is {span} lines (limit {MAX_FUNCTION_LINES})"
                for name, line, span in _function_lengths(path)
            )

    if failures:
        print(f"size limits exceeded in {len(failures)} places:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(
        f"  {checked} files within {MAX_FILE_LINES} lines "
        f"and every function within {MAX_FUNCTION_LINES}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
