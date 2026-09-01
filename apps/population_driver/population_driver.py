#!/usr/bin/env python3
"""Compatibility CLI for bounded Population Driver execution."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.population_driver.population_driver_protocol import (  # noqa: E402
    PopulationDriverError,
    RequestError,
)
from apps.population_driver.runtime import (  # noqa: E402
    retry_population_driver,
    run_population_driver,
    verify_population_driver,
)
from apps.stdio_connector import run_stdio_application  # noqa: E402


def _application(source: str, arguments: list[str]) -> dict[str, object]:
    if len(arguments) != 2 or arguments[0] not in {"retry", "run", "verify"}:
        raise RequestError(
            "usage: population_driver.py {run|retry|verify} STATE_DIRECTORY"
        )
    command, raw_root = arguments
    root = Path(raw_root)
    if command == "run":
        return run_population_driver(source, root)
    if command == "retry":
        return retry_population_driver(source, root)
    if source.strip():
        raise RequestError("verify standard input must be empty")
    return verify_population_driver(root)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        lambda source: _application(source, arguments),
        [],
        error_rules=(
            (RequestError, "invalid_request"),
            ((PopulationDriverError, OSError), "population_driver_error"),
        ),
        stream_error_code="population_driver_error",
    )


if __name__ == "__main__":
    raise SystemExit(main())
