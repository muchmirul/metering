"""Measure agent-supplied candidates through one-shot or JSONL transport."""

from __future__ import annotations

import math
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from metering import ProbabilityError, entropy, self_information

APPS_ROOT = Path(__file__).resolve().parents[1]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from agent_protocol import (  # noqa: E402
    AGENT_SCHEMA_VERSION,
    ProtocolError,
    decode_evaluator_result,
    decode_forecast,
    require_exact_keys,
    require_nonempty_string,
    require_schema_version,
    require_sha256,
)
from stdio_connector import decode_json_object, run_stdio_application  # noqa: E402

SCHEMA_VERSION = 1
MEASUREMENT_TOLERANCE = 1e-12


class RequestError(ValueError):
    """Raised when the agent request does not match the application contract."""


def _parse_json_number(token: str) -> float:
    try:
        exact_value = Decimal(token)
        value = float(token)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise RequestError("JSON number exceeds supported numeric limits") from exc
    if not math.isfinite(value):
        raise RequestError(
            "JSON number is outside the finite double-precision range"
        )
    if (value == 0.0 and exact_value != 0) or (
        value == 1.0 and exact_value != 1
    ):
        raise RequestError(
            "JSON number would change whether its value is zero or one "
            "in double precision"
        )
    return value


def _parse_json_integer(token: str) -> int:
    try:
        exact_value = int(token)
        value = float(exact_value)
    except (OverflowError, ValueError) as exc:
        raise RequestError("JSON number exceeds supported numeric limits") from exc
    if not math.isfinite(value):
        raise RequestError(
            "JSON number is outside the finite double-precision range"
        )
    return exact_value


def _require_exact_keys(
    value: dict[str, object], expected: set[str], location: str
) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if extra:
        details.append(f"extra keys: {', '.join(extra)}")
    if details:
        raise RequestError(f"{location}: {'; '.join(details)}")


def _require_nonempty_string(value: object, location: str) -> str:
    if type(value) is not str or not value:
        raise RequestError(f"{location} must be a non-empty string")
    return value


def _decode_request_object(source: str) -> dict[str, object]:
    return decode_json_object(
        source,
        RequestError,
        parse_float=_parse_json_number,
        parse_int=_parse_json_integer,
    )


def decode_request(source: str) -> tuple[str, str, list[dict[str, object]]]:
    """Decode one strict candidate-measurement request."""

    request = _decode_request_object(source)
    _require_exact_keys(
        request,
        {"schema_version", "candidate", "evaluation", "observations"},
        "request",
    )
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != SCHEMA_VERSION
    ):
        raise RequestError(f"schema_version must be {SCHEMA_VERSION}")

    candidate = _require_nonempty_string(request["candidate"], "candidate")
    evaluation = _require_nonempty_string(request["evaluation"], "evaluation")
    observations = request["observations"]
    if type(observations) is not list or not observations:
        raise RequestError("observations must be a non-empty JSON array")

    decoded_observations: list[dict[str, object]] = []
    seen_observations: set[str] = set()
    expected_observation_keys = {
        "observation",
        "target",
        "target_probability",
    }
    for index, observation in enumerate(observations):
        location = f"observations[{index}]"
        if type(observation) is not dict:
            raise RequestError(f"{location} must be a JSON object")
        _require_exact_keys(observation, expected_observation_keys, location)
        observation_id = _require_nonempty_string(
            observation["observation"], f"{location}.observation"
        )
        target = _require_nonempty_string(
            observation["target"], f"{location}.target"
        )
        if observation_id in seen_observations:
            raise RequestError(
                f"duplicate observation identifier: {observation_id}"
            )
        seen_observations.add(observation_id)
        decoded_observations.append(
            {
                "observation": observation_id,
                "target": target,
                "target_probability": observation["target_probability"],
            }
        )
    return candidate, evaluation, decoded_observations


def measure_candidate(
    candidate: str,
    evaluation: str,
    observations: Sequence[dict[str, object]],
) -> dict[str, object]:
    """Return named measurements without selecting or changing the candidate."""

    outcomes: list[dict[str, object]] = []
    finite_values: list[float] = []
    infinite = False
    for index, observation in enumerate(observations):
        probability = observation["target_probability"]
        try:
            value = self_information(probability, base=2)
        except ProbabilityError as exc:
            raise ProbabilityError(
                f"observations[{index}].target_probability: {exc}"
            ) from exc
        outcome_is_infinite = math.isinf(value)
        infinite = infinite or outcome_is_infinite
        if not outcome_is_infinite:
            finite_values.append(value)
        probability_value = float(probability)
        outcomes.append(
            {
                "infinite": outcome_is_infinite,
                "observation": observation["observation"],
                "target": observation["target"],
                "target_probability": (
                    0.0 if probability_value == 0.0 else probability_value
                ),
                "value_bits": None if outcome_is_infinite else value,
            }
        )

    mean = None if infinite else math.fsum(finite_values) / len(outcomes)
    return {
        "candidate": candidate,
        "evaluation": evaluation,
        "schema_version": SCHEMA_VERSION,
        "measurement": {
            "aggregate": {
                "infinite": infinite,
                "mean_target_surprisal_bits": mean,
                "sample_count": len(outcomes),
            },
            "base": 2.0,
            "metering_measure": "self_information",
            "outcomes": outcomes,
        },
    }


