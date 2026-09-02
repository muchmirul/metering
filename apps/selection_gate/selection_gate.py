#!/usr/bin/env python3
"""Dispatch one schema-v1 or schema-v2 pairwise selection instruction."""

from __future__ import annotations

import sys
from pathlib import Path

from metering import ProbabilityError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import AGENT_SCHEMA_VERSION  # noqa: E402
from apps.selection_gate.fixture_selection import (  # noqa: E402
    RequestError,
    decode_document,
    run_fixture_selection,
)
from apps.selection_gate.task_selection import select_task_reports  # noqa: E402
from apps.stdio_connector import run_stdio_application  # noqa: E402


def _process(source: str) -> dict[str, object]:
    request = decode_document(source)
    if request.get("schema_version") == AGENT_SCHEMA_VERSION:
        return select_task_reports(request)
    return run_fixture_selection(source)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        _process,
        arguments,
        error_rules=(
            (RequestError, "invalid_request"),
            (ProbabilityError, "invalid_probability"),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
