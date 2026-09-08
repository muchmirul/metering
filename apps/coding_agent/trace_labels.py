"""Stable, presentation-only branch labels; no optimizer or Git-ref policy."""

from __future__ import annotations


def branch_suffix(index: int) -> str:
    result = ""
    while index >= 0:
        result = chr(97 + index % 26) + result
        index = index // 26 - 1
    return result


def branch_labels(prefix: str, parents: dict[str, str | None]) -> dict[str, dict]:
    """Input order is immutable registration order, never layout or selection order."""
    labels: dict[str, dict] = {}
    child_counts: dict[str, int] = {}
    next_branch = 0
    for identity, parent in parents.items():
        if parent is None or child_counts.get(parent, 0):
            branch = next_branch
            next_branch += 1
        else:
            branch = labels[parent]["branch_index"]
        depth = labels[parent]["depth"] + 1 if parent is not None else 0
        suffix = branch_suffix(branch)
        labels[identity] = {
            "display_label": f"{prefix}{depth}{suffix if depth or branch else ''}",
            "depth": depth,
            "branch": suffix,
            "branch_index": branch,
            "parent_display_label": labels[parent]["display_label"]
            if parent is not None
            else None,
        }
        if parent is not None:
            child_counts[parent] = child_counts.get(parent, 0) + 1
    return labels