def _measure_agent_task_candidate(request: dict[str, object]) -> dict[str, object]:
    try:
        require_exact_keys(
            request,
            {"schema_version", "candidate", "evaluation", "cases"},
            "request",
        )
        require_schema_version(request["schema_version"])
        candidate = require_sha256(request["candidate"], "candidate")
        evaluation = require_nonempty_string(request["evaluation"], "evaluation")
        raw_cases = request["cases"]
        if type(raw_cases) is not list or not raw_cases:
            raise ProtocolError("cases must be a non-empty JSON array")

        cases: list[dict[str, object]] = []
        seen: set[str] = set()
        finite_values: list[float] = []
        any_infinite = False
        passed_count = 0
        safety_failures = 0
        for index, raw_case in enumerate(raw_cases):
            location = f"cases[{index}]"
            if type(raw_case) is not dict:
                raise ProtocolError(f"{location} must be a JSON object")
            require_exact_keys(raw_case, {"case_id", "forecast", "result"}, location)
            case_id = require_nonempty_string(
                raw_case["case_id"], f"{location}.case_id"
            )
            if case_id in seen:
                raise ProtocolError(f"duplicate case identifier: {case_id}")
            seen.add(case_id)

            forecast = decode_forecast(raw_case["forecast"], f"{location}.forecast")
            forecast_outcomes = cast(list[dict[str, object]], forecast["outcomes"])
            probabilities = {
                str(item["outcome"]): float(item["probability"])
                for item in forecast_outcomes
            }
            measured_entropy = entropy(list(probabilities.values()), base=2)
            entropy_document = cast(dict[str, object], forecast["entropy"])
            reported_entropy = float(entropy_document["value"])
            if not math.isclose(
                reported_entropy,
                measured_entropy,
                rel_tol=MEASUREMENT_TOLERANCE,
                abs_tol=MEASUREMENT_TOLERANCE,
            ):
                raise ProtocolError(
                    f"{location}.forecast.entropy.value does not match Metering"
                )

            result = decode_evaluator_result(raw_case["result"], f"{location}.result")
            if result["candidate_id"] != candidate:
                raise ProtocolError(f"{location}.result changed the candidate ID")
            outcome = str(result["outcome"])
            if outcome not in probabilities:
                raise ProtocolError(
                    f"{location}.forecast did not contain observed outcome {outcome!r}"
                )
            passed = bool(result["passed"])
            safety_passed = bool(result["safety_passed"])
            evidence = result["evidence"]
            target_probability = probabilities[outcome]
            value = self_information(target_probability, base=2)
            infinite = math.isinf(value)
            any_infinite = any_infinite or infinite
            if not infinite:
                finite_values.append(value)
            passed_count += int(passed)
            safety_failures += int(not safety_passed)
            cases.append(
                {
                    "case_id": case_id,
                    "evidence": evidence,
                    "outcome": outcome,
                    "passed": passed,
                    "safety_passed": safety_passed,
                    "target_probability": target_probability,
                    "target_surprisal": {
                        "infinite": infinite,
                        "value_bits": None if infinite else value,
                    },
                }
            )
    except ProtocolError as exc:
        raise RequestError(str(exc)) from exc

    mean = None if any_infinite else math.fsum(finite_values) / len(cases)
    return {
        "candidate": candidate,
        "cases": cases,
        "evaluation": evaluation,
        "forecast_measurement": {
            "aggregate": {
                "infinite": any_infinite,
                "mean_target_surprisal_bits": mean,
                "sample_count": len(cases),
            },
            "base": 2.0,
            "metering_measure": "self_information",
        },
        "schema_version": AGENT_SCHEMA_VERSION,
        "task_summary": {
            "case_count": len(cases),
            "passed_count": passed_count,
            "safety_failures": safety_failures,
        },
    }


def _measure_source(source: str) -> dict[str, object]:
    request = _decode_request_object(source)
    if request.get("schema_version") == AGENT_SCHEMA_VERSION:
        return _measure_agent_task_candidate(request)
    candidate, evaluation, observations = decode_request(source)
    return measure_candidate(candidate, evaluation, observations)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return run_stdio_application(
        _measure_source,
        arguments,
        error_rules=(
            (RequestError, "invalid_request"),
            (ProbabilityError, "invalid_probability"),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
