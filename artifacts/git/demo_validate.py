"""Visible validation command for the deterministic Git artifact example."""

from __future__ import annotations

import ast
from pathlib import Path


def read_answer(path: Path = Path("adapter.py")) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign):
        raise ValueError("adapter.py must contain one assignment")
    assignment = tree.body[0]
    if (
        len(assignment.targets) != 1
        or not isinstance(assignment.targets[0], ast.Name)
        or assignment.targets[0].id != "ANSWER"
        or not isinstance(assignment.value, ast.Constant)
        or type(assignment.value.value) is not str
        or not assignment.value.value
    ):
        raise ValueError("adapter.py must assign one non-empty ANSWER string")
    return assignment.value.value


if __name__ == "__main__":
    read_answer()
