"""Schema-v1 target-surprisal assay instruction."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from metering import ProbabilityError, self_information

from apps.stdio_connector import decode_json_object

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
        raise RequestError("JSON number is outside the finite double-precision range")
    if (value == 0.0 and exact_value != 0) or (value == 1.0 and exact_value != 1):
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
        raise RequestError("JSON number is outside the finite double-precision range")
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
        target = _require_nonempty_string(observation["target"], f"{location}.target")
        if observation_id in seen_observations:
            raise RequestError(f"duplicate observation identifier: {observation_id}")
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


def run_fixture_assay(source: str) -> dict[str, object]:
    candidate, evaluation, observations = decode_request(source)
    return measure_candidate(candidate, evaluation, observations)


decode_document = _decode_request_object
