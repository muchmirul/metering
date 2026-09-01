#!/usr/bin/env python3
"""Validate one evolutionary-harness-v1 workspace without executing it."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.harness.protocol import HarnessProtocolError, load_candidate  # noqa: E402
from apps.harness.runtime_manifest import (  # noqa: E402
    RuntimeManifestError,
    assert_candidate_compatible,
    load_runtime_manifest,
)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) > 1:
        print("usage: validate_candidate.py [CHECKOUT]", file=sys.stderr)
        return 2
    path = Path(arguments[0]) if arguments else Path.cwd()
    try:
        candidate = load_candidate(path)
        runtime_path = os.environ.get("METERING_HARNESS_RUNTIME_MANIFEST")
        if runtime_path:
            runtime = load_runtime_manifest(Path(runtime_path))
            assert_candidate_compatible(
                runtime,
                (path / candidate.paths["dependency_lock"]).read_bytes(),
            )
    except (
        HarnessProtocolError,
        OSError,
        RuntimeManifestError,
        ValueError,
    ) as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
