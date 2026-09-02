#!/usr/bin/env python3
"""Dispatch one schema-v1 or schema-v2 forecast assay instruction."""

from __future__ import annotations

import sys
from pathlib import Path

from metering import ProbabilityError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import AGENT_SCHEMA_VERSION  # noqa: E402
from apps.forecast_assay.agent_assay import (  # noqa: E402
    RequestError as AgentRequestError,
    measure_agent_task_candidate,
)
from apps.forecast_assay.fixture_assay import (  # noqa: E402
    RequestError,
    decode_document,
    run_fixture_assay,
)
from apps.stdio_connector import run_stdio_application  # noqa: E402


def _measure_source(source: str) -> dict[str, object]:
    request = decode_document(source)
    if request.get("schema_version") == AGENT_SCHEMA_VERSION:
        return measure_agent_task_candidate(request)
    return run_fixture_assay(source)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        _measure_source,
        arguments,
        error_rules=(
            ((RequestError, AgentRequestError), "invalid_request"),
            (ProbabilityError, "invalid_probability"),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
