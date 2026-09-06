"""Every file this project touches is UTF-8, stated explicitly.

Amounts carry a rupee sign, and `Path.write_text` without an `encoding`
argument uses whatever the *locale* claims, which is ASCII on plenty of CI
runners and containers. That combination turns "write the report" into
`UnicodeEncodeError` on someone else's machine and works fine on mine, so it
is checked here rather than trusted.
"""

from __future__ import annotations

import ast
from pathlib import Path

from recon.domain.money import RUPEE, format_paise

ROOTS = (Path("src"), Path("scripts"), Path("tests"))
TEXT_IO = {"read_text", "write_text", "open"}
BINARY_MODES = ("rb", "wb", "ab")


def _keyword_names(call: ast.Call) -> set[str]:
    return {kw.arg for kw in call.keywords if kw.arg}


def _is_binary(call: ast.Call) -> bool:
    modes = [a.value for a in call.args if isinstance(a, ast.Constant)]
    return any(m in BINARY_MODES for m in modes if isinstance(m, str))


def _offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in TEXT_IO or _is_binary(node):
            continue
        if "encoding" not in _keyword_names(node):
            found.append(f"{path}:{node.lineno}: {node.func.attr}() without encoding=")
    return found


def test_every_text_read_and_write_names_its_encoding():
    offenders = [
        problem
        for root in ROOTS
        for path in sorted(root.rglob("*.py"))
        for problem in _offenders(path)
    ]
    assert offenders == [], "\n".join(offenders)


def test_amounts_survive_a_round_trip_through_a_file(tmp_path):
    # Arrange
    target = tmp_path / "amount.txt"
    rendered = format_paise(1_234_567)

    # Act
    target.write_text(rendered, encoding="utf-8")

    # Assert
    assert RUPEE in rendered
    assert target.read_text(encoding="utf-8") == rendered
