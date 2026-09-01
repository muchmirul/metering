#!/usr/bin/env python3
"""Deterministic mutation fixture using the production typed Git plumbing."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.harness.protocol import HarnessProtocolError, load_candidate, refresh_manifest  # noqa: E402
from artifacts.git.git_proposer import ProposerError, run_main  # noqa: E402


def _edit(workspace: Path, prompt: str) -> None:
    match = re.search(r'"generation":(\d+)', prompt)
    if match is None:
        raise ProposerError("fixture proposal prompt omitted generation")
    generation = int(match.group(1))
    replacements = {
        1: ("ARITHMETIC_POLICY=SUBTRACT", "ARITHMETIC_POLICY=ADD"),
        2: ("ARITHMETIC_POLICY=ADD", "ARITHMETIC_POLICY=MULTIPLY"),
    }
    if generation not in replacements:
        raise ProposerError("fixture proposer supports exactly two generations")
    candidate = load_candidate(workspace)
    path = workspace / candidate.paths["system_prompt"]
    source = path.read_text(encoding="utf-8")
    old, new = replacements[generation]
    if source.count(old) != 1:
        raise ProposerError(f"fixture parent does not contain {old}")
    path.write_text(source.replace(old, new), encoding="utf-8", newline="")
    try:
        refresh_manifest(workspace)
    except HarnessProtocolError as exc:
        raise ProposerError(str(exc)) from exc


def main() -> int:
    return run_main(agent_name="deterministic harness fixture", edit_workspace=_edit)


if __name__ == "__main__":
    raise SystemExit(main())
