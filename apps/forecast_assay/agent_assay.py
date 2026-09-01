"""Schema-v2 task and forecast assay instruction."""

from __future__ import annotations

import math
from typing import cast

from metering import entropy, self_information

from apps.agent_protocol import (
    AGENT_SCHEMA_VERSION,
    ProtocolError,
    decode_evaluator_result,
    decode_forecast,
    require_exact_keys,
    require_nonempty_string,
    require_schema_version,
    require_sha256,
)

MEASUREMENT_TOLERANCE = 1e-12


class RequestError(ValueError):
    """Raised when an agent assay request violates its contract."""


def measure_agent_task_candidate(request: dict[str, object]) -> dict[str, object]:
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
