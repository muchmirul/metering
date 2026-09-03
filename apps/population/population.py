#!/usr/bin/env python3
"""Operate one canonical source-only candidate population."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import ProtocolError  # noqa: E402
from apps.population.population_index import (  # noqa: E402
    query_index,
    rebuild_index,
    verify_index,
)
from apps.population.population_policy import (  # noqa: E402
    decode_allocation_request,
    decode_archive_request,
)
from apps.population.population_protocol import (  # noqa: E402
    PopulationError,
    RequestError,
    decode_candidate_request,
    decode_experiment_request,
    decode_initialize_request,
    decode_recombination_request,
    decode_run_request,
)
from apps.population.population_state import (  # noqa: E402
    append_validated_record,
    initialize,
    load_state,
    locked_state,
    verify_summary,
)
from apps._support.wire import (  # noqa: E402
    decode_json_object,
    error_document,
    write_document,
)

_REQUEST_COMMANDS = {
    "allocate",
    "archive",
    "candidate",
    "experiment",
    "init",
    "query",
    "recombine",
    "run",
}
_NO_REQUEST_COMMANDS = {"rebuild", "verify", "verify-index"}


def _read_request() -> dict[str, object]:
    stream = getattr(sys.stdin, "buffer", None)
    try:
        source = sys.stdin.read() if stream is None else stream.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RequestError("standard input must be valid UTF-8 JSON") from exc
    return decode_json_object(source, RequestError)


def _arguments(argv: list[str]) -> tuple[str, Path]:
    if len(argv) != 2 or argv[0] not in _REQUEST_COMMANDS | _NO_REQUEST_COMMANDS:
        commands = "|".join(sorted(_REQUEST_COMMANDS | _NO_REQUEST_COMMANDS))
        raise RequestError(f"usage: population.py {commands} STATE")
    path = Path(argv[1]).expanduser().absolute()
    if path.name in {"", ".", ".."}:
        raise RequestError("STATE must name a population directory")
    return argv[0], path


def _mutating_response(
    command: str, root: Path, request: dict[str, object]
) -> dict[str, object]:
    with locked_state(root):
        state = load_state(root)
        if command == "candidate":
            body = decode_candidate_request(request, state)
            kind = "candidate"
        elif command == "experiment":
            body = decode_experiment_request(request)
            kind = "experiment"
        elif command == "run":
            body = decode_run_request(request, state)
            kind = "run"
        elif command == "archive":
            body = decode_archive_request(request, state)
            kind = "archive"
        elif command == "allocate":
            body = decode_allocation_request(request, state)
            kind = "allocation"
        else:
            body = decode_recombination_request(request, state)
            kind = "candidate"
        return append_validated_record(root, state, kind, body)


def execute(
    command: str, root: Path, request: dict[str, object] | None
) -> dict[str, object]:
    if command == "init":
        assert request is not None
        return initialize(root, decode_initialize_request(request))
    if command in {
        "candidate",
        "experiment",
        "run",
        "archive",
        "allocate",
        "recombine",
    }:
        assert request is not None
        return _mutating_response(command, root, request)

    with locked_state(root):
        state = load_state(root)
        if command == "rebuild":
            return rebuild_index(root, state)
        if command == "verify":
            return verify_summary(state, root)
        if command == "verify-index":
            return verify_index(root, state)
        assert command == "query" and request is not None
        return query_index(root, state, request)


def main(argv: list[str] | None = None) -> int:
    try:
        command, root = _arguments(list(sys.argv[1:] if argv is None else argv))
        request = _read_request() if command in _REQUEST_COMMANDS else None
        response = execute(command, root, request)
    except RequestError as exc:
        write_document(sys.stderr, error_document("invalid_request", str(exc)))
        return 2
    except (PopulationError, ProtocolError, OSError) as exc:
        write_document(sys.stderr, error_document("population_error", str(exc)))
        return 2
    write_document(sys.stdout, response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
