#!/usr/bin/env python3
"""Dispatch one fixture or agent generation through the six applications."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import AGENT_SCHEMA_VERSION  # noqa: E402
from apps.controller.agent_generation import (  # noqa: E402
    decode_agent_generation_request,
    run_agent_generation,
)
from apps.controller.component_runtime import (  # noqa: E402
    ControllerError,
    RequestError,
)
from apps.controller.contract import (  # noqa: E402
    ControllerReceiptError,
    validate_agent_generation_receipt,
)
from apps.controller.fixture_generation import (  # noqa: E402
    ObserverSession as _ObserverSession,
    decode_document,
    run_fixture_generation,
    run_generation as _run_generation,
)
from apps.stdio_connector import run_stdio_application  # noqa: E402

# Source-level compatibility for tests and callers that imported these fixture
# owners from the historical controller module.
ObserverSession = _ObserverSession
run_generation = _run_generation


def _process(source: str) -> dict[str, object]:
    request = decode_document(source)
    if request.get("schema_version") == AGENT_SCHEMA_VERSION:
        generation = decode_agent_generation_request(request)
        result = run_agent_generation(generation)
        try:
            validate_agent_generation_receipt(request, result)
        except ControllerReceiptError as exc:
            raise ControllerError(str(exc)) from exc
        return result
    return run_fixture_generation(source)


def _unexpected_controller_error(error: Exception) -> tuple[str, str]:
    detail = str(error) or type(error).__name__
    return "controller_error", f"internal controller failure: {detail}"


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        _process,
        arguments,
        error_rules=(
            (RequestError, "invalid_request"),
            (ControllerError, "controller_error"),
        ),
        unexpected=_unexpected_controller_error,
        stream_error_code="controller_error",
    )


if __name__ == "__main__":
    raise SystemExit(main())
