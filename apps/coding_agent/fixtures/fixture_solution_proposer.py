#!/usr/bin/env python3
"""Deterministic solution proposer using the selected fixture harness."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.coding_agent.harness_workspace_editor import (  # noqa: E402
    CodingMutationError,
    edit_solution_with_harness,
)
from artifacts.git.git_proposer import ProposerError, run_main  # noqa: E402

MODEL = ROOT / "apps" / "harness" / "fixtures" / "fixture_model.py"


def _edit(workspace: Path, objective: str) -> None:
    edit_solution_with_harness(
        workspace,
        objective,
        model_command=[sys.executable, str(MODEL)],
        expected_connector="fixture-v1",
    )


def main() -> int:
    try:
        return run_main(
            agent_name="selected fixture evolutionary harness",
            edit_workspace=_edit,
        )
    except (CodingMutationError, ProposerError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
