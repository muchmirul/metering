"""Measure one agent-supplied mutation candidate through Metering."""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Sequence

from metering import ProbabilityError, self_information


class RequestError(ValueError):
    """Raised when the agent request does not match the application contract."""


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RequestError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> object:
    raise RequestError(f"non-finite number is not valid JSON: {token}")


def decode_request(source: str) -> tuple[str, list[object]]:
    """Decode one strict candidate-measurement request."""

    try:
        request = json.loads(
            source,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
        )
    except RequestError:
        raise
    except json.JSONDecodeError as exc:
        raise RequestError(f"invalid JSON: {exc.msg}") from exc

    if type(request) is not dict:
        raise RequestError("request must be one JSON object")
    expected_keys = {"candidate", "target_probabilities"}
    if set(request) != expected_keys:
        missing = sorted(expected_keys - set(request))
        extra = sorted(set(request) - expected_keys)
        details: list[str] = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"extra keys: {', '.join(extra)}")
        raise RequestError("; ".join(details))

    candidate = request["candidate"]
    if type(candidate) is not str or not candidate:
        raise RequestError("candidate must be a non-empty string")
    probabilities = request["target_probabilities"]
    if type(probabilities) is not list or not probabilities:
        raise RequestError("target_probabilities must be a non-empty JSON array")
    return candidate, probabilities


def measure_candidate(
    candidate: str, probabilities: Sequence[object]
) -> dict[str, object]:
    """Return named measurements without selecting or changing the candidate."""

    outcomes: list[dict[str, object]] = []
    finite_values: list[float] = []
    infinite = False
    for index, probability in enumerate(probabilities):
        try:
            value = self_information(probability, base=2)
        except ProbabilityError as exc:
            raise ProbabilityError(f"target_probabilities[{index}]: {exc}") from exc
        outcome_is_infinite = math.isinf(value)
        infinite = infinite or outcome_is_infinite
        if not outcome_is_infinite:
            finite_values.append(value)
        outcomes.append(
            {
                "infinite": outcome_is_infinite,
                "target_probability": float(probability),
                "value_bits": None if outcome_is_infinite else value,
            }
        )

    mean = None if infinite else math.fsum(finite_values) / len(outcomes)
    return {
        "candidate": candidate,
        "measurement": {
            "aggregate": {
                "infinite": infinite,
                "mean_target_surprisal_bits": mean,
            },
            "base": 2.0,
            "metering_measure": "self_information",
            "outcomes": outcomes,
        },
    }


def _write_error(code: str, message: str) -> None:
    error = {"error": {"code": code, "message": message}}
    sys.stderr.write(canonical_json(error) + "\n")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        _write_error("invalid_request", "command-line arguments are not supported")
        return 2
    try:
        candidate, probabilities = decode_request(sys.stdin.read())
        response = measure_candidate(candidate, probabilities)
    except RequestError as exc:
        _write_error("invalid_request", str(exc))
        return 2
    except ProbabilityError as exc:
        _write_error("invalid_probability", str(exc))
        return 2
    sys.stdout.write(canonical_json(response) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
