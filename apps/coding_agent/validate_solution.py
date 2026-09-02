#!/usr/bin/env python3
"""Non-executing structural validation for a proposed solution workspace."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.harness.workspace import WorkspaceError, snapshot_directory  # noqa: E402


class SolutionValidationError(RuntimeError):
    """Raised when the candidate workspace loses its declared entrypoint."""


def validate(root: Path) -> None:
    entrypoint = os.environ.get("METERING_CODING_ENTRYPOINT")
    if not entrypoint:
        raise SolutionValidationError("METERING_CODING_ENTRYPOINT must be configured")
    files = snapshot_directory(root)
    paths = {str(item["path"]) for item in files}
    if entrypoint not in paths:
        raise SolutionValidationError(
            f"candidate solution omitted its entrypoint: {entrypoint}"
        )


def main() -> int:
    try:
        validate(Path.cwd())
    except (OSError, SolutionValidationError, WorkspaceError, ValueError) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
