"""Evaluate one incumbent/challenger pair after both candidate runs exist."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.agent_protocol import (  # noqa: E402
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
from apps.stdio_connector import (  # noqa: E402
    decode_json_object,
    run_stdio_application,
)

ROOT = Path(__file__).resolve().parents[2]


class AgentRequestError(ValueError):
    """Raised when an evaluator request violates the public contract."""


class EvaluationError(RuntimeError):
    """Raised when the trusted evaluator cannot produce valid evidence."""


def _decode_request(source: str) -> dict[str, object]:
    return decode_json_object(source, AgentRequestError)


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


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        evaluate_pair,
        arguments,
        error_rules=(
            (AgentRequestError, "invalid_request"),
            (EvaluationError, "observer_error"),
        ),
        stream_error_code="observer_error",
    )


if __name__ == "__main__":
    raise SystemExit(main())
