"""Evaluate one incumbent/challenger pair after both candidate runs exist."""

from __future__ import annotations

import json
import sys
from pathlib import Path

APPS_ROOT = Path(__file__).resolve().parents[1]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
    ADAPTER_PROTOCOL_VERSION,
    AGENT_SCHEMA_VERSION,
    ProtocolError,
    decode_candidate_run,
    decode_command,
    decode_evaluator_result,
    decode_task,
    digest,
    require_exact_keys,
    require_nonempty_string,
    require_schema_version,
    require_timeout,
    run_adapter,
)
from stdio_connector import canonical_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class AgentRequestError(ValueError):
    """Raised when an evaluator request violates the public contract."""


class EvaluationError(RuntimeError):
    """Raised when the trusted evaluator cannot produce valid evidence."""


def _write_json(stream: object, document: dict[str, object]) -> None:
    text = canonical_json(document) + "\n"
    try:
        stream.write(text)  # type: ignore[attr-defined]
        stream.flush()  # type: ignore[attr-defined]
    except BrokenPipeError:
        raise


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AgentRequestError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise AgentRequestError(f"non-finite JSON number {token!r} is not allowed")


def _decode_request(source: str) -> dict[str, object]:
    if not source.strip():
        raise AgentRequestError("stdin must contain one JSON object")
    try:
        request = json.loads(
            source,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except AgentRequestError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise AgentRequestError(f"invalid JSON: {exc}") from exc
    if type(request) is not dict:
        raise AgentRequestError("request must be one JSON object")
    return request


def _decode_run(
    value: object,
    location: str,
    case: dict[str, object],
) -> tuple[str, object]:
    try:
        run = decode_candidate_run(value, location)
    except ProtocolError as exc:
        raise AgentRequestError(str(exc)) from exc
    if run["task"] != case:
        raise AgentRequestError(f"{location}.task does not match case")
    return str(run["candidate_id"]), run["runner"]["submission"]


def evaluate_pair(source: str) -> dict[str, object]:
    request = _decode_request(source)
    try:
        require_exact_keys(
            request,
            {
                "schema_version",
                "evaluation",
                "case",
                "incumbent_run",
                "challenger_run",
                "evaluator_command",
                "timeout_seconds",
            },
            "request",
        )
        require_schema_version(request["schema_version"])
        evaluation = require_nonempty_string(request["evaluation"], "evaluation")
        case = decode_task(request["case"], "case")
        command = decode_command(request["evaluator_command"], "evaluator_command")
        timeout = require_timeout(request["timeout_seconds"], "timeout_seconds")
    except ProtocolError as exc:
        raise AgentRequestError(str(exc)) from exc

    incumbent_id, incumbent_submission = _decode_run(
        request["incumbent_run"], "incumbent_run", case
    )
    challenger_id, challenger_submission = _decode_run(
        request["challenger_run"], "challenger_run", case
    )
    if incumbent_id == challenger_id:
        raise AgentRequestError("incumbent and challenger IDs must differ")

    adapter_request = {
        "case": case,
        "evaluation": evaluation,
        "protocol_version": ADAPTER_PROTOCOL_VERSION,
        "submissions": [
            {"candidate_id": incumbent_id, "submission": incumbent_submission},
            {"candidate_id": challenger_id, "submission": challenger_submission},
        ],
    }
    try:
        adapter_response = run_adapter(
            "evaluator adapter",
            command,
            adapter_request,
            timeout_seconds=timeout,
            cwd=ROOT,
        )
        require_exact_keys(adapter_response, {"results"}, "evaluator response")
        raw_results = adapter_response["results"]
        if type(raw_results) is not list or len(raw_results) != 2:
            raise ProtocolError(
                "evaluator response.results must contain exactly two results"
            )
        expected_ids = {incumbent_id, challenger_id}
        results: list[dict[str, object]] = []
        seen: set[str] = set()
        for index, raw_result in enumerate(raw_results):
            location = f"evaluator response.results[{index}]"
            result = decode_evaluator_result(raw_result, location)
            candidate_id = str(result["candidate_id"])
            if candidate_id not in expected_ids or candidate_id in seen:
                raise ProtocolError(
                    f"{location}.candidate_id must identify one unreported candidate"
                )
            seen.add(candidate_id)
            results.append(result)
    except ProtocolError as exc:
        raise EvaluationError(str(exc)) from exc

    results.sort(key=lambda item: str(item["candidate_id"]))
    return {
        "case_id": case["case_id"],
        "evaluation": evaluation,
        "evaluator_id": digest({"command": command}),
        "results": results,
        "schema_version": AGENT_SCHEMA_VERSION,
    }


def _read_stdin() -> str:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return sys.stdin.read()
    try:
        return stream.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgentRequestError("standard input must be valid UTF-8 JSON") from exc


def main() -> int:
    try:
        response = evaluate_pair(_read_stdin())
    except AgentRequestError as exc:
        _write_json(
            sys.stderr,
            {"error": {"code": "invalid_request", "message": str(exc)}},
        )
        return 2
    except EvaluationError as exc:
        _write_json(
            sys.stderr,
            {"error": {"code": "observer_error", "message": str(exc)}},
        )
        return 2
    _write_json(sys.stdout, response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
