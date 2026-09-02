#!/usr/bin/env python3
"""Dispatch one schema-v1 or schema-v2 candidate execution instruction."""

from __future__ import annotations

import sys
from pathlib import Path

from metering import ProbabilityError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import AGENT_SCHEMA_VERSION  # noqa: E402
from apps.candidate_runner.agent_runner import (  # noqa: E402
    RequestError as AgentRequestError,
    run_agent_candidate,
)
from apps.candidate_runner.fixture_runner import (  # noqa: E402
    RequestError,
    decode_document,
    run_fixture_candidate,
)
from apps.stdio_connector import run_stdio_application  # noqa: E402


def _process(source: str) -> dict[str, object]:
    request = decode_document(source)
    if request.get("schema_version") == AGENT_SCHEMA_VERSION:
        return run_agent_candidate(request)
    return run_fixture_candidate(source)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        _process,
        arguments,
        error_rules=(
            ((RequestError, AgentRequestError), "invalid_request"),
            (ProbabilityError, "invalid_probability"),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
